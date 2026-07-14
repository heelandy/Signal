"""ONE EXECUTION PATH — ExecutionService (remediation Phase 5).

Every order source (paper autotrade, manual ticket, TV webhook, future live) submits through
`ExecutionService.submit()`. There is no other door to a broker: the audited defect was
`_paper_autotrade` calling Alpaca directly — no risk gate, no OMS, no journal fills, no
reconciliation, an undated dedup key marked "placed" even on broker errors.

The flow, transactional per step:
  candidate → approval re-check (submit time) → dated idempotency claim → ACCOUNT TRUTH from
  broker + fills (unprovable → reject ACCOUNT_STATE_UNPROVEN, fail closed) → risk.decide() with
  the REAL account → persistent order row (PENDING_SUBMIT before the broker sees it) → broker →
  event/fill ingestion → bracket-integrity check → reconciliation (mismatch → halt_submissions).

Persistence: BOT/data/execution.db (SQLite WAL) — exec_orders / exec_events / exec_fills /
exec_flags. Restart recovery converges rows to broker truth by client_order_id; a broker timeout
leaves the row SUBMIT_UNKNOWN and the key CLAIMED (never resubmit blind — reconciliation
resolves it), while a clean broker ERROR releases the key for a bounded retry.

Every response carries a correlation id + one final action:
  submitted | rejected | duplicate | shadowed | halted
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from bot.config import BOT_ROOT
from bot.contracts import (Mode, OrderRequest, OrderState, OrderType, Side, TimeInForce,
                           TradeCandidate, utcnow_iso)
from bot.risk import Account, decide

DB_PATH = BOT_ROOT / "data" / "execution.db"
ET = ZoneInfo("America/New_York")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS exec_orders(
  order_id TEXT PRIMARY KEY, correlation_id TEXT, idem_key TEXT UNIQUE, source TEXT,
  symbol TEXT, side TEXT, qty INTEGER, planned_entry REAL, stop REAL, tp REAL,
  strategy_version TEXT, state TEXT, broker_order_id TEXT, reason TEXT,
  created_at TEXT, updated_at TEXT, created_epoch REAL);
CREATE TABLE IF NOT EXISTS exec_events(
  seq INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT, state TEXT, message TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS exec_fills(
  fill_id TEXT PRIMARY KEY, order_id TEXT, broker_order_id TEXT, symbol TEXT, side TEXT,
  qty INTEGER, price REAL, at TEXT);
CREATE TABLE IF NOT EXISTS exec_flags(k TEXT PRIMARY KEY, v TEXT);
"""

TERMINAL = ("FILLED", "CANCELLED", "REJECTED", "EXPIRED", "FAILED", "INVESTIGATION_REQUIRED")
SCHEMA_V = 3                     # P1.5: bump WITH a migration below, never without
_SCHEMA_READY: dict[str, bool] = {}   # db paths whose schema has been created (per-thread conns skip it)


class AccountUnproven(RuntimeError):
    """A required piece of account state could not be proven — the order is refused.
    An unprovable limit is a breached limit (fail closed)."""


@dataclass
class ExecutionResult:
    action: str                      # submitted | rejected | duplicate | shadowed | halted
    correlation_id: str
    reason: str = ""
    order_id: str | None = None
    broker_order_id: str | None = None
    qty: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _alert(msg: str, level: str = "critical") -> None:
    try:
        from bot.alerts import alert
        alert(msg, level=level, source="execution")
    except Exception:
        pass


def _fill_et_date(at) -> str:
    """The ET calendar date of a fill timestamp (bug hunt W4): daily/weekly loss buckets are ET-DAY
    buckets, but fills store the broker's UTC `updated_at`. An overnight futures fill after ~20:00
    ET has a NEXT-day UTC date — bucketing on `str(at)[:10]` (UTC) put it in the wrong ET day and
    mis-fed the daily/weekly loss gates. Naive stamps (test fixtures) are treated as already-local."""
    s = str(at)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return s[:10]
    return (dt.date() if dt.tzinfo is None else dt.astimezone(ET).date()).isoformat()


class ExecutionService:
    STALE_SEC = 300                  # non-terminal order untouched this long -> investigation

    def __init__(self, broker, db_path: Path | str = DB_PATH, journal=None,
                 mode: Mode = Mode.PAPER, now=None):
        self.broker = broker
        self.mode = Mode(mode)
        if self.mode is not Mode.LIVE and not getattr(broker, "is_paper", True):
            raise ValueError("non-live mode with a live broker — refused (fail closed)")
        self.now = now or time.time
        self._db_path = str(db_path)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # THREAD-LOCAL connections (bug hunt W1, 2026-07-12): this service is a PROCESS-WIDE
        # singleton (_broker_cache["exec"]) used from the scan-beat thread AND FastAPI request
        # threads at once. ONE shared sqlite connection (check_same_thread=False) corrupts under
        # concurrent submit/poll — InterfaceError 'bad parameter', 'no more rows available', a
        # NoneType fetch. Each thread gets its OWN connection (`self.db` is now per-thread); WAL +
        # busy_timeout serialize writes at the FILE level and UNIQUE(idem_key) still admits exactly
        # one submit per signal. No call-site changes — every `self.db.execute` picks up its thread's
        # connection.
        self._local = threading.local()
        conn = self.db                                         # init-thread connection + schema
        # P1.5 schema versioning (ENFORCED): 1=base · 2=+session/family/grade · 3=+candidate_id.
        # A store written by NEWER code refuses to run under older code (fail loud, never corrupt).
        cur_v = conn.execute("PRAGMA user_version").fetchone()[0]
        if cur_v > SCHEMA_V:
            raise RuntimeError(f"execution.db is schema v{cur_v}, this code understands v{SCHEMA_V} "
                               f"— refusing to run OLD code on a NEWER store (P1.5)")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(exec_orders)")}
        for c in ("session", "family", "grade",                # Phase E.1: classification dims
                  "candidate_id"):                             # P1.1 linkage: tracker <-> fills
            if c not in cols:
                conn.execute(f"ALTER TABLE exec_orders ADD COLUMN {c} TEXT")
        conn.execute(f"PRAGMA user_version={SCHEMA_V}")
        conn.commit()
        if journal is None:
            from bot.journal import Journal
            journal = Journal()
        self.journal = journal

    @property
    def db(self) -> sqlite3.Connection:
        """This thread's sqlite connection (bug hunt W1): one connection per thread makes the
        process-wide singleton safe under concurrent scan-beat + request-thread access. WAL lets
        the connections share the file; each is opened once per thread and reused."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            # isolation_level=None (AUTOCOMMIT): every write is its own short transaction. The
            # default deferred-transaction mode holds a read lock across account_truth's SELECTs and
            # then upgrades to a write for _set_flag — 12 connections doing read-then-upgrade
            # DEADLOCK (busy_timeout can't break a true deadlock -> 'database is locked'). This
            # service already writes per-step-durably (PENDING_SUBMIT committed BEFORE the broker
            # call), so no group atomicity is lost; the explicit .commit() calls become no-ops.
            conn = sqlite3.connect(self._db_path, check_same_thread=False, isolation_level=None)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=10000")          # wait, don't crash, under write contention
            if not _SCHEMA_READY.get(self._db_path):           # create the schema ONCE per db file,
                conn.executescript(_SCHEMA)                    # not on every thread's connection (a
                _SCHEMA_READY[self._db_path] = True            # 12-way CREATE storm = 'database is locked')
            self._local.conn = conn
        return conn

    # ── flags / halt ─────────────────────────────────────────────────────────
    def _flag(self, k: str):
        row = self.db.execute("SELECT v FROM exec_flags WHERE k=?", (k,)).fetchone()
        return row[0] if row else None

    def _set_flag(self, k: str, v) -> None:
        self.db.execute("INSERT INTO exec_flags(k, v) VALUES(?,?) "
                        "ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))
        self.db.commit()

    def halted(self) -> str | None:
        return self._flag("halt_submissions")

    def set_halt(self, why: str) -> None:
        self._set_flag("halt_submissions", why)
        _alert(f"SUBMISSIONS HALTED: {why}")

    def clear_halt(self) -> None:
        self.db.execute("DELETE FROM exec_flags WHERE k='halt_submissions'")
        self.db.commit()

    # ── helpers ──────────────────────────────────────────────────────────────
    def _trade_date(self) -> str:
        return datetime.fromtimestamp(self.now(), tz=ET).date().isoformat()

    def idem_key(self, c: TradeCandidate, session: str = "") -> str:
        # `setup` MUST be in the key (bug hunt L2, 2026-07-12): the duplicate message claims "same
        # setup, same trade date", but omitting setup here meant two DIFFERENT setups at the same
        # symbol/side/price/day collided as a FALSE duplicate — the second order silently dropped.
        setup = getattr(c, "setup", "") or ""
        raw = (f"{c.symbol}|{c.side.value}|{setup}|{round(float(c.entry), 4)}|{session}|"
               f"{self._trade_date()}|{c.strategy_version}")
        return hashlib.sha1(raw.encode()).hexdigest()[:20]

    def _event(self, oid: str, state: str, message: str = "") -> None:
        self.db.execute("INSERT INTO exec_events(order_id, state, message, at) VALUES(?,?,?,?)",
                        (oid, state, message[:300], utcnow_iso()))
        self.db.commit()

    def _update(self, oid: str, state: str, reason: str = "", broker_order_id: str | None = None):
        self.db.execute(
            "UPDATE exec_orders SET state=?, reason=?, updated_at=?, "
            "broker_order_id=COALESCE(?, broker_order_id) WHERE order_id=?",
            (state, reason[:300], utcnow_iso(), broker_order_id, oid))
        self.db.commit()
        self._event(oid, state, reason)

    def _fail_release(self, oid: str, reason: str) -> None:
        """FAILED releases the idempotency key (suffix it away) so a bounded retry can re-claim —
        but only for CLEAN failures; SUBMIT_UNKNOWN never releases (T5.4 timeout-but-accepted)."""
        self.db.execute("UPDATE exec_orders SET state='FAILED', reason=?, updated_at=?, "
                        "idem_key = idem_key || ':failed:' || order_id WHERE order_id=?",
                        (reason[:300], utcnow_iso(), oid))
        self.db.commit()
        self._event(oid, "FAILED", reason)

    # ── account truth ────────────────────────────────────────────────────────
    def _replay_fills(self):
        """Replay exec_fills chronologically → per-symbol net/avg + realized P&L events.
        Deterministic and cheap (paper fills are few); the same math the tests seed.
        Realized tuples are (at, pnl$, symbol, order_id) — the IDENTITY the matrix paper loader
        joins on (completion-order steps 6/7, 2026-07-14: the old (at, pnl) shape forced a
        symbol-blind latest-prior-order attribution that cross-attributed concurrent trades)."""
        from bot.risk import POINT_VALUE
        rows = self.db.execute(
            "SELECT symbol, side, qty, price, at, order_id FROM exec_fills "
            "ORDER BY at, fill_id").fetchall()
        book: dict[str, dict] = {}
        realized: list[tuple[str, float, str, str]] = []   # (at, pnl$, symbol, order_id)
        for sym, side, qty, price, at, oid in rows:
            pv = POINT_VALUE.get(str(sym).upper(), 1.0)
            b = book.setdefault(sym, {"net": 0, "avg": 0.0})
            signed = qty if side == "long" else -qty
            if b["net"] * signed >= 0:                  # extend / open
                tot = abs(b["net"]) + qty
                b["avg"] = (b["avg"] * abs(b["net"]) + price * qty) / tot if tot else 0.0
                b["net"] += signed
            else:                                       # reduce / close -> realize
                net_before = b["net"]
                closed = min(abs(signed), abs(net_before))
                direction = 1 if net_before > 0 else -1
                realized.append((at, (price - b["avg"]) * closed * direction * pv, sym, oid))
                b["net"] = net_before + signed
                if b["net"] == 0:
                    b["avg"] = 0.0
                elif b["net"] * net_before < 0:          # FLIPPED through zero (bug hunt L3, 2026-07-12):
                    b["avg"] = price                     # the residual is a NEW position opened at THIS
                    #                                      fill's price, not the stale pre-flip average
        return book, realized

    def account_truth(self, feed_healthy: bool | None = True,
                      kill_switch: bool = False) -> Account:
        if feed_healthy is not True:
            raise AccountUnproven("market-data feed health not proven")
        try:
            ai = self.broker.account()
            positions = self.broker.positions()
        except Exception as e:
            raise AccountUnproven(f"broker unreachable: {e}") from None
        if ai is None or ai.equity is None:
            raise AccountUnproven("broker returned no equity")
        today = self._trade_date()
        monday = (datetime.fromisoformat(today) -
                  timedelta(days=datetime.fromisoformat(today).weekday())).date().isoformat()
        _, realized = self._replay_fills()
        daily = sum(p for at, p, *_ in realized if _fill_et_date(at) == today)
        weekly = sum(p for at, p, *_ in realized if _fill_et_date(at) >= monday)
        streak = 0
        for _, p, *_ in reversed(realized):
            if p < 0:
                streak += 1
            else:
                break
        trades_today = self.db.execute(
            "SELECT count(*) FROM exec_orders WHERE substr(created_at,1,10)=? "
            "AND state NOT IN ('FAILED','REJECTED')", (today,)).fetchone()[0]
        hw = max(float(self._flag("equity_high_water") or 0.0), float(ai.equity))
        self._set_flag("equity_high_water", hw)
        open_syms = [p.symbol for p in positions if getattr(p, "qty", 0)]
        return Account(equity=float(ai.equity), peak_equity=hw, daily_pnl=daily,
                       weekly_pnl=weekly, open_positions=len(open_syms),
                       open_symbols=open_syms, trades_today=int(trades_today),
                       consecutive_losses=streak, kill_switch=kill_switch,
                       source_healthy=True, mode=self.mode)

    # ── THE door ─────────────────────────────────────────────────────────────
    def submit(self, c: TradeCandidate, source: str, session: str = "",
               feed_healthy: bool | None = True, kill_switch: bool = False,
               qty_mult: float = 1.0, qty_cap: int | None = None,
               grade: str = "") -> ExecutionResult:
        corr = uuid.uuid4().hex[:12]
        why = self.halted()
        if why:
            return ExecutionResult("halted", corr, reason=f"submissions halted: {why}")
        # ENTRY-GROUP REMOVALS (Phase E.3): an adopted removal cannot submit — shadow keeps
        # accruing elsewhere, but no order for a group the cohort test retired.
        from bot.strategy.removals import is_removed
        rm = is_removed(c.symbol, getattr(c, "setup", ""), c.side.value, session)
        if rm:
            return ExecutionResult("rejected", corr,
                                   reason=f"entry group REMOVED ({rm.get('reason', '')}) — "
                                          f"adopted {str(rm.get('adopted_at', ''))[:10]}; "
                                          f"shadow journal keeps accruing")
        # approval at SUBMIT time (multi-tab / cached-page safe): a revoked approval takes
        # effect on the next order, not the next page reload
        from bot.approval import paper_approved
        if self.mode is Mode.PAPER and not paper_approved(c.strategy_version):
            return ExecutionResult("rejected", corr,
                                   reason=f"no paper approval for {c.strategy_version}")
        key = self.idem_key(c, session)
        oid = uuid.uuid4().hex[:16]
        try:
            self.db.execute(
                "INSERT INTO exec_orders(order_id, correlation_id, idem_key, source, symbol, "
                "side, qty, planned_entry, stop, tp, strategy_version, state, created_at, "
                "updated_at, created_epoch, session, family, grade, candidate_id) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,'PENDING_SUBMIT',?,?,?,?,?,?,?)",
                (oid, corr, key, source, c.symbol, c.side.value, 0, float(c.entry),
                 float(c.stop), float(c.tp2), c.strategy_version, utcnow_iso(), utcnow_iso(),
                 self.now(), session, getattr(c, "setup", "") or "", grade,
                 getattr(c, "candidate_id", "") or ""))
            self.db.commit()
        except sqlite3.IntegrityError:
            return ExecutionResult("duplicate", corr, reason=f"idempotency key {key} already "
                                   f"claimed (same setup, same trade date) — no new order")
        try:
            acct = self.account_truth(feed_healthy, kill_switch)
        except AccountUnproven as e:
            self._fail_release(oid, f"ACCOUNT_STATE_UNPROVEN: {e}")
            return ExecutionResult("rejected", corr, order_id=oid,
                                   reason=f"ACCOUNT_STATE_UNPROVEN: {e}")
        rd = decide(c, acct)
        try:
            self.journal.record(rd)
        except Exception as e:                           # ALARM, not silent (bug hunt W7/L8): a
            _alert(f"journal.record(risk {c.symbol}) FAILED — OMS is truth, but the audit record "  # journal
                   f"is lost (full disk?): {e}", level="warn")                                       # write is
        if not rd.approved:                                                                          # best-effort

            self._fail_release(oid, f"risk {rd.reason_code.value}: {rd.notes}")
            return ExecutionResult("rejected", corr, order_id=oid,
                                   reason=f"risk {rd.reason_code.value}: {rd.notes}")
        qty = int(rd.max_qty if qty_mult == 1.0 else max(1, round(rd.max_qty * qty_mult)))
        qty = min(qty, rd.max_qty)                     # hints size DOWN, never past the risk gate
        if qty_cap:
            qty = min(qty, int(qty_cap))
        self.db.execute("UPDATE exec_orders SET qty=? WHERE order_id=?", (qty, oid))
        self.db.commit()
        order = OrderRequest(candidate_id=c.candidate_id, symbol=c.symbol, side=c.side, qty=qty,
                             order_type=OrderType.MARKET, stop_price=c.stop, take_profit=c.tp2,
                             tif=TimeInForce.DAY, idempotency_key=key)
        try:
            ev = self.broker.submit(order)
        except Exception as e:                         # transport timeout: state UNKNOWN — the
            self._update(oid, "SUBMIT_UNKNOWN", str(e))  # key stays claimed; recovery resolves it
            _alert(f"SUBMISSION STATUS UNKNOWN {c.symbol} {c.side.value}: {e}", level="warn")
            return ExecutionResult("rejected", corr, order_id=oid,
                                   reason=f"SUBMISSION STATUS UNKNOWN — do not resubmit; "
                                          f"broker reconciliation in progress ({e})")
        if ev.state is OrderState.ERROR:
            self._fail_release(oid, f"broker error: {ev.message}")
            return ExecutionResult("rejected", corr, order_id=oid,
                                   reason=f"broker error: {ev.message}")
        self._update(oid, "SUBMITTED", f"src={source}", broker_order_id=ev.broker_order_id)
        try:
            self.journal.record(ev)
        except Exception as e:                           # ALARM, not silent (bug hunt W7/L8)
            _alert(f"journal.record(fill {c.symbol}) FAILED — order SUBMITTED + in the OMS, but the "
                   f"journal audit record is lost (full disk?): {e}", level="warn")
        return ExecutionResult("submitted", corr, order_id=oid,
                               broker_order_id=ev.broker_order_id, qty=qty)

    # ── broker-truth ingestion ───────────────────────────────────────────────
    def poll_fills(self) -> dict:
        """Pull broker order states; upsert events/fills idempotently; verify bracket legs on
        entry fills; resolve SUBMIT_UNKNOWN rows by client_order_id (timeout-but-accepted)."""
        fn = getattr(self.broker, "recent_orders", None)
        if fn is None:
            return {"error": "broker has no recent_orders()"}
        try:
            brk = fn()
        except Exception as e:
            return {"error": f"poll failed: {e}"}
        seen = ingested = 0
        for o in brk:
            seen += 1
            coid = str(o.get("client_order_id") or "")
            row = self.db.execute(
                "SELECT order_id, state, symbol, side, qty FROM exec_orders WHERE "
                "broker_order_id=? OR idem_key=?", (str(o.get("id")), coid)).fetchone()
            if not row:
                continue
            oid, state, sym, side, qty = row
            status = str(o.get("status") or "").lower()
            if state in ("SUBMIT_UNKNOWN", "PENDING_SUBMIT"):   # recovery adoption: broker truth
                self._update(oid, "SUBMITTED", "adopted from broker after unknown/crash",
                             broker_order_id=str(o.get("id")))
            filled = int(float(o.get("filled_qty") or 0))     # CUMULATIVE filled qty (broker truth)
            price = float(o.get("avg_fill_price") or 0.0)
            did_ingest = False
            if filled > 0 and price > 0:
                fid = f"{o.get('id')}:{filled}"
                cur = self.db.execute("SELECT 1 FROM exec_fills WHERE fill_id=?", (fid,)).fetchone()
                if not cur:
                    # INCREMENTAL ingest (bug hunt W1 fuzz, 2026-07-12): filled_qty is CUMULATIVE.
                    # Storing it as the fill qty double-counted a partial-then-full sequence (5 then
                    # 10 booked 15 shares for a 10-lot -> false reconcile mismatch / wrong P&L). Book
                    # only the DELTA since the ENTRY fills we've already recorded (excl. leg fills).
                    already = int(self.db.execute(
                        "SELECT COALESCE(SUM(qty), 0) FROM exec_fills WHERE order_id=? "
                        "AND fill_id NOT LIKE 'leg:%'", (oid,)).fetchone()[0])
                    delta = filled - already
                    if delta > 0:
                        self.db.execute(
                            "INSERT OR IGNORE INTO exec_fills(fill_id, order_id, broker_order_id, "
                            "symbol, side, qty, price, at) VALUES(?,?,?,?,?,?,?,?)",
                            (fid, oid, str(o.get("id")), sym, side, delta, price,
                             str(o.get("updated_at") or utcnow_iso())))
                        self.db.commit()
                        ingested += 1
                        did_ingest = True
                        if status in ("filled", "partially_filled"):
                            self._bracket_check(oid, sym, o)   # only at ENTRY fill (legs still working)
            # T4 FIX (bug hunt 2026-07-12): a bracket stop/TP is a NESTED leg of the entry order
            # (recent_orders is nested=True), NOT a separate matchable order — so poll_fills never
            # saw the close: the round trip never finalized AND reconcile would mismatch on every
            # close. Ingest a FILLED protective leg as the OFFSETTING fill, booked against the ENTRY
            # order, so the internal book closes to broker truth and the ENTRY decision finalizes.
            for leg in (o.get("legs") or []):
                lfilled = int(float(leg.get("filled_qty") or 0))
                lprice = float(leg.get("avg_fill_price") or 0.0)
                lid = str(leg.get("id") or "")
                if lfilled <= 0 or lprice <= 0 or not lid:
                    continue
                already_leg = int(self.db.execute(
                    "SELECT COALESCE(SUM(qty), 0) FROM exec_fills WHERE fill_id LIKE ?",
                    (f"leg:{lid}:%",)).fetchone()[0])
                ldelta = lfilled - already_leg                 # CUMULATIVE, like the parent
                if ldelta <= 0:
                    continue
                offset = "short" if side == "long" else "long"  # normalize to the replay convention
                self.db.execute(
                    "INSERT OR IGNORE INTO exec_fills(fill_id, order_id, broker_order_id, symbol, "
                    "side, qty, price, at) VALUES(?,?,?,?,?,?,?,?)",
                    (f"leg:{lid}:{lfilled}", oid, lid, sym, offset, ldelta, lprice,
                     str(leg.get("updated_at") or o.get("updated_at") or utcnow_iso())))
                self.db.commit()
                ingested += 1
                did_ingest = True
            # label lineage: finalize the ENTRY whose round trip just CLOSED (net back to 0) — by
            # SYMBOL via exec_orders, never the closing order's candidate. A still-open entry stays
            # entry_filled; a pure shadow row (no exec_orders link) is never touched.
            if did_ingest:
                book, _ = self._replay_fills()
                if int(book.get(sym, {}).get("net", 0)) == 0:
                    self._finalize_symbol_entries(sym)
                else:
                    self._mark_tracker_filled(oid, final=False)
            if status == "filled":
                self._update(oid, "FILLED", f"avg {price}")
            elif status in ("canceled", "cancelled"):
                self._update(oid, "CANCELLED", "broker cancelled")
            elif status in ("rejected", "expired"):
                self._update(oid, status.upper(), str(o.get("reason") or ""))
        return {"orders_seen": seen, "fills_ingested": ingested}

    def _finalize_symbol_entries(self, sym: str) -> None:
        """T4 round-trip finalization (bug hunt 2026-07-12): the symbol's book just returned to
        net 0, so EVERY filled entry on this symbol has a completed round trip — finalize the
        ENTRY decisions (by symbol via exec_orders), never the closing order's candidate. The
        no-downgrade guard in _mark_tracker_filled keeps late/duplicate polls harmless."""
        rows = self.db.execute(
            "SELECT DISTINCT o.order_id FROM exec_orders o "
            "JOIN exec_fills f ON f.order_id = o.order_id "
            "WHERE o.symbol=? AND COALESCE(o.candidate_id,'') != ''", (sym,)).fetchall()
        for (oid,) in rows:
            self._mark_tracker_filled(oid, final=True)

    def _mark_tracker_filled(self, oid: str, final: bool = False) -> None:
        """Label-lifecycle linkage (P1.1 + T4 round-trip finalization, 2026-07-12). A broker fill
        upgrades the originating tracker decision's state so it can never be confused with a shadow
        row in training or the matrix. CRITICAL (T4): an ENTRY fill sets 'entry_filled' (NOT a final
        label); only a CLOSED round trip (net back to 0) sets 'label_final'. The execution-label
        dataset uses ONLY label_final rows — so a still-open entry can never be scored as a completed
        trade, and a pure shadow row (no exec_orders link) is never touched at all."""
        try:
            row = self.db.execute("SELECT candidate_id FROM exec_orders WHERE order_id=?",
                                  (oid,)).fetchone()
            if not row or not row[0]:
                return
            state = "label_final" if final else "entry_filled"
            from bot.tracker import _con
            con = _con()
            # never DOWNGRADE a finalized label back to entry_filled on a late poll
            con.execute("UPDATE decisions SET state=? WHERE candidate_id=? "
                        "AND (state IS NULL OR state != 'label_final')", (state, row[0]))
            con.commit(); con.close()
        except Exception:
            pass

    def _bracket_check(self, oid: str, sym: str, o: dict) -> None:
        """An entry fill without WORKING protective legs is a CRITICAL halt (T5.7):
        'bracket active' is asserted from broker truth, never assumed from the submit call."""
        legs = o.get("legs")
        if legs is None:
            return                                       # broker payload has no leg info: skip
        working = [l for l in legs
                   if str(l.get("status", "")).lower() in ("new", "accepted", "held", "open",
                                                           "pending_new", "working")]
        if not working:
            self._event(oid, "BRACKET_MISSING", f"{sym}: entry filled but no working "
                                                f"protective leg (legs={legs})")
            self.set_halt(f"bracket missing on {sym} (order {oid}) — entry filled, "
                          f"stop/target not working")

    # ── reconciliation with teeth ────────────────────────────────────────────
    def reconcile(self) -> dict:
        """Broker positions vs the fills-derived internal book. Mismatch → halt + alert;
        a clean pass clears a reconcile-scoped halt."""
        try:
            broker_pos = self.broker.positions()
        except Exception as e:
            return {"_error": f"broker poll failed: {e}"}
        book, _ = self._replay_fills()
        bmap = {}
        for p in broker_pos:
            sgn = 1 if (getattr(p, "side", None) and p.side is Side.LONG) else -1
            bmap[p.symbol] = sgn * int(getattr(p, "qty", 0) or 0)
        out = {}
        bad = []
        for sym in set(book) | set(bmap):
            iq = int(book.get(sym, {}).get("net", 0))
            bq = int(bmap.get(sym, 0))
            if iq != bq:
                out[sym] = f"MISMATCH internal={iq} broker={bq}"
                bad.append(sym)
            else:
                out[sym] = "ok"
        if bad:
            self.set_halt(f"reconcile mismatch: {', '.join(sorted(bad))}")
        else:
            why = self.halted() or ""
            if why.startswith("reconcile mismatch"):
                self.clear_halt()                        # cleared by a clean pass; other halts stay
        return out

    # ── exits through the ONE door (completion-order step 5, 2026-07-14) ────
    def close_symbol(self, sym: str, source: str = "manual") -> dict:
        """SYMBOL-SCOPED exit, OMS-recorded. The audited defect: the webhook 'exit' branch called
        broker.flatten() — an exit for ONE ticker closed the WHOLE account with no OMS record.
        Closes REDUCE risk → deliberately allowed while submissions are halted."""
        sym = str(sym).upper()
        try:
            pos = [p for p in self.broker.positions()
                   if str(p.symbol).upper() == sym and getattr(p, "qty", 0)]
        except Exception as e:
            return {"action": "error", "reason": f"broker positions: {e}"}
        if not pos:
            return {"action": "no_position", "symbol": sym}
        p = pos[0]
        qty = abs(int(p.qty))
        p_side = getattr(p.side, "value", p.side)
        close_side = "short" if str(p_side) == "long" else "long"
        fn = getattr(self.broker, "close_position", None)
        if fn is None:
            return {"action": "error", "reason": "broker has no close_position()"}
        try:
            res = fn(sym)
        except Exception as e:
            return {"action": "error", "reason": f"close failed: {e}"}
        oid = uuid.uuid4().hex[:16]
        self.db.execute(
            "INSERT INTO exec_orders(order_id, correlation_id, idem_key, source, symbol, side, "
            "qty, state, broker_order_id, created_at, updated_at, created_epoch) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (oid, uuid.uuid4().hex[:12], f"close:{sym}:{oid}", f"{source}-exit", sym, close_side,
             qty, "SUBMITTED", str((res or {}).get("broker_order_id") or ""), utcnow_iso(),
             utcnow_iso(), self.now()))
        self.db.commit()
        self._event(oid, "EXIT_SUBMITTED", f"symbol-scoped close ({source}) — {qty} {sym}")
        return {"action": "closed", "symbol": sym, "order_id": oid, "qty": qty}

    def flatten_all(self, source: str = "ui") -> dict:
        """Close EVERYTHING — the deliberate whole-account action (UI 'Flatten All'), audited."""
        fn = getattr(self.broker, "flatten", None)
        if fn is None:
            return {"flattened": False, "error": "broker has no flatten()"}
        res = fn()
        self._event("-", "FLATTEN_ALL", f"close ALL positions + cancel orders via {source}")
        return res

    def cancel_order(self, broker_order_id: str, source: str = "ui") -> dict:
        """Cancel via the broker AND reflect it in the OMS row (the old path skipped the OMS)."""
        try:
            ev = self.broker.cancel(broker_order_id)
        except Exception as e:
            return {"cancelled": "error", "reason": str(e)}
        state = str(getattr(ev.state, "value", ev.state)).lower()
        if state == "cancelled":
            row = self.db.execute("SELECT order_id FROM exec_orders WHERE broker_order_id=? "
                                  "OR order_id=?", (str(broker_order_id), str(broker_order_id))).fetchone()
            if row:
                self._update(row[0], "CANCELLED", f"cancelled via {source}")
        return {"cancelled": state}

    # ── hygiene ──────────────────────────────────────────────────────────────
    def staleness_sweep(self) -> list[str]:
        """Non-terminal orders untouched past the budget flip to INVESTIGATION_REQUIRED —
        nothing sits looking normally 'Pending' forever."""
        cutoff = self.now() - self.STALE_SEC
        rows = self.db.execute(
            "SELECT order_id, state FROM exec_orders WHERE state NOT IN "
            f"({','.join('?' * len(TERMINAL))}) AND created_epoch < ?",
            (*TERMINAL, cutoff)).fetchall()
        flagged = []
        for oid, state in rows:
            self._update(oid, "INVESTIGATION_REQUIRED", f"stale in {state} past "
                                                        f"{self.STALE_SEC}s")
            flagged.append(oid)
        if flagged:
            _alert(f"{len(flagged)} order(s) stale -> INVESTIGATION_REQUIRED", level="warn")
        return flagged

    def recover(self) -> dict:
        """Boot recovery: converge non-terminal rows to broker truth by client_order_id.
        PENDING_SUBMIT with no broker order = crash-before-submit → FAILED (key released).
        SUBMIT_UNKNOWN / SUBMITTED are resolved by poll_fills' adoption path."""
        fn = getattr(self.broker, "recent_orders", None)
        known = {}
        if fn is not None:
            try:
                known = {str(o.get("client_order_id") or ""): o for o in fn()}
            except Exception:
                known = None                             # broker down: leave rows for next pass
        resolved = failed = 0
        if known is not None:
            for oid, key in self.db.execute(
                    "SELECT order_id, idem_key FROM exec_orders WHERE "
                    "state='PENDING_SUBMIT'").fetchall():
                if key in known:
                    self._update(oid, "SUBMITTED", "adopted at recovery",
                                 broker_order_id=str(known[key].get("id")))
                    resolved += 1
                else:
                    self._fail_release(oid, "crash before submit — never reached the broker")
                    failed += 1
        out = self.poll_fills()
        rec = self.reconcile()
        return {"adopted": resolved, "failed_pre_submit": failed, "poll": out, "reconcile": rec}

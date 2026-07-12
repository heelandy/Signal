# BUG HUNT PLAN — adversarial verification of the whole system
*(2026-07-12 · docs-first; execution on go-ahead · freeze intact: a hunt finds defects in what
EXISTS, it builds nothing new · authority: docs/REMEDIATION_PLAN.md discipline — every confirmed
bug gets a RED-first regression test, then the fix, then suite green; findings log:
`docs/BUG_HUNT_LOG.md` created at wave 1)*

Why hunt now: the remediation fixed everything the audit NAMED. Today's boot drill then found
four bugs the audit never saw (watchdog boot-storm, silent worker death, broken mutex read,
a reloader that never reloaded) — proof that the remaining defects are the UNNAMED ones, and
that drills find them. This plan is drills, systematized.

## Rules of engagement

1. **Money path first.** Severity = (can it place/miss/mis-size an order?) > (can it corrupt a
   store?) > (can it lie on a screen?) > cosmetics.
2. **Every find is pinned** — red-first test in `BOT/tests/` (permanent armor), fix, suite green,
   one line in the log with the failure scenario.
3. **Chaos only against scratch state** — kill/corrupt drills run on copies or the dev port;
   the production gates keep running untouched. Deliberate production restarts (if any) get the
   stop.ps1 DELIBERATE log line first.
4. **Time-boxed waves** — a wave ends at its box even with leads open (they carry to the log);
   S ≈ one sitting, M ≈ two.

## Seeded leads (smells already on the board — verify FIRST, they're cheap)

| # | Suspect | Why it smells | Class |
|---|---|---|---|
| L1 | `risk.decide` sizes with `acct.point_value.get(sym, 1.0)` — a silent $1/pt fallback | A future missing from that dict would be sized ~20–100× too big; the registry fails loud, this doesn't | **sizing** |
| L2 | Exec idempotency key = symbol·side·entry·session·date·version — **no family/setup** | Two different entry families firing the same symbol/side/price on one day → the second is a FALSE duplicate | execution |
| L3 | `_replay_fills`: a single fill that FLIPS net direction realizes the closed part but keeps the OLD avg for the residual | Wrong basis for the new position → wrong realized P&L on the next close → wrong daily/weekly limits | accounting |
| L4 | A/B "standard" (+0.306R) vs canonical run (+0.335R) on identical data — explained as "different wrapper," never verified | If the A/B variant config drifted from the live config, the re-validated evidence describes the wrong system (the F75 bug class) | evidence |
| L5 | `evidence()` now computes `fills_scorecard` (matrix loader) on every call; `status()`/readiness/approval UI all call it | Perf under polling + an import-cycle hazard (approval → phase78 → entry_matrix → removals → …) | perf/arch |
| L6 | QQQ/SPY July-7 session hole (Webull ~200-bar fetch cap) | One missing session; also: does the persister need a Yahoo-fallback backfill pass for equities? | data |
| L7 | Persister vs a mid-write kill: tmp+replace is atomic, but the MANIFEST write after it isn't paired (append succeeded + manifest lost = grain exception undercounts) | Provenance drift | data |
| L8 | ~40 `except Exception: pass` sites — inventory never done | Any one of them can be eating a money-path error today | swallow audit |

## Wave 1 — Execution & risk (M) ← the money path

- **Concurrency**: N threads submit the same candidate simultaneously → exactly one `submitted`
  (sqlite UNIQUE must hold under real threads, not just sequential tests). Same for two
  concurrent `poll_fills` (no double-ingested fill), reconcile-during-ingest.
- **Numeric edges**: qty at `qty_mult` boundaries (0.4×1, rounding at .5), `rd.max_qty=0` paths,
  negative/zero/1e9 equity, entry==stop±1e-12, `risk_per_unit` subnormals, L1's point-value
  fallback with a fake future.
- **State-machine fuzz**: drive the service with every broker-response ordering the mock can
  produce (accept→fill→cancel race, fill-after-cancel, replace semantics, duplicate broker
  events, fills for unknown orders) — assert no path mints, loses, or double-counts a share.
- **Key collisions**: L2 — same price two families; same setup re-armed after a FAILED release
  (retry) racing a new signal.

## Wave 2 — Engine invariants (M)

- **Mirror-tape property**: feed a tape and its price-mirror → every long trade must appear as
  an exact short twin (entry/stop/tp/exits mirrored). Any asymmetry = a side-specific bug
  (the short-MFE class, hunted systematically).
- **Property tests** (hypothesis-style, seeded fixtures): no exit before entry; every exit inside
  the entry trade-day; `net_R ≤ gross_R`; stop exits never better than the stop (gap-aware
  bound: never better than min(open,stop)); determinism under row-order/dtype/timezone-repr
  changes of the input frame.
- **Cross-artifact consistency**: entry-matrix backtest rows == fresh `run_backtest` trades
  (count+sum, per symbol); `fills_scorecard` == raw exec_fills math recomputed independently;
  `dataqa` spans == actual parquet tails; L4's A/B-vs-canonical config diff, line by line.

## Wave 3 — Data pipeline & persister chaos (S)

- Poison router frames through `append_bars`: duplicate timestamps, out-of-order, tz-naive
  mixed with aware, a WRONG SYMBOL's prices (identity check exists only in the equity ingest —
  does the persister need a continuity guard? probably yes), inf/0 prices, 10-year-old bars.
- Kill -9 during `persist_day`'s parquet rewrite AND between store-write and manifest-write
  (L7) → store must be either old or new, never torn; manifest drift documented or fixed.
- Resample-under-write: spawn resample while an append rewrites the parquet (duckdb read of a
  replaced file).

## Wave 4 — Clocks & calendars (S)

- **DST**: 2026-11-01 fall-back (duplicated 01:xx ET bars — dedup? session tags? idem keys?)
  and 2026-03-08 spring-forward, through: persister session tagging, tracker trade-day, exec
  idem trade-date, EOD last-bar detection.
- **Midnight ET boundary**: submit at 23:59:59 vs 00:00:01 (key rotation), weekly P&L Monday
  reset at the exact boundary, `busday_count` freshness on Sundays/holidays.
- **Holidays/half-days**: an early-close day through the last-bar EOD flatten (engine) and the
  16:10 persist beat (fires before a 13:00 close's data is final? — verify Yahoo/Webull return
  final bars by then on half-days).

## Wave 5 — Ops chaos drills (S, scratch/dev only)

- Kill -9 matrix: worker mid-scan ×5 (crash records every time? mutex re-acquirable? watchdog
  revives with grace, exactly once?), API mid-request, both at once.
- Corrupt-file matrix: each state file one at a time (approvals.json, boss.json, execution.db
  half-page, tracker WAL, latest_scan.json) → every one must fail LOUD or fail SAFE, never
  fail silent (runtime_state is done; the rest never got the treatment).
- Disk-full simulation on the data dir (backup beat + persister + journal appends).

## Wave 6 — API/UI contract sweep (S)

- Scripted sweep: every GET endpoint → 200 + JSON + no unbounded payload (>2MB flag) + no raw
  traceback leak; every POST without auth token when `API_REQUIRE_AUTH=1` → 401 (flip it on the
  dev port); the documented-open endpoints (kill arm) explicitly asserted open.
- Adversarial payloads into the console's render paths: signals with None/NaN/1e308 fields,
  10KB reason strings, RTL/zero-width unicode in notes → pages must render (esc + no layout
  break); headless-chrome console-error capture added to the driver.
- Path traversal probes on any endpoint that takes a name/path param (`/api/training/report`).

## Wave 7 — Swallow audit & dead wiring (M)

- Inventory every `except Exception` (≈grep count first): classify KEEP (best-effort telemetry) /
  NARROW (catch the specific exception) / **ALARM** (money path — must alert or fail loud).
  The service's swallowed `journal.record` failures are the seeded example: a full disk today
  silently stops the paper-execution record.
- Dead wiring: beats that can never fire, config flags read nowhere, endpoints no page calls,
  imports of retired modules. Retire with a note or wire with a test — nothing stays ambiguous.

## Deliverables & exit

- `docs/BUG_HUNT_LOG.md` — one line per lead: verdict (CONFIRMED-fixed / FALSE-alarm-with-proof /
  DEFERRED-with-reason), test id, severity.
- Every CONFIRMED bug: red test → fix → suite green, same day.
- Exit criteria: all 8 seeded leads adjudicated + all 7 waves boxed; suite grows by the armor;
  STATUS gets a "bug-hunt <date>: N confirmed / M pinned" line.
- Explicitly OUT: anything that adds features, re-tunes parameters, or touches the sealed
  journals — the freeze survives the hunt.

"""Load the Databento batch files already downloaded to D: — NO API key needed.

duckdb reads the .csv.zst directly (streaming, no full decompress) and does the heavy parsing
in SQL, so this stays memory-safe even though a single OPRA day is ~5M rows (the whole QQQ
option chain quoted every minute).

Two datasets present:

  OPRA.PILLAR  cbbo-1m   (D:/OPRA-...)   QQQ option chain, consolidated BBO per minute.
      cols: ts_recv, ts_event, ..., bid_px_00, ask_px_00, bid_sz_00, ask_sz_00, ..., symbol
      symbol = OSI, e.g. "QQQ   260717C00545000" = QQQ 2026-07-17 Call 545.000

  XNAS.ITCH    mbo       (D:/XNAS-...)    QQQ order-book events (market-by-order, full L3).
      cols: ts_recv, ts_event, ..., action, side, price, size, order_id, sequence, symbol
      action: A=add C=cancel M=modify T=trade F=fill R=clear ;  side: B=bid A=ask N=none

All timestamps are returned in ET. Session timezone is pinned to America/New_York in SQL so
results do not depend on the machine's locale.

Usage:
    from bot.market_data import databento_local as L
    L.list_days("opra")                                  # ['2026-05-27', ...]
    q = L.atm_quote("2026-05-27", 545.0, "C", "09:35")   # ATM call quotes at 09:35 ET (small)
    d = L.mbo_cum_delta("2026-05-26", hhmm=("09:30","16:00"))  # RTH order-flow delta per minute
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import duckdb
except ImportError as e:  # pragma: no cover
    raise RuntimeError("duckdb is required: pip install duckdb") from e

from bot.config import settings

ET = "America/New_York"
# (filename stem, directory). The Databento batch ships .csv.zst, but a local extraction job
# decompresses each into a same-named folder. We resolve BOTH layouts (duckdb reads either).
_DSETS = {
    "opra": (lambda d8: f"opra-pillar-{d8}.cbbo-1m.csv", settings.opra_dir),
    "xnas": (lambda d8: f"xnas-itch-{d8}.mbo.csv", settings.xnas_dir),
}


def _con():
    con = duckdb.connect()
    con.execute(f"SET TimeZone='{ET}'")   # machine-independent ET wall-clock for strftime/extract
    return con


def list_days(kind: str = "opra") -> list[str]:
    """Available trading days for 'opra' (options BBO) or 'xnas' (MBO order flow).
    Counts a day present whether it is still .zst or already extracted to a folder/.csv."""
    base = _DSETS[kind][1]
    days = set()
    if base.exists():
        for p in base.iterdir():
            m = re.search(r"(\d{8})\.", p.name)
            if m:
                d = m.group(1)
                days.add(f"{d[:4]}-{d[4:6]}-{d[6:8]}")
    return sorted(days)


def _path_for(kind: str, date: str, base: Path | None = None) -> Path:
    """Resolve one day to a readable path: compressed .zst, extracted folder/<csv>, or flat .csv.
    `base` overrides the dataset's default folder (used for the per-symbol SPY MBO batch)."""
    stem_fn, default_base = _DSETS[kind]
    base = Path(base) if base is not None else default_base
    stem = stem_fn(date.replace("-", ""))
    z = base / (stem + ".zst")
    if z.exists():
        return z                                   # compressed (duckdb streams it)
    inner = base / stem / stem
    if inner.exists():
        return inner                               # extracted into a same-named folder
    flat = base / stem
    if flat.is_file():
        return flat                                # extracted flat
    if (base / stem).is_dir():                     # any csv inside the folder
        for c in sorted((base / stem).glob("*.csv")):
            return c
    raise FileNotFoundError(f"No {kind} data for {date} (.zst or extracted) in {base}")


# --- OPRA option-chain BBO (cbbo-1m) ---------------------------------------
# OSI parsed in SQL: root, 6-digit expiry, C/P, 8-digit strike (×1000).
_OSI_SQL = (
    "regexp_extract(symbol, '^(\\S+)', 1) AS root, "
    "regexp_extract(symbol, '(\\d{6})[CP]\\d{8}$', 1) AS exp6, "
    "regexp_extract(symbol, '\\d{6}([CP])\\d{8}$', 1) AS right, "
    "TRY_CAST(regexp_extract(symbol, '(\\d{8})$', 1) AS BIGINT) / 1000.0 AS strike"
)


def load_cbbo_day(date: str, root: str = "QQQ", minute_et: str | None = None,
                  right: str | None = None, strike_lo: float | None = None,
                  strike_hi: float | None = None) -> pd.DataFrame:
    """Option-chain BBO for one day. Parsing + filters run in SQL so this stays light.

    A whole day is ~5M rows; ALWAYS pass minute_et (and ideally a strike band) for interactive
    use. ts is COALESCE(ts_event, ts_recv) because snapshot rows carry only ts_recv."""
    path = _path_for("opra", date)
    w = ["(bid_px_00 IS NOT NULL OR ask_px_00 IS NOT NULL)", f"symbol LIKE '{root}%'"]
    if minute_et:
        w.append(f"strftime(COALESCE(ts_event, ts_recv), '%H:%M') = '{minute_et}'")
    if right in ("C", "P"):
        w.append(f"regexp_extract(symbol, '\\d{{6}}([CP])\\d{{8}}$', 1) = '{right}'")
    if strike_lo is not None:
        w.append(f"TRY_CAST(regexp_extract(symbol, '(\\d{{8}})$', 1) AS BIGINT)/1000.0 >= {strike_lo}")
    if strike_hi is not None:
        w.append(f"TRY_CAST(regexp_extract(symbol, '(\\d{{8}})$', 1) AS BIGINT)/1000.0 <= {strike_hi}")
    con = _con()
    df = con.execute(
        f"SELECT COALESCE(ts_event, ts_recv) AS ts, symbol, "
        f"bid_px_00 AS bid, ask_px_00 AS ask, bid_sz_00 AS bid_sz, ask_sz_00 AS ask_sz, {_OSI_SQL} "
        f"FROM read_csv_auto('{path.as_posix()}') WHERE {' AND '.join(w)}"
    ).df()
    con.close()
    if not df.empty:
        df["ts_et"] = pd.to_datetime(df["ts"], utc=True, errors="coerce").dt.tz_convert(ET)
        df["expiry"] = "20" + df["exp6"].str[:2] + "-" + df["exp6"].str[2:4] + "-" + df["exp6"].str[4:6]
        df["mid"] = (df["bid"].astype("float64") + df["ask"].astype("float64")) / 2.0
    return df.reset_index(drop=True)


def atm_quote(date: str, underlying_px: float, right: str = "C", minute_et: str = "09:35",
              dte_max: int = 4, band: float = 10.0) -> pd.DataFrame:
    """Nearest-the-money contract quotes at one ET minute — replaces the OPTIONS Pine's
    Black-Scholes COST estimate with a real bid/ask/mid from the chain."""
    ch = load_cbbo_day(date, "QQQ", minute_et=minute_et, right=right,
                        strike_lo=underlying_px - band, strike_hi=underlying_px + band)
    if ch.empty:
        return ch
    if dte_max is not None:
        dte = (pd.to_datetime(ch["expiry"]) - pd.Timestamp(date)).dt.days
        ch = ch[dte.between(0, dte_max)]
    ch = ch.assign(atm_dist=(ch["strike"] - underlying_px).abs())
    return ch.sort_values("atm_dist").head(20).reset_index(drop=True)


# --- XNAS MBO order flow (the "where is price going" engine, MBO phase) ------

def load_mbo_day(date: str, symbol: str = "QQQ", actions: tuple[str, ...] = ("T",),
                 hhmm: tuple[str, str] | None = None) -> pd.DataFrame:
    """Order-book events for one day. Default keeps only TRADE prints (T) — the aggressor prints
    for cumulative delta. NOTE: do NOT include Fills (F); they come as matched buyer+seller pairs
    and cancel the delta to ~0 (verified). actions=() = full book. hhmm bounds to a window.
    The MBO folder is resolved by symbol (QQQ -> xnas_dir, SPY -> xnas_spy_dir)."""
    path = _path_for("xnas", date, base=settings.mbo_dir_for(symbol))
    w = [f"symbol = '{symbol}'", "price IS NOT NULL"]
    if actions:
        w.append("action IN (" + ",".join(f"'{a}'" for a in actions) + ")")
    if hhmm:
        w.append(f"strftime(ts_event, '%H:%M') >= '{hhmm[0]}' AND strftime(ts_event, '%H:%M') < '{hhmm[1]}'")
    con = _con()
    df = con.execute(
        f"SELECT ts_event, action, side, price, size, sequence "
        f"FROM read_csv_auto('{path.as_posix()}') WHERE {' AND '.join(w)}"
    ).df()
    con.close()
    df["ts_et"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce").dt.tz_convert(ET)
    return df.reset_index(drop=True)


def mbo_cum_delta(date: str, symbol: str = "QQQ", freq: str = "1min",
                  hhmm: tuple[str, str] | None = ("09:30", "16:00")) -> pd.DataFrame:
    """Per-bar signed order flow = aggressor-buy size − aggressor-sell size (cumulative delta).

    On QQQ trade (T) prints, `side='B'` is the BUY-aggressor and `side='A'` the SELL-aggressor —
    CALIBRATED empirically: B=buy gives a positive same-minute IC vs price (+0.20), A=buy gives the
    inverse (`research`/MBO analysis 2026-06-29). `side='N'` (~12%) has no side and is dropped.
    Returns minute index with buy_vol, sell_vol, delta, cum_delta. Default bounds to RTH.
    NOTE: 1-min trade-delta only weakly PREDICTS the next minute (IC ~+0.03–0.10); its edge is
    contemporaneous. Real predictive order flow = event-time OFI/queue-imbalance (Evidence, next)."""
    df = load_mbo_day(date, symbol, actions=("T",), hhmm=hhmm)
    if df.empty:
        return pd.DataFrame(columns=["buy_vol", "sell_vol", "delta", "cum_delta"])
    df = df.set_index("ts_et")
    buy = df["size"].where(df["side"] == "B", 0)
    sell = df["size"].where(df["side"] == "A", 0)
    out = pd.DataFrame({
        "buy_vol": buy.resample(freq).sum(),
        "sell_vol": sell.resample(freq).sum(),
    })
    out["delta"] = out["buy_vol"] - out["sell_vol"]
    out["cum_delta"] = out["delta"].cumsum()
    return out.dropna(how="all")


if __name__ == "__main__":
    print("OPRA days:", len(list_days("opra")), "| XNAS days:", len(list_days("xnas")))

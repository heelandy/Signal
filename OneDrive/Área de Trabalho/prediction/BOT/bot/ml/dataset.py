"""Labeled candidate dataset builder (ML-002) — the bridge from the rule engine to the ML/NN layers.

Replays history through the CANONICAL entry standard (bot.strategy.orb_candidates.run_backtest —
the exact rule version the Pine + live BOT trade), then joins every trade with its point-in-time
feature snapshot (bot.ml.features_pit — the same function the live scan uses) and its realized
labels. Persists to the FeatureStore (parquet) keyed by strategy version, so every model can be
traced back to the rule version + data snapshot that produced it.

Labels per candidate (labels are NEVER features):
    y_win      1 if net_R > 0
    y_tp2      1 if the full 4R cap was reached (gross_R >= 0.99 * T2)
    y_stop     1 if the trade lost ~a full R (gross_R <= -0.99)
    net_r / gross_r / mfe_r / mae_r / hold_bars   (analysis + expectancy-by-bucket validation)

    from bot.ml.dataset import build, load_or_build
    df = build("QQQ")           # replay + features + labels
    df = load_or_build("QQQ")   # cached parquet if the strategy version matches
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot.ml.features_pit import FEATURE_COLUMNS, or_levels, pit_features
from bot.ml.registry import FeatureStore

DATASET_NAME = "orb_candidates"


def _store_name(sym: str, tf: str) -> str:
    """Per-timeframe dataset stores (multi-TF training 2026-07-05); 5m keeps the legacy name."""
    return f"{DATASET_NAME}_{sym}" + ("" if tf == "5m" else f"_{tf}")


def build(sym: str = "QQQ", tf: str = "5m", sess: str = "rth", save: bool = True) -> pd.DataFrame:
    """Replay `sym` through the canonical entry standard -> one row per executed candidate:
    meta (ts/symbol/side/version) + FEATURE_COLUMNS + labels.
    tf=1d/1w routes to the SWING dataset (triple-barrier daily/weekly candidates)."""
    if tf in ("1d", "1w"):
        from bot.ml.swing_dataset import build_swing
        return build_swing(sym, tf, save=save)
    from bot.strategy.orb_candidates import (load_state, run_backtest, STRATEGY_VERSION,
                                             ORS, ORE, T2)
    d = load_state(sym, tf, sess)
    tr = run_backtest(d).reset_index(drop=True)
    if not len(tr):
        return pd.DataFrame()
    orh, orl, mins = or_levels(d, ORS, ORE)
    ts_ns = pd.to_datetime(d["ts"], utc=True).astype("int64").to_numpy()   # epoch ns (tz-safe compare)
    rows = []
    for _, t in tr.iterrows():
        ets = pd.Timestamp(t["entry_time"])
        ets_ns = (ets.tz_localize("UTC") if ets.tz is None else ets.tz_convert("UTC")).value
        i = int(np.searchsorted(ts_ns, ets_ns))
        if i >= len(ts_ns) or ts_ns[i] != ets_ns:              # entry bar must exist exactly
            i = min(max(i - 1, 0), len(ts_ns) - 1)
        side = str(t["direction"])
        sign = 1 if side == "long" else -1
        entry = float(t["entry_price"]); risk = float(t["risk_pts"])
        feats = pit_features(d, i, side, entry=entry, stop=entry - sign * risk,
                             orh=orh[i], orl=orl[i], mins_of_day=float(mins[i]), or_e=ORE, rr=T2,
                             symbol=sym)
        gross = float(t["gross_R"]); net = float(t["net_R"])
        rows.append({
            "ts": pd.Timestamp(t["entry_time"]), "symbol": sym, "side": side,
            "strategy_version": STRATEGY_VERSION, "session": sess,
            **{k: feats.get(k, np.nan) for k in FEATURE_COLUMNS},
            "y_win": int(net > 0), "y_tp2": int(gross >= 0.99 * T2), "y_stop": int(gross <= -0.99),
            "net_r": net, "gross_r": gross, "mfe_r": float(t["mfe_R"]), "mae_r": float(t["mae_R"]),
            "hold_bars": int(t["hold_bars"]),
        })
    df = pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
    if len(df):
        from bot.ml.l2_features import attach_l2
        df = attach_l2(df, sym)                  # l2_* columns (NaN when no depth store exists)
        df["tf"] = tf
    if save and len(df):
        FeatureStore().save(_store_name(sym, tf), _version_slug(), df)
    return df


def _version_slug() -> str:
    from bot.strategy.orb_candidates import STRATEGY_VERSION
    return STRATEGY_VERSION.replace(".", "-")


def load_or_build(sym: str = "QQQ", tf: str = "5m", sess: str = "rth") -> pd.DataFrame:
    """Cached dataset for the CURRENT strategy version; rebuilds when the version has moved on."""
    fs = FeatureStore()
    try:
        return fs.load(_store_name(sym, tf), _version_slug())
    except FileNotFoundError:
        return build(sym, tf, sess)


def build_pooled(syms: tuple | list | None = None, save: bool = True, tf: str = "5m") -> pd.DataFrame:
    """POOLED multi-symbol dataset (MLP-001 / optimization #1): one training set across the
    validated instruments, chronologically interleaved so walk-forward folds stay time-ordered.
    Symbol identity rides in the sym_* one-hot features."""
    from bot.ml.features_pit import POOL_SYMBOLS
    frames = []
    for s in (syms or POOL_SYMBOLS):
        df = load_or_build(s, tf)
        if len(df):
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True).sort_values("ts").reset_index(drop=True)
    if save and len(out):
        FeatureStore().save(_store_name("ALL", tf), _version_slug(), out)
    return out


def build_rejects(sym: str = "QQQ", tf: str = "5m", sess: str = "rth", save: bool = True) -> pd.DataFrame:
    """REJECTED / NO-TRADE setups (MLP-001 §2 — 'good trades AND why no trade'): every bar where
    the breakout TRIGGER fired but a rule gate blocked it, with the FIRST failing gate as the
    reason, PIT features, and the HYPOTHETICAL outcome (first-touch walk of the standard trade
    geometry) -> missed_winner / missed_loser labels. Analysis + future no-trade model; these rows
    are NOT mixed into the executed-candidate training set."""
    from bot.strategy.orb_candidates import (load_state, ORS, ORE, CUT, DELAY, STRONG, T2,
                                             STRATEGY_VERSION)
    from bot.strategy.orb_state import ENTRY_STANDARD as ES
    import hs_backtest as B
    d = load_state(sym, tf, sess)
    rejects: list = []
    B._orb_signals(d, ORS, ORE, 0.0, CUT, "close", False, False, entry_delay=DELAY,
                   chase_atr=1.0, strong_body=STRONG, ft_confirm=True, dir_seq=True,
                   watch_live=ES.watch_gate, cooldown_bars=ES.cooldown_bars,
                   stale_bars=ES.stale_bars, retest_atr=ES.retest_atr,
                   collect_rejects=rejects)
    if not rejects:
        return pd.DataFrame()
    orh, orl, mins = or_levels(d, ORS, ORE)
    h = d["high"].to_numpy(float); lo = d["low"].to_numpy(float)
    c = d["close"].to_numpy(float); atr = d["atr14"].to_numpy(float)
    et_date = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York").dt.date.to_numpy()
    rows = []
    for i, side, reason in rejects:
        sign = 1 if side == "long" else -1
        entry = c[i]
        risk = 1.5 * atr[i] if atr[i] == atr[i] and atr[i] > 0 else np.nan   # standard-geometry proxy
        if risk != risk:
            continue
        stop, tp2 = entry - sign * risk, entry + sign * risk * T2
        # first-touch walk within the same trade day (stop-first on same-bar ambiguity)
        hyp = 0.0
        for k in range(i + 1, min(i + 200, len(c))):
            if et_date[k] != et_date[i]:
                hyp = sign * (c[k - 1] - entry) / risk
                break
            adverse = lo[k] if sign == 1 else h[k]
            favor = h[k] if sign == 1 else lo[k]
            if sign * (adverse - stop) <= 0:
                hyp = -1.0
                break
            if sign * (favor - tp2) >= 0:
                hyp = float(T2)
                break
        else:
            hyp = sign * (c[min(i + 199, len(c) - 1)] - entry) / risk
        feats = pit_features(d, i, side, entry=entry, stop=stop, orh=orh[i], orl=orl[i],
                             mins_of_day=float(mins[i]), or_e=ORE, rr=T2, symbol=sym)
        rows.append({"ts": pd.Timestamp(d["ts"].iloc[i]), "symbol": sym, "side": side,
                     "strategy_version": STRATEGY_VERSION, "session": sess,
                     "block_reason": reason,
                     **{k: feats.get(k, np.nan) for k in FEATURE_COLUMNS},
                     "hyp_net_r": round(float(hyp), 3),
                     "missed_winner": int(hyp > 0), "missed_loser": int(hyp <= 0)})
    df = pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
    if save and len(df):
        FeatureStore().save(f"rejects_{sym}", _version_slug(), df)
    return df


def to_xy(df: pd.DataFrame, target: str = "y_win"):
    """(X, y, net_r, ts) arrays for training — X is the ordered FEATURE_COLUMNS matrix with
    median imputation (train code must fit imputation on the TRAIN slice only; this is the raw
    matrix with NaNs preserved). Cached datasets from an OLDER schema degrade gracefully:
    missing columns come back as NaN until the next rebuild."""
    X = df.reindex(columns=FEATURE_COLUMNS).to_numpy(float)
    y = df[target].to_numpy(int)
    return X, y, df["net_r"].to_numpy(float), pd.to_datetime(df["ts"]).to_numpy()


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sym = args[0] if args else "QQQ"
    tf = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--tf=")), "5m")
    df = build(sym, tf=tf)
    print(f"{sym}: {len(df)} labeled candidates | win-rate {df['y_win'].mean():.3f} | "
          f"tp2 {df['y_tp2'].mean():.3f} | stop {df['y_stop'].mean():.3f} | "
          f"avg net {df['net_r'].mean():+.3f}R | span {df['ts'].iloc[0].date()}..{df['ts'].iloc[-1].date()}")
    nan_share = df[FEATURE_COLUMNS].isna().mean().sort_values(ascending=False)
    print("worst-NaN features:", dict(nan_share.head(5).round(3)))
    print("dataset OK")

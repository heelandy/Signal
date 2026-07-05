"""Sequence dataset for the NN layer — fixed-length candle windows ending AT the signal bar.

Each labeled candidate (the SAME canonical replay the tabular dataset uses) becomes one sample:
a [window x channels] matrix of causal per-timestep features. The window ends at the signal close —
no future candles, no future VWAP/session aggregates inside the input (leakage-safe by construction).

Channels per timestep (all ATR- or z-normalized so instruments/regimes are comparable):
    ret_atr, body_dir, up_wick, dn_wick, vol_z, vwap_dist_atr, or_rel_atr,
    st_up, st_down, hour_sin, hour_cos

    from bot.nn.dataset import build_sequences
    ds = build_sequences("QQQ", window=64)   # {"X": [N,T,C], "y": ..., "net_r": ..., "channels": [...]}
"""
from __future__ import annotations

import numpy as np
import pandas as pd

CHANNELS = ["ret_atr", "body_dir", "up_wick", "dn_wick", "vol_z", "vwap_dist_atr",
            "or_rel_atr", "st_up", "st_down", "hour_sin", "hour_cos"]


def _bar_channels(d: pd.DataFrame, orh: np.ndarray, orl: np.ndarray) -> np.ndarray:
    """Per-bar channel matrix [n, C] — every value causal at its own bar's close."""
    c = d["close"].to_numpy(float)
    o = d["open"].to_numpy(float)
    h = d["high"].to_numpy(float)
    lo = d["low"].to_numpy(float)
    atr = d["atr14"].to_numpy(float) if "atr14" in d else np.full(len(d), np.nan)
    atr = np.where(np.isfinite(atr) & (atr > 0), atr, np.nan)
    v = d["volume"].to_numpy(float) if "volume" in d else np.full(len(d), np.nan)
    vw = d["vwap_sess"].to_numpy(float) if "vwap_sess" in d else np.full(len(d), np.nan)
    st = d["st_state"].to_numpy(float) if "st_state" in d else np.zeros(len(d))
    rng = np.where((h - lo) > 0, h - lo, np.nan)
    ret = np.concatenate([[np.nan], np.diff(c)]) / atr
    body = (c - o) / rng
    upw = (h - np.maximum(c, o)) / rng
    dnw = (np.minimum(c, o) - lo) / rng
    vmu = pd.Series(v).rolling(20, min_periods=5).mean().to_numpy()
    vsd = pd.Series(v).rolling(20, min_periods=5).std().to_numpy()
    volz = (v - vmu) / np.where(vsd > 0, vsd, np.nan)
    vwd = (c - vw) / atr
    mid = (orh + orl) / 2.0
    orrel = (c - mid) / atr
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    hr = (et.dt.hour + et.dt.minute / 60.0).to_numpy()
    M = np.column_stack([ret, body, upw, dnw, volz, vwd, orrel,
                         (st == 1).astype(float), (st == 2).astype(float),
                         np.sin(2 * np.pi * hr / 24.0), np.cos(2 * np.pi * hr / 24.0)])
    return np.nan_to_num(np.clip(M, -8, 8), nan=0.0)


def build_sequences(sym: str = "QQQ", window: int = 64, tf: str = "5m", sess: str = "rth") -> dict:
    """Canonical replay -> one [window x channels] sample per executed candidate + labels."""
    from bot.strategy.orb_candidates import load_state, run_backtest, STRATEGY_VERSION, ORS, ORE
    from bot.ml.features_pit import or_levels
    d = load_state(sym, tf, sess)
    tr = run_backtest(d).reset_index(drop=True)
    orh, orl, _ = or_levels(d, ORS, ORE)
    M = _bar_channels(d, orh, orl)
    ts_ns = pd.to_datetime(d["ts"], utc=True).astype("int64").to_numpy()   # epoch ns (tz-safe compare)
    X, y, net_r, sides, ts_out = [], [], [], [], []
    for _, t in tr.iterrows():
        ets = pd.Timestamp(t["entry_time"])
        ets_ns = (ets.tz_localize("UTC") if ets.tz is None else ets.tz_convert("UTC")).value
        i = int(np.searchsorted(ts_ns, ets_ns))
        if i >= len(ts_ns) or ts_ns[i] != ets_ns:
            i = min(max(i - 1, 0), len(ts_ns) - 1)
        if i + 1 < window:
            continue                                    # not enough history for a full window
        seq = M[i + 1 - window:i + 1]                   # ends AT the signal bar (inclusive, causal)
        sign = 1.0 if str(t["direction"]) == "long" else -1.0
        # mirror shorts onto the long frame: flip the directional channels so ONE network learns
        # one pattern language (ret, body, vwap-dist, or-rel, structure flags swap)
        seq = seq.copy()
        if sign < 0:
            seq[:, 0] *= -1; seq[:, 1] *= -1; seq[:, 5] *= -1; seq[:, 6] *= -1
            seq[:, [7, 8]] = seq[:, [8, 7]]
            seq[:, [2, 3]] = seq[:, [3, 2]]
        X.append(seq)
        y.append(int(float(t["net_R"]) > 0))
        net_r.append(float(t["net_R"]))
        sides.append(str(t["direction"]))
        ts_out.append(pd.Timestamp(t["entry_time"]))
    return {"X": np.asarray(X, np.float32), "y": np.asarray(y, int),
            "net_r": np.asarray(net_r, float), "side": sides, "ts": ts_out,
            "channels": CHANNELS, "window": window, "sym": sym,
            "strategy_version": STRATEGY_VERSION}


def build_pooled_sequences(syms: tuple | list | None = None, window: int = 64,
                           tf: str = "5m") -> dict:
    """POOLED multi-symbol sequence set, chronologically interleaved (walk-forward stays honest).
    Channels are ATR-/z-normalized so instruments share one pattern language."""
    from bot.ml.features_pit import POOL_SYMBOLS
    parts = [build_sequences(s, window=window, tf=tf) for s in (syms or POOL_SYMBOLS)]
    parts = [p for p in parts if len(p["X"])]
    if not parts:
        return {"X": np.empty((0, window, len(CHANNELS)), np.float32), "y": np.array([], int),
                "net_r": np.array([]), "side": [], "ts": [], "channels": CHANNELS,
                "window": window, "sym": "ALL", "strategy_version": parts and parts[0]["strategy_version"]}
    ts = [t for p in parts for t in p["ts"]]
    order = np.argsort(np.array([pd.Timestamp(t).value for t in ts]))
    cat = lambda k: np.concatenate([p[k] for p in parts])[order]
    sides = [x for p in parts for x in p["side"]]
    return {"X": cat("X"), "y": cat("y"), "net_r": cat("net_r"),
            "side": [sides[i] for i in order], "ts": [ts[i] for i in order],
            "channels": CHANNELS, "window": window, "sym": "ALL",
            "strategy_version": parts[0]["strategy_version"]}


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "QQQ"
    ds = build_pooled_sequences() if sym.upper() == "ALL" else build_sequences(sym)
    X = ds["X"]
    print(f"{sym}: {X.shape[0]} sequences x {X.shape[1]} bars x {X.shape[2]} channels | "
          f"win-rate {ds['y'].mean():.3f} | finite {np.isfinite(X).all()}")
    print("nn dataset OK")

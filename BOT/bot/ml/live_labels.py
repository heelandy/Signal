"""Post-trade learning queue → training feed (AITP-001 §18 / MLP-001 missed-outcome labels).

Every tracked live signal (auto-shadowed or manually taken/skipped) that has a RESOLVED
first-touch outcome becomes a training-ready row: the PIT feature snapshot that rode with the
decision + the realized label. Taken rows are live executions; skipped rows are MISSED outcomes
(missed_winner / missed_loser) — the live twin of the historical rejects store.

    from bot.ml.live_labels import build_live_labels
    df = build_live_labels()        # -> FeatureStore 'live_outcomes' + returns the frame
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from bot.ml.features_pit import FEATURE_COLUMNS
from bot.ml.registry import FeatureStore

OUTCOME_R = {"tp2": None, "tp1": None, "stop": None}     # result_r column is authoritative


def build_live_labels(save: bool = True) -> pd.DataFrame:
    """Resolved tracker decisions -> labeled rows. Rows without a stored PIT snapshot still land
    (features NaN) so the outcome record is never lost; they upgrade once the scan stores
    snapshots (2026-07-04 onward)."""
    from bot.tracker import _con
    con = _con()
    rows = con.execute(
        "SELECT symbol, side, family, session, taken, outcome, result_r, mfe_r, mae_r,"
        " signal_at, decided_at, json, strategy_version FROM decisions "
        "WHERE outcome NOT IN ('open')").fetchall()
    con.close()
    out = []
    for sym, side, fam, sess, taken, outcome, result_r, mfe_r, mae_r, sig_at, dec_at, raw, sv in rows:
        try:
            sig = json.loads(raw or "{}")
        except Exception:
            sig = {}
        pit = sig.get("pit_features") or {}
        r = float(result_r) if result_r is not None else np.nan
        rec = {"ts": sig_at or dec_at, "symbol": sym, "side": side, "family": fam,
               # P1.1: the row's OWN immutable version rides into training (never back-stamped)
               "strategy_version": sv or sig.get("strategy_version") or "unknown",
               "session": sess, "taken": int(taken or 0), "outcome": outcome,
               "tf": sig.get("tf") or sig.get("timeframe") or "5m",   # capture timeframe (journal->training-lab tf match)
               **{k: pit.get(k, np.nan) for k in FEATURE_COLUMNS},
               "net_r": r, "mfe_r": mfe_r, "mae_r": mae_r,
               "y_win": int(r > 0) if r == r else None,
               "missed_winner": int((not taken) and r == r and r > 0),
               "missed_loser": int((not taken) and r == r and r <= 0)}
        out.append(rec)
    df = pd.DataFrame(out)
    if len(df):
        df = df.sort_values("ts").reset_index(drop=True)
        if save:
            FeatureStore().save("live_outcomes", "v1", df)
    return df


def summary() -> dict:
    df = build_live_labels(save=False)
    if not len(df):
        return {"rows": 0}
    taken = df[df["taken"] == 1]
    skipped = df[df["taken"] == 0]
    return {"rows": int(len(df)),
            "taken": int(len(taken)),
            "taken_win_rate": round(float((taken["net_r"] > 0).mean()), 3) if len(taken) else None,
            "skipped": int(len(skipped)),
            "missed_winners": int(df["missed_winner"].sum()),
            "missed_losers": int(df["missed_loser"].sum()),
            "with_features": int(df[FEATURE_COLUMNS[0]].notna().sum())}


if __name__ == "__main__":
    s = summary()
    df = build_live_labels()
    print(f"live_outcomes: {s}")
    print("live labels OK")

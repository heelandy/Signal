"""Model registry + champion–challenger + feature store (ML-001/003/004/006).

- FeatureStore: versioned feature matrices on disk (parquet) for training/replay parity.
- ModelRegistry: persist models (pickle) + JSON metadata; track the live "champion" per name.
- ChampionChallenger: a challenger only replaces the champion if it beats it OOS by a margin
  (continuous-learning promotion gate). Models never gain trade authority — they advise sizing.
"""
from __future__ import annotations

import json
import pickle
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd

from bot.config import BOT_ROOT
from bot.ml.validation import auc

ML_DIR = BOT_ROOT / "data" / "ml"
REPORTS_DIR = ML_DIR / "reports"


def _jsonable(x):
    """Deep-convert numpy scalars/arrays and NaN to JSON-safe values (NaN -> None so the
    dashboard's JSON.parse never chokes)."""
    if isinstance(x, dict):
        return {k: _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, np.ndarray):
        return _jsonable(x.tolist())
    if isinstance(x, (np.floating, float)):
        f = float(x)
        return None if f != f else f
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def save_report(kind: str, sym: str, report: dict) -> Path:
    """Persist a training run report (ml|nn) — the training dashboard's raw material."""
    from bot.contracts import utcnow_iso
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = utcnow_iso().replace(":", "").replace("-", "")[:15]
    p = REPORTS_DIR / f"{kind}_{sym}_{ts}.json"
    body = {"kind": kind, "sym": sym, "created_at": utcnow_iso(), **_jsonable(report)}
    p.write_text(json.dumps(body, indent=1), encoding="utf-8")
    return p


def list_reports() -> list[dict]:
    """Newest-first index of saved training reports (headline fields only)."""
    if not REPORTS_DIR.exists():
        return []
    out = []
    for p in sorted(REPORTS_DIR.glob("*.json"), key=lambda q: q.stat().st_mtime, reverse=True):
        if p.stem.startswith("ab_"):                 # the A/B study has its own endpoint/panel
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("created_at") is None:              # un-timestamped STUDY reports (phase78/gauntlet/
            continue                                 # sweep/...) have their own panels; phase78 re-saves
                                                     # hourly so by mtime it hijacked the "latest run" slot
        out.append({"name": p.stem, "kind": d.get("kind", p.stem.split("_")[0]),
                    "sym": d.get("sym"), "created_at": d.get("created_at"),
                    "oos_auc": d.get("oos_auc"), "oos_brier": d.get("oos_brier"),
                    "best": d.get("best"), "promote": d.get("promote"),
                    "samples": d.get("samples") or d.get("sequences"),
                    "reason": d.get("reason")})
    return out


def load_report(name: str) -> dict | None:
    p = REPORTS_DIR / f"{name}.json"
    if not p.exists() or p.parent.resolve() != REPORTS_DIR.resolve():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


class FeatureStore:
    def __init__(self, root: Path = ML_DIR / "features"):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)

    def save(self, name: str, version: str, df: pd.DataFrame) -> Path:
        p = self.root / f"{name}__{version}.parquet"
        df.to_parquet(p, index=False)
        return p

    def load(self, name: str, version: str) -> pd.DataFrame:
        return pd.read_parquet(self.root / f"{name}__{version}.parquet")

    def versions(self, name: str) -> list[str]:
        return sorted(p.stem.split("__")[1] for p in self.root.glob(f"{name}__*.parquet"))


@dataclass
class ModelMeta:
    name: str
    version: str
    metrics: dict
    champion: bool = False
    created_at: str = ""
    features: list | None = None        # feature schema the model was trained on (ML-011)
    strategy_version: str | None = None  # the rule version the labels came from (one rule at a time)


class ModelRegistry:
    def __init__(self, root: Path = ML_DIR / "models"):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)

    def _paths(self, name, version):
        return self.root / f"{name}__{version}.pkl", self.root / f"{name}__{version}.json"

    def register(self, model, name: str, version: str, metrics: dict, champion: bool = False,
                 features: list | None = None, strategy_version: str | None = None) -> ModelMeta:
        from bot.contracts import utcnow_iso
        pkl, js = self._paths(name, version)
        pkl.write_bytes(pickle.dumps(model))
        meta = ModelMeta(name, version, metrics, champion, utcnow_iso(),
                         features=features, strategy_version=strategy_version)
        js.write_text(json.dumps(asdict(meta)), encoding="utf-8")
        if champion:
            self._set_champion(name, version)
        try:
            from bot.audit import log as _audit
            _audit("model_registered", name=name, version=version, champion=champion,
                   metrics={k: v for k, v in metrics.items() if not isinstance(v, dict)},
                   strategy_version=strategy_version)
        except Exception:
            pass
        return meta

    def load(self, name: str, version: str):
        pkl, _ = self._paths(name, version)
        return pickle.loads(pkl.read_bytes())

    def list(self, name: str | None = None) -> list[ModelMeta]:
        out = []
        for js in self.root.glob("*.json"):
            d = json.loads(js.read_text(encoding="utf-8"))
            if name is None or d["name"] == name:
                out.append(ModelMeta(**d))
        return sorted(out, key=lambda m: m.created_at)

    def _set_champion(self, name: str, version: str) -> None:
        for js in self.root.glob(f"{name}__*.json"):
            d = json.loads(js.read_text(encoding="utf-8"))
            d["champion"] = (d["version"] == version)
            js.write_text(json.dumps(d), encoding="utf-8")

    def champion(self, name: str):
        for m in self.list(name):
            if m.champion:
                return self.load(name, m.version), m
        return None, None

    def promote(self, name: str, version: str) -> bool:
        """MANUAL promotion (AITP governance): make a registered pending model the champion."""
        _, js = self._paths(name, version)
        if not js.exists():
            return False
        self._set_champion(name, version)
        try:
            from bot.audit import log as _audit
            _audit("model_promoted", name=name, version=version, by="user")
        except Exception:
            pass
        return True


class ChampionChallenger:
    def __init__(self, registry: ModelRegistry, margin: float = 0.01):
        self.reg = registry; self.margin = margin

    def evaluate(self, name: str, challenger, X_test, y_test) -> dict:
        ch_auc = auc(y_test, challenger.predict_proba(X_test))
        champ, meta = self.reg.champion(name)
        cm_auc = auc(y_test, champ.predict_proba(X_test)) if champ is not None else 0.0
        promote = champ is None or (ch_auc - cm_auc) >= self.margin
        return {"challenger_auc": round(float(ch_auc), 3), "champion_auc": round(float(cm_auc), 3),
                "promote": bool(promote)}

    def maybe_promote(self, name: str, version: str, challenger, X_test, y_test) -> dict:
        res = self.evaluate(name, challenger, X_test, y_test)
        if res["promote"]:
            self.reg.register(challenger, name, version, {"oos_auc": res["challenger_auc"]}, champion=True)
        return res


if __name__ == "__main__":
    import tempfile
    from bot.ml.predictor import DirectionModel
    rng = np.random.default_rng(2)
    n = 500; X = rng.normal(size=(n, 6))
    y = (X[:, 0] + 0.5 * X[:, 2] + rng.normal(scale=0.4, size=n) > 0).astype(int)
    Xtr, ytr, Xte, yte = X[:400], y[:400], X[400:], y[400:]
    tmp = Path(tempfile.mkdtemp())
    fs = FeatureStore(tmp / "f"); fs.save("orb", "1", pd.DataFrame(X, columns=[f"f{i}" for i in range(6)]))
    assert fs.versions("orb") == ["1"]

    reg = ModelRegistry(tmp / "m")
    champ = DirectionModel(epochs=300).fit(Xtr[:200], ytr[:200])     # weaker champion (less data)
    reg.register(champ, "orb", "1.0", {"oos_auc": 0.7}, champion=True)
    challenger = DirectionModel(epochs=800).fit(Xtr, ytr)            # stronger challenger
    cc = ChampionChallenger(reg)
    res = cc.maybe_promote("orb", "2.0", challenger, Xte, yte)
    print("champion-challenger:", res)
    _, meta = reg.champion("orb")
    print("live champion now:", meta.version, "| registry has", len(reg.list("orb")), "models")
    print("ml registry/feature-store/champion-challenger OK")

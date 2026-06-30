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


class ModelRegistry:
    def __init__(self, root: Path = ML_DIR / "models"):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)

    def _paths(self, name, version):
        return self.root / f"{name}__{version}.pkl", self.root / f"{name}__{version}.json"

    def register(self, model, name: str, version: str, metrics: dict, champion: bool = False) -> ModelMeta:
        from bot.contracts import utcnow_iso
        pkl, js = self._paths(name, version)
        pkl.write_bytes(pickle.dumps(model))
        meta = ModelMeta(name, version, metrics, champion, utcnow_iso())
        js.write_text(json.dumps(asdict(meta)), encoding="utf-8")
        if champion:
            self._set_champion(name, version)
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

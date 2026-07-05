"""NN similarity clusters (MLP-001 §9) — "does this setup look like past WINNERS or past chop?"

Pattern clusters over the candle-sequence dataset: sequences are standardized, PCA-compressed and
K-means clustered on TRAINING history only; each cluster carries its historical win-rate and
average net R. A new rule-valid setup is scored by its nearest cluster — an interpretable
similarity read ("this looks like cluster 3: 44% winners, +0.31R") next to the NN probability.

Honesty: clusters are fit on the FIRST 70% of sequences (chronological); the OOS 30% verifies the
cluster win-rate SPREAD holds forward (best-vs-worst cluster spread must stay positive).

    python -m bot.nn.similarity ALL
"""
from __future__ import annotations

import numpy as np

from bot.ml.registry import ModelRegistry, save_report

_reg = ModelRegistry()
N_CLUSTERS = 6
PCA_DIMS = 24
TRAIN_FRAC = 0.70


class SequenceClusters:
    """PCA + KMeans over flattened sequences + per-cluster outcome stats. predict_proba returns
    the cluster's TRAIN win-rate for each sequence (registry-compatible advisory score)."""

    def __init__(self, n_clusters: int = N_CLUSTERS, dims: int = PCA_DIMS, seed: int = 7):
        self.n_clusters, self.dims, self.seed = n_clusters, dims, seed
        self.pca = self.km = None
        self.mu = self.sd = None
        self.stats: dict = {}
        self.name = "seq_clusters"

    def _flat(self, X):
        X = np.asarray(X, np.float32)
        return X.reshape(len(X), -1)

    def fit(self, X, y, net_r):
        from sklearn.decomposition import PCA
        from sklearn.cluster import KMeans
        F = self._flat(X)
        self.mu, self.sd = F.mean(0), F.std(0) + 1e-8
        Z = (F - self.mu) / self.sd
        self.pca = PCA(n_components=min(self.dims, Z.shape[1], len(Z) - 1), random_state=self.seed)
        E = self.pca.fit_transform(Z)
        self.km = KMeans(n_clusters=self.n_clusters, n_init=10, random_state=self.seed)
        lab = self.km.fit_predict(E)
        for c in range(self.n_clusters):
            m = lab == c
            self.stats[c] = {"n": int(m.sum()),
                             "win_rate": round(float(y[m].mean()), 3) if m.sum() else None,
                             "avg_r": round(float(net_r[m].mean()), 3) if m.sum() else None}
        return self

    def assign(self, X):
        Z = (self._flat(X) - self.mu) / self.sd
        return self.km.predict(self.pca.transform(Z))

    def predict_proba(self, X):
        lab = self.assign(X)
        return np.array([self.stats[int(c)]["win_rate"] or 0.0 for c in lab], float)


def train_similarity(sym: str = "ALL", window: int = 64) -> dict:
    from bot.nn.dataset import build_sequences, build_pooled_sequences
    ds = build_pooled_sequences(window=window) if sym.upper() == "ALL" else build_sequences(sym, window=window)
    X, y, net_r = ds["X"], ds["y"], ds["net_r"]
    if len(X) < 200:
        return {"error": f"only {len(X)} sequences"}
    k = int(TRAIN_FRAC * len(X))
    sc = SequenceClusters().fit(X[:k], y[:k], net_r[:k])
    # OOS verification: does the train-ranked best-vs-worst cluster spread hold forward?
    lab_oos = sc.assign(X[k:])
    oos_stats = {}
    for c in range(sc.n_clusters):
        m = lab_oos == c
        oos_stats[c] = {"n": int(m.sum()),
                        "win_rate": round(float(y[k:][m].mean()), 3) if m.sum() >= 10 else None,
                        "avg_r": round(float(net_r[k:][m].mean()), 3) if m.sum() >= 10 else None}
    ranked = sorted((c for c in sc.stats if sc.stats[c]["avg_r"] is not None),
                    key=lambda c: -sc.stats[c]["avg_r"])
    spread_ok = None
    if len(ranked) >= 2:
        best, worst = ranked[0], ranked[-1]
        b, w = oos_stats[best]["avg_r"], oos_stats[worst]["avg_r"]
        spread_ok = (b is not None and w is not None and b > w)
    rep = {"sym": sym.upper(), "sequences": int(len(X)), "window": window,
           "clusters_train": {str(c): v for c, v in sc.stats.items()},
           "clusters_oos": {str(c): v for c, v in oos_stats.items()},
           "oos_spread_holds": spread_ok,
           "strategy_version": ds["strategy_version"]}
    if spread_ok:
        version = f"{sym.upper()}-k{sc.n_clusters}-w{window}"
        _reg.register(sc, "nn_similarity", version,
                      {"oos_spread_holds": True, "gates_passed": True},
                      champion=True,          # advisory read, never trades — safe to serve
                      features=[f"seq:{window}"], strategy_version=ds["strategy_version"])
        rep["version"] = version
        rep["promote"] = True
    else:
        rep["promote"] = False
        rep["reason"] = "best-vs-worst cluster spread does not hold out-of-sample"
    try:
        save_report("similarity", sym.upper(), rep)
    except Exception:
        pass
    return rep


def similarity_score(seq: np.ndarray) -> dict | None:
    """Nearest-cluster read for one [window x channels] sequence (None = no fitted clusters)."""
    model, _ = _reg.champion("nn_similarity")
    if model is None:
        return None
    try:
        c = int(model.assign(seq[None, ...])[0])
        return {"cluster": c, **model.stats[c]}
    except Exception:
        return None


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "ALL"
    r = train_similarity(sym)
    for k, v in r.items():
        print(f"  {k}: {v}")
    print("similarity OK")

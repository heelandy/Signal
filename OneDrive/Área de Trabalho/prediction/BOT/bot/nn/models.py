"""NN model zoo (NN-002) — sequence classifiers behind the SAME fit/predict_proba interface as the
tabular zoo, so purged walk-forward, calibration, gates and the registry treat them identically.

Always available: NumpyMLP (dependency-free flatten-MLP baseline). With PyTorch installed (CPU
wheel in the venv as of 2026-07-04): MLP, 1D-CNN, GRU, LSTM, CNN-GRU hybrid. Transformer/TFT/MoE
stay on the research roadmap until these baselines prove out (development order rule §14).

Input X: float32 [N, T, C] sequence tensors from bot.nn.dataset. All models standardize channels
with TRAIN statistics and early-stop on a chronological validation tail — never shuffled splits.
"""
from __future__ import annotations

import numpy as np


class NumpyMLP:
    """Dependency-free 1-hidden-layer MLP on the flattened window (the honest baseline)."""

    def __init__(self, hidden: int = 32, lr: float = 0.05, epochs: int = 300,
                 l2: float = 1e-4, seed: int = 7):
        self.hidden, self.lr, self.epochs, self.l2, self.seed = hidden, lr, epochs, l2, seed
        self.W1 = self.b1 = self.W2 = self.b2 = None
        self.mu = self.sd = None
        self.name = "np_mlp"

    def _flat(self, X):
        X = np.asarray(X, np.float64)
        return X.reshape(len(X), -1)

    def fit(self, X, y):
        rng = np.random.default_rng(self.seed)
        Xf = self._flat(X)
        self.mu, self.sd = Xf.mean(0), Xf.std(0) + 1e-9
        Xs = (Xf - self.mu) / self.sd
        y = np.asarray(y, np.float64)
        n, d = Xs.shape
        h = self.hidden
        self.W1 = rng.normal(0, 1 / np.sqrt(d), (d, h)); self.b1 = np.zeros(h)
        self.W2 = rng.normal(0, 1 / np.sqrt(h), h); self.b2 = 0.0
        for _ in range(self.epochs):
            z1 = Xs @ self.W1 + self.b1
            a1 = np.tanh(z1)
            p = 1 / (1 + np.exp(-(a1 @ self.W2 + self.b2)))
            g = (p - y) / n
            gW2 = a1.T @ g + self.l2 * self.W2
            gb2 = g.sum()
            ga1 = np.outer(g, self.W2) * (1 - a1 ** 2)
            gW1 = Xs.T @ ga1 + self.l2 * self.W1
            gb1 = ga1.sum(0)
            self.W2 -= self.lr * gW2; self.b2 -= self.lr * gb2
            self.W1 -= self.lr * gW1; self.b1 -= self.lr * gb1
        return self

    def predict_proba(self, X):
        Xs = (self._flat(X) - self.mu) / self.sd
        a1 = np.tanh(Xs @ self.W1 + self.b1)
        return 1 / (1 + np.exp(-(a1 @ self.W2 + self.b2)))


def _torch_available() -> bool:
    try:
        import torch  # noqa: F401
        return True
    except ImportError:
        return False


class TorchSeqModel:
    """Uniform torch wrapper: channel standardization (train stats) + early stopping on the
    chronological tail + BCE. arch: mlp | cnn | gru | lstm | cnn_gru."""

    def __init__(self, arch: str = "gru", hidden: int = 32, epochs: int = 80, lr: float = 1e-3,
                 batch: int = 64, patience: int = 10, val_frac: float = 0.15, seed: int = 7):
        self.arch, self.hidden, self.epochs, self.lr = arch, hidden, epochs, lr
        self.batch, self.patience, self.val_frac, self.seed = batch, patience, val_frac, seed
        self.net = None
        self.mu = self.sd = None
        self.name = f"torch_{arch}"

    def _build(self, T: int, C: int):
        import torch.nn as nn

        class GAP(nn.Module):
            def forward(self, x):                       # [N, C, T] -> [N, C]
                return x.mean(dim=-1)

        class TakeLast(nn.Module):
            def forward(self, x):                       # rnn output tuple -> last hidden step
                out, _ = x
                return out[:, -1, :]

        h = self.hidden
        if self.arch == "mlp":
            return nn.Sequential(nn.Flatten(), nn.Linear(T * C, 2 * h), nn.ReLU(),
                                 nn.Dropout(0.3), nn.Linear(2 * h, h), nn.ReLU(), nn.Linear(h, 1))
        if self.arch == "cnn":
            return nn.Sequential(_Transpose(), nn.Conv1d(C, h, 5, padding=2), nn.ReLU(),
                                 nn.Conv1d(h, h, 3, padding=1), nn.ReLU(), GAP(),
                                 nn.Dropout(0.3), nn.Linear(h, 1))
        if self.arch in ("gru", "lstm"):
            rnn = (nn.GRU if self.arch == "gru" else nn.LSTM)(C, h, batch_first=True)
            return nn.Sequential(_RNNWrap(rnn), nn.Dropout(0.3), nn.Linear(h, 1))
        if self.arch == "cnn_gru":
            return _CnnGru(C, h)
        if self.arch == "transformer":
            return _SeqTransformer(T, C, h)
        if self.arch == "moe":
            return _MoE(C, h)
        raise ValueError(f"unknown arch {self.arch}")

    def fit(self, X, y):
        import torch
        import torch.nn as nn
        torch.manual_seed(self.seed)
        X = np.asarray(X, np.float32)
        y = np.asarray(y, np.float32)
        # channel standardization with TRAIN statistics only
        self.mu = X.mean(axis=(0, 1), keepdims=True)
        self.sd = X.std(axis=(0, 1), keepdims=True) + 1e-8
        Xs = (X - self.mu) / self.sd
        k = max(int(len(Xs) * (1 - self.val_frac)), 1)      # chronological tail = validation
        Xtr, ytr, Xva, yva = Xs[:k], y[:k], Xs[k:], y[k:]
        self.net = self._build(X.shape[1], X.shape[2])
        opt = torch.optim.Adam(self.net.parameters(), lr=self.lr, weight_decay=1e-4)
        lossf = nn.BCEWithLogitsLoss()
        tX = torch.from_numpy(Xtr); ty = torch.from_numpy(ytr)
        vX = torch.from_numpy(Xva) if len(Xva) else None
        vy = torch.from_numpy(yva) if len(Xva) else None
        best, best_state, bad = float("inf"), None, 0
        for _ in range(self.epochs):
            self.net.train()
            perm = torch.randperm(len(tX))
            for b in range(0, len(tX), self.batch):
                idx = perm[b:b + self.batch]
                opt.zero_grad()
                out = self.net(tX[idx]).squeeze(-1)
                loss = lossf(out, ty[idx])
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.net.parameters(), 1.0)
                opt.step()
            if vX is not None and len(vX) >= 10:
                self.net.eval()
                with torch.no_grad():
                    vloss = float(lossf(self.net(vX).squeeze(-1), vy))
                if vloss < best - 1e-4:
                    best, bad = vloss, 0
                    best_state = {k2: v.clone() for k2, v in self.net.state_dict().items()}
                else:
                    bad += 1
                    if bad >= self.patience:
                        break
        if best_state is not None:
            self.net.load_state_dict(best_state)
        return self

    def predict_proba(self, X):
        import torch
        X = (np.asarray(X, np.float32) - self.mu) / self.sd
        self.net.eval()
        with torch.no_grad():
            logits = self.net(torch.from_numpy(X)).squeeze(-1).numpy()
        return 1 / (1 + np.exp(-logits))


if _torch_available():
    import torch.nn as _nn

    class _Transpose(_nn.Module):
        def forward(self, x):                            # [N, T, C] -> [N, C, T] for Conv1d
            return x.transpose(1, 2)

    class _RNNWrap(_nn.Module):
        def __init__(self, rnn):
            super().__init__()
            self.rnn = rnn

        def forward(self, x):
            out, _ = self.rnn(x)
            return out[:, -1, :]

    class _CnnGru(_nn.Module):
        """CNN front-end for local candle patterns -> GRU for sequence memory (the hybrid)."""

        def __init__(self, C, h):
            super().__init__()
            self.conv = _nn.Sequential(_Transpose(), _nn.Conv1d(C, h, 5, padding=2), _nn.ReLU())
            self.gru = _nn.GRU(h, h, batch_first=True)
            self.head = _nn.Sequential(_nn.Dropout(0.3), _nn.Linear(h, 1))

        def forward(self, x):
            z = self.conv(x).transpose(1, 2)             # back to [N, T, h]
            out, _ = self.gru(z)
            return self.head(out[:, -1, :])

    class _SeqTransformer(_nn.Module):
        """Small Transformer encoder (research ladder step after RNNs prove out): learned
        positional embedding + 2 encoder layers + mean-pool head. Deliberately tiny — big
        attention models overfit a few thousand trade sequences."""

        def __init__(self, T, C, h):
            super().__init__()
            self.inp = _nn.Linear(C, h)
            self.pos = _nn.Parameter(__import__("torch").zeros(1, T, h))
            layer = _nn.TransformerEncoderLayer(d_model=h, nhead=4, dim_feedforward=2 * h,
                                                dropout=0.2, batch_first=True)
            self.enc = _nn.TransformerEncoder(layer, num_layers=2)
            self.head = _nn.Sequential(_nn.Dropout(0.3), _nn.Linear(h, 1))

        def forward(self, x):
            z = self.enc(self.inp(x) + self.pos[:, :x.shape[1], :])
            return self.head(z.mean(dim=1))

    class _MoE(_nn.Module):
        """Mixture-of-experts: 3 GRU experts + a softmax gate over the sequence summary —
        the gate learns WHICH regime expert to trust (MLP-001 'Mixture of Experts by regime')."""

        def __init__(self, C, h, n_exp: int = 3):
            super().__init__()
            self.experts = _nn.ModuleList([_nn.GRU(C, h, batch_first=True) for _ in range(n_exp)])
            self.heads = _nn.ModuleList([_nn.Linear(h, 1) for _ in range(n_exp)])
            self.gate = _nn.Sequential(_nn.Linear(C, h), _nn.ReLU(), _nn.Linear(h, n_exp))

        def forward(self, x):
            import torch
            g = torch.softmax(self.gate(x.mean(dim=1)), dim=-1)          # [N, n_exp]
            outs = []
            for rnn, head in zip(self.experts, self.heads):
                o, _ = rnn(x)
                outs.append(head(o[:, -1, :]))
            return (torch.stack(outs, dim=-1).squeeze(1) * g).sum(dim=-1, keepdim=True)


def nn_zoo() -> dict:
    """Name -> zero-arg factory for every sequence model available in this environment."""
    zoo = {"np_mlp": lambda: NumpyMLP()}
    if _torch_available():
        for arch in ("mlp", "cnn", "gru", "lstm", "cnn_gru", "transformer", "moe"):
            zoo[f"torch_{arch}"] = (lambda a=arch: TorchSeqModel(arch=a))
    return zoo


if __name__ == "__main__":   # self-test: every model learns a synthetic trend-vs-chop task
    rng = np.random.default_rng(5)
    n, T, C = 400, 32, 6
    y = rng.integers(0, 2, n)
    X = rng.normal(0, 1, (n, T, C)).astype(np.float32)
    drift = np.linspace(0, 1.5, T)
    X[:, :, 0] += np.where(y[:, None] == 1, drift, -drift)   # winners trend up in channel 0
    for name, factory in nn_zoo().items():
        m = factory().fit(X[:320], y[:320])
        p = m.predict_proba(X[320:])
        acc = ((p > 0.5).astype(int) == y[320:]).mean()
        assert acc > 0.7, (name, acc)
        print(f"  {name:10} OOS acc {acc:.1%}")
    print("nn models OK")

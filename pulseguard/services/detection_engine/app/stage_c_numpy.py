"""Stage C inference without PyTorch: the trained GRU's forward pass in
NumPy, so the live detection engine does not need torch at runtime.

Why: the CUDA-bundled torch wheel costs ~700 MB of resident memory just to
import, which alone would blow the whole stack's 1.5 GB budget. Training
still uses torch (train_stage_c.py); training writes the weights to
`stage_c.npz` next to `stage_c.pt`, and this module reproduces
torch.nn.GRU's equations exactly (test_stage_c_numpy_parity.py pins the
outputs to torch's within float tolerance).

torch.nn.GRU, per layer and step (gate order r, z, n in the stacked weights):
    r  = sigmoid(W_ir x + b_ir + W_hr h + b_hr)
    z  = sigmoid(W_iz x + b_iz + W_hz h + b_hz)
    n  = tanh(W_in x + b_in + r * (W_hn h + b_hn))
    h' = (1 - z) * n + z * h
Dropout between layers is training-only. With packed sequences only the
first `length` steps are consumed; the top layer's last hidden state feeds
the linear classifier.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


class StageCNumpy:
    def __init__(self, weights: dict[str, np.ndarray]):
        self.layers = []
        layer = 0
        while f"gru.weight_ih_l{layer}" in weights:
            self.layers.append(tuple(np.asarray(weights[f"gru.{n}_l{layer}"], dtype=np.float64)
                                     for n in ("weight_ih", "weight_hh", "bias_ih", "bias_hh")))
            layer += 1
        if not self.layers:
            raise ValueError("no GRU layers in weights")
        self.hidden = self.layers[0][1].shape[1]
        self.w_out = np.asarray(weights["classifier.weight"], dtype=np.float64)
        self.b_out = np.asarray(weights["classifier.bias"], dtype=np.float64)

    @classmethod
    def load(cls, path: Path) -> "StageCNumpy":
        with np.load(path) as data:
            return cls({k: data[k] for k in data.files})

    def logit(self, seq: np.ndarray, length: int) -> float:
        x = np.asarray(seq, dtype=np.float64)[: max(1, int(length))]
        for w_ih, w_hh, b_ih, b_hh in self.layers:
            h = np.zeros(self.hidden)
            outputs = []
            gi_all = x @ w_ih.T + b_ih
            for gi in gi_all:
                gh = w_hh @ h + b_hh
                H = self.hidden
                r = _sigmoid(gi[:H] + gh[:H])
                z = _sigmoid(gi[H:2 * H] + gh[H:2 * H])
                n = np.tanh(gi[2 * H:] + r * gh[2 * H:])
                h = (1.0 - z) * n + z * h
                outputs.append(h)
            x = np.stack(outputs)
        return float((self.w_out @ h + self.b_out).reshape(-1)[0])

    def proba(self, seq: np.ndarray, length: int) -> float:
        return float(_sigmoid(np.array(self.logit(seq, length))))


def export_state_dict(state_dict, path: Path) -> None:
    """torch state_dict -> .npz (called from training, where torch exists)."""
    np.savez(path, **{k: v.detach().cpu().numpy() for k, v in state_dict.items()})

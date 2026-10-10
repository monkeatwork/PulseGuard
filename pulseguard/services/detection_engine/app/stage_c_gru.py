"""Stage C: GRU over the raw per-user event sequence (CLAUDE.md, L4
architecture: "catches low-and-slow"). Architecture per DECISIONS.md,
"Stage C (GRU) architecture": 2-layer, hidden_size=64, dropout 0.2, BCE
loss on the user-episode label. Sequence construction lives in
sequence_dataset.py — this module is the model definition only.
"""

from __future__ import annotations

import torch
import torch.nn as nn

from services.detection_engine.app.sequence_dataset import STEP_FEATURE_DIM

GRU_HIDDEN_SIZE = 64
GRU_NUM_LAYERS = 2
GRU_DROPOUT = 0.2


class StageCGRU(nn.Module):
    def __init__(
        self,
        input_size: int = STEP_FEATURE_DIM,
        hidden_size: int = GRU_HIDDEN_SIZE,
        num_layers: int = GRU_NUM_LAYERS,
        dropout: float = GRU_DROPOUT,
    ):
        super().__init__()
        self.gru = nn.GRU(
            input_size,
            hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.classifier = nn.Linear(hidden_size, 1)

    def forward(self, x: torch.Tensor, lengths: torch.Tensor) -> torch.Tensor:
        """`x`: (batch, seq_len, input_size), zero-padded at the end.
        `lengths`: (batch,) true sequence lengths, each >= 1. Returns raw
        logits of shape (batch,) — apply sigmoid for a probability."""
        packed = nn.utils.rnn.pack_padded_sequence(
            x, lengths.cpu(), batch_first=True, enforce_sorted=False
        )
        _, h_n = self.gru(packed)
        last_layer_hidden = h_n[-1]  # (batch, hidden_size): top layer's final hidden state
        logits = self.classifier(last_layer_hidden).squeeze(-1)
        return logits

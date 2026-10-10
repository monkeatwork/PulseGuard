"""The NumPy GRU used live must reproduce the torch GRU used in training."""

from __future__ import annotations

import numpy as np
import torch

from services.detection_engine.app.sequence_dataset import SEQUENCE_LENGTH, STEP_FEATURE_DIM
from services.detection_engine.app.stage_c_gru import StageCGRU
from services.detection_engine.app.stage_c_numpy import StageCNumpy, export_state_dict


def test_numpy_forward_matches_torch(tmp_path):
    torch.manual_seed(3)
    model = StageCGRU()
    model.eval()
    path = tmp_path / "stage_c.npz"
    export_state_dict(model.state_dict(), path)
    np_model = StageCNumpy.load(path)

    rng = np.random.default_rng(0)
    for length in (1, 2, 7, SEQUENCE_LENGTH):
        seq = np.zeros((SEQUENCE_LENGTH, STEP_FEATURE_DIM), dtype=np.float32)
        seq[:length] = rng.random((length, STEP_FEATURE_DIM))
        with torch.no_grad():
            expected = model(torch.tensor(seq[None]), torch.tensor([length])).item()
        assert abs(np_model.logit(seq, length) - expected) < 1e-4

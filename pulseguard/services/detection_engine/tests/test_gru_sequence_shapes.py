"""Stage C GRU shape/masking tests, including sequences shorter than
SEQUENCE_LENGTH (per the Phase 5 plan gate)."""

from __future__ import annotations

import torch

from services.detection_engine.app.sequence_dataset import SEQUENCE_LENGTH, STEP_FEATURE_DIM
from services.detection_engine.app.stage_c_gru import StageCGRU


def test_forward_pass_produces_one_logit_per_batch_item():
    model = StageCGRU()
    batch_size = 8
    x = torch.randn(batch_size, SEQUENCE_LENGTH, STEP_FEATURE_DIM)
    lengths = torch.full((batch_size,), SEQUENCE_LENGTH, dtype=torch.long)
    logits = model(x, lengths)
    assert logits.shape == (batch_size,)


def test_forward_pass_handles_variable_length_sequences_including_length_one():
    model = StageCGRU()
    x = torch.randn(4, SEQUENCE_LENGTH, STEP_FEATURE_DIM)
    lengths = torch.tensor([1, 5, 20, 12], dtype=torch.long)
    logits = model(x, lengths)
    assert logits.shape == (4,)
    assert torch.isfinite(logits).all()


def test_padding_beyond_length_does_not_affect_output():
    """Two sequences identical up to their true length, differing only in
    the zero-padded tail, must produce identical logits -- proving the
    padding mask (via pack_padded_sequence) actually works."""
    model = StageCGRU()
    model.eval()

    base = torch.randn(1, SEQUENCE_LENGTH, STEP_FEATURE_DIM)
    length = 7
    seq_a = base.clone()
    seq_a[:, length:, :] = 0.0
    seq_b = base.clone()
    seq_b[:, length:, :] = torch.randn(1, SEQUENCE_LENGTH - length, STEP_FEATURE_DIM)  # garbage padding

    lengths = torch.tensor([length])
    with torch.no_grad():
        logits_a = model(seq_a, lengths)
        logits_b = model(seq_b, lengths)

    assert torch.allclose(logits_a, logits_b, atol=1e-5)


def test_model_output_dtype_and_no_nans():
    model = StageCGRU()
    x = torch.randn(3, SEQUENCE_LENGTH, STEP_FEATURE_DIM)
    lengths = torch.tensor([SEQUENCE_LENGTH, 3, 1], dtype=torch.long)
    logits = model(x, lengths)
    assert logits.dtype == torch.float32
    assert not torch.isnan(logits).any()

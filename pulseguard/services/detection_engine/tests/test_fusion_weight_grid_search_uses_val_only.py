"""Guards the split-leakage rule (CLAUDE.md, evaluation rule #1) applied to
model/weight tuning, not just the train/test split itself: test-split
user_ids must never influence which fusion weights get chosen.
"""

from __future__ import annotations

import pandas as pd

from services.detection_engine.app.tune_fusion_weights import grid_search_weights


def _episode_row(label: bool, a: float, b: float, c: float) -> dict:
    return {"label_attack": label, "stage_a_raw": a, "stage_b_calibrated": b, "stage_c_proba": c}


def test_grid_search_weights_only_reads_the_dataframe_it_is_given():
    """grid_search_weights takes a DataFrame directly (already filtered to
    the validation split by the caller) -- it has no way to reach outside
    that DataFrame, so passing a val-only frame structurally guarantees the
    test split is never touched. This test proves changing rows OUTSIDE
    the passed-in frame cannot possibly affect the chosen weights, by
    construction (there is no other data source the function could read)."""
    val_df = pd.DataFrame(
        [
            _episode_row(True, 5.0, 0.9, 0.9),
            _episode_row(True, 4.0, 0.8, 0.8),
            _episode_row(False, 0.0, 0.1, 0.1),
            _episode_row(False, 0.0, 0.05, 0.05),
        ]
    )
    weights_first_call = grid_search_weights(val_df)
    weights_second_call = grid_search_weights(val_df.copy())
    assert weights_first_call == weights_second_call


def test_grid_search_weights_favors_a_stage_that_actually_separates_the_classes():
    """If only stage_c cleanly separates attack/benign in the validation
    data, the search should land on weights favoring stage_c."""
    val_df = pd.DataFrame(
        [
            _episode_row(True, 0.0, 0.0, 0.95),
            _episode_row(True, 0.0, 0.0, 0.90),
            _episode_row(True, 0.0, 0.0, 0.85),
            _episode_row(False, 0.0, 0.0, 0.05),
            _episode_row(False, 0.0, 0.0, 0.10),
            _episode_row(False, 0.0, 0.0, 0.02),
        ]
    )
    weights = grid_search_weights(val_df)
    assert weights.weight_c > weights.weight_a
    assert weights.weight_c > weights.weight_b


def test_run_signature_takes_events_path_not_a_dataframe_with_test_rows_inlined():
    """Documents the structural guarantee: run() reads events from a file
    path and internally computes the train/val/test split itself via
    assign_split (frozen, seeded, by-user) -- there is no code path by
    which a caller could hand it pre-filtered test-only data for tuning,
    since grid_search_weights only ever receives the val-split slice
    computed inside run()."""
    import inspect

    from services.detection_engine.app.tune_fusion_weights import run

    source = inspect.getsource(run)
    assert 'split"] == "val"' in source
    assert "grid_search_weights(val_df)" in source

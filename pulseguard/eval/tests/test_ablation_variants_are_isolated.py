"""Confirms the ablation actually excludes the ablated feature from the
model's input matrix (not just "untrained-on-it") -- otherwise the
ablation wouldn't be measuring what it claims to."""

from __future__ import annotations

from eval.ablation.run_ablation import RESPONSE_BEHAVIOUR_ONLY_EXCLUDED, VARIANTS
from services.detection_engine.app.feature_table import FEATURE_COLUMNS, FREQUENCY_COLUMNS, to_model_matrix


def test_frequency_only_variant_excludes_all_response_behaviour_columns():
    from services.detection_engine.app.feature_table import RESPONSE_BEHAVIOUR_COLUMNS

    columns = VARIANTS["frequency_only"]
    assert columns == FREQUENCY_COLUMNS
    for col in RESPONSE_BEHAVIOUR_COLUMNS:
        assert col not in columns


def test_full_variant_includes_every_feature_column():
    assert set(VARIANTS["frequency_plus_response_behaviour"]) == set(FEATURE_COLUMNS)


def test_minus_slope_variant_excludes_only_the_slope_columns():
    columns = VARIANTS["response_behaviour_minus_latency_drift_slope"]
    for excluded in RESPONSE_BEHAVIOUR_ONLY_EXCLUDED:
        assert excluded not in columns
    # every other feature column, including the other response-behaviour
    # ones, must still be present
    other_columns = [c for c in FEATURE_COLUMNS if c not in RESPONSE_BEHAVIOUR_ONLY_EXCLUDED]
    assert set(columns) == set(other_columns)


def test_to_model_matrix_actually_drops_the_excluded_columns_from_the_dataframe():
    import pandas as pd

    fake_table = pd.DataFrame(
        [
            {c: 0.0 for c in FEATURE_COLUMNS},
        ]
    )
    minus_slope_columns = VARIANTS["response_behaviour_minus_latency_drift_slope"]
    matrix = to_model_matrix(fake_table, minus_slope_columns)

    for excluded in RESPONSE_BEHAVIOUR_ONLY_EXCLUDED:
        assert excluded not in matrix.columns, (
            f"{excluded} leaked into the model matrix despite being ablated"
        )

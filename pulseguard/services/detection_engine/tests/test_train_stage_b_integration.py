"""End-to-end test of train_stage_b.run() against a small synthetic events
DataFrame shaped like the generator's output -- catches wiring bugs
(feature_table -> split -> XGBoost -> calibration -> fused Stage A+B eval)
cheaply, before running the real ~50k-user corpus."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from services.detection_engine.app.train_stage_b import run

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _burst_rows(user_id, burst_id, label_attack, profile, pairs):
    rows = []
    for offset, decision, latency in pairs:
        prompt_ts = T0 + timedelta(seconds=offset)
        decision_ts = prompt_ts + timedelta(seconds=latency)
        rows.append(dict(user_id=user_id, ts=prompt_ts, event_type="mfa_prompt", decision=None,
                          decision_latency_ms=None, geo_country="US", device_id="d1",
                          label_attack=label_attack, attack_profile=profile, burst_id=burst_id))
        rows.append(dict(user_id=user_id, ts=decision_ts, event_type="mfa_decision", decision=decision,
                          decision_latency_ms=int(latency * 1000), geo_country="US", device_id="d1",
                          label_attack=label_attack, attack_profile=profile, burst_id=burst_id))
    return rows


def _synthetic_events(n_per_class: int) -> pd.DataFrame:
    rows = []
    for i in range(n_per_class):
        n = 10 + (i % 5)
        hv_pairs = [(j * 30, "deny" if j < n - 1 else "approve", 5.0 - j * 0.4) for j in range(n)]
        rows += _burst_rows(f"attacker{i}", f"burst_hv_{i}", True, "high_volume_burst", hv_pairs)

        bh_pairs = [(j * 1200, "approve", 4.0) for j in range(6)]
        rows += _burst_rows(f"poweruser{i}", f"burst_bh_{i}", False, None, bh_pairs)
    return pd.DataFrame(rows)


def test_train_stage_b_end_to_end_produces_valid_results(tmp_path: Path):
    events_df = _synthetic_events(n_per_class=200)
    events_path = tmp_path / "events.parquet"
    events_df.to_parquet(events_path)

    model_out = tmp_path / "model_registry" / "stage_b.json"
    results_dir = tmp_path / "results"

    results = run(events_path, seed=42, model_out=model_out, results_dir=results_dir)

    assert model_out.exists()
    assert (model_out.parent / "stage_b_calibrator.pkl").exists()
    assert (results_dir / "stage_ab.json").exists()

    assert results["n_bursts_evaluated"] > 0
    assert 0.0 <= results["overall"]["precision"] <= 1.0 if results["overall"]["precision"] is not None else True
    assert 0.0 <= results["overall"]["recall"] <= 1.0 if results["overall"]["recall"] is not None else True
    # high_volume_burst has a strong, learnable multi-event signature -- Stage
    # A+B should catch a meaningful share of it on held-out data
    assert results["by_profile"]["high_volume_burst"]["recall"] > 0.5

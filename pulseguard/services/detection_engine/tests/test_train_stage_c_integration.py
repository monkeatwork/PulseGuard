"""End-to-end test of train_stage_c.run() against a small synthetic events
DataFrame -- catches wiring bugs (sequence building -> split -> GRU
training -> threshold selection -> episode-level eval) cheaply."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from services.detection_engine.app.train_stage_c import run

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
        n = 8 + (i % 4)
        # low_and_slow-shaped: many denials, then one approve, widely paced
        ls_pairs = [(j * 1800, "deny" if j < n - 1 else "approve", 3.0 - j * 0.1) for j in range(n)]
        rows += _burst_rows(f"attacker{i}", f"burst_ls_{i}", True, "low_and_slow", ls_pairs)

        bh_pairs = [(j * 1200, "approve", 4.0) for j in range(6)]
        rows += _burst_rows(f"poweruser{i}", f"burst_bh_{i}", False, None, bh_pairs)
    return pd.DataFrame(rows)


def test_train_stage_c_end_to_end_produces_valid_results(tmp_path: Path):
    events_df = _synthetic_events(n_per_class=150)
    events_path = tmp_path / "events.parquet"
    events_df.to_parquet(events_path)

    model_out = tmp_path / "model_registry" / "stage_c.pt"
    results_dir = tmp_path / "results"

    results = run(events_path, seed=42, model_out=model_out, results_dir=results_dir)

    assert model_out.exists()
    assert (results_dir / "stage_c.json").exists()
    assert results["n_episodes_evaluated"] > 0
    for metric in ("precision", "recall", "fpr"):
        value = results["overall"][metric]
        assert value is None or 0.0 <= value <= 1.0

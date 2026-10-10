"""Tests the final report generator against synthetic fixture JSON files
(not the real eval/results/ output, so this test is self-contained and
doesn't depend on which real runs have or haven't been executed)."""

from __future__ import annotations

import json
from pathlib import Path

from eval.harness.report import build_final_report, render_adversarial_section, render_ablation_section, render_headline_comparison


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data))


def test_render_headline_comparison_includes_every_present_file(tmp_path: Path):
    _write(tmp_path / "baseline_splunk.json", {"overall": {"precision": 1.0, "recall": 0.3, "fpr": 0.0}, "n_bursts_evaluated": 100})
    _write(tmp_path / "stage_c.json", {"overall": {"precision": 1.0, "recall": 1.0, "fpr": 0.0}, "n_episodes_evaluated": 50})

    table = render_headline_comparison(tmp_path)
    assert "Splunk" in table
    assert "Stage C" in table
    assert "Elastic" not in table  # file doesn't exist, correctly skipped


def test_render_headline_comparison_handles_missing_files_gracefully(tmp_path: Path):
    table = render_headline_comparison(tmp_path)
    assert "Detector" in table  # header still renders even with zero data files


def test_render_ablation_section_flags_no_measurable_lift(tmp_path: Path):
    _write(
        tmp_path / "ablation.json",
        {
            "variants": {
                "frequency_only": {"n_features": 9, "overall": {"recall": 0.8, "precision": 0.5, "fpr": 0.5}},
                "frequency_plus_response_behaviour": {"n_features": 19, "overall": {"recall": 0.801, "precision": 0.9, "fpr": 0.03}},
            },
            "response_behaviour_lift_percentage_points": 0.1,
            "latency_drift_slope_lift_percentage_points": 0.0,
            "no_measurable_lift_response_behaviour": True,
            "no_measurable_lift_latency_drift_slope": True,
            "noise_floor_percentage_points": 2.0,
        },
    )
    section = render_ablation_section(tmp_path)
    assert "NO MEASURABLE LIFT" in section


def test_render_ablation_section_does_not_flag_a_real_lift(tmp_path: Path):
    _write(
        tmp_path / "ablation.json",
        {
            "variants": {
                "frequency_only": {"n_features": 9, "overall": {"recall": 0.5, "precision": 0.3, "fpr": 0.7}},
                "frequency_plus_response_behaviour": {"n_features": 19, "overall": {"recall": 0.9, "precision": 0.9, "fpr": 0.03}},
            },
            "response_behaviour_lift_percentage_points": 40.0,
            "latency_drift_slope_lift_percentage_points": 10.0,
            "no_measurable_lift_response_behaviour": False,
            "no_measurable_lift_latency_drift_slope": False,
            "noise_floor_percentage_points": 2.0,
        },
    )
    section = render_ablation_section(tmp_path)
    assert "NO MEASURABLE LIFT" not in section


def test_render_adversarial_section_reports_anti_dos_status(tmp_path: Path):
    _write(
        tmp_path / "adversarial.json",
        {
            "baselines": {"splunk": {"mimicry_adversarial": {"recall": 0.02}, "slow_pacing_adversarial": {"recall": 0.0}}},
            "stage_ab": {"mimicry_adversarial": {"recall": 0.93}, "slow_pacing_adversarial": {"recall": 0.92}},
            "stage_c": {"mimicry_adversarial": {"recall": 1.0}, "slow_pacing_adversarial": {"recall": 1.0}},
            "anti_dos_invariant_holds_under_mimicry_pacing": True,
        },
    )
    section = render_adversarial_section(tmp_path)
    assert "HOLDS" in section
    assert "splunk" in section


def test_build_final_report_assembles_all_sections_from_json_only(tmp_path: Path):
    _write(tmp_path / "baseline_splunk.json", {"overall": {"precision": 1.0, "recall": 0.3, "fpr": 0.0}, "n_bursts_evaluated": 100})
    _write(
        tmp_path / "ablation.json",
        {
            "variants": {"frequency_only": {"n_features": 9, "overall": {"recall": 0.5, "precision": 0.3, "fpr": 0.7}}},
            "response_behaviour_lift_percentage_points": 40.0,
            "latency_drift_slope_lift_percentage_points": 10.0,
            "no_measurable_lift_response_behaviour": False,
            "no_measurable_lift_latency_drift_slope": False,
            "noise_floor_percentage_points": 2.0,
        },
    )
    report = build_final_report(tmp_path)
    assert "PulseGuard" in report
    assert "Headline detector comparison" in report
    assert "Ablation" in report
    assert "Adversarial evaluation" in report

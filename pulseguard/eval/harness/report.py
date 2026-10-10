"""Renders eval/results/*.json into a comparison table. Every later phase's
report is built the same way: read the harness's JSON output, never hand-type
a number (Phase 8's final-report gate depends on this discipline)."""

from __future__ import annotations

import json
from pathlib import Path


def load_result(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def render_markdown_comparison(results_by_name: dict[str, dict]) -> str:
    lines = [
        "| Detector | Precision | Recall | FPR | Bursts evaluated |",
        "|---|---|---|---|---|",
    ]
    for name, result in results_by_name.items():
        o = result["overall"]
        precision = f"{o['precision']:.3f}" if o["precision"] is not None else "n/a"
        recall = f"{o['recall']:.3f}" if o["recall"] is not None else "n/a"
        fpr = f"{o['fpr']:.3f}" if o["fpr"] is not None else "n/a"
        lines.append(f"| {name} | {precision} | {recall} | {fpr} | {result['n_bursts_evaluated']} |")
    return "\n".join(lines)


def render_per_profile_markdown(name: str, result: dict) -> str:
    lines = [f"### {name} — per-profile breakdown", "", "| Profile | Recall | FPR | TP | FP | TN | FN |", "|---|---|---|---|---|---|---|"]
    for profile, counts in result["by_profile"].items():
        recall = f"{counts['recall']:.3f}" if counts["recall"] is not None else "n/a"
        fpr = f"{counts['fpr']:.3f}" if counts["fpr"] is not None else "n/a"
        lines.append(
            f"| {profile} | {recall} | {fpr} | {counts['tp']} | {counts['fp']} | {counts['tn']} | {counts['fn']} |"
        )
    return "\n".join(lines)


def build_report(results_dir: Path, names: list[str]) -> str:
    results = {name: load_result(results_dir / f"baseline_{name}.json") for name in names}
    sections = [render_markdown_comparison(results)]
    for name, result in results.items():
        sections.append(render_per_profile_markdown(name, result))
    return "\n\n".join(sections)


def _fmt(value, decimals: int = 3) -> str:
    return f"{value:.{decimals}f}" if isinstance(value, (int, float)) else "n/a"


def _detector_row(name: str, overall: dict, n: int) -> str:
    return f"| {name} | {_fmt(overall.get('precision'))} | {_fmt(overall.get('recall'))} | {_fmt(overall.get('fpr'))} | {n} |"


def render_headline_comparison(results_dir: Path) -> str:
    """The single table every later number in this report is measured
    against: industry baselines, Stage A+B, Stage C, and the full fusion,
    all on the SAME frozen test split (CLAUDE.md, evaluation rule #2)."""
    lines = ["## Headline detector comparison (frozen test split)", "",
             "| Detector | Precision | Recall | FPR | N evaluated |", "|---|---|---|---|---|"]

    for filename, label, n_key in [
        ("baseline_splunk.json", "Splunk (>9/10min)", "n_bursts_evaluated"),
        ("baseline_elastic.json", "Elastic (2 deny+success/10min)", "n_bursts_evaluated"),
        ("stage_ab.json", "Stage A+B", "n_bursts_evaluated"),
        ("stage_c.json", "Stage C (GRU)", "n_episodes_evaluated"),
        ("full_fusion.json", "Full fusion (A+B+C)", "n_episodes_evaluated"),
    ]:
        path = results_dir / filename
        if not path.exists():
            continue
        result = load_result(path)
        lines.append(_detector_row(label, result["overall"], result.get(n_key, "n/a")))
        if filename == "stage_ab.json":
            for key, sub_label in (("stage_a_only", "  Stage A alone"), ("stage_b_only", "  Stage B alone")):
                if key in result:
                    lines.append(_detector_row(sub_label, result[key]["overall"], result.get(n_key, "n/a")))

    fusion_path = results_dir / "full_fusion.json"
    if fusion_path.exists():
        fusion = load_result(fusion_path)
        if "weights" in fusion:
            w = fusion["weights"]
            lines.append("")
            lines.append(
                f"Operating point (tuned on the validation split, loaded by the live scorer): "
                f"weights A={w['a']:.2f} / B={w['b']:.2f} / C={w['c']:.2f}, threshold {fusion['threshold']:.2f}."
            )
        if "unit" in fusion:
            lines.append(f"Unit: {fusion['unit']}.")

    return "\n".join(lines)


def render_ablation_section(results_dir: Path) -> str:
    path = results_dir / "ablation.json"
    if not path.exists():
        return "## Ablation\n\n_not yet run_"

    result = load_result(path)
    lines = ["## Ablation: frequency-only vs +response-behaviour vs -latency_drift_slope", "",
              "| Variant | Features | Recall | Precision | FPR |", "|---|---|---|---|---|"]
    for name, variant in result["variants"].items():
        o = variant["overall"]
        lines.append(f"| {name} | {variant['n_features']} | {_fmt(o['recall'])} | {_fmt(o['precision'])} | {_fmt(o['fpr'])} |")

    lines.append("")
    lines.append(
        f"Response-behaviour lift: **{result['response_behaviour_lift_percentage_points']:.1f} percentage points** "
        f"({'below' if result['no_measurable_lift_response_behaviour'] else 'above'} the "
        f"{result['noise_floor_percentage_points']}-point noise floor)."
    )
    lines.append(
        f"latency_drift_slope lift: **{result['latency_drift_slope_lift_percentage_points']:.1f} percentage points**."
    )
    supplementary = result.get("supplementary")
    if supplementary:
        lines.append("")
        lines.append(
            "Supplementary deltas (full minus ablated variant; reported alongside the recall lift, never instead of it): "
            f"response-behaviour F1 {supplementary['response_behaviour_f1_delta']:+.3f}, "
            f"FPR {supplementary['response_behaviour_fpr_delta']:+.3f}, "
            f"average precision {supplementary['response_behaviour_average_precision_delta']:+.3f}; "
            f"latency_drift_slope F1 {supplementary['latency_drift_slope_f1_delta']:+.3f}, "
            f"FPR {supplementary['latency_drift_slope_fpr_delta']:+.3f}, "
            f"average precision {supplementary['latency_drift_slope_average_precision_delta']:+.3f}."
        )
    if result["no_measurable_lift_latency_drift_slope"]:
        lines.append("")
        lines.append(
            "> **NO MEASURABLE LIFT:** `latency_drift_slope` did not improve recall beyond the noise floor "
            "on this benchmark. See DECISIONS.md for the full investigation and why this is a structural, "
            "understood result rather than an unexplained gap."
        )
    return "\n".join(lines)


def render_adversarial_section(results_dir: Path) -> str:
    path = results_dir / "adversarial.json"
    if not path.exists():
        return "## Adversarial evaluation\n\n_not yet run_"

    result = load_result(path)
    lines = ["## Adversarial evaluation (1-prompt/5-min pacing, mimicry attacker)", "",
              "| Detector | Mimicry recall | Slow-pacing recall |", "|---|---|---|"]
    profiles = ("mimicry_adversarial", "slow_pacing_adversarial")
    for key, label in [("baselines", None), ("stage_ab", "Stage A+B"), ("stage_c", "Stage C"), ("full_fusion", "Full fusion")]:
        if key == "baselines":
            for detector_name, by_profile in result.get("baselines", {}).items():
                mimicry = by_profile.get(profiles[0], {}).get("recall")
                slow = by_profile.get(profiles[1], {}).get("recall")
                lines.append(f"| {detector_name} | {_fmt(mimicry)} | {_fmt(slow)} |")
        else:
            if key not in result:
                continue
            by_profile = result.get(key, {})
            mimicry = by_profile.get(profiles[0], {}).get("recall")
            slow = by_profile.get(profiles[1], {}).get("recall")
            lines.append(f"| {label} | {_fmt(mimicry)} | {_fmt(slow)} |")

    lines.append("")
    invariant = result.get("anti_dos_invariant_holds_under_mimicry_pacing")
    lines.append(f"Anti-DoS invariant under mimicry pacing: **{'HOLDS' if invariant else 'VIOLATED'}**.")
    return "\n".join(lines)


def build_final_report(results_dir: Path) -> str:
    """Assembles the Phase 8 final report entirely from eval/results/*.json
    — no hand-typed numbers (CLAUDE.md's own discipline for this report)."""
    sections = [
        "# PulseGuard — Final Evaluation Report",
        "",
        "_Generated entirely from `eval/results/*.json` — see DECISIONS.md for the full narrative, "
        "methodology notes, and honestly-reported limitations behind every number here._",
        "",
        render_headline_comparison(results_dir),
        "",
        render_ablation_section(results_dir),
        "",
        render_adversarial_section(results_dir),
    ]
    return "\n".join(sections)

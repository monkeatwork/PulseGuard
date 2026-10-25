"""Research sections of final_report.md (HANDOFF.md task 5), generated from
the research result files only, never hand-edited. `make report` appends
them after the frozen harness report (eval/harness/report.py), which is
left untouched.

Every sentence that states a conclusion is computed from the numbers, the
way the ablation's no-lift banners are: if a result changes, the sentence
changes with it.
"""

from __future__ import annotations

import json
from pathlib import Path

DETECTOR_NAMES = {
    "splunk": "Splunk (>9 / 10 min)",
    "elastic": "Elastic (2 deny + approve)",
    "deny_run_rule": "2 consecutive denials (one-line rule)",
    "isolation_forest": "Isolation Forest",
    "logistic_regression": "Logistic regression",
    "frequency_only": "PulseGuard, frequency features only",
    "stage_b": "Stage B (XGBoost)",
    "stage_c": "Stage C (GRU)",
    "pulseguard": "PulseGuard, full fusion",
}
SWEEP_ORDER = (
    "splunk", "elastic", "deny_run_rule", "isolation_forest", "logistic_regression", "frequency_only", "stage_c",
    "pulseguard",
)
# A difference smaller than this is not called a difference (same floor as
# the ablation study's no-lift rule).
NOISE_FLOOR = 0.02


def _load(results_dir: Path, name: str) -> dict | None:
    path = results_dir / name
    return json.loads(path.read_text()) if path.exists() else None


def _f(v, digits=3) -> str:
    return "—" if v is None else f"{v:.{digits}f}"


def _ci(cell: dict, digits=3) -> str:
    if cell["mean"] is None:
        return "—"
    if cell.get("ci_low") is None:
        return _f(cell["mean"], digits)
    return f"{_f(cell['mean'], digits)} [{_f(cell['ci_low'], digits)}, {_f(cell['ci_high'], digits)}]"


def sweep_section(sweep: dict) -> list[str]:
    cfg, summary = sweep["config"], sweep["summary"]
    strengths = list(summary)
    lines = [
        "## Fatigue-strength sweep",
        "",
        f"Corpus regenerated, every model retrained and evaluated at each fatigue strength s "
        f"(null model **{cfg['base_fatigue']['null_model']}**, shape {cfg['base_fatigue']['shape']}, "
        f"{cfg['scale']:,} users, seeds {', '.join(cfg['seeds'])}). s = 0: attack latencies drawn from exactly the "
        f"benign distributions; s = 1: the full collapse to a 0.74 s median. Cells: mean across seeds "
        f"[95% CI]. Test split, by user. Figure: `fatigue_sweep.png`.",
        "",
    ]
    for metric, label in (("recall", "Recall"), ("fpr", "False-positive rate"), ("precision", "Precision")):
        lines += [f"**{label}**", "", "| Detector | " + " | ".join(f"s = {float(s):g}" for s in strengths) + " |",
                  "|---|" + "---|" * len(strengths)]
        for det in SWEEP_ORDER:
            if det in summary[strengths[0]]:
                lines.append(f"| {DETECTOR_NAMES[det]} | " + " | ".join(_ci(summary[s][det][metric]) for s in strengths) + " |")
        lines.append("")

    zero = summary.get("0.0") or summary[strengths[0]]
    pg, el, sp, dr = (zero[d]["recall"]["mean"] for d in ("pulseguard", "elastic", "splunk", "deny_run_rule"))
    pg_fpr, dr_fpr = zero["pulseguard"]["fpr"]["mean"], zero["deny_run_rule"]["fpr"]["mean"]
    beats_rules = pg - max(el, sp) > NOISE_FLOOR
    beats_deny_run = (pg - dr > NOISE_FLOOR) or (dr_fpr - pg_fpr > NOISE_FLOOR / 10)
    lines += [
        "**Key question: at s = 0, does PulseGuard still beat the rules?** "
        + (
            f"Yes, against the industry rules: recall {pg:.3f} vs Elastic {el:.3f} and Splunk {sp:.3f}, with no latency "
            f"signal in the data at all. "
            if beats_rules
            else f"No: recall {pg:.3f} vs Elastic {el:.3f} and Splunk {sp:.3f}. "
        )
        + (
            f"But a one-line rule that fires on two consecutive denials reaches recall {dr:.3f} at FPR {_f(dr_fpr, 4)} "
            f"(PulseGuard: FPR {_f(pg_fpr, 4)}), so the margin over the industry rules comes from the decision sequence "
            f"(no benign profile in the generator ever denies twice in a row), not from learned response behaviour. "
            if not beats_deny_run
            else f"It also beats a one-line two-consecutive-denials rule (recall {dr:.3f}, FPR {_f(dr_fpr, 4)}). "
        ),
        "",
    ]
    grid = sweep.get("grid_summary") or {}
    if grid:
        keys = list(grid)
        lines += [
            "### Trained on one strength, tested on another",
            "",
            "PulseGuard (full fusion), each model at its own validation threshold, scored unchanged on the test users "
            "of a corpus generated at another strength. Rows: training strength; columns: test strength.",
            "",
        ]
        for metric, label in (("recall", "Recall"), ("fpr", "FPR")):
            lines += [f"**{label}**", "", "| train \\ test | " + " | ".join(f"{float(k):g}" for k in keys) + " |",
                      "|---|" + "---|" * len(keys)]
            for tr in keys:
                lines.append(f"| {float(tr):g} | " + " | ".join(_f(grid[tr][te]["pulseguard"][metric]["mean"]) for te in keys) + " |")
            lines.append("")
        worst = min((grid[tr][te]["pulseguard"]["recall"]["mean"], tr, te) for tr in keys for te in keys)
        lines += [
            f"Lowest cell: recall {worst[0]:.3f} (trained at s = {float(worst[1]):g}, tested at s = {float(worst[2]):g}).",
            "",
        ]
    return lines


def before_capitulation_section(bc: dict) -> list[str]:
    lines = [
        "## Detection before capitulation",
        "",
        "Share of capitulating test attacks where the detector fired strictly before the victim's approving tap "
        "(an alert on the tap itself is too late for an in-band defence), and how many prompts the victim had received "
        "when it fired. Corpus: " + ", ".join(
            f"s = {float(s):g} ({v['fatigue']['null_model']})" for s, v in bc["by_strength"].items()
        ) + f", seed {bc['seed']}.",
        "",
    ]
    for s, res in bc["by_strength"].items():
        o = res["overall"]
        lines += [
            f"**Fatigue s = {float(s):g}, null {res['fatigue']['null_model']}**",
            "",
            "| Detector | Before capitulation [95% CI] | Only at/after | Missed | Median prompts until detection | Median prompts to spare |",
            "|---|---|---|---|---|---|",
        ]
        for det in ("splunk", "elastic", "deny_run_rule", "frequency_only", "stage_c", "pulseguard"):
            if det not in o:
                continue
            d = o[det]
            ci = d["detected_before_capitulation_ci"]
            lines.append(
                f"| {DETECTOR_NAMES[det]} | {_f(d['detected_before_capitulation'])} [{_f(ci[0])}, {_f(ci[1])}] | "
                f"{_f(d['detected_only_at_or_after_capitulation'])} | {_f(d['missed_capitulated'])} | "
                f"{_f(d['median_prompts_until_detection'], 1)} | {_f(d['median_prompts_to_spare'], 1)} |"
            )
        n = o["pulseguard"]["n_capitulated"]
        lines += ["", f"{n} capitulating attacks; {o['pulseguard']['n_held_out_to_the_end']} where the victim held out.", ""]
        by = res["by_profile"]
        lines += ["Per attack profile (before capitulation, PulseGuard / Elastic / Splunk):", ""]
        for prof, dets in by.items():
            lines.append(
                f"- {prof}: {_f(dets['pulseguard']['detected_before_capitulation'])} / "
                f"{_f(dets['elastic']['detected_before_capitulation'])} / {_f(dets['splunk']['detected_before_capitulation'])}"
            )
        lines.append("")
    return lines


def adaptive_section(adv: dict) -> list[str]:
    res = adv["results"]
    from eval.research.adaptive_attacker import GAPS_SECONDS

    def label(g):
        return f"{g // 60} min" if g < 3600 else f"{g // 3600} h"

    lines = [
        "## Adaptive attacker",
        "",
        f"{adv['n_victims_per_setting']} test-split victims per setting; detectors trained once on the default "
        f"seed-{adv['seed']} corpus, scored at their validation thresholds. The attacker chooses the gap between prompts, "
        "whether prompts land in the victim's usual login hours, and a lure. Figure: `adaptive_attacker.png`.",
        "",
    ]
    for victim in res:
        for usual, lure in ((0, 0), (1, 0), (0, 1), (1, 1)):
            lines += [
                f"**Victim: {victim}; usual hours {'on' if usual else 'off'}; lure {'on' if lure else 'off'}** (recall)",
                "",
                "| Gap | Splunk | Elastic | 2 denials | PulseGuard | Logistic reg. | Campaign (median h) |",
                "|---|---|---|---|---|---|---|",
            ]
            for g in GAPS_SECONDS:
                r = res[victim][f"{g}:{usual}:{lure}"]
                lines.append(
                    f"| {label(g)} | {_f(r['splunk']['recall'])} | {_f(r['elastic']['recall'])} | "
                    f"{_f(r['deny_run_rule']['recall'])} | {_f(r['pulseguard']['recall'])} | "
                    f"{_f(r['logistic_regression']['recall'])} | {r['_campaign']['median_duration_hours']:.1f} |"
                )
            lines.append("")
    holds = adv["anti_lockout_holds_everywhere"]
    lines += [
        f"Anti-lockout invariant at every setting: **{'HOLDS' if holds else 'VIOLATED'}** (no lock action ever issued; "
        "one cooldown window after the attack the legitimate user is always offered a step-up or an alternate factor).",
        "",
        "Benign test FPR at this operating point: "
        + ", ".join(f"{DETECTOR_NAMES.get(k, k)} {_f(v, 4)}" for k, v in adv["benign_test_fpr_at_this_operating_point"].items()
                    if k in DETECTOR_NAMES)
        + ".",
        "",
    ]
    return lines


def robustness_section(rob: dict) -> list[str]:
    lines = [
        "## Robustness to the assumed fatigue model",
        "",
        "Trained once on the assumed model (linear collapse, s = 1, matched null), then tested on corpora whose fatigue "
        "shape, per-victim strength or benign latency differ; next to a model retrained on each variant. "
        f"Seed {rob['seed']}, test split.",
        "",
        "| Test corpus | PulseGuard (assumed model) recall / FPR | PulseGuard (retrained) recall / FPR | Logistic reg. (assumed) recall / FPR | 2 denials recall / FPR |",
        "|---|---|---|---|---|",
    ]
    for name, v in rob["variants"].items():
        a, r = v["trained_on_assumed"]["pulseguard"], v["retrained_on_variant"]["pulseguard"]
        lr, dr = v["trained_on_assumed"]["logistic_regression"], v["rules"]["deny_run_rule"]
        lines.append(
            f"| {name} | {_f(a['recall'])} / {_f(a['fpr'], 4)} | {_f(r['recall'])} / {_f(r['fpr'], 4)} | "
            f"{_f(lr['recall'])} / {_f(lr['fpr'], 4)} | {_f(dr['recall'])} / {_f(dr['fpr'], 4)} |"
        )
    lines.append("")
    return lines


def hard_negative_section(files: list[dict]) -> list[str]:
    """One sweep per benign deny-run rate (fatigue_sweep --benign-deny-run-rate)."""
    files = sorted(files, key=lambda d: d["config"]["hard_negatives"]["deny_run_rate"])
    dets = ("deny_run_rule", "elastic", "logistic_regression", "frequency_only", "pulseguard")
    lines = [
        "## Benign users who deny several prompts in a row",
        "",
        "In the default corpus no benign episode ever has two consecutive denials, so a one-line rule separates the "
        "classes. Here a share r of benign high-activity logins is preceded by 2-4 denied prompts (benign denial "
        "latency, own device). r is an assumption, so it is swept. Each cell: recall / FPR, seed "
        f"{', '.join(files[0]['config']['seeds'])}, matched null.",
        "",
        "| r | s | " + " | ".join(DETECTOR_NAMES[d] for d in dets) + " |",
        "|---|---|" + "---|" * len(dets),
    ]
    for data in files:
        r = data["config"]["hard_negatives"]["deny_run_rate"]
        for s, cells in data["summary"].items():
            lines.append(
                f"| {r:g} | {float(s):g} | "
                + " | ".join(f"{_f(cells[d]['recall']['mean'])} / {_f(cells[d]['fpr']['mean'], 4)}" for d in dets)
                + " |"
            )
    lines.append("")
    # Does the latency signal start to matter once deny runs stop being free?
    for data in files:
        summ = data["summary"]
        keys = list(summ)
        lo, hi = summ[keys[0]]["pulseguard"], summ[keys[-1]]["pulseguard"]
        r = data["config"]["hard_negatives"]["deny_run_rate"]
        d_fpr = (lo["fpr"]["mean"] or 0) - (hi["fpr"]["mean"] or 0)
        d_rec = (hi["recall"]["mean"] or 0) - (lo["recall"]["mean"] or 0)
        verdict = "matters" if d_fpr > NOISE_FLOOR / 10 or d_rec > NOISE_FLOOR else "does not measurably matter"
        lines.append(
            f"- r = {r:g}: from s = {float(keys[0]):g} to s = {float(keys[-1]):g}, PulseGuard recall changes by "
            f"{d_rec:+.3f} and FPR by {-d_fpr:+.4f}: the latency signal {verdict}."
        )
    lines.append("")
    return lines


def build_research_sections(results_dir: Path) -> str:
    parts: list[str] = ["", "# Research extensions (HANDOFF.md tasks 1-4)", ""]
    for name, fn in (
        ("fatigue_sweep.json", sweep_section),
        ("fatigue_sweep_legacy.json", None),
        ("before_capitulation.json", before_capitulation_section),
        ("adaptive_attacker.json", adaptive_section),
        ("robustness.json", robustness_section),
    ):
        data = _load(results_dir, name)
        if data is None:
            continue
        if name == "fatigue_sweep_legacy.json":
            section = sweep_section(data)
            section[0] = "## Fatigue-strength sweep, original (legacy) formula"
            section.insert(2, "HANDOFF.md's literal definition: only the end point of the collapse moves with s; the "
                              "attack latency spread and the 1-2 s lure stay as they were, so s = 0 still carries a "
                              "latency signal. Shown for comparison with the matched sweep above.\n")
            parts += section
        else:
            parts += fn(data)
    hard = [json.loads(p.read_text()) for p in sorted(results_dir.glob("hard_negatives_r*.json"))]
    if hard:
        parts += hard_negative_section(hard)
    return "\n".join(parts)

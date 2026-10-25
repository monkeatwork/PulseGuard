"""Fatigue-strength sweep (HANDOFF.md task 1) and the train/test strength
grid.

For every seed and every strength s, regenerate the corpus with the
latency collapse scaled by s, retrain every stage on it, and evaluate on the
by-user test split with the frozen harness rules. This answers "how much of
PulseGuard's score is the curve we drew into the data?" with a curve rather
than a single point.

The grid goes one step further: models trained at strength s_train are
scored, unchanged and at their own validation thresholds, on the test
users of the corpus generated at s_test. The corpora are paired (same
users, episodes and decisions; only attack latencies differ, see
test_generator_determinism.py), so a cell differs from its diagonal only in
the fatigue the victim shows. The realistic question it answers: we
trained on our assumed curve -- what if real victims show less of it?

Default null model is "matched": at s = 0 attack latencies are drawn from
exactly the benign distributions, so whatever the detector still catches
there it catches without any latency signal. Pass --fatigue-null legacy to
sweep the original formula (HANDOFF.md's literal definition), which keeps a
latency signal even at s = 0 (latency_models.FatigueConfig).

Usage:
    python -m eval.research.fatigue_sweep --seeds 42 1 2 3 4 \
        --out eval/results/fatigue_sweep.json --plot eval/results/fatigue_sweep.png
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from benchmark.generator.latency_models import (
    BENIGN_SOURCES,
    FATIGUE_SHAPES,
    NULL_MODELS,
    FatigueConfig,
)
from eval.research.corpora import build_events, load_users
from eval.research.stats import across_seeds, with_wilson
from eval.research.suite import evaluate_models, evaluate_rules, prepare, score_points, summarize, train_suite

logger = logging.getLogger("pulseguard.eval.research.fatigue_sweep")

DEFAULT_STRENGTHS = (0.0, 0.25, 0.5, 0.75, 1.0)
REPORTED = (
    "splunk", "elastic", "deny_run_rule", "isolation_forest", "logistic_regression", "frequency_only", "stage_b", "stage_c", "pulseguard",
)
GRID_DETECTORS = ("isolation_forest", "logistic_regression", "frequency_only", "stage_b", "stage_c", "pulseguard")
METRICS = ("precision", "recall", "fpr")


def run_seed(users, seed: int, base: FatigueConfig, strengths, gru_epochs: int, grid: bool) -> dict:
    views, suites = {}, {}
    runs = {}
    for s in strengths:
        t0 = time.time()
        config = base.with_strength(s)
        events = build_events(users, seed, config)
        view = prepare(events, seed)
        suite = train_suite(view, seed, gru_epochs)
        points = score_points(suite, view)
        models = evaluate_models(suite, points, seed)
        rules = evaluate_rules(events, seed)
        results = {name: with_wilson(summarize(r)) for name, r in {**rules, **models}.items()}
        runs[str(s)] = {
            "fatigue": config.as_dict(),
            "n_test_episodes": models["pulseguard"]["n_episodes_evaluated"],
            "operating_point": suite.describe(),
            "detectors": results,
            "by_profile": {name: r["by_profile"] for name, r in {**rules, **models}.items()},
        }
        logger.info(
            "seed=%d s=%.2f  pulseguard P=%.3f R=%.3f FPR=%.3f | freq R=%.3f FPR=%.3f | elastic R=%.3f | splunk R=%.3f  (%.0fs)",
            seed, s, results["pulseguard"]["precision"] or 0, results["pulseguard"]["recall"] or 0,
            results["pulseguard"]["fpr"] or 0, results["frequency_only"]["recall"] or 0,
            results["frequency_only"]["fpr"] or 0, results["elastic"]["recall"] or 0,
            results["splunk"]["recall"] or 0, time.time() - t0,
        )
        if grid:
            views[s], suites[s] = view, suite

    grid_out = {}
    if grid:
        for s_train, suite in suites.items():
            grid_out[str(s_train)] = {}
            for s_test, view in views.items():
                models = evaluate_models(suite, score_points(suite, view), seed)
                grid_out[str(s_train)][str(s_test)] = {
                    name: with_wilson(summarize(models[name])) for name in GRID_DETECTORS
                }
    return {"runs": runs, "grid": grid_out}


def summarize_across_seeds(per_seed: dict, strengths) -> dict:
    out = {}
    for s in map(str, strengths):
        out[s] = {
            det: {m: across_seeds(per_seed[seed]["runs"][s]["detectors"][det][m] for seed in per_seed) for m in METRICS}
            for det in REPORTED
        }
    return out


def summarize_grid(per_seed: dict, strengths) -> dict:
    seeds = [seed for seed in per_seed if per_seed[seed]["grid"]]
    if not seeds:
        return {}
    out = {}
    for tr in map(str, strengths):
        out[tr] = {}
        for te in map(str, strengths):
            out[tr][te] = {
                det: {m: across_seeds(per_seed[seed]["grid"][tr][te][det][m] for seed in seeds) for m in METRICS}
                for det in GRID_DETECTORS
            }
    return out


def plot(summary: dict, grid: dict, out_path: Path, title: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    strengths = [float(s) for s in summary]
    styles = {
        "splunk": ("Splunk (>9 / 10 min)", "#8c8c8c", "s"),
        "elastic": ("Elastic (2 deny + approve)", "#e08a2c", "^"),
        "isolation_forest": ("Isolation Forest", "#59a14f", "v"),
        "deny_run_rule": ("2 consecutive denials (one-line rule)", "#222222", "x"),
        "frequency_only": ("Frequency features only", "#4c78a8", "o"),
        "pulseguard": ("PulseGuard (full fusion)", "#c23b5a", "D"),
    }
    ncols = 4 if grid else 3
    fig, axes = plt.subplots(1, ncols, figsize=(4.2 * ncols, 3.6))
    for ax, metric, label in zip(axes, METRICS, ("Precision", "Recall", "False-positive rate")):
        for det, (name, colour, marker) in styles.items():
            cells = [summary[s][det][metric] for s in summary]
            mean = [c["mean"] for c in cells]
            ax.plot(strengths, mean, marker=marker, color=colour, label=name, linewidth=1.6, markersize=5)
            lo = [c["ci_low"] for c in cells]
            hi = [c["ci_high"] for c in cells]
            if all(v is not None for v in lo + hi):
                ax.fill_between(strengths, lo, hi, color=colour, alpha=0.15, linewidth=0)
        ax.set_xlabel("Fatigue strength s")
        ax.set_title(label)
        ax.set_xticks(strengths)
        ax.grid(alpha=0.3)
        if metric != "fpr":
            ax.set_ylim(-0.02, 1.02)
    axes[0].legend(fontsize=7, loc="lower right")
    if grid:
        import numpy as np

        keys = list(grid)
        mat = np.array([[grid[tr][te]["pulseguard"]["recall"]["mean"] for te in keys] for tr in keys])
        ax = axes[3]
        im = ax.imshow(mat, vmin=0, vmax=1, cmap="viridis", origin="lower")
        ax.set_xticks(range(len(keys)), [f"{float(k):g}" for k in keys])
        ax.set_yticks(range(len(keys)), [f"{float(k):g}" for k in keys])
        ax.set_xlabel("Test strength")
        ax.set_ylabel("Train strength")
        ax.set_title("PulseGuard recall, train vs test")
        for i in range(len(keys)):
            for j in range(len(keys)):
                ax.text(j, i, f"{mat[i, j]:.2f}", ha="center", va="center", fontsize=7,
                        color="white" if mat[i, j] < 0.6 else "black")
        fig.colorbar(im, ax=ax, fraction=0.046)
    fig.suptitle(title, fontsize=10)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rba-zip", default="data/raw/rba-dataset.zip")
    parser.add_argument("--scale", type=int, default=50000)
    parser.add_argument("--seeds", type=int, nargs="+", default=[42])
    parser.add_argument("--strengths", type=float, nargs="+", default=list(DEFAULT_STRENGTHS))
    parser.add_argument("--fatigue-null", choices=NULL_MODELS, default="matched")
    parser.add_argument("--fatigue-shape", choices=FATIGUE_SHAPES, default="linear")
    parser.add_argument("--benign-latency", choices=BENIGN_SOURCES, default="legacy")
    parser.add_argument("--fatigue-heterogeneity", type=float, default=0.0)
    parser.add_argument("--gru-epochs", type=int, default=None, help="default: train_stage_c.EPOCHS")
    parser.add_argument("--no-grid", action="store_true", help="skip the train/test strength grid")
    parser.add_argument("--out", default="eval/results/fatigue_sweep.json")
    parser.add_argument("--plot", default=None)
    parser.add_argument("--merge", nargs="+", default=None,
                        help="combine the per-seed results of these sweep JSONs (same setup) into --out")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for noisy in ("pulseguard.detection_engine.train_stage_c",):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    from services.detection_engine.app.train_stage_c import EPOCHS

    base = FatigueConfig(1.0, args.fatigue_shape, args.fatigue_null, args.benign_latency, args.fatigue_heterogeneity)
    out_path = Path(args.out)
    # Resumable: a seed already in the output file is not re-run.
    previous = json.loads(out_path.read_text()) if out_path.exists() else {}
    same_setup = previous.get("config", {}).get("base_fatigue") == base.as_dict() and previous.get("config", {}).get(
        "strengths"
    ) == args.strengths and previous.get("config", {}).get("scale") == args.scale
    per_seed = previous.get("per_seed", {}) if same_setup else {}

    def write() -> None:
        result = {
            "config": {
                "base_fatigue": base.as_dict(),
                "strengths": args.strengths,
                "scale": args.scale,
                "seeds": list(per_seed),
                "gru_epochs": args.gru_epochs or EPOCHS,
                "unit": "episode (positive if any decision point crosses the threshold); test split, by user",
                "thresholds": "every model's threshold chosen on its own corpus's validation split",
                "intervals": "summary: mean and t-based 95% CI across seeds; per-run *_ci: Wilson 95%",
            },
            "summary": summarize_across_seeds(per_seed, args.strengths),
            "grid_summary": summarize_grid(per_seed, args.strengths),
            "per_seed": per_seed,
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2, default=str))
        if args.plot:
            title = (
                f"Fatigue sweep: null={base.null_model}, shape={base.shape}, benign={base.benign_source}, "
                f"seeds={len(per_seed)}, {args.scale:,} users"
            )
            plot(result["summary"], result["grid_summary"], Path(args.plot), title)

    if args.merge:
        # Seeds run as separate processes, combined here. Every part must
        # come from the same setup, or the summary would average unlike runs.
        for part in map(Path, args.merge):
            data = json.loads(part.read_text())
            cfg = data["config"]
            if (cfg["base_fatigue"], cfg["strengths"], cfg["scale"]) != (base.as_dict(), args.strengths, args.scale):
                raise SystemExit(f"{part}: different sweep setup, refusing to merge")
            per_seed.update(data["per_seed"])
        write()
        return 0

    users = load_users(Path(args.rba_zip), args.scale)
    for seed in args.seeds:
        if str(seed) in per_seed:
            logger.info("seed %d already in %s, skipping", seed, out_path)
            continue
        per_seed[str(seed)] = run_seed(users, seed, base, args.strengths, args.gru_epochs or EPOCHS, not args.no_grid)
        write()
    return 0


if __name__ == "__main__":
    sys.exit(main())

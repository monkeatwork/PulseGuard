"""Robustness of the trained detector to the fatigue model it assumed.

The sweep varies HOW MUCH fatigue there is. This varies its form, and the
benign baseline, while the detector keeps the one it was trained on:

  trained on   linear collapse, strength 1, matched null, legacy benign
  tested on    exponential (collapse early), step (sudden collapse half-way),
               heterogeneous victims (per-episode strength multiplier,
               sd 0.5 and 1.0 -- some victims slow down instead),
               benign latency fitted to field data (DuoLungo), with and
               without fatigue

Each variant is reported twice: scored by the detector trained on the
assumed model (no retraining, its validation thresholds), and by a detector
retrained on the variant itself. The gap between the two is what the
assumption costs if reality differs. Corpora are paired (same users,
episodes and decisions), so only latencies differ from the training corpus.

Usage:
    python -m eval.research.robustness --out eval/results/robustness.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from benchmark.generator.latency_models import FatigueConfig
from eval.research.corpora import build_events, load_users
from eval.research.stats import with_wilson
from eval.research.suite import evaluate_models, evaluate_rules, prepare, score_points, summarize, train_suite

logger = logging.getLogger("pulseguard.eval.research.robustness")

ASSUMED = FatigueConfig(strength=1.0, shape="linear", null_model="matched")
VARIANTS = {
    "assumed (linear, s=1)": ASSUMED,
    "exponential, s=1": FatigueConfig(1.0, "exponential", "matched"),
    "step, s=1": FatigueConfig(1.0, "step", "matched"),
    "heterogeneous sd=0.5, s=1": FatigueConfig(1.0, "linear", "matched", heterogeneity=0.5),
    "heterogeneous sd=1.0, s=1": FatigueConfig(1.0, "linear", "matched", heterogeneity=1.0),
    "DuoLungo benign, s=1": FatigueConfig(1.0, "linear", "matched", benign_source="duolungo"),
    "DuoLungo benign, s=0": FatigueConfig(0.0, "linear", "matched", benign_source="duolungo"),
}
REPORTED = ("isolation_forest", "logistic_regression", "frequency_only", "stage_b", "stage_c", "pulseguard")


def _models(suite, view, seed) -> dict:
    res = evaluate_models(suite, score_points(suite, view), seed)
    return {name: with_wilson(summarize(res[name])) for name in REPORTED}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rba-zip", default="data/raw/rba-dataset.zip")
    parser.add_argument("--scale", type=int, default=50000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--gru-epochs", type=int, default=None)
    parser.add_argument("--out", default="eval/results/robustness.json")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("pulseguard.detection_engine.train_stage_c").setLevel(logging.WARNING)

    from services.detection_engine.app.train_stage_c import EPOCHS

    epochs = args.gru_epochs or EPOCHS
    users = load_users(Path(args.rba_zip), args.scale)
    assumed_view = prepare(build_events(users, args.seed, ASSUMED), args.seed)
    assumed = train_suite(assumed_view, args.seed, epochs)

    results = {}
    for name, config in VARIANTS.items():
        events = assumed_view.events_df if config == ASSUMED else build_events(users, args.seed, config)
        view = assumed_view if config == ASSUMED else prepare(events, args.seed)
        own = assumed if config == ASSUMED else train_suite(view, args.seed, epochs)
        results[name] = {
            "fatigue": config.as_dict(),
            "trained_on_assumed": _models(assumed, view, args.seed),
            "retrained_on_variant": _models(own, view, args.seed),
            "rules": {k: with_wilson(summarize(v)) for k, v in evaluate_rules(events, args.seed).items()},
        }
        a, r = results[name]["trained_on_assumed"]["pulseguard"], results[name]["retrained_on_variant"]["pulseguard"]
        logger.info(
            "%-28s pulseguard assumed-model R=%.3f FPR=%.4f | retrained R=%.3f FPR=%.4f",
            name, a["recall"] or 0, a["fpr"] or 0, r["recall"] or 0, r["fpr"] or 0,
        )
    out = {
        "seed": args.seed,
        "scale": args.scale,
        "assumed_model": ASSUMED.as_dict(),
        "split": "test (by user)",
        "variants": results,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

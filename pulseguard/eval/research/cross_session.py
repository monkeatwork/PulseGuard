"""Cross-session guard: closing the slow-pacing gap (follow-up to task 3).

PulseGuard scores sessions, and a session ends after 60 minutes of quiet,
so the adaptive attacker that waits 2-4 h between prompts is never seen as a
burst. services/detection_engine/app/cross_session_guard.py counts, per user
and across sessions, denials that no approval followed within
`resolve_seconds`. Here it is evaluated alone and OR-ed with PulseGuard.

Every benign denial the generator makes is followed by an approval within
the hour (a retry), so on the default corpus unresolved denials separate
the classes for free. Real users also deny prompts and never retry. To make
the false-positive number mean something, each benign user gets stray
unresolved denials: on each day they were active, with probability p, one
denied prompt from their own device at a random time, as its own benign
episode. p is unknown, so it is swept.

The guard's two settings, K (unresolved denials needed) and the window,
are chosen on VALIDATION users only: the setting that catches the most slow
adaptive attacks (gaps of 2 h and more) generated against validation users,
among those whose validation FPR on users never attacked (at
p = STRAY_RATE_FOR_SELECTION) is within VAL_FPR_BUDGET. It is then reported unchanged on the test users.

PulseGuard is trained once on the default corpus (legacy null, s = 1, as
for the adaptive attacker) and scored at its validation operating point.

Usage:
    python -m eval.research.cross_session --out eval/results/cross_session.json \
        --plot eval/results/cross_session.png
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from benchmark.generator.attack_profiles import HardNegativeConfig, _prompt_decision_pair, _rng_uuid
from benchmark.generator.cli import _raw_event_to_record
from benchmark.generator.latency_models import DEFAULT_FATIGUE, sample_benign_deny_latency_ms
from benchmark.generator.seed import child_rng
from eval.research.adaptive_attacker import (
    GAPS_SECONDS,
    VICTIMS,
    anti_lockout,
    build_setting,
    victims_for_test_users,
)
from eval.research.corpora import build_events, load_users
from eval.research.stats import wilson, with_wilson
from eval.research.suite import prepare, score_points, summarize, train_suite
from services.detection_engine.app.cross_session_guard import CrossSessionGuardConfig, unresolved_counts
from services.detection_engine.app.episode_eval import episode_frame, evaluate

logger = logging.getLogger("pulseguard.eval.research.cross_session")

STRAY_RATES = (0.0, 0.02, 0.1, 0.3)
STRAY_RATE_FOR_SELECTION = 0.1
K_GRID = (2, 3, 4, 5)
WINDOW_GRID = (86400, 3 * 86400, 7 * 86400)
RESOLVE_SECONDS = 10 * 60
SLOW_GAPS = tuple(g for g in GAPS_SECONDS if g >= 7200)
VAL_FPR_BUDGET = 0.002  # PulseGuard's own benign FPR level
DETECTORS = ("pulseguard", "guard", "pulseguard_or_guard")


def add_stray_denials(events_df: pd.DataFrame, seed: int, rate: float) -> pd.DataFrame:
    """Per benign user and active day (any login), one unresolved denial with
    probability `rate`. Draws are made for every day whatever the rate, so
    corpora are paired: a stray present at rate p is present at every rate
    above p, at the same time."""
    if rate <= 0:
        return events_df
    benign = events_df[
        events_df["event_type"].isin(("login_attempt", "mfa_decision")) & ~events_df["label_attack"].astype(bool)
    ]
    records = []
    for user_id, g in benign.groupby("user_id", sort=True):
        rng = child_rng(seed, user_id, "stray_denial")
        last = g.sort_values("ts").iloc[-1]
        for day in sorted(g["ts"].dt.floor("D").unique()):
            u, offset = rng.random(), int(rng.integers(0, 86400))
            latency = sample_benign_deny_latency_ms(rng, DEFAULT_FATIGUE.benign_source)
            session = str(_rng_uuid(rng))
            if u >= rate:
                continue
            ts = pd.Timestamp(day).to_pydatetime() + timedelta(seconds=offset)
            pair = _prompt_decision_pair(
                user_id=user_id, prompt_ts=ts, decision="deny", latency_ms=latency,
                attacker_src_ip=last["src_ip"], attacker_device_id=last["device_id"],
                attacker_user_agent=last["user_agent"], victim_src_ip=last["src_ip"],
                victim_device_id=last["device_id"], victim_user_agent=last["user_agent"],
                session_id=session, geo_country=last["geo_country"], label_attack=False, attack_profile=None,
            )
            records.extend(_raw_event_to_record(e, f"stray:{user_id}:{ts.isoformat()}") for e in pair)
    if not records:
        return events_df
    strays = pd.DataFrame.from_records(records)
    strays["ts"] = pd.to_datetime(strays["ts"], utc=True).dt.tz_convert(events_df["ts"].dt.tz)
    return pd.concat([events_df, strays], ignore_index=True).sort_values(["user_id", "ts"], kind="stable")


def guard_counts_for_points(events_df: pd.DataFrame, points: pd.DataFrame, config: CrossSessionGuardConfig,
                            history: pd.DataFrame | None = None) -> np.ndarray:
    """Unresolved-denial count at every decision point, aligned with
    `points` (iter_decision_points order: episode id, then time). `history`
    adds earlier events of the same users that are not themselves scored."""
    full = events_df if history is None else pd.concat([history, events_df], ignore_index=True)
    counts = unresolved_counts(full, config)
    dec = full.loc[counts.index, ["burst_id", "ts"]].assign(c=counts.to_numpy())
    dec = dec[dec["burst_id"].isin(set(points["generator_burst_id"]))].sort_values(["burst_id", "ts"], kind="stable")
    if dec["burst_id"].tolist() != points["generator_burst_id"].tolist():
        raise RuntimeError("guard counts and decision points are misaligned")
    return dec["c"].to_numpy()


def _col(k: int, window: int) -> str:
    return f"hit_guard_k{k}_w{window // 86400}d"


def guard_setting(k: int, window: int) -> str:
    return f"K={k}, window={window // 86400}d"


def score_corpus(events_df: pd.DataFrame, suite, seed: int) -> pd.DataFrame:
    points = score_points(suite, prepare(events_df, seed))
    for window in WINDOW_GRID:
        counts = guard_counts_for_points(events_df, points, CrossSessionGuardConfig(1, window, RESOLVE_SECONDS))
        for k in K_GRID:
            points[_col(k, window)] = counts >= k
    return points


def episode_results(points: pd.DataFrame, seed: int, k: int, window: int, split: str = "test") -> dict:
    points = points.assign(hit_guard=points[_col(k, window)])
    points["hit_pulseguard_or_guard"] = points["hit_pulseguard"] | points["hit_guard"]
    grid = [_col(kk, w) for kk in K_GRID for w in WINDOW_GRID]
    eps = episode_frame(points, seed, [f"hit_{d}" for d in DETECTORS] + grid)
    eps = eps[eps["split"] == split]
    # Benign episodes of users who were never attacked: an alert in the day
    # after a real attack on the same account is not a nuisance to a normal user.
    attacked = set(eps.loc[eps["label_attack"].astype(bool), "user_id"])
    clean = eps[~eps["label_attack"].astype(bool) & ~eps["user_id"].isin(attacked)]

    def cell(col: str, ci: bool = True) -> dict:
        r = summarize(evaluate(eps, eps[col].astype(bool)))
        r = with_wilson(r) if ci else r
        r["fpr_never_attacked_users"] = float(clean[col].astype(bool).mean()) if len(clean) else None
        r["n_benign_never_attacked"] = len(clean)
        return r

    out = {d: cell(f"hit_{d}") for d in DETECTORS}
    out["guard_grid"] = {guard_setting(kk, w): cell(_col(kk, w), ci=False) for kk in K_GRID for w in WINDOW_GRID}
    return out


def slow_attack_recall(base: pd.DataFrame, seed: int, n_users: int, split: str) -> dict:
    """Guard recall per (K, window) on the slow adaptive attacks (gap >= 2 h,
    every timing/lure choice) against `split` users, with their benign
    history in the counter."""
    victims = victims_for_test_users(base, seed, n_users, split=split)
    ids = {v["user_id"] for v in victims}
    history = base[base["user_id"].isin(ids) & ~base["label_attack"].astype(bool)]
    caught: dict[str, list[bool]] = {}
    # One setting at a time: settings share victims and start times, so
    # pooling them would add their denials up in one counter.
    for g, u, lure in itertools.product(SLOW_GAPS, (False, True), (False, True)):
        attacks = build_setting(victims, seed, g, u, lure, "default_fatigue")
        full = pd.concat([history, attacks], ignore_index=True)
        for window in WINDOW_GRID:
            counts = unresolved_counts(full, CrossSessionGuardConfig(1, window, RESOLVE_SECONDS))
            dec = full.loc[counts.index, ["burst_id"]].assign(c=counts.to_numpy())
            peak = dec[dec["burst_id"].isin(set(attacks["burst_id"]))].groupby("burst_id")["c"].max()
            for k in K_GRID:
                caught.setdefault(guard_setting(k, window), []).extend((peak >= k).tolist())
    return {name: float(np.mean(v)) for name, v in caught.items()}


def select_guard(points: pd.DataFrame, base: pd.DataFrame, seed: int, n_users: int) -> tuple[tuple[int, int], dict]:
    """Most slow-attack recall on validation users among settings whose
    validation FPR on never-attacked users is within budget; ties go to the
    shorter window, then the larger K."""
    slow = slow_attack_recall(base, seed, n_users, split="val")
    grid = episode_results(points, seed, K_GRID[0], WINDOW_GRID[0], split="val")["guard_grid"]
    val = {
        name: {"fpr": grid[name]["fpr"], "fpr_never_attacked_users": grid[name]["fpr_never_attacked_users"],
               "slow_attack_recall": slow[name]}
        for name in grid
    }
    ok = [
        (k, w) for k in K_GRID for w in WINDOW_GRID
        if (val[guard_setting(k, w)]["fpr_never_attacked_users"] or 0) <= VAL_FPR_BUDGET
    ]
    chosen = max(ok or [(K_GRID[-1], WINDOW_GRID[0])], key=lambda kw: (slow[guard_setting(*kw)], -kw[1], kw[0]))
    return chosen, val


def adaptive(base: pd.DataFrame, suite, seed: int, n_users: int, k: int, window: int) -> dict:
    victims = victims_for_test_users(base, seed, n_users)
    ids = {v["user_id"] for v in victims}
    history = base[base["user_id"].isin(ids) & ~base["label_attack"].astype(bool)]
    config = CrossSessionGuardConfig(k, window, RESOLVE_SECONDS)
    results = {}
    for victim_name in VICTIMS:
        results[victim_name] = {}
        for gap, usual, lure in itertools.product(GAPS_SECONDS, (False, True), (False, True)):
            df = build_setting(victims, seed, gap, usual, lure, victim_name)
            points = score_points(suite, prepare(df, seed))
            points["hit_guard"] = guard_counts_for_points(df, points, config, history) >= k
            points["hit_pulseguard_or_guard"] = points["hit_pulseguard"] | points["hit_guard"]
            caught = points.groupby("generator_burst_id")[[f"hit_{d}" for d in DETECTORS]].max()
            res = {
                d: {"recall": float(caught[f"hit_{d}"].mean()), "recall_ci": wilson(int(caught[f"hit_{d}"].sum()), len(caught))}
                for d in DETECTORS
            }
            res["_anti_lockout"] = anti_lockout(df, points, "hit_pulseguard_or_guard")
            results[victim_name][f"{gap}:{int(usual)}:{int(lure)}"] = res
            logger.info(
                "%s gap=%5ds usual=%d lure=%d  pulseguard=%.3f guard=%.3f either=%.3f lockout-invariant=%s",
                victim_name, gap, usual, lure, res["pulseguard"]["recall"], res["guard"]["recall"],
                res["pulseguard_or_guard"]["recall"], res["_anti_lockout"]["holds"],
            )
    return results


def plot(out: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.5))
    res = out["adaptive"]["default_fatigue"]
    style = {"pulseguard": ("PulseGuard", "#c23b5a", "D"), "guard": ("Cross-session guard", "#2f6db5", "o"),
             "pulseguard_or_guard": ("PulseGuard OR guard", "#222222", "x")}
    for det, (name, color, marker) in style.items():
        ys = [res[f"{g}:0:0"][det]["recall"] for g in GAPS_SECONDS]
        ax1.plot(range(len(GAPS_SECONDS)), ys, marker=marker, color=color, label=name)
    ax1.set_xticks(range(len(GAPS_SECONDS)), [f"{g // 60}m" if g < 3600 else f"{g // 3600}h" for g in GAPS_SECONDS])
    ax1.set(title="Adaptive attacker recall (no lure, any hours)", xlabel="Gap between prompts", ylabel="Recall", ylim=(-0.03, 1.03))
    ax1.grid(alpha=0.3)
    ax1.legend(fontsize=8)
    rates = list(out["stray_sweep"])
    for det, (name, color, marker) in style.items():
        ax2.plot([float(r) for r in rates], [out["stray_sweep"][r][det]["fpr"] for r in rates], marker=marker, color=color,
                 label=f"{name}, all benign episodes")
        if det != "pulseguard":
            ax2.plot([float(r) for r in rates], [out["stray_sweep"][r][det]["fpr_never_attacked_users"] for r in rates],
                     marker=marker, color=color, linestyle="--", label=f"{name}, users never attacked")
    ax2.set(title=f"Benign FPR vs stray-denial rate ({out['chosen']})", xlabel="Stray unresolved denials per active day (p)",
            ylabel="False-positive rate")
    ax2.grid(alpha=0.3)
    ax2.legend(fontsize=8)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rba-zip", default="data/raw/rba-dataset.zip")
    parser.add_argument("--scale", type=int, default=50000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-users", type=int, default=400, help="test-split victims per adaptive setting")
    parser.add_argument("--gru-epochs", type=int, default=None)
    parser.add_argument("--out", default="eval/results/cross_session.json")
    parser.add_argument("--plot", default="eval/results/cross_session.png")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("pulseguard.detection_engine.train_stage_c").setLevel(logging.WARNING)

    from services.detection_engine.app.train_stage_c import EPOCHS

    users = load_users(Path(args.rba_zip), args.scale)
    base = build_events(users, args.seed, DEFAULT_FATIGUE)
    suite = train_suite(prepare(base, args.seed), args.seed, args.gru_epochs or EPOCHS)

    scored = {rate: score_corpus(add_stray_denials(base, args.seed, rate), suite, args.seed) for rate in STRAY_RATES}
    (k, window), val = select_guard(scored[STRAY_RATE_FOR_SELECTION], base, args.seed, args.n_users)
    logger.info("chosen %s (validation, p=%g): %s", guard_setting(k, window), STRAY_RATE_FOR_SELECTION, val)
    stray_sweep = {}
    for rate, points in scored.items():
        stray_sweep[str(rate)] = episode_results(points, args.seed, k, window)
        logger.info("p=%g  %s", rate, {d: (stray_sweep[str(rate)][d]["recall"], stray_sweep[str(rate)][d]["fpr"]) for d in DETECTORS})

    deny_runs = build_events(users, args.seed, DEFAULT_FATIGUE, HardNegativeConfig(deny_run_rate=0.1))
    deny_run_result = episode_results(score_corpus(deny_runs, suite, args.seed), args.seed, k, window)

    out = {
        "seed": args.seed,
        "scale": args.scale,
        "guard": {"resolve_seconds": RESOLVE_SECONDS, "k_grid": list(K_GRID), "window_grid_seconds": list(WINDOW_GRID)},
        "selection": {"stray_rate": STRAY_RATE_FOR_SELECTION, "val_fpr_budget": VAL_FPR_BUDGET,
                      "slow_gaps_seconds": list(SLOW_GAPS), "val": val},
        "chosen": guard_setting(k, window),
        "chosen_config": CrossSessionGuardConfig(k, window, RESOLVE_SECONDS).as_dict(),
        "operating_point": suite.describe(),
        "split": "test (by user)",
        "stray_sweep": stray_sweep,
        "benign_deny_runs_r0.1": deny_run_result,
        "adaptive": adaptive(base, suite, args.seed, args.n_users, k, window),
    }
    out["anti_lockout_holds_everywhere"] = all(
        r["_anti_lockout"]["holds"] for v in out["adaptive"].values() for r in v.values()
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, default=str))
    if args.plot:
        plot(out, Path(args.plot))
    return 0


if __name__ == "__main__":
    sys.exit(main())

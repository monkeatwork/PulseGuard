"""Adaptive attacker with a budget (HANDOFF.md task 3).

Threat model: the attacker holds the victim's password and controls WHEN
prompts are sent and whether a social-engineering lure accompanies them,
but not how the victim reacts. Per setting the attacker chooses:

  (a) pacing: the gap between prompts, from 1 minute to 4 hours (+/-20%
      jitter, so it is not perfectly periodic);
  (b) timing: whether each prompt is moved into the victim's usual login
      hours (UTC hours of their own benign RBA logins), at the cost of a
      longer campaign;
  (c) a lure on or off: on = at a random prompt after the first denial the
      victim is talked into approving (lure latency), ending the attack.

The prompt budget per episode is 6-14 prompts, as for the existing
mimicry / slow-pacing adversaries; the time budget is what the pacing and
timing choices cost, reported as the campaign duration.

The victim's reaction comes from the benchmark's latency model: the
default corpus model (legacy null, strength 1), and a victim showing no
latency change at all (matched null, strength 0) as the worst case for
PulseGuard. Detectors are trained once on the default seed-42 corpus and
scored at their validation-chosen operating point; nothing is re-tuned per
setting. Episodes are generated for TEST-split users only.

The anti-lockout invariant is checked at every setting by replaying each
episode's prompts through the real mitigation controller once the detector
has alerted (the attacker fails every step-up), then asking what the
legitimate user gets when they next sign in: always a step-up or an
alternate factor, never a lock, and never more than one cooldown window of
waiting.

Usage:
    python -m eval.research.adaptive_attacker --out eval/results/adaptive_attacker.json \
        --plot eval/results/adaptive_attacker.png
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from benchmark.generator.attack_profiles import RawEvent, _final_decision, _prompt_decision_pair, _rng_uuid
from benchmark.generator.cli import _raw_event_to_record
from benchmark.generator.latency_models import (
    DEFAULT_FATIGUE,
    FatigueConfig,
    sample_fatigue_latency_ms,
    sample_lure_latency_ms,
)
from benchmark.generator.seed import child_rng
from eval.harness.split import assign_split
from eval.research.corpora import build_events, load_users
from eval.research.stats import wilson
from eval.research.suite import RULES, evaluate_rules, prepare, score_points, train_suite
from services.mitigation.app.controller import UserMitigationState, decide_action
from services.mitigation.app.cooldown import STEP_UP_COOLDOWN_SECONDS

logger = logging.getLogger("pulseguard.eval.research.adaptive_attacker")

GAPS_SECONDS = (60, 120, 300, 600, 1200, 2400, 3600, 7200, 14400)
GAP_JITTER = 0.2
PROMPT_COUNT_RANGE = (6, 15)  # rng.integers upper bound is exclusive
VICTIMS = {
    "default_fatigue": DEFAULT_FATIGUE,
    "no_latency_signal": FatigueConfig(strength=0.0, null_model="matched"),
}
MODELS = ("pulseguard", "stage_b", "stage_c", "frequency_only", "isolation_forest", "logistic_regression")
LEGIT_RETURN_AFTER_SECONDS = 60


def usual_hours(login_ts: list[datetime]) -> list[int]:
    return sorted({ts.hour for ts in login_ts})


def _next_usual_time(ts: datetime, hours: list[int], rng: np.random.Generator) -> datetime:
    """The first moment at or after `ts` whose UTC hour is one the victim
    normally logs in at (random minute within that hour if moved)."""
    if ts.hour in hours:
        return ts
    for step in range(1, 49):
        candidate = (ts + timedelta(hours=step)).replace(minute=0, second=0, microsecond=0)
        if candidate.hour in hours:
            return candidate + timedelta(seconds=int(rng.integers(0, 3600)))
    return ts


def generate_adaptive_attack(
    rng: np.random.Generator,
    user_id: str,
    start_ts: datetime,
    victim: dict,
    gap_seconds: int,
    hours: list[int] | None,
    lure: bool,
    fatigue: FatigueConfig,
) -> list[RawEvent]:
    n = int(rng.integers(*PROMPT_COUNT_RANGE))
    lure_index = int(rng.integers(1, n)) if lure else None
    attacker_ip = f"198.18.1.{int(rng.integers(1, 254))}"
    attacker_device = f"unknown-device-{_rng_uuid(rng)}"
    session_id = str(_rng_uuid(rng))
    events: list[RawEvent] = []
    ts = _next_usual_time(start_ts, hours, rng) if hours else start_ts
    for i in range(n):
        if lure_index is not None and i == lure_index:
            decision, latency_ms = "approve", sample_lure_latency_ms(rng, fatigue)
        else:
            decision = _final_decision(rng) if i == n - 1 else "deny"
            latency_ms = sample_fatigue_latency_ms(rng, i, n, decision, fatigue)
        events.extend(
            _prompt_decision_pair(
                user_id=user_id,
                prompt_ts=ts,
                decision=decision,
                latency_ms=latency_ms,
                attacker_src_ip=attacker_ip,
                attacker_device_id=attacker_device,
                attacker_user_agent="AttackerClient/1.0",
                victim_src_ip=victim["src_ip"],
                victim_device_id=victim["device_id"],
                victim_user_agent=victim["user_agent"],
                session_id=session_id,
                geo_country=victim["country"],
                label_attack=True,
                attack_profile="adaptive",
            )
        )
        if decision == "approve":
            break
        jitter = 1.0 + float(rng.uniform(-GAP_JITTER, GAP_JITTER))
        ts = ts + timedelta(milliseconds=latency_ms) + timedelta(seconds=gap_seconds * jitter)
        if hours:
            ts = _next_usual_time(ts, hours, rng)
    return events


def victims_for_test_users(events_df: pd.DataFrame, seed: int, n_users: int, split: str = "test") -> list[dict]:
    logins = events_df[events_df["event_type"] == "login_attempt"]
    out = []
    for user_id, g in logins.groupby("user_id", sort=True):
        if assign_split(seed, user_id) != split:
            continue
        g = g.sort_values("ts")
        last = g.iloc[-1]
        out.append(
            {
                "user_id": user_id,
                "start_ts": last["ts"] + timedelta(hours=1),
                "device_id": last["device_id"],
                "user_agent": last["user_agent"],
                "src_ip": last["src_ip"],
                "country": last["geo_country"] if isinstance(last["geo_country"], str) else "US",
                "hours": usual_hours([t.to_pydatetime() for t in g["ts"]]),
            }
        )
        if len(out) >= n_users:
            break
    return out


def build_setting(victims: list[dict], seed: int, gap: int, usual: bool, lure: bool, victim_name: str) -> pd.DataFrame:
    fatigue = VICTIMS[victim_name]
    records = []
    for v in victims:
        # Paired across settings: the same per-user stream for every setting.
        rng = child_rng(seed, v["user_id"], "adaptive")
        burst = generate_adaptive_attack(
            rng, v["user_id"], v["start_ts"], v, gap, v["hours"] if usual else None, lure, fatigue
        )
        burst_id = f"adaptive:{v['user_id']}:{gap}:{int(usual)}:{int(lure)}:{victim_name}"
        records.extend(_raw_event_to_record(e, burst_id) for e in burst)
    df = pd.DataFrame.from_records(records)
    df["attack_profile"] = df["attack_profile"].astype(object)
    return df


def anti_lockout(df: pd.DataFrame, points: pd.DataFrame, hit_col: str) -> dict:
    """Replays each episode through the mitigation controller from the
    detector's first alert on; every step-up offered to the attacker fails.
    Then the legitimate user signs in LEGIT_RETURN_AFTER_SECONDS after the
    last prompt, and again one cooldown window later."""
    first_alert = {}
    for ep, g in points.groupby("generator_burst_id"):
        g = g.sort_values(["session_index", "decision_index"])
        k = next((j for j, f in enumerate(g[hit_col].to_numpy()) if f), None)
        if k is not None:
            first_alert[ep] = k
    actions_seen: set[str] = set()
    legit_first, legit_later = {}, {}
    for ep, g in df.groupby("burst_id"):
        if ep not in first_alert:
            continue
        g = g.sort_values("ts")
        decisions = g[g["event_type"] == "mfa_decision"]["ts"].tolist()
        prompts = g[g["event_type"] == "mfa_prompt"]["ts"].tolist()
        alert_ts = decisions[first_alert[ep]]
        state = UserMitigationState()
        for ts in [alert_ts] + [p for p in prompts if p > alert_ts]:
            action = decide_action(state, ts.to_pydatetime())
            actions_seen.add(action)
            if action == "step_up_required":
                state.record_failure(ts.to_pydatetime())
        back = prompts[-1].to_pydatetime() + timedelta(seconds=LEGIT_RETURN_AFTER_SECONDS)
        a1 = decide_action(state, back)
        a2 = decide_action(state, back + timedelta(seconds=STEP_UP_COOLDOWN_SECONDS))
        legit_first[a1] = legit_first.get(a1, 0) + 1
        legit_later[a2] = legit_later.get(a2, 0) + 1
        actions_seen |= {a1, a2}
    allowed = {"step_up_required", "alt_factor_required", "cooldown_active"}
    holds = actions_seen <= allowed and set(legit_later) <= {"step_up_required", "alt_factor_required"}
    return {
        "holds": holds,
        "n_alerted_episodes": len(first_alert),
        "actions_seen": sorted(actions_seen),
        "legit_user_on_return": legit_first,
        "legit_user_one_cooldown_later": legit_later,
    }


def evaluate_setting(df: pd.DataFrame, suite, seed: int) -> dict:
    view = prepare(df, seed)
    points = score_points(suite, view)
    out = {}
    episodes = points.groupby("generator_burst_id")
    for det in MODELS:
        caught = episodes[f"hit_{det}"].max()
        out[det] = {"recall": float(caught.mean()), "recall_ci": wilson(int(caught.sum()), len(caught)), "n": len(caught)}
    for name, res in evaluate_rules(df, seed).items():
        o = res["overall"]
        out[name] = {"recall": o["recall"], "recall_ci": wilson(o["tp"], o["tp"] + o["fn"]), "n": res["n_bursts_evaluated"]}
    durations = df.groupby("burst_id")["ts"].agg(lambda s: (s.max() - s.min()).total_seconds() / 3600)
    prompts = df[df["event_type"] == "mfa_prompt"].groupby("burst_id").size()
    out["_campaign"] = {
        "median_duration_hours": float(durations.median()),
        "median_prompts": float(prompts.median()),
        "capitulated": float(
            df[df["event_type"] == "mfa_decision"].groupby("burst_id")["decision"].agg(lambda d: (d == "approve").any()).mean()
        ),
    }
    out["_anti_lockout"] = anti_lockout(df, points, "hit_pulseguard")
    return out


def plot(results: dict, out_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    gaps = [g / 60 for g in GAPS_SECONDS]
    styles = {
        "splunk": ("Splunk", "#8c8c8c", "s"),
        "elastic": ("Elastic", "#e08a2c", "^"),
        "deny_run_rule": ("2 consecutive denials", "#222222", "x"),
        "pulseguard": ("PulseGuard", "#c23b5a", "D"),
    }
    fig, axes = plt.subplots(1, 4, figsize=(16, 3.8), sharey=True)
    for ax, (usual, lure) in zip(axes, itertools.product((False, True), (False, True))):
        for victim, dash in (("default_fatigue", "-"), ("no_latency_signal", "--")):
            for det, (name, colour, marker) in styles.items():
                if det != "pulseguard" and victim != "default_fatigue":
                    continue  # the rules never read latency
                ys = [results[victim][f"{g}:{int(usual)}:{int(lure)}"][det]["recall"] for g in GAPS_SECONDS]
                label = name if det != "pulseguard" else f"{name} ({'no latency signal' if dash == '--' else 'default victim'})"
                ax.plot(gaps, ys, dash, marker=marker, color=colour, label=label, markersize=4, linewidth=1.5)
        ax.axvline(60, color="#555", linewidth=0.8, linestyle=":")
        ax.text(66, 0.45, "session gap\n(60 min)", fontsize=7, color="#555")
        ax.set_xscale("log")
        ax.set_xticks([1, 2, 5, 10, 20, 60, 120, 240], ["1m", "2m", "5m", "10m", "20m", "1h", "2h", "4h"])
        ax.set_xlabel("Gap between prompts")
        ax.set_title(f"usual hours {'on' if usual else 'off'}, lure {'on' if lure else 'off'}", fontsize=10)
        ax.set_ylim(-0.02, 1.02)
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("Recall")
    axes[0].legend(fontsize=7, loc="center left")
    fig.suptitle("Adaptive attacker: recall vs pacing (detectors trained on the default corpus, seed 42)", fontsize=10)
    fig.tight_layout()
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rba-zip", default="data/raw/rba-dataset.zip")
    parser.add_argument("--scale", type=int, default=50000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-users", type=int, default=400, help="test-split victims per setting")
    parser.add_argument("--gru-epochs", type=int, default=None)
    parser.add_argument("--out", default="eval/results/adaptive_attacker.json")
    parser.add_argument("--plot", default="eval/results/adaptive_attacker.png")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("pulseguard.detection_engine.train_stage_c").setLevel(logging.WARNING)

    from services.detection_engine.app.train_stage_c import EPOCHS

    users = load_users(Path(args.rba_zip), args.scale)
    base = build_events(users, args.seed, DEFAULT_FATIGUE)
    view = prepare(base, args.seed)
    suite = train_suite(view, args.seed, args.gru_epochs or EPOCHS)
    from eval.research.suite import evaluate_models

    benign_fpr = {k: v["overall"]["fpr"] for k, v in evaluate_models(suite, score_points(suite, view), args.seed).items()}
    benign_fpr.update({k: v["overall"]["fpr"] for k, v in evaluate_rules(base, args.seed).items()})

    victims = victims_for_test_users(base, args.seed, args.n_users)
    results: dict[str, dict] = {}
    for victim_name in VICTIMS:
        results[victim_name] = {}
        for gap, usual, lure in itertools.product(GAPS_SECONDS, (False, True), (False, True)):
            df = build_setting(victims, args.seed, gap, usual, lure, victim_name)
            res = evaluate_setting(df, suite, args.seed)
            results[victim_name][f"{gap}:{int(usual)}:{int(lure)}"] = res
            logger.info(
                "%s gap=%5ds usual=%d lure=%d  pulseguard=%.3f elastic=%.3f splunk=%.3f  dur=%.1fh  lockout-invariant=%s",
                victim_name, gap, usual, lure, res["pulseguard"]["recall"], res["elastic"]["recall"] or 0,
                res["splunk"]["recall"] or 0, res["_campaign"]["median_duration_hours"], res["_anti_lockout"]["holds"],
            )
    out = {
        "seed": args.seed,
        "scale": args.scale,
        "n_victims_per_setting": len(victims),
        "setting_key": "gap_seconds:usual_hours(0/1):lure(0/1)",
        "victims": {k: v.as_dict() for k, v in VICTIMS.items()},
        "operating_point": suite.describe(),
        "benign_test_fpr_at_this_operating_point": benign_fpr,
        "anti_lockout_holds_everywhere": all(
            r["_anti_lockout"]["holds"] for v in results.values() for r in v.values()
        ),
        "results": results,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, default=str))
    if args.plot:
        plot(results, Path(args.plot))
    return 0


if __name__ == "__main__":
    sys.exit(main())

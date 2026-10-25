# PulseGuard handoff for Claude Code

Put this file in the root of your PulseGuard clone and tell Claude Code: "Read HANDOFF.md and start on task 1."

## Context

- Project: PulseGuard, a detector for MFA fatigue (push-bombing) attacks, MITRE ATT&CK T1621. University project, VIT BCSE410L.
- Repo: https://github.com/sehrawaty/PulseGuard. Spec in `CLAUDE.md`, decisions in `pulseguard/DECISIONS.md`, current results in `pulseguard/eval/results/final_report.md`.
- Literature survey (43 papers) and roadmap: https://claude.ai/artifact/LPuXUv4EziDpNziEjdXPtx
- Target: IEEE A4 conference paper format.

## The problem with the current results

Treat every number in `eval/results/` as untrusted until we reproduce it ourselves.

The benchmark is synthetic. `pulseguard/benchmark/generator/latency_models.py` hard-codes the fatigue signal: the median reaction time drops linearly from about 5 s (`FATIGUE_MU_START = 1.6`) to 0.74 s (`FATIGUE_MU_END = -0.3`) across a burst. The detector then learns that line, so the near-perfect scores (precision 0.999, recall 1.000) are circular. The RBA base dataset contains no push prompts or approve/deny decisions, so every reaction time is synthetic.

## Contributions to deliver

1. A detector that reads how the user responds, evaluated honestly across fatigue strengths.
2. An evaluation against adaptive attackers with a budget.
3. A new metric: detection before capitulation (before the victim taps Approve).
4. A released, seeded benchmark generator with adjustable fatigue strength.

Out of scope: a real-human user study. It goes in the paper as future work.

## Tasks, in order

### Task 0: Reproduce
- `pip install -r pulseguard/requirements-dev.txt`, then from `pulseguard/`: `make pipeline SEED=42` (the `data` target downloads the RBA dataset from Zenodo, about 1.1 GB). Use a smaller `SCALE` first if the machine is slow.
- Run `make test`.
- Compare the fresh `eval/results/*.json` with the committed ones. Write `eval/results/REPRODUCTION.md` listing each headline number: committed value, reproduced value, match yes/no.

### Task 1: Fatigue-strength sweep
- Make the fatigue strength a generator parameter. For example, add `--fatigue-strength s` in [0, 1], where `FATIGUE_MU_END = FATIGUE_MU_START + s * (-0.3 - 1.6)`. s = 0 means no latency drop at all, and s = 1 is the current setting. Keep the default identical to today so the seed-42 corpus is unchanged.
- For s in {0, 0.25, 0.5, 0.75, 1.0}: regenerate the corpus, retrain, and evaluate with the frozen harness (by-user split, same seed).
- Report precision, recall and false-positive rate for Splunk, Elastic, frequency-only, and full PulseGuard at each s. Save to `eval/results/fatigue_sweep.json` and plot it to `eval/results/fatigue_sweep.png`.
- Key question: at s = 0, does PulseGuard still beat the rules (because of deny-run and capitulation features)? Report the answer honestly either way.

### Task 2: Detection before capitulation
- For each attack episode, find the index of the first decision point where the fused score crosses the threshold, and the index of the capitulating approval.
- Report: the share of attacks detected strictly before the approval, the median number of prompts until detection, and the same for the Splunk and Elastic rules (the moment each rule would first fire).
- Save to `eval/results/before_capitulation.json`.

### Task 3: Adaptive attacker with a budget
- Extend `eval/adversarial/` with an attacker that chooses (a) the gap between prompts, from 1 minute to several hours, (b) whether prompts happen in the victim's usual login hours, taken from their benign history, and (c) a lure on or off.
- Plot recall against the attacker's pacing for Splunk, Elastic and PulseGuard. Save to `eval/results/adaptive_attacker.json` and `.png`.
- Also check the anti-lockout invariant at every setting.

### Task 4: One learned baseline (optional)
- Add an Isolation Forest on the same feature vector (unsupervised, trained on benign training users only). Evaluate with the frozen harness next to the rules.

### Task 5: Write-up
- Regenerate `final_report.md` and add the new tables and figures.
- Reframe the claim: response behaviour cuts false positives on heavy legitimate users. `latency_drift_slope` is a hypothesis that needs real human data.

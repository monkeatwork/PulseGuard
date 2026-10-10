> **Status (2026-10-11): addressed.** Each item below is resolved in code and recorded in `DECISIONS.md` ("Remediation (REMEDIATION_TASK.md)" entries), with the re-measured results in `eval/results/` and `final_report.md`. This file is kept as the record of what was asked.

# Remediation task — PulseGuard

You are working on **PulseGuard**, a behaviour-aware detector for MFA fatigue attacks
(MITRE ATT&CK T1621). It is a university project for BCSE410L Cyber Security at VIT.
All 8 implementation phases are already built and evaluated; 229 Python tests and 15
dashboard component tests pass; the live Docker pipeline runs end to end. Your job is
**not** to build features. Your job is to fix 14 verified defects, several of which
currently invalidate the project's reported results.

## Read these first, in this order

1. `CLAUDE.md` — the authoritative spec. Its "core insight" and "evaluation rules"
   sections override any convenience you might be tempted by.
2. `DECISIONS.md` — the append-only narrative record of every decision, bug and honest
   finding so far. **Long, but read the last five entries in full**: they contain the
   evidence behind most of the defects below, including two mandatory disclosures that
   must survive your changes.
3. `eval/results/final_report.md` — every currently reported number. Generated from
   JSON, never hand-edited. Assume it is **stale the moment you start**.

## Hard rules — these are not negotiable and not yours to relax

1. **Split train/test BY USER, never by event.** Event-level splits leak per-user
   baseline state. `eval/harness/split.py` already does deterministic MD5 bucketing;
   do not replace it.
2. **False-positive rate is a primary reported metric.** Not an afterthought, not
   omitted when inconvenient.
3. **Do not tune anything until it looks good.** This is the single most important
   rule in this task. If a fix makes a metric worse, report the worse number. If
   `latency_drift_slope` still shows no lift after you fix the granularity problem,
   say so plainly. A clearly-reported negative result is worth more than an inflated
   one, and inflating one here would destroy the project's credibility.
4. **Never adjust a threshold, weight or feature set to move a metric** unless that
   adjustment is itself tuned on the **validation** split and documented. Test-split
   users must never influence any tuning decision.
5. **The benchmark generator stays seeded and deterministic.** Same seed, byte-identical
   output. There is a determinism test; keep it passing.
6. **`docker compose up` remains the only setup step.** No manual bootstrap.
7. **Every autonomous decision gets one line in `DECISIONS.md`**: what you decided,
   what you rejected, why. Append; never rewrite history. If you later discover a
   decision was wrong, add a new entry rather than editing the old one.
8. **Do not modify `eval/harness/`** to make results change. The harness is frozen and
   reused verbatim across phases; that is what makes the numbers comparable. If you
   genuinely believe the harness is wrong, stop and surface it rather than editing it.

## The cascade — read before touching anything

These defects are not independent. Changing the benchmark data or the feature
granularity invalidates the trained Stage B/C models, the tuned fusion weights, and
every number in `eval/results/`. The phases below are ordered so the expensive
retrain-and-re-evaluate cycle happens **once**, at a single point, rather than after
each fix. Do not reorder without a reason recorded in `DECISIONS.md`.

Work phase by phase. Do not start a phase before the previous one's verification passes.

---

## Phase A — Benchmark and granularity

Everything here changes the data or the features, so it must land before any retraining.

### A1. The Redis burst buffer expires before low-and-slow's next prompt arrives

`common/pulseguard_common/redis_keys.py:9` sets `BURST_KEY_TTL_SECONDS = 15 * 60`.
`benchmark/generator/attack_profiles.py:47` sets
`LOW_AND_SLOW_GAP_SECONDS_RANGE = (20 * 60, 40 * 60)`.

The TTL is **shorter than the inter-prompt gap**, so a low-and-slow user's buffer is
gone before their next prompt arrives. Combined with the 5-minute gap segmentation in
`common/pulseguard_common/windows.py`, every low-and-slow prompt becomes an isolated
single-event fragment with no history — so the response-behaviour features are
structurally undefined for **the exact attack profile the project claims to catch that
fixed-threshold SIEM rules miss.**

This is the root cause of the two problems below it (A2, and the zero lift of
`latency_drift_slope`). Fix this first and carefully.

Note the design tension before you pick a fix: the 5-minute segmentation threshold is
*deliberate* — it exists so low-and-slow's 20-40 minute pacing is correctly **not**
treated as one dense burst. So the answer is probably **not** "raise the gap
threshold", which would merge fragments the design wants separate. Consider instead a
per-user rolling window or session-level aggregation layer that spans fragments while
keeping fragment-level burst semantics intact. Whatever you choose, record the rejected
alternatives.

**Verify:** a replayed low-and-slow episode produces a feature vector in which
`latency_drift_slope_valid` is `True` and `deny_run_length` reflects the whole episode,
not a single prompt.

### A2. Live scores fragments; the evaluation scored episodes

The offline harness scores one **episode** (a whole labelled session). The live feature
engine scores **gap-segmented fragments**. The score distributions differ, so the frozen
operating point does not transfer: with the tuned threshold of 0.01, benign
`benign_high_activity` fragments score ~0.050-0.056 and raise alerts, while offline that
same threshold measured `fpr = 0.000` on 1537 benign episodes. Both numbers are correct;
they measure different objects.

Pick one and justify it: either score at session granularity in the live path so it
matches the evaluation, or re-run the frozen harness at fragment granularity so the
reported numbers describe what actually runs. **Session-level scoring is the more
principled choice** and likely resolves A1 at the same time — but if you choose it,
confirm the in-band latency budget in `CLAUDE.md` (single-digit-millisecond scoring)
still holds, since aggregation adds work per event.

**Verify:** the granularity the live path scores at is the granularity the reported
FPR was measured at. State explicitly in `DECISIONS.md` which one you chose.

### A3. The hard negative never denies

`benchmark/generator/attack_profiles.py`'s `generate_benign_high_activity_session`
hardcodes `decision="approve"`. No benign example in the corpus ever contains an
isolated denial, so "any lone denial is an attack" is a free shortcut the models can
take instead of learning response-behaviour drift. A partial fix
(`generate_benign_occasional_denial_session`) was added earlier; it is not enough,
because the *high-activity* hard negative — the one that makes the FPR metric
meaningful — still never denies.

Give the high-activity hard negative occasional genuine denials (a user who fat-fingers,
or declines a prompt they did not expect, then approves the next one legitimately).
Latency distributions must come from the published human-subjects parameters already in
`benchmark/generator/latency_models.py` — do not invent new ones.

**Verify:** a benign high-activity session can contain a denial followed by an approval
without being labelled an attack, and the shortcut no longer separates the classes.

### A4. Stage C's near-perfect scores are confounded by episode length

Episode lengths are disjoint across profiles: roughly 4 events for benign fragments,
12-26 for low-and-slow, 30-78 for high-volume burst. Stage C can therefore separate the
classes by **counting events**, which is not the fine-grained temporal learning the GRU
is there to demonstrate. Its reported perfect scores are substantially a benchmark
artifact.

Make the length ranges overlap materially across profiles, so length alone cannot
separate them.

**Verify:** compute and record the length distribution per profile; overlap must be
substantial. Then, after Phase B retraining, compare Stage C's score to its old one —
**expect it to drop, and report the drop.** A drop here is the benchmark getting more
honest, not a regression.

---

## Phase B — Retrain, retune, and make the live path match the evaluation

Run this phase **once**, after Phase A is fully verified.

### B1. Retrain and re-evaluate everything

In dependency order: regenerate the benchmark (`make data` must stay idempotent) →
retrain Stage B (`train_stage_b.py`) → retrain Stage C (`train_stage_c.py`) → re-tune
fusion weights on the **validation split only** (`tune_fusion_weights.py`) → re-run the
full evaluation → re-run the ablation → re-run the adversarial evaluation →
regenerate `eval/results/final_report.md` from JSON.

Also re-reproduce the two industry baselines (Splunk `>9 prompts/10min`, Elastic
`2 denials + success/10min`) on the new corpus. Every later claim is measured against
them, so they must describe the same data.

**Verify:** `final_report.md` is regenerated from JSON with no hand-typed numbers, and
`eval/results/*.json` all refer to the new corpus.

### B2. The live system runs at fusion weights nothing was ever evaluated at

`services/detection_engine/app/live_scorer.py:92` does `self._weights = FusionWeights()`
— the **defaults** (0.25 / 0.45 / 0.30). The tuned weights recorded in
`eval/results/full_fusion.json` are `{a: 0.0, b: 0.0, c: 1.0}`.
`services/detection_engine/app/tune_fusion_weights.py:143` writes its results to
`full_fusion.json` and **never persists the weights anywhere loadable** — so the live
scorer could not have loaded them even if it tried.

Every reported metric was measured at the tuned weights. The running system scores at
the untuned defaults. They are different systems.

Persist the tuned weights to `services/detection_engine/app/model_registry/` alongside
`stage_b.json` and `stage_c.pt`, and load them in `live_scorer.py`. **Build this
persistence mechanism early in the phase and populate it at the end**, after retuning.
Fail loudly on startup if the weights file is missing — silently falling back to
defaults is exactly the bug you are fixing.

Do the same for the alert threshold: `ALERT_THRESHOLD` in `live_scorer.py` is currently
a hardcoded default of `0.01` copied by hand from `full_fusion.json`. It should be read
from the persisted operating point, so the live system cannot drift from the evaluated
one again.

**Verify:** an automated test asserts the live scorer's weights and threshold equal the
persisted tuned values, and that a missing weights file raises rather than defaults.

### B3. Decide honestly what tuned weights of (0, 0, 1) mean

If retuning again collapses to Stage C alone, then Stage A and Stage B contribute
**nothing** to the reported numbers — including Stage B, the XGBoost over the
response-behaviour feature vector, which is the project's stated contribution. The
"weighted fusion of three stages" claim would then be describing something the system
does not do.

**Do not force the weights to be non-zero to make the architecture look used.** That
would be tuning for appearance and is forbidden by rule 3. Instead, resolve it honestly.
Legitimate outcomes include: the grid search was over too coarse a grid or the wrong
objective and a corrected search yields a genuine mixture; or Stage C really does
dominate on this benchmark and the fusion claim should be narrowed to say so. Either is
publishable. Pretending is not.

Note that A4 may change this on its own: if Stage C was winning partly by counting
events, removing that shortcut may redistribute the weights legitimately.

**Verify:** `DECISIONS.md` states the resolved position and the evidence for it.

### B4. SHAP explanations currently explain a component with zero weight

`explain_shap.py` derives the analyst-facing "top-3 reasons" from **Stage B**. At the
tuned weights, Stage B has weight 0.0 — so the reasons shown on the dashboard explain a
model that did not contribute to the score that fired the alert. The explainability
story is incoherent as it stands.

The fix depends on B3's outcome. If fusion legitimately becomes a mixture, SHAP over
Stage B is defensible and you need only confirm it. If Stage C continues to dominate,
the explanation must either come from the dominant component or be labelled clearly for
what it is. There is an existing test (`test_shap_top3.py`) asserting a
response-behaviour feature appears in the top 3; make sure it still tests something
meaningful rather than something decorative.

**Verify:** the explanation shown for an alert is attributable to the component that
actually drove that alert's score.

### B5. Re-check the two mandatory disclosures

Two findings were disclosed honestly in `DECISIONS.md` and must be re-examined, not
quietly dropped:

- **`latency_drift_slope` showed exactly 0.0 percentage points of lift** — the full
  model and the minus-slope model produced byte-identical predictions
  (tp=8098, fp=753, tn=21771, fn=647). `CLAUDE.md` calls this feature "the single most
  important feature in the system." Phase A should make it computable where it
  previously was not. **Re-run the ablation with `latency_drift_slope` individually
  removed and report the result either way.** If it still shows no lift, that stands as
  the project's honest finding and the claim about the feature must be corrected, not
  the measurement.
- **Stage C's near-perfect performance was substantially a length artifact** (A4).
  Re-measure and report the new number.

The report has an automatic `NO MEASURABLE LIFT` banner with a documented 2-point noise
floor (`eval/ablation/run_ablation.py`). It is deliberately **not manually
suppressible**. Leave it that way.

**Verify:** the ablation runs with the feature genuinely excluded from the vector (not
merely untrained-on — there is already a test for this), and the banner fires correctly
in both directions.

---

## Phase C — Live-path robustness

No re-evaluation needed; these are runtime correctness only.

### C1. Kafka offsets are auto-committed with no failure path

`live_scorer.py` and `services/mitigation/app/live_worker.py` both use confluent-kafka's
default auto-commit. A crash mid-batch silently drops or double-processes bursts.
Worse, `live_scorer.py:221` catches **every** exception and continues, so a
systematically malformed message is lost with nothing but a log line.

Commit offsets explicitly after successful processing, and add a dead-letter path so a
message that cannot be processed is preserved and visible rather than swallowed.

**Verify:** a test proves a message that raises during scoring is not silently lost,
and that offsets are not advanced past an unprocessed message.

### C2. At-least-once delivery is accidental, not designed

In `services/feature_engine/app/streaming_app.py`, the finalize timer sends enriched
messages **before** deleting the consumed Redis buffer. This happens to preserve the
buffer if the send crashes — which is genuinely what saved a real crash during
development — but nothing documents or asserts it, so any future reordering would
silently remove the property.

Make it deliberate: document the ordering as load-bearing and add a test that fails if
the delete moves before the send.

### C3. Concurrent bursts for one user share the wrong context

Flagged in `streaming_app.py`'s own module docstring: when one timer tick finalizes more
than one burst for the same user, every finalized burst uses the **last** raw event in
that user's buffer for geo/device context, rather than the context belonging to that
specific burst. Attach context per burst.

**Verify:** a unit test with two ready bursts for one user, each carrying different
geo/device values, asserts each gets its own.

### C4. Single-partition topology with no scale path

`pulseguard.events.raw` runs with 1 partition. This was a deliberate correction — Faust
requires a table to co-partition with its source topic, and a 6-partition table against
a 1-partition topic caused a `PartitionsMismatch` crash-loop (recorded in
`DECISIONS.md`). Since the per-user buffer now lives in Redis rather than a Faust table,
that constraint may no longer bind.

Re-examine whether multi-partition operation is now possible, keyed by `user_id` so a
user's events stay ordered within a partition. If it is still not worth it for a
single-worker deployment, record that as the decision and move on — this is the lowest
priority item in the phase.

---

## Phase D — Completeness and honesty of scope

### D1. Four of five telemetry adapters do not exist

`CLAUDE.md` describes L1 as "Entra ID sign-in logs, Okta System Log, Duo Admin API,
Keycloak (prototype), benchmark replay — all behind one adapter interface."
`services/ingestion/app/adapters/` contains **only** `replay.py`. There is no adapter
interface at all, just one concrete implementation.

Either implement the interface plus at least the Keycloak prototype adapter (a Keycloak
container is already running and currently unused — see D2), or **correct `CLAUDE.md`
and the report to describe what actually exists.** Both are acceptable; claiming five
adapters when there is one is not. If you implement the interface, define it so
`replay.py` becomes one implementation of it rather than a special case.

### D2. Keycloak runs but nothing touches it

A healthy Keycloak container is in `docker-compose.yml` with no code path using it.
Either wire it up as the test IdP `CLAUDE.md` says it is (pairs naturally with D1), or
remove it from the compose file. A container that exists only to look complete is worse
than no container.

### D3. README does not document the live pipeline

`README.md` is 55 lines and never mentions the replay endpoint, how to trigger a live
detection, or the dashboard URL — so nobody can actually run the thing it describes.
Document: `docker compose up`, `make data`, how to trigger a replay, where the dashboard
is, and what a reader should expect to see. Include the known-issues section honestly.

---

## Environment traps — these cost real debugging time already

- **Anything imported by more than one service's Docker image must live in
  `common/pulseguard_common/`.** Each service's Dockerfile copies only its own directory
  plus `common/`. A `services.<other_service>.app.X` import works locally (whole repo on
  `sys.path`) and fails in the container. This has bitten this project three times.
- **Faust forbids writing to a Table outside stream iteration.** Time-driven
  finalization must use Redis, not a Faust table. Do not "simplify" it back.
- **`tests/integration/test_compose_health.py` is destructive.** testcontainers tears
  down with `docker compose down --volumes`, deleting the `pg_data` volume and every
  alert/event row, and leaves the stack down. This is correct for what it asserts (a
  *clean* checkout comes up with zero steps) — do not soften it, just do not run it
  against data you want to keep.
- **pytest requires unique test-file basenames repo-wide** (no `__init__.py` in test
  dirs). Two files named `test_api.py` in different services will fail collection.
- **Configure logging inside the FastAPI lifespan with `force=True`**, not at module
  import. uvicorn's `dictConfig` clears root handlers, and bare `basicConfig()` is a
  silent no-op if root already has one. See `detection_engine/app/main.py`.
- **Redis publishes on host port 6380, not 6379. Redpanda's host-reachable listener is
  19092, not 9092** (9092 is the internal listener, advertised as `redpanda:9092`, which
  resolves only inside the compose network).
- **Rebuild with `docker compose build` after editing service code.** A stale image
  silently running old code has caused a confusing debugging session here before.
- Docker Desktop on this machine has been flaky under load: host-side `POST` requests
  sometimes hang. Reproduce from inside the container
  (`docker compose exec <service> python -c "..."`) before suspecting application code.

## Definition of done

- All 229+ Python tests and 15 dashboard tests pass, plus new tests for each fix above.
- `eval/results/final_report.md` is regenerated from JSON and describes the system that
  actually runs — same granularity, same weights, same threshold.
- `DECISIONS.md` has an entry per fix: decided / rejected / why, including every place a
  metric got **worse**.
- The two mandatory disclosures are re-measured and reported honestly, whichever way
  they land.
- No metric was moved by adjusting a threshold, weight or feature set outside a
  documented validation-split tuning step.

## Surface rather than resolve

Stop and report, instead of working around, if:

- The Zenodo RBA dataset cannot be re-fetched (record 10.5281/zenodo.6782156). **Do not
  substitute synthetic benign data** — the FPR metric depends on real benign behaviour.
  Report the exact error.
- `latency_drift_slope` still shows no measurable lift after Phase A. Carry on building
  and flag it plainly. Do not tune the evaluation until the feature looks good.
- Any fix would require an event-level train/test split, weakening the anti-DoS
  invariant (the escalation ceiling must never lock out a legitimate user), or editing
  the frozen harness.
- A fix would make a reported metric worse and you cannot see how to avoid it. Report
  the worse number; do not hide it.

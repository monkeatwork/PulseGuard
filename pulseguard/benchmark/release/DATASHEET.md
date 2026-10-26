# Datasheet: PulseGuard MFA-fatigue benchmark v{version}

Structure follows Gebru et al., "Datasheets for Datasets" (CACM 2021).

## Motivation

**Why was it created?** No public labelled dataset of MFA fatigue (push-bombing,
MITRE ATT&CK T1621) exists. Detectors for it are evaluated on private logs or not
at all. This corpus provides labelled push-flood episodes alongside realistic
benign authentication, so detectors can be compared on precision, recall and
false-positive rate.

**Who created it?** The PulseGuard project (BCSE410L Cyber Security, VIT SCOPE).

## Composition

**What do the instances represent?** Authentication events of one user:
`login_attempt` (from the base dataset), and `mfa_prompt` / `mfa_decision` pairs
(generated). Events are grouped into labelled **episodes** (`burst_id`); an
episode is either one attack or one benign stretch of MFA activity.

{stats}

**Labels.** `label_attack` (bool) on every event of an episode; `attack_profile`
names the attack type, or is empty for benign episodes:

| Profile | What it is |
|---|---|
| `high_volume_burst` | Many prompts within minutes until the victim approves or the attacker stops |
| `low_and_slow` | Prompts paced below fixed SIEM thresholds |
| `social_engineering_assisted` | A lure (e.g. a fake helpdesk call) mid-burst; the victim approves quickly |
| benign `benign_high_activity` | Power users with many legitimate logins per day, occasionally a deny and a retry |
| benign `benign_occasional_denial` | One denied prompt (mis-tap), later unrelated approvals |
| `plain_benign` | Base-dataset logins with no MFA activity (no episode) |

**Is anything missing?** Real attacker and victim behaviour. Decisions and
decision latencies are generated, not observed (see Collection).

**Recommended split.** By user, never by event: `splits.csv` gives each user's
split (70/15/15, MD5 of seed and user ID). Event-level splits leak per-user
baselines across the split.

**Confidential data?** Login fields (user ID, IP, country, device, user agent)
come from the base dataset as its authors published it; see its documentation
for how it was anonymised. Generated fields contain no personal data.

## Collection process

- **Base:** Wiefling et al., "Login Data Set for Risk-Based Authentication",
  Zenodo, doi:10.5281/zenodo.6782156 (CC BY 4.0). The first {users} distinct
  users in file order, with their login attempts among the first {rows_scanned}
  rows.
- **Overlay:** `benchmark/generator` (seeded, deterministic) adds prompt/decision
  pairs. Approve and deny latencies are lognormal. In this version the
  parameters are the generator's default (`benign_source = {benign_source}`).
  The default parameters are hand-picked; the optional `duolungo` source fits
  the approve latency to 16,851 real Duo logins (Prapty & Tsudik, NDSS USEC
  2026). Under attack, latency shrinks over the burst towards a reflexive tap.
  That collapse is a modelling assumption, not a measurement: no published
  study has measured latency under push-bombing.
- **Seed:** {seed}. The corpus can be regenerated bit-for-bit in content (see
  README, "Verify").

## Known properties a user of the corpus should know

- In this version no benign episode has two consecutive denials. A one-line rule
  ("two denials in a row") therefore separates the classes almost perfectly. The
  generator has an opt-in `--benign-deny-run-rate` for harder benign data.
- Every benign denial is followed by an approval within the hour. Rules that
  count unresolved denials across sessions get a free advantage here.
- The base data cover a few days of activity per user, so long-horizon
  (weeks) behaviour is not represented.

## Uses

**Intended:** benchmarking MFA-fatigue detectors; ablations of
frequency vs response-behaviour signals; teaching.

**Not intended:** estimating real-world prevalence of MFA fatigue, or claims
about real human latency under attack. Results on this corpus are an upper bound
on what transfers to real logs.

## Distribution

- **License:** CC BY 4.0 (see `LICENSE-DATA.md`). Attribution is required for the base dataset
  and this corpus.
- **Integrity:** `SHA256SUMS` (file bytes) and `manifest.json` →
  `content_sha256` (row content, independent of the parquet writer version).

## Maintenance

Issues and corrections are tracked in the project repository. Any new version
will change `version` and `content_sha256`, and will be described in the
changelog.

// Plain-language glossary for every feature in the detector's vector
// (common/pulseguard_common/enrichment.py: BurstFeatureVector).

export const FREQUENCY = [
  { key: "n_prompts", label: "Prompts in session", help: "How many push prompts this session has contained so far.", fmt: "int" },
  { key: "prompts_per_window", label: "Prompts in last 10 min", help: "Prompts inside the 10-minute window ending now — the same window Splunk's >9-in-10-min rule counts.", fmt: "int" },
  { key: "inter_prompt_mean", label: "Mean gap between prompts", help: "Average time between consecutive prompts in the session.", fmt: "s" },
  { key: "inter_prompt_std", label: "Gap variability", help: "Standard deviation of the gaps between prompts.", fmt: "s" },
  { key: "burst_duration_seconds", label: "Session duration", help: "First prompt to latest prompt.", fmt: "s" },
  { key: "off_hours_flag", label: "Off-hours", help: "First prompt falls between 00:00 and 06:00 UTC.", fmt: "bool" },
  { key: "geo_novelty", label: "New country", help: "Country never seen for this user before.", fmt: "bool" },
  { key: "device_novelty", label: "New device", help: "Device never seen for this user before.", fmt: "bool" },
  { key: "baseline_is_cold_start", label: "Cold-start baseline", help: "Fewer than 30 observed events for this user: the cohort baseline is blended in.", fmt: "bool" },
];

export const RESPONSE = [
  { key: "latency_drift_slope", valid: "latency_drift_slope_valid", label: "Latency drift slope", help: "Linear-regression slope of decision latency across the session (ms per prompt). Strongly negative when deliberation collapses into a reflexive tap.", fmt: "slope", star: true },
  { key: "deny_run_length", label: "Leading deny run", help: "Consecutive denials before the first approval.", fmt: "int" },
  { key: "capitulation_flag", label: "Capitulation", help: "The deny → deny → … → approve signature (at least two denials, then an approval).", fmt: "bool" },
  { key: "approval_latency_z", valid: "approval_latency_z_valid", label: "Approval latency z-score", help: "How unusual the approval's latency is against this user's own history.", fmt: "z" },
  { key: "post_burst_approval_gap_seconds", valid: "post_burst_approval_gap_valid", label: "Gap: last denial → approval", help: "Time between the final denial and the eventual approval.", fmt: "s" },
  { key: "denial_latency_variance", valid: "denial_latency_variance_valid", label: "Denial latency variance", help: "Spread of the user's denial response times (ms²).", fmt: "var" },
];

export const STEP_FEATURES = {
  "sequence: denials": "Denials in the sequence",
  "sequence: approvals": "Approvals in the sequence",
  "sequence: unanswered prompts": "Unanswered prompts",
  "sequence: latency present": "Answered prompts",
  "sequence: decision latency": "Decision latency pattern",
  "sequence: inter-prompt gap": "Prompt pacing",
};

const ALL = Object.fromEntries([...FREQUENCY, ...RESPONSE].map((f) => [f.key, f]));
export const featureLabel = (key) => ALL[key]?.label || STEP_FEATURES[key] || key;

export function formatFeature(f, vector) {
  const v = vector?.[f.key];
  if (f.valid && vector && vector[f.valid] === false) return null;
  if (v == null) return null;
  switch (f.fmt) {
    case "bool":
      return v ? "Yes" : "No";
    case "int":
      return String(v);
    case "s":
      return v >= 3600 ? `${(v / 3600).toFixed(1)} h` : v >= 60 ? `${(v / 60).toFixed(1)} min` : `${Number(v).toFixed(1)} s`;
    case "slope":
      return `${v > 0 ? "+" : ""}${Math.round(v)} ms/prompt`;
    case "z":
      return `${v > 0 ? "+" : ""}${Number(v).toFixed(2)} σ`;
    case "var":
      return `${(Math.sqrt(v) / 1000).toFixed(2)} s (sd)`;
    default:
      return String(v);
  }
}

export const STAGES = [
  { key: "a", name: "Stage A", full: "Stage A · per-user statistical deviation", color: "var(--series-1)" },
  { key: "b", name: "Stage B", full: "Stage B · XGBoost over the feature vector", color: "var(--series-2)" },
  { key: "c", name: "Stage C", full: "Stage C · GRU over the event sequence", color: "var(--series-3)" },
];
export const SOURCE_LABEL = { stage_a: "Stage A (statistical)", stage_b: "Stage B (XGBoost · TreeSHAP)", stage_c: "Stage C (GRU · occlusion)" };

export const PROFILES = {
  high_volume_burst: { label: "High-volume burst", attack: true, blurb: "Many prompts in quick succession until the victim gives in — the classic MFA bombing." },
  low_and_slow: { label: "Low-and-slow", attack: true, blurb: "Prompts paced 20–40 minutes apart to stay under every fixed-threshold SIEM rule." },
  social_engineering_assisted: { label: "Social-engineering assisted", attack: true, blurb: "A fake 'IT support' call mid-burst talks the victim into a fast approval." },
  benign_high_activity: { label: "Benign power user", attack: false, blurb: "A legitimate user approving dozens of logins a day — with the occasional honest denial. The hard negative." },
  benign_occasional_denial: { label: "Benign occasional denial", attack: false, blurb: "One mis-tap or unrecognised prompt, then ordinary approvals. Must not alert." },
  simulator_attack: { label: "Live simulator (attack)", attack: true, blurb: "You played the victim." },
  simulator_benign: { label: "Live simulator (benign)", attack: false, blurb: "You logged in yourself." },
};
export const profileLabel = (p) => PROFILES[p]?.label || p || "Unlabelled";

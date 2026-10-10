import { AlertTriangle, CheckCircle2, FileText, ShieldCheck, Swords } from "lucide-react";
import { api } from "../api/client.js";
import { Card, Empty, ErrorNote, Help, Legend } from "../components/ui.jsx";
import { fmtPct, fmtNum } from "../lib/format.js";
import { profileLabel } from "../lib/features.js";
import { usePoll } from "../lib/hooks.js";

const DETECTORS = [
  { key: "baseline_splunk", label: "Splunk rule", sub: ">9 prompts in 10 min", baseline: true },
  { key: "baseline_elastic", label: "Elastic rule", sub: "2 denials + success in 10 min", baseline: true },
  { key: "stage_ab", label: "Stage A or B", sub: "either stage fires" },
  { key: "stage_a_only", label: "Stage A alone", sub: "fixed statistical rule" },
  { key: "stage_b_only", label: "Stage B alone", sub: "XGBoost, calibrated" },
  { key: "stage_c", label: "Stage C", sub: "GRU over the sequence" },
  { key: "full_fusion", label: "PulseGuard fusion", sub: "A + B + C at the operating point", ours: true },
];
const ATTACK_PROFILES = ["high_volume_burst", "low_and_slow", "social_engineering_assisted"];

// One-hue sequential ramp (blue 150 -> 650) for the per-profile table.
const RAMP = ["#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281"];
const rampColor = (v) => RAMP[Math.max(0, Math.min(RAMP.length - 1, Math.round(v * (RAMP.length - 1))))];
const inkOn = (v) => (v > 0.55 ? "#fff" : "var(--ink)");

function Bar({ value, color = "var(--series-1)", max = 1 }) {
  const v = value == null ? 0 : value;
  return (
    <div className="row" style={{ gap: 8 }}>
      <div style={{ flex: 1, height: 10, background: "var(--surface-sunken)", borderRadius: 4 }}>
        <div style={{ width: `${Math.min(1, v / max) * 100}%`, height: "100%", background: color, borderRadius: "0 4px 4px 0" }} />
      </div>
      <span className="num small" style={{ width: 52, textAlign: "right" }}>{value == null ? "n/a" : value.toFixed(3)}</span>
    </div>
  );
}

// stage_ab.json also carries each half of "A OR B" on its own; surface them
// as their own detector rows so a false positive can be traced to its stage.
function withSubDetectors(r) {
  if (!r?.stage_ab) return r;
  const out = { ...r };
  if (r.stage_ab.stage_a_only) out.stage_a_only = r.stage_ab.stage_a_only;
  if (r.stage_ab.stage_b_only) out.stage_b_only = r.stage_ab.stage_b_only;
  return out;
}

export default function Evaluation() {
  const res = usePoll(() => api.evalResults(), 0);
  const r = withSubDetectors(res.data);
  if (res.error) return <ErrorNote error={res.error} />;
  if (!r) return <Card><Empty title="Loading results…" /></Card>;
  if (!r.full_fusion) return <Card><Empty icon={FileText} title="No evaluation results found">Run the offline pipeline (make pipeline).</Empty></Card>;

  const fusion = r.full_fusion;
  return (
    <>
      <div className="banner info">
        <FileText size={18} />
        <div className="small">
          Every number on this page is read verbatim from <code>eval/results/*.json</code>, produced by the frozen evaluation harness on the
          <b> by-user test split</b> (no test user was ever seen in training or tuning). Unit: <b>{fusion.unit || "episode"}</b> — the same rule the
          live system alerts on.
        </div>
      </div>

      <div className="grid g-main">
        <Card title="Detectors on the same test split" sub="False-positive rate is a primary metric, reported next to recall and precision"
          actions={<Legend items={[{ label: "Industry baseline", color: "var(--series-muted)" }, { label: "PulseGuard", color: "var(--series-1)" }]} />}>
          <table className="table">
            <thead>
              <tr>
                <th>Detector</th>
                <th style={{ width: "22%" }}>Recall</th>
                <th style={{ width: "22%" }}>Precision</th>
                <th style={{ width: "22%" }}>False-positive rate <Help text="Share of benign episodes (including the benign power users) that raised an alert. Lower is better." /></th>
              </tr>
            </thead>
            <tbody>
              {DETECTORS.filter((d) => r[d.key]).map((d) => {
                const o = r[d.key].overall;
                const color = d.baseline ? "var(--series-muted)" : "var(--series-1)";
                return (
                  <tr key={d.key} style={d.ours ? { background: "var(--brand-soft)" } : undefined}>
                    <td>
                      <div style={{ fontWeight: 600 }}>{d.label}</div>
                      <div className="tiny muted">{d.sub}</div>
                    </td>
                    <td><Bar value={o.recall} color={color} /></td>
                    <td><Bar value={o.precision} color={color} /></td>
                    <td><Bar value={o.fpr} color={o.fpr > 0.05 ? "var(--serious)" : color} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="tiny muted" style={{ marginTop: 8 }}>
            n = {fmtNum(fusion.n_episodes_evaluated)} test episodes · confusion counts: TP {fusion.overall.tp} · FP {fusion.overall.fp} · TN {fusion.overall.tn} · FN {fusion.overall.fn}
          </div>
        </Card>
        <Card title="Operating point" sub="Tuned on the validation split only, persisted, and loaded by the live scorer">
          <OperatingPoint fusion={fusion} />
        </Card>
      </div>

      <Card title="Recall by attack profile" sub="Where each detector catches — and misses — the three attack styles; last column is the benign false-positive rate">
        <table className="table">
          <thead>
            <tr>
              <th>Detector</th>
              {ATTACK_PROFILES.map((p) => <th key={p} className="r">{profileLabel(p)}</th>)}
              <th className="r">Benign FPR</th>
            </tr>
          </thead>
          <tbody>
            {DETECTORS.filter((d) => r[d.key]).map((d) => (
              <tr key={d.key}>
                <td style={{ fontWeight: d.ours ? 650 : 500 }}>{d.label}</td>
                {ATTACK_PROFILES.map((p) => {
                  const v = r[d.key].by_profile?.[p]?.recall;
                  return (
                    <td key={p} className="r num" style={{ background: v == null ? undefined : rampColor(v), color: v == null ? undefined : inkOn(v), fontWeight: 600, borderBottom: "2px solid var(--surface)" }}>
                      {fmtPct(v)}
                    </td>
                  );
                })}
                <td className="r num">{fmtPct(r[d.key].by_profile?.benign_high_activity?.fpr)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="row tiny muted" style={{ marginTop: 10, gap: 6 }}>
          <span>0%</span>
          <div style={{ display: "flex", width: 180, height: 8, borderRadius: 4, overflow: "hidden" }}>{RAMP.map((c) => <div key={c} style={{ flex: 1, background: c }} />)}</div>
          <span>100% recall</span>
        </div>
      </Card>

      <div className="grid g-2">
        <Ablation ab={r.ablation} />
        <Adversarial adv={r.adversarial} />
      </div>
      {r.episode_lengths && <EpisodeLengths lengths={r.episode_lengths} stageC={r.stage_c} />}
    </>
  );
}

function OperatingPoint({ fusion }) {
  const w = fusion.weights || {};
  const parts = [
    { k: "a", label: "Stage A", color: "var(--series-1)" },
    { k: "b", label: "Stage B", color: "var(--series-2)" },
    { k: "c", label: "Stage C", color: "var(--series-3)" },
  ];
  return (
    <div className="col" style={{ gap: 14 }}>
      <div>
        <div className="small muted">Fusion weights</div>
        <div style={{ display: "flex", height: 22, borderRadius: 6, overflow: "hidden", marginTop: 6, background: "var(--surface-sunken)" }}>
          {parts.map((p) => (w[p.k] > 0 ? <div key={p.k} style={{ width: `${w[p.k] * 100}%`, background: p.color, borderRight: "2px solid var(--surface)" }} title={`${p.label} ${w[p.k]}`} /> : null))}
        </div>
        <div className="legend" style={{ marginTop: 8 }}>
          {parts.map((p) => (
            <span className="key" key={p.k}><span className="sw" style={{ background: p.color }} />{p.label} {(w[p.k] ?? 0).toFixed(2)}</span>
          ))}
        </div>
      </div>
      <div className="row between"><span className="muted small">Alert threshold</span><b className="num">{fusion.threshold?.toFixed(2)}</b></div>
      {fusion.validation_f1 != null && <div className="row between"><span className="muted small">Validation F1 at this point</span><b className="num">{fusion.validation_f1.toFixed(3)}</b></div>}
      <div className="row between"><span className="muted small">Weight grid step</span><b className="num">{fusion.weight_grid_step ?? 0.1}</b></div>
      <p className="tiny muted">
        A stage with weight 0 contributes nothing to the alerts the system raises; explanations are always taken from the stage that did.
      </p>
    </div>
  );
}

function Ablation({ ab }) {
  if (!ab) return <Card title="Ablation"><Empty title="Not run" /></Card>;
  const names = {
    frequency_only: "Frequency features only",
    frequency_plus_response_behaviour: "+ response behaviour (full)",
    response_behaviour_minus_latency_drift_slope: "Full − latency_drift_slope",
  };
  const sup = ab.supplementary;
  return (
    <Card title="Ablation: does reading the reaction help?" sub="Same model and split; only the feature set changes (excluded columns are removed from the matrix)">
      <table className="table compact">
        <thead>
          <tr><th>Variant</th><th className="r">Feat.</th><th style={{ width: "26%" }}>Recall</th><th style={{ width: "26%" }}>FPR</th></tr>
        </thead>
        <tbody>
          {Object.entries(ab.variants).map(([k, v]) => (
            <tr key={k}>
              <td className="small">{names[k] || k}</td>
              <td className="r num">{v.n_features}</td>
              <td><Bar value={v.overall.recall} /></td>
              <td><Bar value={v.overall.fpr} color="var(--series-2)" /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="col" style={{ gap: 8, marginTop: 12 }}>
        <div className="row between small"><span>Response-behaviour lift (recall)</span><b className="num">{ab.response_behaviour_lift_percentage_points.toFixed(1)} pp</b></div>
        <div className="row between small"><span>latency_drift_slope lift (recall)</span><b className="num">{ab.latency_drift_slope_lift_percentage_points.toFixed(1)} pp</b></div>
        {sup && (
          <div className="tiny muted">
            Supplementary (full − ablated): response behaviour F1 {sup.response_behaviour_f1_delta >= 0 ? "+" : ""}{sup.response_behaviour_f1_delta.toFixed(3)}, FPR {sup.response_behaviour_fpr_delta >= 0 ? "+" : ""}{sup.response_behaviour_fpr_delta.toFixed(3)};
            latency_drift_slope F1 {sup.latency_drift_slope_f1_delta >= 0 ? "+" : ""}{sup.latency_drift_slope_f1_delta.toFixed(3)}, AP {sup.latency_drift_slope_average_precision_delta >= 0 ? "+" : ""}{sup.latency_drift_slope_average_precision_delta.toFixed(3)}.
          </div>
        )}
        {ab.no_measurable_lift_latency_drift_slope && (
          <div className="banner warning small">
            <AlertTriangle size={16} />
            <span><b>No measurable lift:</b> removing <code>latency_drift_slope</code> did not change recall beyond the {ab.noise_floor_percentage_points}-point noise floor on this benchmark. Reported as measured — see DECISIONS.md.</span>
          </div>
        )}
        {ab.no_measurable_lift_response_behaviour && (
          <div className="banner warning small">
            <AlertTriangle size={16} />
            <span><b>No measurable lift</b> from the response-behaviour family on this benchmark.</span>
          </div>
        )}
      </div>
    </Card>
  );
}

function Adversarial({ adv }) {
  if (!adv) return <Card title="Adversarial evaluation"><Empty title="Not run" /></Card>;
  const rows = [
    ["Splunk rule", adv.baselines?.splunk],
    ["Elastic rule", adv.baselines?.elastic],
    ["Stage A + B", adv.stage_ab],
    ["Stage C", adv.stage_c],
    ["PulseGuard fusion", adv.full_fusion],
  ].filter(([, v]) => v);
  return (
    <Card title={<span className="row" style={{ gap: 8 }}><Swords size={17} /> Adversarial evaluation</span>} sub={`${adv.n_adversarial_episodes} attacks built to evade: 1 prompt / 5 min, and an attacker mimicking the victim's own rhythm`}>
      <table className="table compact">
        <thead>
          <tr><th>Detector</th><th style={{ width: "34%" }}>Mimicry recall</th><th style={{ width: "34%" }}>Slow-pacing recall</th></tr>
        </thead>
        <tbody>
          {rows.map(([label, v]) => (
            <tr key={label}>
              <td className="small">{label}</td>
              <td><Bar value={v.mimicry_adversarial?.recall} /></td>
              <td><Bar value={v.slow_pacing_adversarial?.recall} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className={`banner ${adv.anti_dos_invariant_holds_under_mimicry_pacing ? "good" : "critical"} small`} style={{ marginTop: 12 }}>
        {adv.anti_dos_invariant_holds_under_mimicry_pacing ? <ShieldCheck size={16} /> : <AlertTriangle size={16} />}
        <span>
          Anti-DoS invariant under sustained mimicry pacing: <b>{adv.anti_dos_invariant_holds_under_mimicry_pacing ? "holds" : "violated"}</b> — the escalation
          ceiling never locks the legitimate user out.
        </span>
      </div>
    </Card>
  );
}

function EpisodeLengths({ lengths, stageC }) {
  const entries = Object.entries(lengths.profiles);
  const max = Math.max(...entries.map(([, s]) => s.max));
  return (
    <Card title="Episode lengths overlap across profiles" sub="Prompts per episode (5th–95th percentile, median tick): length alone cannot separate attack from benign">
      <div className="col" style={{ gap: 10 }}>
        {entries.map(([p, s]) => (
          <div key={p} className="row" style={{ gap: 12 }}>
            <div className="small" style={{ width: 210 }}>{profileLabel(p)}</div>
            <div style={{ position: "relative", flex: 1, height: 18 }}>
              <div style={{ position: "absolute", top: 8, left: 0, right: 0, height: 1, background: "var(--grid)" }} />
              <div title={`p5 ${s.p5} – p95 ${s.p95}`} style={{ position: "absolute", top: 4, height: 10, borderRadius: 4, left: `${(s.p5 / max) * 100}%`, width: `${Math.max(1, ((s.p95 - s.p5) / max) * 100)}%`, background: ["benign_high_activity", "benign_occasional_denial"].includes(p) ? "var(--series-3)" : "var(--series-2)" }} />
              <div style={{ position: "absolute", top: 1, height: 16, width: 2, background: "var(--ink)", left: `${(s.median / max) * 100}%` }} />
            </div>
            <div className="num tiny muted" style={{ width: 130, textAlign: "right" }}>{s.p5}–{s.p95} (median {s.median})</div>
          </div>
        ))}
        <Legend items={[{ label: "Attack profile", color: "var(--series-2)" }, { label: "Benign profile", color: "var(--series-3)" }, { label: "Median", color: "var(--ink)", line: true }]} />
        {stageC && (
          <p className="tiny muted">
            <CheckCircle2 size={12} style={{ verticalAlign: -2 }} /> Previously the ranges were disjoint and Stage C could separate classes by counting events; its
            score on this overlapping benchmark is the one reported above.
          </p>
        )}
      </div>
    </Card>
  );
}

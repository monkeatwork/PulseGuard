import { ArrowRight, Brain, Database, Gauge, Layers, Radio, ShieldCheck, Workflow } from "lucide-react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, ChartTooltip, Legend } from "../components/ui.jsx";
import { FREQUENCY, RESPONSE } from "../lib/features.js";
import { usePoll } from "../lib/hooks.js";
import { api } from "../api/client.js";

// Median decision latency implied by the benchmark generator's published
// parameters (benchmark/generator/latency_models.py): benign approvals are
// LogNormal(mu=1.6); a fatigue burst's mu decays linearly 1.6 -> -0.3.
// The median of a LogNormal is e^mu. Illustration of the model, not data.
const N = 15;
const MODEL = Array.from({ length: N }, (_, i) => ({
  i: i + 1,
  fatigued: +Math.exp(1.6 + (i / (N - 1)) * (-0.3 - 1.6)).toFixed(2),
  legitimate: +Math.exp(1.6).toFixed(2),
}));

const LAYERS = [
  { lvl: "L1", icon: Radio, title: "Telemetry", svc: "ingestion", body: "Adapters behind one interface: benchmark replay and the live victim simulator. (Entra ID, Okta, Duo: future adapters.)" },
  { lvl: "L2", icon: Workflow, title: "Ingestion", svc: "ingestion", body: "FastAPI collectors validate the canonical event and produce to Kafka, keyed by user so each user stays ordered." },
  { lvl: "L3", icon: Layers, title: "Feature engine", svc: "features", body: "Faust stream worker. Keeps each user's open session in Redis and featurises the session-so-far on every decision." },
  { lvl: "L4", icon: Brain, title: "Detection", svc: "detection", body: "Stage A deviation · Stage B XGBoost · Stage C GRU, fused at the validation-tuned operating point. ~1–2 ms per decision." },
  { lvl: "L5", icon: ShieldCheck, title: "Response", svc: "mitigation", body: "Controller forces step-up through the IdP, with cooldown and an escalation ceiling that never locks the user out. SOC dashboard + CEF." },
];

export default function Architecture({ health }) {
  const op = usePoll(() => api.operatingPoint(), 0);
  return (
    <>
      <Card title="The core insight" sub="Every deployed defence changes the prompt or counts the prompts. None reads the user's reaction.">
        <div className="grid g-2" style={{ alignItems: "center" }}>
          <div className="col" style={{ gap: 10 }}>
            <p>
              An attacker who already holds the password floods the victim with push prompts until one is approved. Nothing
              cryptographic is broken — the target is human habituation. A fatigued approval and a genuine approval are
              <b> cryptographically identical</b>.
            </p>
            <p>
              What differs is the <b>trajectory of the user's decision latency</b>: under fatigue, deliberation collapses into a
              reflexive tap, so latency falls prompt after prompt. A legitimate user's latency is stationary. PulseGuard measures
              that collapse — <code>latency_drift_slope</code> — together with the deny-run and capitulation pattern, and acts
              while the attack is still in progress.
            </p>
            <p className="small muted">
              Chart: median latency implied by the benchmark generator's latency model (published human-subjects parameters in
              <code> latency_models.py</code>) — an illustration of the model, not measured data.
            </p>
          </div>
          <div>
            <Legend items={[{ label: "Fatigued victim (attack burst)", color: "var(--series-2)", line: true }, { label: "Legitimate user", color: "var(--series-1)", line: true }]} />
            <div style={{ height: 230 }}>
              <ResponsiveContainer>
                <LineChart data={MODEL} margin={{ top: 10, right: 16, bottom: 4, left: 0 }}>
                  <CartesianGrid stroke="var(--grid)" vertical={false} />
                  <XAxis dataKey="i" tickLine={false} axisLine={{ stroke: "var(--axis)" }} />
                  <YAxis tickLine={false} axisLine={false} width={40} tickFormatter={(v) => `${v}s`} />
                  <Tooltip content={({ active, payload }) => active && payload?.length ? (
                    <ChartTooltip title={`Prompt ${payload[0].payload.i}`} rows={[["Fatigued", `${payload[0].payload.fatigued}s`], ["Legitimate", `${payload[0].payload.legitimate}s`]]} />
                  ) : null} />
                  <Line dataKey="legitimate" stroke="var(--series-1)" strokeWidth={2} dot={false} isAnimationActive={false} />
                  <Line dataKey="fatigued" stroke="var(--series-2)" strokeWidth={2} isAnimationActive={false} dot={{ r: 3.5, fill: "var(--series-2)", stroke: "var(--surface)", strokeWidth: 2 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      </Card>

      <Card title="Five layers" sub="Live status of each service">
        <div className="row" style={{ alignItems: "stretch", gap: 8, flexWrap: "wrap" }}>
          {LAYERS.map((l, idx) => {
            const Icon = l.icon;
            const up = health?.data?.[l.svc];
            return (
              <div key={l.lvl} className="row" style={{ alignItems: "stretch", gap: 8, flex: "1 1 180px" }}>
                <div className="stage" style={{ flex: 1 }}>
                  <div className="row between">
                    <span className="lvl">{l.lvl}</span>
                    <span className="dot" style={{ background: up ? "var(--good)" : "var(--axis)" }} title={up ? "healthy" : "unreachable"} />
                  </div>
                  <div className="row" style={{ gap: 8, marginTop: 6 }}>
                    <span className="icon-chip"><Icon size={15} /></span>
                    <b>{l.title}</b>
                  </div>
                  <p className="small muted" style={{ marginTop: 8 }}>{l.body}</p>
                </div>
                {idx < LAYERS.length - 1 && <ArrowRight size={16} color="var(--axis)" style={{ alignSelf: "center" }} />}
              </div>
            );
          })}
        </div>
        <div className="row wrap small muted" style={{ marginTop: 14, gap: 8 }}>
          <Database size={14} /> Kafka (KRaft) · Redis · PostgreSQL + TimescaleDB · FastAPI · Faust · XGBoost · PyTorch (training) · React + Recharts · Docker Compose
        </div>
      </Card>

      <div className="grid g-3">
        <Card title="Stage A · statistical" sub="Per-user deviation">
          <p className="small">The single most anomalous signal in the session — latency z-score against the user's own baseline, drift slope, deny run, or the 10-minute prompt count. Cheap and fully explainable.</p>
          <Weight value={op.data?.weight_a} color="var(--series-1)" />
        </Card>
        <Card title="Stage B · XGBoost" sub="Both feature families, isotonic-calibrated">
          <p className="small">Gradient-boosted trees over all frequency and response-behaviour features. Explained with exact TreeSHAP when it drives an alert.</p>
          <Weight value={op.data?.weight_b} color="var(--series-2)" />
        </Card>
        <Card title="Stage C · GRU" sub="Raw event sequence">
          <p className="small">A recurrent network over the step-by-step decision sequence, connecting an early denial to a later approval across low-and-slow pacing.</p>
          <Weight value={op.data?.weight_c} color="var(--series-3)" />
        </Card>
      </div>

      <div className="grid g-2">
        <Card title="Feature families" sub="What the detector sees at every decision">
          <div className="grid g-2" style={{ gap: 20 }}>
            <div>
              <h3 style={{ color: "var(--brand-ink)" }}>Response behaviour — the contribution</h3>
              <ul className="small" style={{ paddingLeft: 18, margin: "8px 0 0" }}>
                {RESPONSE.map((f) => <li key={f.key} title={f.help}><code>{f.key}</code></li>)}
              </ul>
            </div>
            <div>
              <h3>Frequency & context</h3>
              <ul className="small" style={{ paddingLeft: 18, margin: "8px 0 0" }}>
                {FREQUENCY.map((f) => <li key={f.key} title={f.help}><code>{f.key}</code></li>)}
              </ul>
            </div>
          </div>
        </Card>
        <Card title="Response without self-inflicted DoS" sub="The escalation ceiling (evaluation rule 6)">
          <div className="timeline">
            <div className="tl-item brand"><b>Alert</b><div className="small muted">First decision whose fused score crosses the threshold.</div></div>
            <div className="tl-item brand"><b>Step-up</b><div className="small muted">IdP suspends blind push approval and asks for a number match the attacker cannot see.</div></div>
            <div className="tl-item serious"><b>Cooldown (5 min)</b><div className="small muted">At most one forced step-up per user per window — no challenge storms.</div></div>
            <div className="tl-item serious"><b>Alternate factor</b><div className="small muted">After 3 failed step-ups in 30 minutes the push channel is replaced by another factor.</div></div>
            <div className="tl-item good"><b>Never locked out</b><div className="small muted">There is no "lock" action in the code or the database schema at all.</div></div>
          </div>
        </Card>
      </div>
    </>
  );
}

function Weight({ value, color }) {
  return (
    <div className="row" style={{ marginTop: 12, gap: 8 }}>
      <Gauge size={14} color="var(--ink-3)" />
      <span className="small muted">Fusion weight</span>
      <div style={{ flex: 1, height: 8, background: "var(--surface-sunken)", borderRadius: 4 }}>
        <div style={{ width: `${(value ?? 0) * 100}%`, height: "100%", background: color, borderRadius: 4 }} />
      </div>
      <b className="num small">{value == null ? "—" : value.toFixed(2)}</b>
    </div>
  );
}

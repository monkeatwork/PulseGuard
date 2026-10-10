import { useMemo, useState } from "react";
import {
  CheckCheck, Download, Eye, KeyRound, ShieldAlert, ShieldCheck, Smartphone, Laptop, TrendingDown, UserRound,
} from "lucide-react";
import { api } from "../api/client.js";
import { Card, Empty, ErrorNote, Help, LabelBadge, Segmented, SeverityBadge, StatusBadge } from "../components/ui.jsx";
import LatencyTrajectoryChart from "../charts/LatencyTrajectoryChart.jsx";
import ScoreTrajectoryChart from "../charts/ScoreTrajectoryChart.jsx";
import StageContribution from "../charts/StageContribution.jsx";
import Reasons from "../charts/Reasons.jsx";
import { FREQUENCY, RESPONSE, formatFeature, profileLabel } from "../lib/features.js";
import { fmtDateTime, fmtMs, fmtScore, fmtTime, shortUser, timeAgo } from "../lib/format.js";
import { navigate, usePoll } from "../lib/hooks.js";

export default function Alerts({ selectedId }) {
  const [status, setStatus] = useState("all");
  const alerts = usePoll(() => api.alerts(status === "all" ? "" : `&status=${status}`), 4000, [status]);
  const list = alerts.data || [];
  const selected = selectedId || list[0]?.alert_id;

  return (
    <div className="grid" style={{ gridTemplateColumns: "minmax(280px, 360px) minmax(0, 1fr)", alignItems: "start" }}>
      <section className="card" style={{ position: "sticky", top: 80 }}>
        <div className="card-head" style={{ paddingBottom: 12 }}>
          <h2>Queue</h2>
          <div className="actions">
            <Segmented
              label="Filter by status"
              value={status}
              onChange={setStatus}
              options={[
                { value: "all", label: "All" },
                { value: "open", label: "Open" },
                { value: "acknowledged", label: "Ack" },
                { value: "resolved", label: "Done" },
              ]}
            />
          </div>
        </div>
        <ErrorNote error={alerts.error} />
        <div style={{ maxHeight: "calc(100vh - 190px)", overflow: "auto", borderTop: "1px solid var(--border)" }}>
          {list.length === 0 && !alerts.loading && (
            <Empty icon={ShieldCheck} title="No alerts here">
              Replay an attack from the <a href="#/lab">Attack Lab</a> to see one appear.
            </Empty>
          )}
          {list.map((a) => (
            <button
              key={a.alert_id}
              className="list-item"
              aria-selected={a.alert_id === selected}
              onClick={() => navigate(`/alerts/${a.alert_id}`)}
            >
              <div className="col" style={{ gap: 4, flex: 1, minWidth: 0 }}>
                <div className="row" style={{ gap: 8 }}>
                  <SeverityBadge score={a.fused_score} />
                  <span className="mono small" style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis" }}>{shortUser(a.user_id)}</span>
                </div>
                <div className="tiny muted">
                  {profileLabel(a.scenario?.profile)} · {a.n_decisions} decisions · {timeAgo(a.ts)}
                </div>
              </div>
              <div className="col" style={{ gap: 4, alignItems: "flex-end" }}>
                <span className="num" style={{ fontWeight: 650 }}>{fmtScore(a.fused_score)}</span>
                <StatusBadge status={a.status} />
              </div>
            </button>
          ))}
        </div>
      </section>
      {selected ? <AlertDetail key={selected} id={selected} onChanged={alerts.refresh} /> : !alerts.loading && <Card><Empty title="Select an alert" /></Card>}
    </div>
  );
}

function AlertDetail({ id, onChanged }) {
  const detail = usePoll(() => api.alert(id), 3000, [id]);
  const a = detail.data;
  const baseline = usePoll(() => (a ? api.baseline(a.user_id) : Promise.resolve(null)), 10000, [a?.user_id]);
  const [busy, setBusy] = useState(false);

  const setStatus = async (status) => {
    setBusy(true);
    try {
      await api.setAlertStatus(id, status);
      await detail.refresh();
      onChanged?.();
    } finally {
      setBusy(false);
    }
  };

  if (detail.error && !a) return <Card><ErrorNote error={detail.error} /></Card>;
  if (!a) return <Card><Empty title="Loading alert…" /></Card>;

  const fv = a.feature_vector || {};
  const w = a.operating_point?.weights;
  const threshold = a.operating_point?.threshold;

  return (
    <div className="col fade-in" style={{ gap: 16 }}>
      <section className="card card-pad">
        <div className="row wrap between" style={{ gap: 16 }}>
          <div className="col" style={{ gap: 6 }}>
            <div className="row wrap" style={{ gap: 8 }}>
              <SeverityBadge score={a.fused_score} />
              <StatusBadge status={a.status} />
              <LabelBadge attack={a.scenario?.label_attack} />
              <span className="badge outline">{profileLabel(a.scenario?.profile)}</span>
            </div>
            <h1 className="mono" style={{ fontSize: 20 }}>
              <UserRound size={18} style={{ verticalAlign: -3, marginRight: 6 }} />
              {a.user_id}
            </h1>
            <div className="small muted">
              Raised {fmtDateTime(a.ts)} at decision {(a.first_crossing_decision ?? 0) + 1} of {a.n_decisions} · updated {timeAgo(a.updated_ts)}
            </div>
          </div>
          <div className="col" style={{ alignItems: "flex-end", gap: 10 }}>
            <div style={{ textAlign: "right" }}>
              <div className="small muted">Fused score</div>
              <div style={{ fontSize: 34, fontWeight: 700, letterSpacing: "-0.02em", lineHeight: 1 }}>{fmtScore(a.fused_score)}</div>
              {threshold != null && <div className="tiny muted">threshold {threshold.toFixed(2)}</div>}
            </div>
            <div className="row">
              {a.status !== "acknowledged" && a.status !== "resolved" && (
                <button className="btn sm" disabled={busy} onClick={() => setStatus("acknowledged")}>
                  <Eye size={14} /> Acknowledge
                </button>
              )}
              {a.status !== "resolved" && (
                <button className="btn sm" disabled={busy} onClick={() => setStatus("resolved")}>
                  <CheckCheck size={14} /> Resolve
                </button>
              )}
              <a className="btn sm" href={api.cefUrl(a.alert_id)} download={`pulseguard-${a.alert_id}.cef`}>
                <Download size={14} /> CEF
              </a>
            </div>
          </div>
        </div>
      </section>

      <div className="grid g-2">
        <Card
          title={<span className="row" style={{ gap: 8 }}><TrendingDown size={17} /> Decision latency across the session</span>}
          sub="The core signal: a fatigued user's reaction time collapses; a legitimate user's stays flat"
        >
          <LatencyTrajectoryChart sequence={a.sequence} slope={fv.latency_drift_slope} slopeValid={fv.latency_drift_slope_valid} />
        </Card>
        <Card title="Score at every decision" sub="Scored on the session so far — the alert fires at the first crossing">
          <ScoreTrajectoryChart trajectory={a.score_trajectory} threshold={threshold} />
        </Card>
      </div>

      <div className="grid g-2">
        <Card title="Why this fired" sub="Top-3 reasons from the component that drove the score">
          <Reasons reasons={a.shap_top3} source={a.explanation_source} />
        </Card>
        <Card title="How the score is assembled" sub="Weights and threshold are the persisted, validation-tuned operating point">
          <StageContribution scores={{ a: a.stage_a_score, b: a.stage_b_score, c: a.stage_c_score }} weights={w} threshold={threshold} />
        </Card>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1.4fr) minmax(0, 1fr)" }}>
        <Card title="Feature vector at the strongest decision point" sub="Both feature families, as the detector saw them">
          <FeatureColumns vector={fv} />
        </Card>
        <div className="col" style={{ gap: 16 }}>
          <Card title="Response timeline" sub="Detection → mitigation → identity provider">
            <Timeline alert={a} />
          </Card>
          <Card title="Prompt origin vs. responder">
            <Origins prompts={a.prompts} sequence={a.sequence} />
          </Card>
          <Card title="User baseline" sub="EWMA latency baseline in Redis">
            <Baseline data={baseline.data} />
          </Card>
        </div>
      </div>
    </div>
  );
}

function FeatureColumns({ vector }) {
  const block = (title, list, help) => (
    <div>
      <div className="row" style={{ gap: 6, marginBottom: 4 }}>
        <h3>{title}</h3>
        <Help text={help} />
      </div>
      {list.map((f) => {
        const value = formatFeature(f, vector);
        return (
          <div className={`feature ${f.star ? "star" : ""}`} key={f.key} title={f.help}>
            <span>
              <div style={{ fontWeight: 550 }}>{f.label}</div>
              <div className="fname">{f.key}</div>
            </span>
            <span className="fval">{value ?? <span className="na">undefined</span>}</span>
          </div>
        );
      })}
    </div>
  );
  return (
    <div className="feature-grid">
      {block("Response behaviour", RESPONSE, "PulseGuard's contribution: how the user reacts, not how often they are prompted.")}
      {block("Frequency & context", FREQUENCY, "Established UEBA building blocks: how often, when, from where.")}
    </div>
  );
}

function Timeline({ alert }) {
  const items = useMemo(() => {
    const out = [{ ts: alert.ts, tone: "critical", title: `Alert raised (score ${fmtScore(alert.fused_score)})`, body: `Decision ${(alert.first_crossing_decision ?? 0) + 1} crossed the threshold.` }];
    const label = {
      step_up_required: ["brand", "Step-up forced", "Blind push approval suspended; number-matching challenge issued."],
      cooldown_active: ["serious", "Cooldown active", "Already stepped up in the last 5 minutes — no repeat challenge (anti-DoS)."],
      alt_factor_required: ["serious", "Escalated to alternate factor", "Repeated failed step-ups: push channel replaced — never a lockout."],
    };
    alert.mitigation_actions?.forEach((m) => {
      const [tone, title, body] = label[m.action_type] || ["", m.action_type, ""];
      out.push({ ts: m.ts, tone, title, body });
    });
    alert.idp_challenges?.forEach((c) => {
      out.push({ ts: c.ts, tone: "brand", title: `IdP ${c.kind === "step_up" ? "step-up" : "alternate-factor"} challenge`, body: `Status: ${c.status}` });
      if (c.resolved_ts) out.push({ ts: c.resolved_ts, tone: c.status === "passed" ? "good" : "critical", title: `Challenge ${c.status}`, body: "" });
    });
    return out.sort((x, y) => new Date(x.ts) - new Date(y.ts));
  }, [alert]);
  return (
    <div className="timeline">
      {items.map((it, i) => (
        <div className={`tl-item ${it.tone}`} key={i}>
          <div style={{ fontWeight: 600 }}>{it.title}</div>
          <div className="when">{fmtTime(it.ts)}</div>
          {it.body && <div className="small muted">{it.body}</div>}
        </div>
      ))}
      {alert.mitigation_actions?.length === 0 && (
        <div className="tl-item">
          <div className="small muted">Waiting for the mitigation controller…</div>
        </div>
      )}
    </div>
  );
}

function Origins({ prompts = [], sequence = [] }) {
  const pIps = [...new Set(prompts.map((p) => p.src_ip))];
  const pDev = [...new Set(prompts.map((p) => p.device_id))];
  const rDev = [...new Set(sequence.map((s) => s.device_id))];
  const rIps = [...new Set(sequence.map((s) => s.src_ip))];
  const differs = pDev.join() !== rDev.join();
  return (
    <div className="col" style={{ gap: 10 }}>
      <div className="row" style={{ alignItems: "flex-start" }}>
        <span className="icon-chip critical"><Laptop size={15} /></span>
        <div className="small">
          <div style={{ fontWeight: 600 }}>Prompts triggered from</div>
          <div className="mono tiny muted">{pIps.join(", ") || "—"} · {pDev.join(", ") || "—"}</div>
        </div>
      </div>
      <div className="row" style={{ alignItems: "flex-start" }}>
        <span className="icon-chip"><Smartphone size={15} /></span>
        <div className="small">
          <div style={{ fontWeight: 600 }}>Answered on</div>
          <div className="mono tiny muted">{rIps.join(", ") || "—"} · {rDev.join(", ") || "—"}</div>
        </div>
      </div>
      {differs && pDev.length > 0 && (
        <div className="tiny muted">The login was initiated from a different device than the one approving it — expected for any push MFA, which is why origin alone cannot tell attack from habit.</div>
      )}
    </div>
  );
}

function Baseline({ data }) {
  if (!data) return <p className="small muted">Loading…</p>;
  return (
    <div className="col" style={{ gap: 6 }}>
      <div className="row between small">
        <span className="muted">Approval latency baseline</span>
        <b className="num">{data.event_count ? `${fmtMs(data.latency_mean_ms)} ± ${fmtMs(data.latency_std_ms)}` : "none yet"}</b>
      </div>
      <div className="row between small">
        <span className="muted">Observed approvals</span>
        <b className="num">{data.event_count}</b>
      </div>
      <div className="row between small">
        <span className="muted">Baseline mode</span>
        {data.cold_start ? (
          <span className="badge warning" title={`Fewer than ${data.cold_start_threshold} events: cohort prior blended in`}><KeyRound size={11} /> Cold start (cohort blend)</span>
        ) : (
          <span className="badge good">Personal baseline</span>
        )}
      </div>
      <div className="row between small">
        <span className="muted">Open session</span>
        <b className="num">{data.open_session ? `${data.open_session.n_decisions} decisions` : "closed"}</b>
      </div>
      <div className="tiny muted">Baselines advance once per closed session, so a session is always scored against history, never itself.</div>
    </div>
  );
}

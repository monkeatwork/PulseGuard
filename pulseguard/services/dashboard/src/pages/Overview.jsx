import { Activity, Fingerprint, FlaskConical, Gauge, ShieldCheck, ShieldAlert, Smartphone, Timer } from "lucide-react";
import { api } from "../api/client.js";
import { Card, Empty, ErrorNote, ScoreBar, SeverityBadge, StatTile, LabelBadge } from "../components/ui.jsx";
import { fmtMs, fmtNum, fmtScore, fmtTime, shortUser, timeAgo } from "../lib/format.js";
import { navigate, usePoll } from "../lib/hooks.js";
import { profileLabel } from "../lib/features.js";
import PipelineStrip from "../components/PipelineStrip.jsx";

export default function Overview({ stats, health }) {
  const scores = usePoll(() => api.recentScores(40), 2500);
  const alerts = usePoll(() => api.alerts(), 4000);
  const op = usePoll(() => api.operatingPoint(), 0);
  const s = stats.data;
  const threshold = op.data?.threshold;
  const stepUps = s?.mitigation_actions?.step_up_required ?? 0;
  const altFactor = s?.mitigation_actions?.alt_factor_required ?? 0;

  return (
    <>
      <section className="card hero card-pad">
        <div className="row wrap between" style={{ gap: 20 }}>
          <div className="col" style={{ gap: 8 }}>
            <span className="badge brand" style={{ alignSelf: "flex-start" }}>
              <Fingerprint size={12} /> Response-behaviour modelling
            </span>
            <h1>Every other defence counts the prompts. PulseGuard reads the reaction.</h1>
            <p>
              A fatigued user's decision latency collapses across a push-prompt burst as deliberation turns into a reflexive
              tap; a legitimate user's stays steady. PulseGuard scores every decision as it arrives and forces a step-up{" "}
              <b>before</b> the capitulation approval can open a session.
            </p>
          </div>
          <div className="row wrap">
            <a className="btn primary lg" href="#/lab">
              <FlaskConical size={17} /> Replay an attack
            </a>
            <a className="btn lg" href="#/lab" onClick={() => sessionStorage.setItem("pg-open-phone", "1")}>
              <Smartphone size={17} /> Be the victim
            </a>
          </div>
        </div>
      </section>

      <ErrorNote error={stats.error} />
      <div className="grid g-4">
        <StatTile icon={ShieldAlert} tone="critical" label="Open alerts" value={fmtNum(s?.alerts_open)} foot={`${fmtNum(s?.alerts_total)} raised this run`} />
        <StatTile icon={Activity} label="Decisions scored" value={fmtNum(s?.decisions_scored)} foot={`across ${fmtNum(s?.sessions_scored)} sessions`}
          help="Every approve/deny is scored on the session so far, the moment it arrives." />
        <StatTile icon={ShieldCheck} tone="good" label="Step-ups forced" value={fmtNum(stepUps)} foot={`${altFactor} escalated to alternate factor · 0 lockouts`}
          help="The escalation ceiling never locks a user out: after repeated failed step-ups the push channel is replaced by another factor." />
        <StatTile icon={Timer} tone="warning" label="Scoring latency (p50)" value={fmtMs(s?.scoring_ms_p50)} foot={`p95 ${fmtMs(s?.scoring_ms_p95)} · in-band budget < 10 ms`} />
      </div>

      <Card title="Pipeline" sub="Telemetry → ingestion → features → detection → response, all live">
        <PipelineStrip health={health.data} op={op.data} stats={s} />
      </Card>

      <div className="grid g-main">
        <Card
          title="Live decision feed"
          sub="Each row is one approve/deny, scored on its whole session so far"
          actions={<span className="row small muted"><span className="dot live" /> live</span>}
        >
          {scores.data?.length ? (
            <table className="table compact">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>User</th>
                  <th>Decision</th>
                  <th className="r">Latency</th>
                  <th style={{ width: "34%" }}>Fused score {threshold != null && <span className="muted">(| = {threshold.toFixed(2)})</span>}</th>
                </tr>
              </thead>
              <tbody>
                {scores.data.slice(0, 14).map((r) => (
                  <tr key={`${r.episode_id}-${r.decision_index}`}>
                    <td className="num muted">{fmtTime(r.ts)}</td>
                    <td className="mono small">{shortUser(r.user_id)}</td>
                    <td>
                      <span className="row" style={{ gap: 6 }}>
                        <span className="dot" style={{ background: r.decision === "approve" ? "var(--series-1)" : r.decision === "deny" ? "var(--series-2)" : "var(--series-muted)" }} />
                        {r.decision || "—"}
                      </span>
                    </td>
                    <td className="r num">{fmtMs(r.decision_latency_ms)}</td>
                    <td>
                      <div className="row">
                        <ScoreBar value={r.fused_score} threshold={r.threshold} />
                        <span className="num small" style={{ width: 42, textAlign: "right" }}>{fmtScore(r.fused_score)}</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty icon={Gauge} title="Nothing scored yet">
              Start a replay or the victim simulator in the <a href="#/lab">Attack Lab</a>.
            </Empty>
          )}
        </Card>

        <Card title="Latest alerts" actions={<a className="btn sm ghost" href="#/alerts">View all</a>}>
          {alerts.data?.length ? (
            <div className="col" style={{ gap: 0, margin: "-6px -20px -10px" }}>
              {alerts.data.slice(0, 7).map((a) => (
                <button key={a.alert_id} className="list-item" onClick={() => navigate(`/alerts/${a.alert_id}`)}>
                  <SeverityBadge score={a.fused_score} />
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div className="mono small" style={{ fontWeight: 600 }}>{shortUser(a.user_id)}</div>
                    <div className="tiny muted">
                      {profileLabel(a.scenario?.profile)} · {timeAgo(a.ts)}
                    </div>
                  </div>
                  <LabelBadge attack={a.scenario?.label_attack} />
                  <span className="num" style={{ fontWeight: 650 }}>{fmtScore(a.fused_score)}</span>
                </button>
              ))}
            </div>
          ) : (
            <Empty icon={ShieldCheck} title="No alerts">Quiet — nothing has crossed the evaluated threshold.</Empty>
          )}
        </Card>
      </div>
    </>
  );
}

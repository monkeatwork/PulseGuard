import { useEffect, useMemo, useState } from "react";
import {
  CheckCircle2, Clock3, FlaskConical, Hand, Laptop, MapPin, Play, ShieldAlert, ShieldCheck, Smartphone, Square, Wifi, Zap,
} from "lucide-react";
import { api } from "../api/client.js";
import { Card, Empty, ErrorNote, LabelBadge, Legend, Segmented, SeverityBadge } from "../components/ui.jsx";
import ScoreTrajectoryChart from "../charts/ScoreTrajectoryChart.jsx";
import LatencyTrajectoryChart from "../charts/LatencyTrajectoryChart.jsx";
import { PROFILES, profileLabel } from "../lib/features.js";
import { fmtDuration, fmtMs, fmtScore, fmtTime, shortUser } from "../lib/format.js";
import { navigate, usePoll } from "../lib/hooks.js";

export default function AttackLab() {
  const [tab, setTab] = useState(() => {
    try {
      if (sessionStorage.getItem("pg-open-phone")) {
        sessionStorage.removeItem("pg-open-phone");
        return "phone";
      }
    } catch {
      /* storage unavailable */
    }
    return "replay";
  });
  return (
    <>
      <div className="row between wrap">
        <Segmented
          label="Attack Lab mode"
          value={tab}
          onChange={setTab}
          options={[
            { value: "replay", label: "Scenario replay" },
            { value: "phone", label: "Be the victim" },
          ]}
        />
        <span className="small muted">
          Ground-truth labels are shown for the audience only — they never reach the detector.
        </span>
      </div>
      {tab === "replay" ? <ScenarioReplay /> : <VictimSimulator />}
    </>
  );
}

/* ------------------------------------------------------------------ replay */

const PROFILE_ORDER = ["high_volume_burst", "low_and_slow", "social_engineering_assisted", "benign_high_activity", "benign_occasional_denial"];
const PACES = [
  { value: 0.15, label: "Fast" },
  { value: 0.5, label: "Normal" },
  { value: 1.2, label: "Slow" },
];

function ScenarioReplay() {
  const [profile, setProfile] = useState("high_volume_burst");
  const [pace, setPace] = useState(0.5);
  const [watching, setWatching] = useState(null);
  const [error, setError] = useState(null);
  const episodes = usePoll(() => api.scenarios(profile), 0, [profile]);
  const runs = usePoll(() => api.runs(), 1500);
  const alerts = usePoll(() => api.alerts(), 2500);
  const alertByUser = useMemo(() => Object.fromEntries((alerts.data || []).map((a) => [a.user_id, a])), [alerts.data]);
  const replayRuns = (runs.data || []).filter((r) => r.source === "replay");
  const watched = watching || replayRuns[0]?.user_id;

  const start = async (burstId) => {
    setError(null);
    try {
      const run = await api.replay({ burst_id: burstId, pace_seconds: pace, time_mode: "preserve" });
      setWatching(run.user_id);
      runs.refresh();
    } catch (e) {
      setError(e);
    }
  };

  return (
    <>
      <div className="grid" style={{ gridTemplateColumns: "repeat(5, minmax(0, 1fr))" }}>
        {PROFILE_ORDER.map((p) => (
          <button key={p} className="scenario" aria-pressed={profile === p} onClick={() => setProfile(p)}>
            <div className="row between">
              <b>{PROFILES[p].label}</b>
              <LabelBadge attack={PROFILES[p].attack} />
            </div>
            <div className="desc">{PROFILES[p].blurb}</div>
          </button>
        ))}
      </div>
      <ErrorNote error={error} />
      <div className="grid g-main">
        <Card
          title={`${profileLabel(profile)} episodes`}
          sub="Held-out test-split episodes from the benchmark — real RBA users with seeded attack overlays"
          actions={
            <span className="row small">
              <span className="muted">Replay speed</span>
              <Segmented label="Replay speed" value={pace} onChange={setPace} options={PACES} />
            </span>
          }
        >
          {episodes.data?.length ? (
            <table className="table compact">
              <thead>
                <tr>
                  <th>Episode</th>
                  <th className="r">Prompts</th>
                  <th className="r">Denials</th>
                  <th className="r">Real duration</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {episodes.data.map((e) => (
                  <tr key={e.burst_id}>
                    <td className="mono small">{shortUser(String(e.user_id))}</td>
                    <td className="r num">{e.n_prompts}</td>
                    <td className="r num">{e.n_denials}</td>
                    <td className="r num">{fmtDuration(e.duration_seconds)}</td>
                    <td className="r">
                      <button className="btn sm primary" onClick={() => start(e.burst_id)}>
                        <Play size={13} /> Replay
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty icon={FlaskConical} title={episodes.loading ? "Loading episodes…" : "No episodes for this profile"} />
          )}
          <p className="tiny muted" style={{ marginTop: 10 }}>
            Replays keep every event's original timestamps and gaps (a 5-hour low-and-slow attack replays in seconds with its
            real 20–40 minute spacing), so the live pipeline computes exactly the features the offline evaluation scored.
          </p>
        </Card>
        <Card title="Replay runs" sub="Outcome as decided by the live pipeline">
          {replayRuns.length ? (
            <div className="col" style={{ gap: 0, margin: "-6px -20px -10px" }}>
              {replayRuns.slice(0, 8).map((r) => {
                const alert = alertByUser[r.user_id];
                const pct = r.n_total ? Math.round((100 * r.n_events) / r.n_total) : r.status === "finished" ? 100 : 0;
                return (
                  <button key={r.run_id} className="list-item" aria-selected={watched === r.user_id} onClick={() => setWatching(r.user_id)}>
                    <div className="col" style={{ gap: 6, flex: 1, minWidth: 0 }}>
                      <div className="row between">
                        <span className="small" style={{ fontWeight: 600 }}>{profileLabel(r.profile)}</span>
                        <LabelBadge attack={r.label_attack} />
                      </div>
                      <div className="progress"><div style={{ width: `${pct}%` }} /></div>
                      <div className="row between tiny muted">
                        <span className="mono">{shortUser(r.user_id)}</span>
                        <span>
                          {alert ? (
                            <a href={`#/alerts/${alert.alert_id}`} onClick={(ev) => ev.stopPropagation()} style={{ color: "var(--critical-ink)", fontWeight: 600 }}>
                              Alert · {fmtScore(alert.fused_score)}
                            </a>
                          ) : r.status === "running" ? (
                            `${r.n_events}/${r.n_total ?? "?"} events`
                          ) : (
                            <span style={{ color: "var(--good-ink)", fontWeight: 600 }}>No alert</span>
                          )}
                        </span>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          ) : (
            <Empty icon={Play} title="No replays yet">Pick an episode and press Replay.</Empty>
          )}
        </Card>
      </div>
      {watched && <RunWatcher userId={watched} alert={alertByUser[watched]} />}
    </>
  );
}

function RunWatcher({ userId, alert }) {
  const scores = usePoll(() => api.recentScores(300, userId), 1200, [userId]);
  const op = usePoll(() => api.operatingPoint(), 0);
  const rows = [...(scores.data || [])].reverse();
  // A replay can span more than one session (benign users go quiet for hours);
  // show the latest session.
  const lastEpisode = rows.at(-1)?.episode_id;
  const session = rows.filter((r) => r.episode_id === lastEpisode);
  const sequence = session.map((r) => ({ decision: r.decision, decision_latency_ms: r.decision_latency_ms }));
  const slope = fitSlope(sequence);
  return (
    <div className="grid g-2 fade-in">
      <Card
        title={<span className="mono">{shortUser(userId)} · live</span>}
        sub="Fused score at each decision as it is scored"
        actions={alert ? <button className="btn sm" onClick={() => navigate(`/alerts/${alert.alert_id}`)}><ShieldAlert size={14} /> Open alert</button> : null}
      >
        <ScoreTrajectoryChart trajectory={session} threshold={op.data?.threshold} />
      </Card>
      <Card title="Decision latency" sub="Approve/deny reaction times in this session">
        <LatencyTrajectoryChart sequence={sequence} slope={slope.slope} slopeValid={slope.valid} />
      </Card>
    </div>
  );
}

// Client-side least-squares slope for live views that have no stored feature
// vector (the alert view uses the feature engine's own value instead).
function fitSlope(sequence) {
  const pts = sequence.map((s, i) => [i + 1, s.decision_latency_ms]).filter(([, y]) => y != null);
  if (pts.length < 2) return { slope: 0, valid: false };
  const mx = pts.reduce((a, [x]) => a + x, 0) / pts.length;
  const my = pts.reduce((a, [, y]) => a + y, 0) / pts.length;
  const num = pts.reduce((a, [x, y]) => a + (x - mx) * (y - my), 0);
  const den = pts.reduce((a, [x]) => a + (x - mx) ** 2, 0);
  return den ? { slope: num / den, valid: true } : { slope: 0, valid: false };
}

/* --------------------------------------------------------------- simulator */

function VictimSimulator() {
  const [mode, setMode] = useState("attack");
  const [pacing, setPacing] = useState(6);
  const [simId, setSimId] = useState(null);
  const [error, setError] = useState(null);
  const [lastOutcome, setLastOutcome] = useState(null);
  const sim = usePoll(() => (simId ? api.sim(simId) : Promise.resolve(null)), simId ? 700 : 0, [simId]);
  const s = sim.data;
  const scores = usePoll(() => (s ? api.recentScores(200, s.user_id) : Promise.resolve([])), s ? 1200 : 0, [s?.user_id]);
  const op = usePoll(() => api.operatingPoint(), 0);

  const start = async () => {
    setError(null);
    setLastOutcome(null);
    try {
      const created = await api.startSim({ mode, pacing_seconds: pacing, max_prompts: 25 });
      setSimId(created.sim_id);
    } catch (e) {
      setError(e);
    }
  };
  const stop = async () => {
    if (simId) await api.simStop(simId).catch(() => {});
    sim.refresh();
  };
  const respond = async (decision) => {
    try {
      const r = await api.simRespond(simId, decision);
      setLastOutcome(r);
      sim.refresh();
    } catch (e) {
      setError(e);
    }
  };
  const login = async () => {
    try {
      await api.simLogin(simId);
      sim.refresh();
    } catch (e) {
      setError(e);
    }
  };

  const trajectory = [...(scores.data || [])].reverse();
  const history = s?.history || [];
  const seq = history.map((h) => ({ decision: h.decision, decision_latency_ms: h.latency_ms }));
  const slope = fitSlope(seq);
  const running = s?.status === "running";

  return (
    <div className="grid" style={{ gridTemplateColumns: "minmax(0, 340px) minmax(0, 1fr)", alignItems: "start" }}>
      <div className="col" style={{ gap: 16 }}>
        <Card title="Scenario" sub="You are the account owner; the phone is your authenticator">
          <div className="col" style={{ gap: 14 }}>
            <Segmented
              label="Simulation mode"
              value={mode}
              onChange={setMode}
              options={[
                { value: "attack", label: "Attacker pushes" },
                { value: "benign", label: "I log in myself" },
              ]}
            />
            {mode === "attack" ? (
              <div className="col" style={{ gap: 6 }}>
                <label className="row between small" htmlFor="pacing">
                  <span>Attacker sends a push every</span>
                  <b className="num">{pacing} s</b>
                </label>
                <input id="pacing" type="range" min={3} max={20} step={1} value={pacing} onChange={(e) => setPacing(Number(e.target.value))} disabled={running} />
                <p className="tiny muted">
                  Try it the way a worn-down user does: read and deny the first few carefully, then start tapping faster.
                  PulseGuard watches your reaction time — not just the count.
                </p>
              </div>
            ) : (
              <p className="tiny muted">The negative control: start your own logins from your laptop and approve them normally. Nothing should fire.</p>
            )}
            <div className="row">
              {!running ? (
                <button className="btn primary" onClick={start}><Zap size={15} /> Start</button>
              ) : (
                <button className="btn" onClick={stop}><Square size={14} /> Stop</button>
              )}
              {running && mode === "benign" && s?.mode === "benign" && !s?.pending && (
                <button className="btn" onClick={login}><Laptop size={15} /> Log in from my laptop</button>
              )}
            </div>
            <ErrorNote error={error} />
          </div>
        </Card>
        <Phone sim={s} onRespond={respond} lastOutcome={lastOutcome} />
      </div>

      <div className="col" style={{ gap: 16 }}>
        <SimStatus sim={s} lastOutcome={lastOutcome} />
        <div className="grid g-2">
          <Card title="Your reaction times" sub="Measured from push shown to button pressed">
            {seq.length ? (
              <LatencyTrajectoryChart sequence={seq} slope={slope.slope} slopeValid={slope.valid} height={240} />
            ) : (
              <Empty icon={Hand} title="Answer a push to see your latency" />
            )}
          </Card>
          <Card title="PulseGuard's score" sub="Every answer is scored on the session so far">
            {trajectory.length ? (
              <ScoreTrajectoryChart trajectory={trajectory.filter((t) => t.episode_id === trajectory.at(-1)?.episode_id)} threshold={op.data?.threshold} height={240} />
            ) : (
              <Empty icon={ShieldCheck} title="No decisions scored yet" />
            )}
          </Card>
        </div>
        <Card title="Event log">
          {s?.messages?.length || history.length ? (
            <div className="timeline">
              {[...(s?.messages || []).map((m) => ({ ts: m.ts, kind: m.kind, text: m.text })),
                ...history.map((h) => ({ ts: h.ts, kind: h.decision, text: `You ${h.decision === "timeout" ? "ignored" : h.decision === "approve" ? "approved" : "denied"} a push from ${h.origin === "you" ? "your own login" : "the attacker"}${h.latency_ms != null ? ` in ${fmtMs(h.latency_ms)}` : ""}.` }))]
                .sort((a, b) => new Date(a.ts) - new Date(b.ts))
                .map((m, i) => (
                  <div key={i} className={`tl-item ${m.kind === "protected" ? "good" : m.kind === "compromised" ? "critical" : m.kind === "approve" ? "brand" : ""}`}>
                    <div className="small">{m.text}</div>
                    <div className="when">{fmtTime(m.ts)}</div>
                  </div>
                ))}
            </div>
          ) : (
            <p className="small muted">Start the scenario to begin.</p>
          )}
        </Card>
      </div>
    </div>
  );
}

function SimStatus({ sim, lastOutcome }) {
  if (!sim) {
    return (
      <div className="banner info">
        <Smartphone size={18} />
        <div className="small">
          <b>How this works.</b> An attacker already has the password and keeps triggering push prompts. Every answer you give
          travels through the real pipeline — Kafka, the feature engine, the three-stage detector and the mitigation controller.
          If PulseGuard decides you are being fatigued, the identity provider stops honouring push approvals for this account.
        </div>
      </div>
    );
  }
  if (sim.status === "protected" || lastOutcome?.outcome === "held_for_step_up") {
    return (
      <div className="banner good">
        <ShieldCheck size={18} />
        <div className="small"><b>Protected.</b> PulseGuard forced a number-matching step-up. Push approvals for this account are suspended, so the attacker's login cannot complete — even if you tap Approve.</div>
      </div>
    );
  }
  if (sim.status === "compromised") {
    return (
      <div className="banner critical">
        <ShieldAlert size={18} />
        <div className="small"><b>Compromised.</b> Your approval let the attacker in before PulseGuard had seen enough to intervene. Try again — deny a few prompts first, the way a real victim would, before giving in.</div>
      </div>
    );
  }
  return (
    <div className="banner info">
      <Clock3 size={18} />
      <div className="small">
        <b>{sim.mode === "attack" ? "Attack in progress" : "Benign session"}.</b> {sim.prompts_sent} push{sim.prompts_sent === 1 ? "" : "es"} sent · user <span className="mono">{sim.user_id}</span>
      </div>
    </div>
  );
}

function Phone({ sim, onRespond, lastOutcome }) {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  const challenge = sim?.challenges?.find((c) => c.status === "pending");
  const pending = sim?.status === "running" ? sim?.pending : null;
  return (
    <div className="phone" aria-label="Simulated phone">
      <div className="phone-screen">
        <div className="phone-notch" />
        <div className="phone-status">
          <span>{now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
          <span className="row" style={{ gap: 4 }}><Wifi size={12} /> 5G</span>
        </div>
        <div className="phone-time">{now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })}</div>
        <div className="phone-date">{now.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" })}</div>

        {pending && (
          <div className="push" key={pending.prompt_id} role="alertdialog" aria-label="Sign-in request">
            <div className="app"><span className="app-icon"><ShieldCheck size={12} /></span> Authenticator · now</div>
            <div className="ttl">Approve sign-in?</div>
            <div className="meta">
              <div className="row" style={{ gap: 5 }}><MapPin size={11} /> {pending.country} · {pending.origin_ip}</div>
              <div className="row" style={{ gap: 5 }}><Laptop size={11} /> {pending.origin_device}</div>
            </div>
            <div className="acts">
              <button className="deny" onClick={() => onRespond("deny")}>Deny</button>
              <button className="approve" onClick={() => onRespond("approve")}>Approve</button>
            </div>
          </div>
        )}

        {!pending && challenge && <StepUpCard challenge={challenge} />}

        {!pending && !challenge && sim?.status === "compromised" && (
          <div className="phone-msg compromised"><b>Signed in from a new device.</b><br />If this wasn't you, change your password.</div>
        )}
        {!pending && !challenge && sim?.status === "protected" && (
          <div className="phone-msg protected"><b>Sign-in blocked.</b><br />Unusual approval pattern detected. Push approvals are paused for your account.</div>
        )}
        {!pending && !challenge && sim?.status === "running" && (
          <div className="phone-msg idle">{sim.mode === "attack" ? "Waiting for the next push…" : "Use “Log in from my laptop” to start a login."}</div>
        )}
        {!sim && <div className="phone-msg idle">No notifications</div>}
        {lastOutcome?.outcome === "held_for_step_up" && !challenge && (
          <div className="phone-msg protected"><CheckCircle2 size={14} style={{ verticalAlign: -2 }} /> Your last approval was held by the IdP.</div>
        )}
        <div className="phone-home" />
      </div>
    </div>
  );
}

function StepUpCard({ challenge }) {
  const [done, setDone] = useState(null);
  const options = useMemo(() => {
    const n = challenge.number_match;
    const set = new Set([n]);
    while (set.size < 3) set.add(10 + Math.floor(Math.random() * 90));
    return [...set].sort(() => Math.random() - 0.5);
  }, [challenge.challenge_id, challenge.number_match]);
  const answer = async (passed) => {
    await api.resolveChallenge(challenge.challenge_id, passed).catch(() => {});
    setDone(passed ? "passed" : "failed");
  };
  if (done) {
    return (
      <div className={`phone-msg ${done === "passed" ? "protected" : "compromised"}`}>
        {done === "passed" ? "Verified — it was you. Escalation history cleared." : "Reported. Repeated failures move this account to an alternate factor — never a lockout."}
      </div>
    );
  }
  return (
    <div className="push">
      <div className="app"><span className="app-icon"><ShieldCheck size={12} /></span> Security check</div>
      <div className="ttl">Is this sign-in you?</div>
      <div className="meta">Pick the number shown on the sign-in screen. The attacker can't see it.</div>
      <div className="small muted" style={{ marginTop: 8 }}>The sign-in screen shows:</div>
      <div className="challenge-num">{challenge.number_match}</div>
      <div className="acts" style={{ gridTemplateColumns: "1fr 1fr 1fr" }}>
        {options.map((n) => (
          <button key={n} className="deny" onClick={() => answer(n === challenge.number_match)}>{n}</button>
        ))}
      </div>
      <button className="btn sm ghost" style={{ marginTop: 8, width: "100%" }} onClick={() => answer(false)}>This wasn't me</button>
    </div>
  );
}

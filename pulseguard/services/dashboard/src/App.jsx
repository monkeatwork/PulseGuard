import { Activity, BarChart3, FlaskConical, LayoutDashboard, Network, ShieldAlert } from "lucide-react";
import { api } from "./api/client.js";
import { usePoll, useRoute } from "./lib/hooks.js";
import Overview from "./pages/Overview.jsx";
import Alerts from "./pages/Alerts.jsx";
import AttackLab from "./pages/AttackLab.jsx";
import Evaluation from "./pages/Evaluation.jsx";
import Architecture from "./pages/Architecture.jsx";

const NAV = [
  { id: "", label: "Overview", icon: LayoutDashboard, title: "SOC overview", sub: "Live MFA-fatigue detection across every session" },
  { id: "alerts", label: "Alerts", icon: ShieldAlert, title: "Alerts", sub: "One alert per session that crossed the evaluated threshold" },
  { id: "lab", label: "Attack Lab", icon: FlaskConical, title: "Attack Lab", sub: "Replay labelled attacks — or play the victim yourself" },
  { id: "evaluation", label: "Evaluation", icon: BarChart3, title: "Evaluation", sub: "Offline results on the frozen by-user test split" },
  { id: "architecture", label: "How it works", icon: Network, title: "How PulseGuard works", sub: "Five layers, one insight: read the user's reaction" },
];

export const SERVICES = [
  { id: "ingestion", label: "Ingestion" },
  { id: "features", label: "Feature engine" },
  { id: "detection", label: "Detection" },
  { id: "mitigation", label: "Mitigation" },
];

export function useServiceHealth(interval = 8000) {
  return usePoll(async () => {
    const entries = await Promise.all(
      SERVICES.map(async (s) => {
        try {
          const h = await api.health(s.id);
          return [s.id, h.status === "ok"];
        } catch {
          return [s.id, false];
        }
      }),
    );
    return Object.fromEntries(entries);
  }, interval);
}

export default function App() {
  const route = useRoute();
  const section = route[0] || "";
  const current = NAV.find((n) => n.id === section) || NAV[0];
  const health = useServiceHealth();
  const stats = usePoll(() => api.stats(), 5000);
  const allUp = health.data && Object.values(health.data).every(Boolean);
  const openAlerts = stats.data?.alerts_open ?? 0;

  return (
    <div className="shell">
      <aside className="sidebar" aria-label="Main navigation">
        <div className="app-brand">
          <div className="app-brand-mark" aria-hidden="true">
            <Activity size={19} strokeWidth={2.6} />
          </div>
          <div>
            <div className="app-brand-name">PulseGuard</div>
            <div className="app-brand-sub">MFA fatigue defence · T1621</div>
          </div>
        </div>
        <div className="nav-label">Monitor</div>
        {NAV.slice(0, 2).map((n) => (
          <NavItem key={n.id} item={n} active={current.id === n.id} badge={n.id === "alerts" && openAlerts ? openAlerts : null} />
        ))}
        <div className="nav-label">Demonstrate</div>
        {NAV.slice(2).map((n) => (
          <NavItem key={n.id} item={n} active={current.id === n.id} />
        ))}
        <div className="sidebar-foot small muted">
          <div className="row" style={{ gap: 8 }}>
            <span className={`dot ${allUp ? "live" : ""}`} style={allUp ? {} : { background: "var(--warning)" }} />
            {health.data ? (allUp ? "All services healthy" : "Some services starting…") : "Checking services…"}
          </div>
          <div className="tiny" style={{ marginTop: 6 }}>BCSE410L Cyber Security · VIT</div>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="title">
            <h1 style={{ fontSize: 18 }}>{current.title}</h1>
            <span className="small muted">{current.sub}</span>
          </div>
          <div className="spacer" />
          <div className="row small muted" aria-label="Service health">
            {SERVICES.map((s) => (
              <span key={s.id} className="row" style={{ gap: 5 }} title={`${s.label}: ${health.data?.[s.id] ? "healthy" : "unreachable"}`}>
                <span className="dot" style={{ background: health.data?.[s.id] ? "var(--good)" : "var(--axis)" }} />
                {s.label}
              </span>
            ))}
          </div>
        </header>
        <main className="page fade-in" key={section}>
          {section === "" && <Overview stats={stats} health={health} />}
          {section === "alerts" && <Alerts selectedId={route[1]} />}
          {section === "lab" && <AttackLab />}
          {section === "evaluation" && <Evaluation />}
          {section === "architecture" && <Architecture health={health} />}
        </main>
      </div>
    </div>
  );
}

function NavItem({ item, active, badge }) {
  const Icon = item.icon;
  return (
    <a className="nav-item" href={`#/${item.id}`} aria-current={active ? "page" : undefined}>
      <Icon size={17} />
      {item.label}
      {badge ? <span className="count">{badge}</span> : null}
    </a>
  );
}

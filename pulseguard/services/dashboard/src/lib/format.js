export const fmtScore = (v) => (v == null || Number.isNaN(v) ? "—" : Number(v).toFixed(3));
export const fmtPct = (v, d = 1) => (v == null ? "n/a" : `${(v * 100).toFixed(d)}%`);
export const fmtMs = (v) => {
  if (v == null) return "—";
  if (v >= 1000) return `${(v / 1000).toFixed(v >= 10000 ? 0 : 1)} s`;
  return `${Math.round(v)} ms`;
};
export const fmtDuration = (seconds) => {
  if (seconds == null) return "—";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
};
export const fmtNum = (v) => {
  if (v == null) return "—";
  const n = Number(v);
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (Math.abs(n) >= 1e4) return `${(n / 1e3).toFixed(1)}K`;
  return n.toLocaleString();
};
export const fmtTime = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—");
export const fmtDateTime = (iso) =>
  iso ? new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";
export const timeAgo = (iso) => {
  if (!iso) return "—";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
};
// Replays run as "<corpus user>~<run>"; show something short and readable.
export const shortUser = (u) => {
  if (!u) return "—";
  const [base, run] = u.split("~");
  const b = base.length > 14 ? `${base.slice(0, 6)}…${base.slice(-4)}` : base;
  return run ? `${b}~${run}` : b;
};

export const severity = (score) => {
  if (score >= 0.85) return { level: "critical", label: "Critical" };
  if (score >= 0.6) return { level: "serious", label: "High" };
  if (score >= 0.35) return { level: "warning", label: "Medium" };
  return { level: "good", label: "Low" };
};

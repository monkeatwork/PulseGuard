import { AlertOctagon, AlertTriangle, CheckCircle2, CircleDot, HelpCircle, Inbox } from "lucide-react";
import { severity } from "../lib/format.js";

export function Card({ title, sub, actions, children, className = "", pad = false, ...rest }) {
  return (
    <section className={`card ${className}`} {...rest}>
      {(title || actions) && (
        <div className="card-head">
          <div>
            {title && <h2>{title}</h2>}
            {sub && <div className="sub">{sub}</div>}
          </div>
          {actions && <div className="actions">{actions}</div>}
        </div>
      )}
      <div className={pad || title ? "card-body" : ""}>{children}</div>
    </section>
  );
}

export function StatTile({ label, value, foot, icon: Icon, tone = "", help }) {
  return (
    <div className="card stat">
      <div className="label">
        {Icon && (
          <span className={`icon-chip ${tone}`}>
            <Icon size={15} strokeWidth={2.2} />
          </span>
        )}
        {label}
        {help && <Help text={help} />}
      </div>
      <div className="value">{value}</div>
      {foot && <div className="foot">{foot}</div>}
    </div>
  );
}

export function Help({ text }) {
  return (
    <span className="help" title={text} aria-label={text} role="img">
      <HelpCircle size={13} />
    </span>
  );
}

const SEV_ICON = { critical: AlertOctagon, serious: AlertTriangle, warning: AlertTriangle, good: CheckCircle2 };

// Status is never colour alone: icon + label + colour.
export function SeverityBadge({ score }) {
  const { level, label } = severity(score ?? 0);
  const Icon = SEV_ICON[level] || CircleDot;
  return (
    <span className={`badge ${level}`} aria-label={`${label} severity`}>
      <Icon size={12} strokeWidth={2.5} aria-hidden="true" />
      {label}
    </span>
  );
}

export function StatusBadge({ status }) {
  const map = { open: ["critical", "Open"], acknowledged: ["warning", "Acknowledged"], resolved: ["good", "Resolved"] };
  const [tone, label] = map[status] || ["neutral", status];
  return <span className={`badge ${tone}`}>{label}</span>;
}

export function LabelBadge({ attack }) {
  if (attack == null) return null;
  return attack ? (
    <span className="badge critical" title="Ground-truth label of the replayed scenario (never shown to the detector)">Attack</span>
  ) : (
    <span className="badge good" title="Ground-truth label of the replayed scenario (never shown to the detector)">Benign</span>
  );
}

export function ScoreBar({ value, threshold, color }) {
  const v = Math.max(0, Math.min(1, value ?? 0));
  const fill = color || (threshold != null && v >= threshold ? "var(--critical)" : "var(--series-1)");
  return (
    <div className="scorebar" role="meter" aria-valuemin={0} aria-valuemax={1} aria-valuenow={v} aria-label="fused score">
      <div className="fill" style={{ width: `${v * 100}%`, background: fill }} />
      {threshold != null && <div className="thr" style={{ left: `calc(${threshold * 100}% - 1px)` }} title={`threshold ${threshold}`} />}
    </div>
  );
}

export function Segmented({ options, value, onChange, label }) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={value === o.value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Empty({ icon: Icon = Inbox, title, children }) {
  return (
    <div className="empty">
      <div className="ico">
        <Icon size={20} />
      </div>
      <div style={{ fontWeight: 600, color: "var(--ink-2)" }}>{title}</div>
      {children && <div className="small">{children}</div>}
    </div>
  );
}

export function Legend({ items }) {
  return (
    <div className="legend">
      {items.map((it) => (
        <span className="key" key={it.label}>
          <span className={it.line ? "ln" : "sw"} style={{ background: it.color }} />
          {it.label}
        </span>
      ))}
    </div>
  );
}

export function ChartTooltip({ title, rows }) {
  return (
    <div className="tooltip">
      {title && <div className="t">{title}</div>}
      {rows.map(([k, v]) => (
        <div className="r" key={k}>
          <span>{k}</span>
          <b>{v}</b>
        </div>
      ))}
    </div>
  );
}

export function ErrorNote({ error }) {
  if (!error) return null;
  return (
    <div className="banner warning small" role="status">
      <AlertTriangle size={16} />
      <span>Could not reach the API ({String(error.message || error)}). Retrying…</span>
    </div>
  );
}

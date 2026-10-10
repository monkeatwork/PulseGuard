// Status color never carries meaning alone -- pairs an icon glyph with the
// label text (dataviz skill: "a status color never carries meaning alone").
const LEVELS = {
  critical: { icon: "▲", label: "Critical" },
  serious: { icon: "▲", label: "Elevated" },
  warning: { icon: "●", label: "Watch" },
};

export function levelForScore(score) {
  if (score >= 0.85) return "critical";
  if (score >= 0.6) return "serious";
  return "warning";
}

export default function StatusBadge({ score }) {
  const level = levelForScore(score);
  const { icon, label } = LEVELS[level];
  return (
    <span className="status-badge" data-level={level}>
      <span aria-hidden="true">{icon}</span>
      {label}
    </span>
  );
}

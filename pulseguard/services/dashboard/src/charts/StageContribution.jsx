import { STAGES } from "../lib/features.js";
import { fmtScore } from "../lib/format.js";
import { Legend } from "../components/ui.jsx";

// How the fused score is assembled: each stage's weight x score, stacked,
// against the alert threshold. A zero-weight stage contributes nothing and is
// shown as such -- the weights are the persisted operating point.
export default function StageContribution({ scores, weights, threshold }) {
  if (!weights) return <p className="muted small">Operating point unavailable.</p>;
  const capA = Math.min(Math.max(scores.a ?? 0, 0) / 5, 1); // fusion.normalize_stage_a_score
  const raw = { a: capA, b: scores.b ?? 0, c: scores.c ?? 0 };
  const total = weights.a + weights.b + weights.c || 1;
  const parts = STAGES.map((s) => ({ ...s, w: weights[s.key] / total, score: raw[s.key], contrib: (weights[s.key] / total) * raw[s.key] }));
  const fused = parts.reduce((a, p) => a + p.contrib, 0);
  return (
    <div className="col" style={{ gap: 12 }}>
      <div style={{ position: "relative", height: 26, background: "var(--surface-sunken)", borderRadius: 6, display: "flex", overflow: "hidden" }}>
        {parts.map((p) =>
          p.contrib > 0.0005 ? (
            <div key={p.key} title={`${p.name}: ${fmtScore(p.contrib)}`} style={{ width: `${p.contrib * 100}%`, background: p.color, borderRight: "2px solid var(--surface)" }} />
          ) : null,
        )}
        {threshold != null && <div style={{ position: "absolute", left: `calc(${threshold * 100}% - 1px)`, top: -2, bottom: -2, width: 2, background: "var(--ink)" }} />}
      </div>
      <Legend items={parts.map((p) => ({ label: p.name, color: p.color }))} />
      <table className="table compact">
        <thead>
          <tr>
            <th>Stage</th>
            <th className="r">Score</th>
            <th className="r">Weight</th>
            <th className="r">Contribution</th>
          </tr>
        </thead>
        <tbody>
          {parts.map((p) => (
            <tr key={p.key}>
              <td>
                <span className="row" style={{ gap: 8 }}>
                  <span className="dot" style={{ background: p.color }} />
                  <span>
                    <b>{p.name}</b>
                    <div className="tiny muted">{p.full.split("· ")[1]}</div>
                  </span>
                </span>
              </td>
              <td className="r num">{fmtScore(p.score)}</td>
              <td className="r num">{p.w.toFixed(2)}</td>
              <td className="r num">{fmtScore(p.contrib)}</td>
            </tr>
          ))}
          <tr>
            <td><b>Fused</b> <span className="muted small">(threshold {threshold?.toFixed(2)})</span></td>
            <td />
            <td />
            <td className="r num"><b>{fmtScore(fused)}</b></td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

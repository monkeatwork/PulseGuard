import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartTooltip, Legend } from "../components/ui.jsx";
import { fmtMs, fmtScore } from "../lib/format.js";

function Tip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const r = payload[0].payload;
  return (
    <ChartTooltip
      title={`Decision ${r.n} · ${r.decision || "—"}`}
      rows={[
        ["Fused score", fmtScore(r.fused_score)],
        ["Stage A", fmtScore(r.stage_a_score)],
        ["Stage B", fmtScore(r.stage_b_score)],
        ["Stage C", fmtScore(r.stage_c_score)],
        ["Latency", fmtMs(r.decision_latency_ms)],
      ]}
    />
  );
}

export default function ScoreTrajectoryChart({ trajectory = [], threshold, height = 220 }) {
  if (!trajectory.length) return <p className="muted small">No scored decision points yet.</p>;
  const data = trajectory.map((t) => ({ ...t, n: t.decision_index + 1 }));
  const first = data.find((d) => threshold != null && d.fused_score >= threshold);
  return (
    <div className="col" style={{ gap: 8 }}>
      <Legend
        items={[
          { label: "Fused score at each decision", color: "var(--series-1)", line: true },
          ...(threshold != null ? [{ label: `Alert threshold ${threshold.toFixed(2)} (validation-tuned)`, color: "var(--critical)", line: true }] : []),
        ]}
      />
      <div className="chart" style={{ height }} data-testid="score-chart">
        <ResponsiveContainer>
          <ComposedChart data={data} margin={{ top: 10, right: 16, bottom: 6, left: 0 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis dataKey="n" tickLine={false} axisLine={{ stroke: "var(--axis)" }} label={{ value: "Decision in session", position: "insideBottom", offset: -2, className: "axis-label" }} height={36} />
            <YAxis domain={[0, 1]} ticks={[0, 0.25, 0.5, 0.75, 1]} tickLine={false} axisLine={false} width={40} />
            <Tooltip content={<Tip />} cursor={{ stroke: "var(--axis)" }} />
            <Area dataKey="fused_score" stroke="none" fill="var(--series-1)" fillOpacity={0.1} isAnimationActive={false} />
            <Line dataKey="fused_score" stroke="var(--series-1)" strokeWidth={2} isAnimationActive={false}
              dot={{ r: 4, fill: "var(--series-1)", stroke: "var(--surface)", strokeWidth: 2 }} />
            {threshold != null && <ReferenceLine y={threshold} stroke="var(--critical)" strokeWidth={1.5} />}
            {first && (
              <ReferenceLine x={first.n} stroke="var(--axis)"
                label={{ value: `alert @ decision ${first.n}`, position: "insideTopLeft", fill: "var(--ink-2)", fontSize: 11 }} />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

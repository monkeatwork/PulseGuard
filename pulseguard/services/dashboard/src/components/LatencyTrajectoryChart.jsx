import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

// One series (this burst's decision latency across prompt index), one
// axis -- visualizes the response-behaviour signature latency_drift_slope
// is computed from (CLAUDE.md: "the single most important feature").
export default function LatencyTrajectoryChart({ points }) {
  if (!points || points.length === 0) {
    return <p className="detail-empty">No prompt/decision sequence available for this burst.</p>;
  }

  return (
    <div className="chart-wrapper">
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={points} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="promptIndex"
            tick={{ fill: "var(--text-muted)", fontSize: 11 }}
            stroke="var(--border)"
            label={{ value: "Prompt index", position: "insideBottom", offset: -4, fill: "var(--text-muted)", fontSize: 11 }}
          />
          <YAxis
            tick={{ fill: "var(--text-muted)", fontSize: 11 }}
            stroke="var(--border)"
            label={{ value: "Latency (ms)", angle: -90, position: "insideLeft", fill: "var(--text-muted)", fontSize: 11 }}
          />
          <Tooltip
            contentStyle={{ background: "var(--surface-0)", border: "1px solid var(--border)", fontSize: 12 }}
            formatter={(value, _name, props) => [`${value} ms`, props.payload.decision]}
            labelFormatter={(label) => `Prompt #${label}`}
          />
          <Line
            type="monotone"
            dataKey="latencyMs"
            stroke="var(--series-1)"
            strokeWidth={2}
            dot={{ r: 4, fill: "var(--series-1)" }}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

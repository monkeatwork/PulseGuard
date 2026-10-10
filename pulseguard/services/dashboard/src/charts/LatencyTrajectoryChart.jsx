import { CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartTooltip, Legend } from "../components/ui.jsx";
import { fmtMs } from "../lib/format.js";

const COLORS = { approve: "var(--series-1)", deny: "var(--series-2)", timeout: "var(--series-muted)" };

// Fitted line from the feature engine's own latency_drift_slope (ms per
// prompt), anchored through the mean of the answered points -- the line the
// detector actually "saw", not a separate client-side fit.
export function buildTrajectory(sequence, slope, slopeValid) {
  const rows = sequence.map((s, i) => ({
    i: i + 1,
    latency: s.decision_latency_ms != null ? s.decision_latency_ms / 1000 : null,
    approve: s.decision === "approve" && s.decision_latency_ms != null ? s.decision_latency_ms / 1000 : null,
    deny: s.decision === "deny" && s.decision_latency_ms != null ? s.decision_latency_ms / 1000 : null,
    decision: s.decision,
  }));
  const pts = rows.filter((r) => r.latency != null);
  if (slopeValid && pts.length >= 2) {
    const mx = pts.reduce((a, r) => a + r.i, 0) / pts.length;
    const my = pts.reduce((a, r) => a + r.latency, 0) / pts.length;
    const s = slope / 1000;
    rows.forEach((r) => {
      r.fit = Math.max(0, my + s * (r.i - mx));
    });
  }
  return rows;
}

function Tip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const r = payload[0].payload;
  return (
    <ChartTooltip
      title={`Prompt ${r.i}`}
      rows={[
        ["Decision", r.decision || "—"],
        ["Latency", r.latency != null ? fmtMs(r.latency * 1000) : "no answer"],
        ...(r.fit != null ? [["Fitted trend", fmtMs(r.fit * 1000)]] : []),
      ]}
    />
  );
}

const dot = (color) => (props) => {
  const { cx, cy, value } = props;
  if (value == null || cx == null || cy == null) return null;
  return <circle cx={cx} cy={cy} r={5} fill={color} stroke="var(--surface)" strokeWidth={2} />;
};

export default function LatencyTrajectoryChart({ sequence = [], slope = 0, slopeValid = false, height = 260 }) {
  if (!sequence.length) return <p className="muted small">No decisions recorded for this session.</p>;
  const data = buildTrajectory(sequence, slope, slopeValid);
  return (
    <div className="col" style={{ gap: 8 }}>
      <Legend
        items={[
          { label: "Denied", color: COLORS.deny },
          { label: "Approved", color: COLORS.approve },
          { label: slopeValid ? `Drift slope ${Math.round(slope)} ms/prompt` : "Drift slope undefined (too few points)", color: "var(--ink)", line: true },
        ]}
      />
      <div className="chart" style={{ height }} data-testid="latency-chart">
        <ResponsiveContainer>
          <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 6, left: 0 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis dataKey="i" tickLine={false} axisLine={{ stroke: "var(--axis)" }} label={{ value: "Prompt in session", position: "insideBottom", offset: -2, className: "axis-label" }} height={36} />
            <YAxis tickLine={false} axisLine={false} width={44} tickFormatter={(v) => `${v}s`} />
            <Tooltip content={<Tip />} cursor={{ stroke: "var(--axis)" }} />
            <Line dataKey="latency" stroke="var(--series-muted)" strokeWidth={1} dot={false} isAnimationActive={false} connectNulls />
            <Line dataKey="fit" stroke="var(--ink)" strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line dataKey="deny" stroke="none" dot={dot(COLORS.deny)} activeDot={false} isAnimationActive={false} />
            <Line dataKey="approve" stroke="none" dot={dot(COLORS.approve)} activeDot={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

import { render, screen } from "@testing-library/react";
import { SeverityBadge, ScoreBar, LabelBadge } from "../components/ui.jsx";
import Reasons from "../charts/Reasons.jsx";
import StageContribution from "../charts/StageContribution.jsx";
import { buildTrajectory } from "../charts/LatencyTrajectoryChart.jsx";
import { formatFeature, RESPONSE } from "../lib/features.js";
import { severity, shortUser } from "../lib/format.js";

describe("severity", () => {
  it("maps scores to levels with a text label, never colour alone", () => {
    render(<SeverityBadge score={0.93} />);
    expect(screen.getByText("Critical")).toBeInTheDocument();
    expect(severity(0.7).label).toBe("High");
    expect(severity(0.4).label).toBe("Medium");
    expect(severity(0.1).label).toBe("Low");
  });

  it("labels the ground truth explicitly", () => {
    render(<LabelBadge attack={false} />);
    expect(screen.getByText("Benign")).toBeInTheDocument();
  });

  it("exposes the score as an accessible meter", () => {
    render(<ScoreBar value={0.62} threshold={0.41} />);
    expect(screen.getByRole("meter")).toHaveAttribute("aria-valuenow", "0.62");
  });
});

describe("latency trajectory", () => {
  const seq = [
    { decision: "deny", decision_latency_ms: 6000 },
    { decision: "deny", decision_latency_ms: 4000 },
    { decision: "deny", decision_latency_ms: 2000 },
    { decision: "approve", decision_latency_ms: 500 },
  ];

  it("draws the feature engine's own slope through the mean of the answered points", () => {
    const rows = buildTrajectory(seq, -1800, true);
    const mean = (6 + 4 + 2 + 0.5) / 4;
    expect(rows[0].fit - rows[1].fit).toBeCloseTo(1.8);
    expect((rows[1].fit + rows[2].fit) / 2).toBeCloseTo(mean); // passes through (x̄, ȳ)
    expect(rows[3].approve).toBe(0.5);
    expect(rows[0].deny).toBe(6);
  });

  it("draws no fitted line when the slope is undefined", () => {
    const rows = buildTrajectory(seq.slice(0, 1), 0, false);
    expect(rows[0].fit).toBeUndefined();
  });
});

describe("explanations", () => {
  it("names the component that produced the reasons and signs each one", () => {
    render(
      <Reasons
        source="stage_c"
        reasons={[
          { feature: "sequence: denials", shap_value: 3.2, feature_value: 7 },
          { feature: "latency_drift_slope", shap_value: -0.4, feature_value: -900 },
        ]}
      />,
    );
    expect(screen.getByText(/Stage C \(GRU/)).toBeInTheDocument();
    expect(screen.getByText("Denials in the sequence")).toBeInTheDocument();
    expect(screen.getByText("Latency drift slope")).toBeInTheDocument();
    expect(screen.getByText("−0.40")).toBeInTheDocument();
  });

  it("shows a zero-weight stage contributing nothing", () => {
    render(<StageContribution scores={{ a: 5, b: 0.9, c: 0.8 }} weights={{ a: 0, b: 0, c: 1 }} threshold={0.5} />);
    const rows = screen.getAllByRole("row");
    const stageB = rows.find((r) => r.textContent.includes("Stage B"));
    expect(stageB.textContent).toContain("0.000");
    const fused = rows.find((r) => r.textContent.includes("Fused"));
    expect(fused.textContent).toContain("0.800");
  });
});

describe("feature formatting", () => {
  it("never fabricates a value for an invalid feature", () => {
    const slope = RESPONSE.find((f) => f.key === "latency_drift_slope");
    expect(formatFeature(slope, { latency_drift_slope: 0, latency_drift_slope_valid: false })).toBeNull();
    expect(formatFeature(slope, { latency_drift_slope: -812.4, latency_drift_slope_valid: true })).toBe("-812 ms/prompt");
  });

  it("shortens replay user ids but keeps the run suffix", () => {
    expect(shortUser("-1008114484897748134~ab12")).toBe("-10081…7748134~ab12".replace("7748134", "8134"));
    expect(shortUser("victim-3f2a1c")).toBe("victim-3f2a1c");
  });
});

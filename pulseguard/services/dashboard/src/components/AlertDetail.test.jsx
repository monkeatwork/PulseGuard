import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AlertDetail from "./AlertDetail.jsx";

const FIXTURE_ALERT = {
  alert_id: "a1",
  user_id: "attacker_target_1",
  ts: "2026-01-01T12:00:00Z",
  fused_score: 0.93,
  shap_top3: [
    { feature: "latency_drift_slope", shap_value: -1.42, feature_value: -812.3 },
    { feature: "deny_run_length", shap_value: 0.87, feature_value: 9 },
    { feature: "capitulation_flag", shap_value: 0.51, feature_value: 1 },
  ],
  sequence: [
    { decision_latency_ms: 5200, decision: "deny" },
    { decision_latency_ms: 3100, decision: "deny" },
    { decision_latency_ms: 900, decision: "approve" },
  ],
};

describe("AlertDetail", () => {
  it("shows an empty state when no alert is selected", () => {
    render(<AlertDetail alert={null} />);
    expect(screen.getByText(/select an alert/i)).toBeInTheDocument();
  });

  it("renders the user id, fused score, latency chart, and SHAP reasons from a fixture payload", () => {
    render(<AlertDetail alert={FIXTURE_ALERT} />);
    expect(screen.getByText("attacker_target_1")).toBeInTheDocument();
    expect(screen.getByText(/0\.930/)).toBeInTheDocument();
    expect(screen.getByText("Latency trajectory")).toBeInTheDocument();
    expect(screen.getByText("Top reasons (SHAP)")).toBeInTheDocument();
    expect(screen.getByText("latency_drift_slope")).toBeInTheDocument();
  });

  it("renders a working CEF export link pointing at this alert's id", () => {
    render(<AlertDetail alert={FIXTURE_ALERT} />);
    const link = screen.getByText("Export CEF");
    expect(link).toHaveAttribute("href", expect.stringContaining("/alerts/a1/cef"));
  });
});

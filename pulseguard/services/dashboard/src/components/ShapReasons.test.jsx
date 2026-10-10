import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ShapReasons from "./ShapReasons.jsx";

const FIXTURE_REASONS = [
  { feature: "latency_drift_slope", shap_value: -1.42, feature_value: -812.3 },
  { feature: "deny_run_length", shap_value: 0.87, feature_value: 9 },
  { feature: "capitulation_flag", shap_value: 0.51, feature_value: 1 },
];

describe("ShapReasons", () => {
  it("renders all three reasons from a fixture payload", () => {
    render(<ShapReasons reasons={FIXTURE_REASONS} />);
    expect(screen.getByText("latency_drift_slope")).toBeInTheDocument();
    expect(screen.getByText("deny_run_length")).toBeInTheDocument();
    expect(screen.getByText("capitulation_flag")).toBeInTheDocument();
  });

  it("sizes bars proportionally to |shap_value|, largest at full width", () => {
    render(<ShapReasons reasons={FIXTURE_REASONS} />);
    const bars = screen.getAllByRole("listitem").map((item) => item.querySelector(".shap-bar-fill"));
    expect(bars[0].style.width).toBe("100%"); // -1.42 is the largest magnitude
    expect(parseFloat(bars[1].style.width)).toBeLessThan(100);
  });

  it("shows an empty state message when there are no reasons", () => {
    render(<ShapReasons reasons={[]} />);
    expect(screen.getByText(/no shap explanation/i)).toBeInTheDocument();
  });
});

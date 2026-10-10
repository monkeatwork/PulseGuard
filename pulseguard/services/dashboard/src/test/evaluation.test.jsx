import { render, screen, waitFor } from "@testing-library/react";
import Evaluation from "../pages/Evaluation.jsx";

const overall = (recall, precision, fpr) => ({ tp: 1, fp: 0, tn: 1, fn: 0, recall, precision, fpr });
const RESULTS = {
  baseline_splunk: { overall: overall(0.3, 1, 0), by_profile: {} },
  baseline_elastic: { overall: overall(0.6, 1, 0), by_profile: {} },
  stage_ab: { overall: overall(0.9, 0.8, 0.09), by_profile: {} },
  stage_c: { overall: overall(0.95, 0.97, 0.01), by_profile: {} },
  full_fusion: {
    overall: overall(0.97, 0.98, 0.012),
    by_profile: { low_and_slow: { recall: 0.9 }, benign_high_activity: { fpr: 0.012 } },
    weights: { a: 0.1, b: 0.3, c: 0.6 },
    threshold: 0.42,
    unit: "episode (positive if any decision point crosses the threshold)",
    n_episodes_evaluated: 3859,
  },
  ablation: {
    variants: {
      frequency_only: { n_features: 9, overall: overall(0.8, 0.5, 0.3) },
      frequency_plus_response_behaviour: { n_features: 19, overall: overall(0.95, 0.9, 0.02) },
      response_behaviour_minus_latency_drift_slope: { n_features: 17, overall: overall(0.95, 0.9, 0.02) },
    },
    response_behaviour_lift_percentage_points: 15,
    latency_drift_slope_lift_percentage_points: 0,
    no_measurable_lift_latency_drift_slope: true,
    no_measurable_lift_response_behaviour: false,
    noise_floor_percentage_points: 2,
  },
  adversarial: { n_adversarial_episodes: 400, baselines: {}, anti_dos_invariant_holds_under_mimicry_pacing: true },
};

beforeEach(() => {
  global.fetch = vi.fn(async () => ({ ok: true, headers: { get: () => "application/json" }, json: async () => RESULTS }));
});

it("renders every detector from the result files and keeps the negative result visible", async () => {
  render(<Evaluation />);
  await waitFor(() => expect(screen.getAllByText("PulseGuard fusion").length).toBeGreaterThan(0));
  expect(screen.getAllByText("Splunk rule").length).toBeGreaterThan(0);
  expect(screen.getByText(/No measurable lift:/)).toBeInTheDocument();
  expect(screen.getByText("0.42")).toBeInTheDocument();
  expect(screen.getByText(/holds/)).toBeInTheDocument();
});

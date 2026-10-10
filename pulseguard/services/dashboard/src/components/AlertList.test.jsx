import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import AlertList from "./AlertList.jsx";

const FIXTURE_ALERTS = [
  { alert_id: "a1", user_id: "attacker_target_1", ts: "2026-01-01T12:00:00Z", fused_score: 0.93 },
  { alert_id: "a2", user_id: "poweruser_1", ts: "2026-01-01T09:00:00Z", fused_score: 0.42 },
];

describe("AlertList", () => {
  it("renders one row per alert from a fixture payload", () => {
    render(<AlertList alerts={FIXTURE_ALERTS} selectedAlertId={null} onSelect={() => {}} />);
    expect(screen.getByText("attacker_target_1")).toBeInTheDocument();
    expect(screen.getByText("poweruser_1")).toBeInTheDocument();
  });

  it("calls onSelect with the alert_id when a row is clicked", () => {
    const onSelect = vi.fn();
    render(<AlertList alerts={FIXTURE_ALERTS} selectedAlertId={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByText("attacker_target_1"));
    expect(onSelect).toHaveBeenCalledWith("a1");
  });

  it("marks the selected row via data-selected", () => {
    render(<AlertList alerts={FIXTURE_ALERTS} selectedAlertId="a2" onSelect={() => {}} />);
    const rows = screen.getAllByRole("listitem");
    expect(rows[1]).toHaveAttribute("data-selected", "true");
    expect(rows[0]).toHaveAttribute("data-selected", "false");
  });

  it("shows an empty state when there are no alerts", () => {
    render(<AlertList alerts={[]} selectedAlertId={null} onSelect={() => {}} />);
    expect(screen.getByText(/no alerts/i)).toBeInTheDocument();
  });
});

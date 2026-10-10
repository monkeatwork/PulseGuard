import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import StatusBadge, { levelForScore } from "./StatusBadge.jsx";

describe("levelForScore", () => {
  it("classifies high scores as critical", () => {
    expect(levelForScore(0.95)).toBe("critical");
    expect(levelForScore(0.85)).toBe("critical");
  });

  it("classifies mid scores as serious", () => {
    expect(levelForScore(0.7)).toBe("serious");
    expect(levelForScore(0.6)).toBe("serious");
  });

  it("classifies low scores as warning", () => {
    expect(levelForScore(0.3)).toBe("warning");
  });
});

describe("StatusBadge", () => {
  it("renders the label as visible text, never color alone", () => {
    render(<StatusBadge score={0.9} />);
    expect(screen.getByText("Critical")).toBeInTheDocument();
  });

  it("sets data-level for styling hooks", () => {
    render(<StatusBadge score={0.9} />);
    const badge = screen.getByText("Critical").closest(".status-badge");
    expect(badge).toHaveAttribute("data-level", "critical");
  });
});

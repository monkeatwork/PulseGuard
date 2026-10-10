import { CheckCircle2, CircleDashed } from "lucide-react";

const LAYERS = [
  { lvl: "L1", nm: "Telemetry", svc: "ingestion", detail: () => "Replay + live simulator adapters" },
  { lvl: "L2", nm: "Ingestion → Kafka", svc: "ingestion", detail: () => "Canonical events, keyed by user" },
  { lvl: "L3", nm: "Feature engine", svc: "features", detail: () => "Session features + Redis baselines" },
  {
    lvl: "L4", nm: "Detection", svc: "detection",
    detail: (op) => (op ? `A·B·C fusion = ${op.weight_a.toFixed(2)}/${op.weight_b.toFixed(2)}/${op.weight_c.toFixed(2)}, thr ${op.threshold.toFixed(2)}` : "Stage A/B/C fusion"),
  },
  { lvl: "L5", nm: "Response", svc: "mitigation", detail: (op, s) => `${s?.mitigation_actions?.step_up_required ?? 0} step-ups · SOC + CEF` },
];

export default function PipelineStrip({ health, op, stats }) {
  return (
    <div className="pipeline">
      {LAYERS.map((l) => {
        const up = health?.[l.svc];
        return (
          <div className="stage" key={l.lvl}>
            <div className="lvl">{l.lvl}</div>
            <div className="nm">{l.nm}</div>
            <div className="st">
              {up ? <CheckCircle2 size={13} color="var(--good)" /> : <CircleDashed size={13} />}
              {l.detail(op, stats)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

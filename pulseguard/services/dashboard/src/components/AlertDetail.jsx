import LatencyTrajectoryChart from "./LatencyTrajectoryChart.jsx";
import ShapReasons from "./ShapReasons.jsx";
import StatusBadge from "./StatusBadge.jsx";
import { cefExportUrl } from "../api/client.js";

export default function AlertDetail({ alert }) {
  if (!alert) {
    return <p className="detail-empty">Select an alert to see its details.</p>;
  }

  const points = (alert.sequence || []).map((event, index) => ({
    promptIndex: index,
    latencyMs: event.decision_latency_ms,
    decision: event.decision,
  }));

  return (
    <div>
      <div className="alert-row-top">
        <h2 style={{ margin: 0, fontSize: 18 }}>{alert.user_id}</h2>
        <a className="cef-export-button" href={cefExportUrl(alert.alert_id)} download>
          Export CEF
        </a>
      </div>
      <p className="alert-meta">
        <StatusBadge score={alert.fused_score} /> &nbsp; fused score {alert.fused_score.toFixed(3)} &middot;{" "}
        {new Date(alert.ts).toLocaleString()}
      </p>

      <h3 className="section-title">Latency trajectory</h3>
      <LatencyTrajectoryChart points={points} />

      <h3 className="section-title">Top reasons (SHAP)</h3>
      <ShapReasons reasons={alert.shap_top3} />
    </div>
  );
}

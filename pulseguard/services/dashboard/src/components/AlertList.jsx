import StatusBadge from "./StatusBadge.jsx";

export default function AlertList({ alerts, selectedAlertId, onSelect }) {
  if (!alerts || alerts.length === 0) {
    return <p className="detail-empty">No alerts to show.</p>;
  }

  return (
    <div className="alert-list" role="list" aria-label="Alert queue">
      {alerts.map((alert) => (
        <button
          key={alert.alert_id}
          type="button"
          className="alert-row"
          data-selected={alert.alert_id === selectedAlertId}
          role="listitem"
          onClick={() => onSelect(alert.alert_id)}
        >
          <div className="alert-row-top">
            <span className="alert-user">{alert.user_id}</span>
            <span className="alert-score">{alert.fused_score.toFixed(2)}</span>
          </div>
          <StatusBadge score={alert.fused_score} />
          <span className="alert-meta">{new Date(alert.ts).toLocaleString()}</span>
        </button>
      ))}
    </div>
  );
}

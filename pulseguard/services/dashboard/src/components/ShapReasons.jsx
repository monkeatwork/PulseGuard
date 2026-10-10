// Renders an alert's SHAP top-3 reasons (CLAUDE.md, L4: "SHAP top-3
// reasons per alert") as horizontal bars sized by |shap_value|, sequential
// single-hue encoding since this is one series of magnitudes, not
// categories -- no legend needed for a single series.
export default function ShapReasons({ reasons }) {
  if (!reasons || reasons.length === 0) {
    return <p className="detail-empty">No SHAP explanation available for this alert.</p>;
  }

  const maxAbs = Math.max(...reasons.map((r) => Math.abs(r.shap_value)), 1e-9);

  return (
    <div role="list" aria-label="Top SHAP reasons">
      {reasons.map((reason) => {
        const widthPct = (Math.abs(reason.shap_value) / maxAbs) * 100;
        return (
          <div className="shap-reason" role="listitem" key={reason.feature}>
            <span className="shap-reason-name" title={reason.feature}>
              {reason.feature}
            </span>
            <div className="shap-bar-track">
              <div className="shap-bar-fill" style={{ width: `${widthPct}%` }} />
            </div>
            <span className="shap-reason-value">{reason.shap_value.toFixed(2)}</span>
          </div>
        );
      })}
    </div>
  );
}

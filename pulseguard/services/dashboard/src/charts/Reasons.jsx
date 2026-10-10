import { featureLabel, SOURCE_LABEL } from "../lib/features.js";

// Top-3 reasons, signed: positive pushed toward "attack". The bar length is
// relative to the largest reason; the source label says which component
// produced them (always the one that dominated the fused score).
export default function Reasons({ reasons = [], source }) {
  if (!reasons.length) return <p className="muted small">No explanation recorded.</p>;
  const max = Math.max(...reasons.map((r) => Math.abs(r.shap_value))) || 1;
  return (
    <div>
      {source && (
        <div className="small muted" style={{ marginBottom: 6 }}>
          Explained by <b style={{ color: "var(--ink)" }}>{SOURCE_LABEL[source] || source}</b> — the component that contributed most to this alert's score.
        </div>
      )}
      {reasons.map((r) => {
        const toward = r.shap_value >= 0;
        return (
          <div className="reason" key={r.feature}>
            <div>
              <div style={{ fontWeight: 600 }}>{featureLabel(r.feature)}</div>
              <div className="tiny muted mono">
                {r.feature} = {typeof r.feature_value === "number" ? +r.feature_value.toFixed(2) : String(r.feature_value)}
              </div>
            </div>
            <div style={{ background: "var(--surface-sunken)", borderRadius: 4, height: 8 }}>
              <div className="bar" style={{ width: `${(Math.abs(r.shap_value) / max) * 100}%`, background: toward ? "var(--series-2)" : "var(--series-1)", borderRadius: 4 }} />
            </div>
            <div className="num small" style={{ textAlign: "right" }}>
              {toward ? "+" : "−"}
              {Math.abs(r.shap_value).toFixed(2)}
            </div>
          </div>
        );
      })}
      <div className="legend" style={{ marginTop: 8 }}>
        <span className="key"><span className="sw" style={{ background: "var(--series-2)" }} />towards attack</span>
        <span className="key"><span className="sw" style={{ background: "var(--series-1)" }} />towards benign</span>
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import AlertDetail from "./components/AlertDetail.jsx";
import AlertList from "./components/AlertList.jsx";
import { fetchAlertDetail, fetchAlerts } from "./api/client.js";
import "./styles.css";

export default function App() {
  const [alerts, setAlerts] = useState([]);
  const [selectedAlertId, setSelectedAlertId] = useState(null);
  const [selectedAlert, setSelectedAlert] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchAlerts()
      .then(setAlerts)
      .catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    if (!selectedAlertId) {
      setSelectedAlert(null);
      return;
    }
    fetchAlertDetail(selectedAlertId)
      .then(setSelectedAlert)
      .catch((err) => setError(err.message));
  }, [selectedAlertId]);

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1 className="app-title">PulseGuard SOC Dashboard</h1>
        {error && <span style={{ color: "var(--status-critical)", fontSize: 12 }}>{error}</span>}
      </header>
      <AlertList alerts={alerts} selectedAlertId={selectedAlertId} onSelect={setSelectedAlertId} />
      <div className="detail-pane">
        <AlertDetail alert={selectedAlert} />
      </div>
    </div>
  );
}

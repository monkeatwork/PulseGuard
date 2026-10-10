// Thin fetch wrapper for the detection_engine / mitigation REST APIs.
// Base URLs are read from Vite env vars so docker-compose can point the
// dashboard at the right service hostnames without a rebuild.
const DETECTION_ENGINE_BASE_URL = import.meta.env.VITE_DETECTION_ENGINE_URL || "http://localhost:8003";
const MITIGATION_BASE_URL = import.meta.env.VITE_MITIGATION_URL || "http://localhost:8004";

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${url} returned ${response.status}`);
  }
  return response.json();
}

export async function fetchAlerts(limit = 50) {
  return getJson(`${DETECTION_ENGINE_BASE_URL}/alerts?limit=${limit}`);
}

export async function fetchAlertDetail(alertId) {
  return getJson(`${DETECTION_ENGINE_BASE_URL}/alerts/${alertId}`);
}

export async function fetchMitigationActions(userId) {
  return getJson(`${MITIGATION_BASE_URL}/actions?user_id=${encodeURIComponent(userId)}`);
}

export function cefExportUrl(alertId) {
  return `${DETECTION_ENGINE_BASE_URL}/alerts/${alertId}/cef`;
}

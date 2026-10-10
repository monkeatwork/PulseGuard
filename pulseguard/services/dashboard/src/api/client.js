// Every call goes through the dashboard's own origin; nginx proxies /api/*
// to the four services (services/dashboard/nginx.conf).
const BASE = "/api";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: options.body ? { "content-type": "application/json" } : undefined,
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* not JSON */
    }
    throw new Error(`${path}: ${detail}`);
  }
  const type = res.headers.get("content-type") || "";
  return type.includes("json") ? res.json() : res.text();
}

const q = encodeURIComponent;

export const api = {
  health: (svc) => request(`/${svc}/health`),
  alerts: (params = "") => request(`/detection/alerts?limit=200${params}`),
  alert: (id) => request(`/detection/alerts/${q(id)}`),
  setAlertStatus: (id, status) => request(`/detection/alerts/${q(id)}`, { method: "PATCH", body: { status } }),
  cefUrl: (id) => `${BASE}/detection/alerts/${q(id)}/cef`,
  stats: () => request(`/detection/stats`),
  recentScores: (limit = 60, userId) => request(`/detection/scores/recent?limit=${limit}${userId ? `&user_id=${q(userId)}` : ""}`),
  operatingPoint: () => request(`/detection/operating-point`),
  evalResults: () => request(`/detection/eval/results`),
  deadLetters: () => request(`/detection/dead-letters`),
  baseline: (userId) => request(`/features/baselines/${q(userId)}`),
  actions: (userId) => request(`/mitigation/actions?limit=100${userId ? `&user_id=${q(userId)}` : ""}`),
  controllerState: (userId) => request(`/mitigation/state/${q(userId)}`),
  scenarios: (profile) => request(`/ingestion/scenarios?limit=200${profile ? `&profile=${q(profile)}` : ""}`),
  replay: (body) => request(`/ingestion/scenarios/replay`, { method: "POST", body }),
  runs: () => request(`/ingestion/runs?limit=40`),
  stopRun: (id) => request(`/ingestion/runs/${q(id)}/stop`, { method: "POST" }),
  startSim: (body) => request(`/ingestion/simulator`, { method: "POST", body }),
  sim: (id) => request(`/ingestion/simulator/${q(id)}`),
  simRespond: (id, decision) => request(`/ingestion/simulator/${q(id)}/respond`, { method: "POST", body: { decision } }),
  simLogin: (id) => request(`/ingestion/simulator/${q(id)}/login`, { method: "POST" }),
  simStop: (id) => request(`/ingestion/simulator/${q(id)}/stop`, { method: "POST" }),
  challenges: (userId) => request(`/ingestion/idp/challenges?limit=50${userId ? `&user_id=${q(userId)}` : ""}`),
  resolveChallenge: (id, passed) => request(`/ingestion/idp/challenges/${q(id)}/resolve`, { method: "POST", body: { passed } }),
};

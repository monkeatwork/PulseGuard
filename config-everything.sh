#!/usr/bin/env bash
# One-time setup after cloning: checks Docker, writes .env, pulls and builds
# every image, and verifies the trained models load. Safe to re-run.
source "$(dirname "$0")/scripts/common.sh"

say "Checking Docker"
require_docker
ok "$(docker --version)"
mem_bytes="$(docker info --format '{{.MemTotal}}' 2>/dev/null || echo 0)"
mem_mb=$(( mem_bytes / 1024 / 1024 ))
if [ "$mem_mb" -gt 0 ] && [ "$mem_mb" -lt 1400 ]; then
  warn "Docker has ${mem_mb} MB of memory; PulseGuard needs about 1.0-1.3 GB. Raise it in Docker Desktop > Settings > Resources if containers get killed."
else
  ok "Docker memory: ${mem_mb} MB"
fi

say "Writing configuration"
if [ ! -f .env ]; then cp .env.example .env; ok "created pulseguard/.env"; else ok "pulseguard/.env already exists (kept)"; fi
port="$(dashboard_port)"
if (command -v lsof >/dev/null && lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1); then
  warn "Port $port is in use. Set PULSEGUARD_PORT to a free port in pulseguard/.env."
fi

say "Checking trained models and demo data"
for f in services/detection_engine/app/model_registry/{operating_point.json,stage_b.json,stage_b_calibrator.pkl,stage_c.npz} data/demo/demo_events.parquet; do
  [ -f "$f" ] || die "missing $f (it ships with the repository - is the clone complete?)"
done
ok "models and demo corpus present"

say "Pulling base images (first run downloads ~1 GB)"
"${COMPOSE[@]}" pull --ignore-buildable postgres redis kafka

say "Building PulseGuard images"
"${COMPOSE[@]}" build

say "Self-test: the detector loads its evaluated operating point"
"${COMPOSE[@]}" run --rm --no-deps -e LIVE_SCORER=off detection_engine \
  python -c "from services.detection_engine.app.live_scorer import LiveScorer; s=LiveScorer(); w=s.weights; print(f'operating point: weights=({w.weight_a:.2f}, {w.weight_b:.2f}, {w.weight_c:.2f}) threshold={s.threshold:.2f}')"

ok "Everything is configured. Start PulseGuard with ./run.sh"

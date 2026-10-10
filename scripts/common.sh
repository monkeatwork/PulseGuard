# Shared helpers for config-everything.sh / run.sh / stop.sh (sourced).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$ROOT/pulseguard"
cd "$APP"

COMPOSE=(docker compose -f docker-compose.yml)
# Only for build machines behind a TLS-intercepting proxy; never needed on a laptop.
if [ -n "${PULSEGUARD_EXTRA_CA:-}" ]; then COMPOSE+=(-f docker-compose.ca.yml); fi

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m ok\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m  !\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mERR\033[0m %s\n' "$*" >&2; exit 1; }

require_docker() {
  command -v docker >/dev/null 2>&1 || die "Docker is not installed. Install Docker Desktop: https://docs.docker.com/get-docker/"
  docker info >/dev/null 2>&1 || die "Docker is installed but not running. Start Docker Desktop and try again."
  docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is missing (it ships with Docker Desktop)."
}

dashboard_port() {
  local port="3000"
  if [ -f .env ]; then port="$(grep -E '^PULSEGUARD_PORT=' .env | tail -1 | cut -d= -f2 || true)"; fi
  echo "${PULSEGUARD_PORT:-${port:-3000}}"
}

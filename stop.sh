#!/usr/bin/env bash
# Stops and removes every PulseGuard container, network and data volume.
# Built images are kept so the next ./run.sh starts quickly.
source "$(dirname "$0")/scripts/common.sh"
require_docker

say "Stopping PulseGuard"
"${COMPOSE[@]}" down --volumes --remove-orphans
left="$(docker ps -a --filter label=com.docker.compose.project=pulseguard -q)"
[ -z "$left" ] || docker rm -f $left >/dev/null
ok "All PulseGuard containers, networks and volumes are gone."

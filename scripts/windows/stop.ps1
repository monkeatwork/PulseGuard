# Stops and removes every PulseGuard container, network and data volume.
# Built images are kept so the next .\run starts quickly.
. (Join-Path $PSScriptRoot 'common.ps1')
Require-Docker

Say 'Stopping PulseGuard'
Compose down --volumes --remove-orphans
$left = docker ps -a --filter label=com.docker.compose.project=pulseguard -q
if ($left) { docker rm -f $left *> $null }
Ok 'All PulseGuard containers, networks and volumes are gone.'

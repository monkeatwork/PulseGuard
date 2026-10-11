# Starts PulseGuard from a clean slate every time: any previous run's
# containers AND data are removed first, then the stack is started and
# waited on until every service is healthy.
. (Join-Path $PSScriptRoot 'common.ps1')
Require-Docker

Say 'Clearing any previous run'
Quiet docker compose @ComposeFiles down --volumes --remove-orphans

Say 'Starting PulseGuard (fresh database, fresh Kafka, fresh baselines)'
try {
  Compose up -d --build --wait --wait-timeout 300
} catch {
  & docker compose @ComposeFiles ps
  Die 'Some services did not become healthy. Logs: docker compose -f pulseguard\docker-compose.yml logs <service>'
}
Compose ps --format 'table {{.Service}}\t{{.Status}}'

$url = "http://localhost:$(Dashboard-Port)"
Ok "PulseGuard is running: $url"
Write-Host '    Stop everything with .\stop'
try { Start-Process $url } catch { }

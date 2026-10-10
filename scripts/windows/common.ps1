# Shared helpers for the Windows scripts (dot-sourced).
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$App = Join-Path $Root 'pulseguard'
Set-Location $App

$ComposeFiles = @('-f', 'docker-compose.yml')
if ($env:PULSEGUARD_EXTRA_CA) { $ComposeFiles += @('-f', 'docker-compose.ca.yml') }

function Say($m)  { Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host " ok $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  ! $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "ERR $m" -ForegroundColor Red; exit 1 }

# A simple (non-advanced) function on purpose: every argument, including
# ones like "-e", lands in $args untouched instead of being parsed as a
# PowerShell common parameter (-ErrorAction, ...).
function Compose {
  & docker compose @ComposeFiles @args
  if ($LASTEXITCODE -ne 0) { throw "docker compose $($args -join ' ') failed (exit $LASTEXITCODE)" }
}

function Require-Docker {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Die 'Docker is not installed. Install Docker Desktop: https://docs.docker.com/desktop/install/windows-install/'
  }
  docker info *> $null
  if ($LASTEXITCODE -ne 0) { Die 'Docker is installed but not running. Start Docker Desktop, wait for "Engine running", then try again.' }
  docker compose version *> $null
  if ($LASTEXITCODE -ne 0) { Die 'Docker Compose v2 is missing (it ships with Docker Desktop).' }
}

function Dashboard-Port {
  if ($env:PULSEGUARD_PORT) { return $env:PULSEGUARD_PORT }
  if (Test-Path '.env') {
    $line = Get-Content '.env' | Where-Object { $_ -match '^PULSEGUARD_PORT=' } | Select-Object -Last 1
    if ($line) { return ($line -split '=', 2)[1].Trim() }
  }
  return '3000'
}

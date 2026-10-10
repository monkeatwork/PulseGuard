# One-time setup after cloning: checks Docker, writes .env, pulls and builds
# every image, and verifies the trained models load. Safe to re-run.
. (Join-Path $PSScriptRoot 'common.ps1')

Say 'Checking Docker'
Require-Docker
Ok (docker --version)
$memBytes = [int64](docker info --format '{{.MemTotal}}')
$memMb = [math]::Floor($memBytes / 1MB)
if ($memMb -gt 0 -and $memMb -lt 1400) {
  Warn "Docker has $memMb MB of memory; PulseGuard needs about 1.0-1.3 GB. Raise it in Docker Desktop > Settings > Resources (or .wslconfig) if containers get killed."
} else { Ok "Docker memory: $memMb MB" }

Say 'Writing configuration'
if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env'; Ok 'created pulseguard\.env' } else { Ok 'pulseguard\.env already exists (kept)' }
$port = Dashboard-Port
try {
  if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
    Warn "Port $port is in use. Set PULSEGUARD_PORT to a free port in pulseguard\.env."
  }
} catch { }

Say 'Checking trained models and demo data'
$required = @(
  'services\detection_engine\app\model_registry\operating_point.json',
  'services\detection_engine\app\model_registry\stage_b.json',
  'services\detection_engine\app\model_registry\stage_b_calibrator.pkl',
  'services\detection_engine\app\model_registry\stage_c.npz',
  'data\demo\demo_events.parquet'
)
foreach ($f in $required) { if (-not (Test-Path $f)) { Die "missing $f (it ships with the repository - is the clone complete?)" } }
Ok 'models and demo corpus present'

Say 'Pulling base images (first run downloads ~1 GB)'
Compose pull --ignore-buildable postgres redis kafka

Say 'Building PulseGuard images'
Compose build

Say 'Self-test: the detector loads its evaluated operating point'
Compose run --rm --no-deps -e LIVE_SCORER=off detection_engine python -c "from services.detection_engine.app.live_scorer import LiveScorer; s=LiveScorer(); w=s.weights; print(f'operating point: weights=({w.weight_a:.2f}, {w.weight_b:.2f}, {w.weight_c:.2f}) threshold={s.threshold:.2f}')"

Ok 'Everything is configured. Start PulseGuard with .\run'

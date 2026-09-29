<#
.SYNOPSIS
  Start HelpMate for development. Each service opens in its own window so you can read its log.

.EXAMPLE
  ./scripts/dev.ps1              # API :8000 + speech :8001 + web :5173 (adapters from .env; fakes by default)
  ./scripts/dev.ps1 -Mock        # web only, MSW mocks in the browser, no backend at all
  ./scripts/dev.ps1 -Infra       # also start Postgres + SeaweedFS (Docker)
  ./scripts/dev.ps1 -Prod        # build the web app; FastAPI serves it on :8000 (what Tailscale points at)
  ./scripts/dev.ps1 -NoSpeech    # skip the speech service

  If Windows blocks the script: powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
#>
param(
  [switch]$Mock,
  [switch]$Infra,
  [switch]$Prod,
  [switch]$NoSpeech
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path "$root\.env")) {
  Copy-Item "$root\.env.example" "$root\.env"
  Write-Host "Created .env from .env.example (all fakes)." -ForegroundColor Yellow
}

function Open-ServiceWindow([string]$title, [string]$dir, [string]$command) {
  $script = "`$host.UI.RawUI.WindowTitle = '$title'; Set-Location '$dir'; $command"
  Start-Process powershell -ArgumentList "-NoExit", "-Command", $script | Out-Null
  Write-Host "  started $title"
}

if ($Infra) {
  docker compose --env-file "$root\.env" -f "$root\infra\docker-compose.yml" up -d
}

if ($Mock) {
  Open-ServiceWindow "HelpMate web (mock) :5173" "$root\web" "npm run dev:mock"
  Write-Host "`nOpen http://127.0.0.1:5173 (MSW mocks, no backend)" -ForegroundColor Green
  return
}

if ($Prod) {
  Push-Location "$root\web"
  try { npm run build } finally { Pop-Location }
  $env:HELPMATE_SERVE_WEB = "1"   # inherited by the API window below
}

Open-ServiceWindow "HelpMate API :8000" "$root\backend" "uv run helpmate-api"
if (-not $NoSpeech) {
  Open-ServiceWindow "HelpMate speech :8001" "$root\services\speech" "uv run helpmate-speech"
}
if ($Prod) {
  Write-Host "`nOpen http://127.0.0.1:8000 (production build served by FastAPI)" -ForegroundColor Green
} else {
  Open-ServiceWindow "HelpMate web :5173" "$root\web" "npm run dev"
  Write-Host "`nOpen http://127.0.0.1:5173   (API health: http://127.0.0.1:8000/api/health)" -ForegroundColor Green
}

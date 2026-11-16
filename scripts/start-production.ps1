# Production-like local run: build the frontend once, then serve UI and API from one
# process on http://127.0.0.1:8000 (no dev servers, same mode as the root Dockerfile).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venvPy = if ($env:OS -eq "Windows_NT") { Join-Path $root "backend/.venv/Scripts/python.exe" } else { Join-Path $root "backend/.venv/bin/python" }
$py = $venvPy
if (-not (Test-Path $py)) { throw "Run scripts/setup.ps1 first." }

Push-Location "$root/frontend"; npm run build; if ($LASTEXITCODE) { throw "Frontend build failed." }; Pop-Location
$env:FRONTEND_DIST = "$root/frontend/dist"
Push-Location "$root/backend"
& $py -m alembic upgrade head; if ($LASTEXITCODE) { throw "Database migration failed." }
Write-Host "Serving on http://127.0.0.1:8000  (Ctrl+C to stop)" -ForegroundColor Cyan
& $py -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2
Pop-Location

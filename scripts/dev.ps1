# Start the backend (http://127.0.0.1:8000) and the frontend dev server (http://localhost:5173)
# in two new PowerShell windows. Close the windows to stop them.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venvPy = if ($env:OS -eq "Windows_NT") { Join-Path $root "backend/.venv/Scripts/python.exe" } else { Join-Path $root "backend/.venv/bin/python" }
$py = $venvPy
if (-not (Test-Path $py)) { throw "Run scripts/setup.ps1 first." }

# Bring the database up to date first (safe to run every time; it only applies new migrations).
Push-Location (Join-Path $root "backend")
try {
    & $py -m alembic upgrade head
    if ($LASTEXITCODE) { throw "Database migration failed." }
} finally { Pop-Location }

Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "Set-Location '$root/backend'; & '$py' -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "Set-Location '$root/frontend'; npm run dev"

Write-Host "Backend:  http://127.0.0.1:8000/api/docs"
Write-Host "Frontend: http://localhost:5173   (opening in a few seconds)"
Start-Sleep -Seconds 4
Start-Process "http://localhost:5173"

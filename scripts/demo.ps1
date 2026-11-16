# Run DataBridge locally in PUBLIC DEMO MODE, exactly as a public visitor would see it.
#   * shared, read-only SAMPLE data is loaded automatically on start-up
#   * each browser only sees its own uploads; uploads are deleted after 24 hours
#   * 10 MB / 50,000-row upload limits, rate limits
# Uses a separate database and data folder (backend/data/demo), so your normal local data is untouched.
#   powershell -ExecutionPolicy Bypass -File scripts\demo.ps1
# Close the two windows to stop it.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = if ($env:OS -eq "Windows_NT") { Join-Path $root "backend/.venv/Scripts/python.exe" } else { Join-Path $root "backend/.venv/bin/python" }
if (-not (Test-Path $py)) { throw "Run scripts/setup.ps1 first." }

$demoDir = Join-Path $root "backend/data/demo"
New-Item -ItemType Directory -Force -Path $demoDir | Out-Null
$dbUrl = "sqlite:///" + ((Join-Path $demoDir "databridge-demo.db") -replace "\\", "/")
$envCmd = "`$env:DEMO_MODE='true'; `$env:DATA_DIR='$demoDir'; `$env:DATABASE_URL='$dbUrl'; `$env:AI_PROVIDER='none'"

$env:DEMO_MODE = "true"; $env:DATA_DIR = $demoDir; $env:DATABASE_URL = $dbUrl
Push-Location (Join-Path $root "backend")
try {
    & $py -m alembic upgrade head
    if ($LASTEXITCODE) { throw "Database migration failed." }
} finally { Pop-Location }

Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "$envCmd; Set-Location '$root/backend'; & '$py' -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "Set-Location '$root/frontend'; npm run dev"

Write-Host "Demo mode starting. The sample data is prepared on the first start (a few seconds)."
Write-Host "Frontend: http://localhost:5173"
Start-Sleep -Seconds 8
Start-Process "http://localhost:5173"

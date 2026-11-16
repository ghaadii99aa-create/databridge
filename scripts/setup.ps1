# DataBridge — one-time local setup on Windows (PowerShell 5.1+ or PowerShell 7).
# Run from the databridge folder:   powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Check($step) { if ($LASTEXITCODE -ne 0) { throw "$step failed (exit code $LASTEXITCODE). See the output above." } }
function Require($cmd, $hint) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "$cmd was not found. $hint" }
}
Require python "Install Python 3.11-3.13 from https://www.python.org/downloads/ and tick 'Add python.exe to PATH'."
Require npm "Install Node.js 20 or 22 LTS from https://nodejs.org/."

$pyver = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ([version]$pyver -lt [version]"3.11" -or [version]$pyver -ge [version]"3.14") {
    throw "Python $pyver found; DataBridge needs Python 3.11, 3.12 or 3.13."
}
Write-Host "Python $pyver, Node $(node --version)" -ForegroundColor DarkGray

Write-Host "`n[1/5] Creating Python virtual environment (backend\.venv)" -ForegroundColor Green
if (-not (Test-Path backend/.venv)) { python -m venv backend/.venv; Check "Creating the virtual environment" }
$venvPy = if ($env:OS -eq "Windows_NT") { Join-Path $root "backend/.venv/Scripts/python.exe" } else { Join-Path $root "backend/.venv/bin/python" }
$py = $venvPy
& $py -m pip install --upgrade pip --quiet; Check "Upgrading pip"

Write-Host "[2/5] Installing backend dependencies" -ForegroundColor Green
& $py -m pip install -r backend/requirements-dev.txt --quiet; Check "Installing backend dependencies"

Write-Host "[3/5] Preparing configuration" -ForegroundColor Green
if (-not (Test-Path backend/.env)) {
    Copy-Item backend/.env.example backend/.env
    Write-Host "      Created backend/.env (SQLite by default; edit it to use PostgreSQL)."
}
if (-not (Test-Path sample_data/retail_sales_sample.csv)) { & $py scripts/generate_sample_data.py; Check "Generating sample data" }

Write-Host "[4/5] Applying database migrations" -ForegroundColor Green
Push-Location backend
& $py -m alembic upgrade head; Check "Database migration"
Pop-Location

Write-Host "[5/5] Installing frontend dependencies" -ForegroundColor Green
Push-Location frontend
npm ci --no-audit --no-fund; Check "Installing frontend dependencies"
Pop-Location

Write-Host "`nSetup complete. Start the app with:  powershell -ExecutionPolicy Bypass -File scripts/dev.ps1" -ForegroundColor Cyan

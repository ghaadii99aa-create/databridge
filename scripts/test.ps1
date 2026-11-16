# Run all automated tests. Pass -Postgres "<url>" to also run the backend suite on PostgreSQL, e.g.
#   scripts/test.ps1 -Postgres "postgresql+psycopg://databridge:PASSWORD@localhost:5432/databridge_test"
param([string]$Postgres = "")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venvPy = if ($env:OS -eq "Windows_NT") { Join-Path $root "backend/.venv/Scripts/python.exe" } else { Join-Path $root "backend/.venv/bin/python" }
$py = $venvPy

Write-Host "Backend tests (SQLite)" -ForegroundColor Green
Push-Location "$root/backend"; & $py -m pytest -q; $backend = $LASTEXITCODE
if ($Postgres) {
    Write-Host "Backend tests (PostgreSQL)" -ForegroundColor Green
    $env:TEST_DATABASE_URL = $Postgres; & $py -m pytest -q; $backend = $backend -bor $LASTEXITCODE
    Remove-Item Env:\TEST_DATABASE_URL
}
Pop-Location

Write-Host "Frontend type check and tests" -ForegroundColor Green
Push-Location "$root/frontend"; npm run typecheck; $tc = $LASTEXITCODE; npm test; $fe = $LASTEXITCODE; Pop-Location

if ($backend -or $tc -or $fe) { Write-Host "Some checks failed." -ForegroundColor Red; exit 1 }
Write-Host "All checks passed." -ForegroundColor Cyan

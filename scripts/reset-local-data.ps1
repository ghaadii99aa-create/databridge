# Delete the local SQLite database and stored files, then recreate an empty schema.
# Asks for confirmation. Does not touch PostgreSQL or Docker volumes.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$data = Join-Path $root "backend/data"
$venvPy = if ($env:OS -eq "Windows_NT") { Join-Path $root "backend/.venv/Scripts/python.exe" } else { Join-Path $root "backend/.venv/bin/python" }
$answer = Read-Host "Delete everything in $data ? Type yes to continue"
if ($answer -ne "yes") { Write-Host "Cancelled."; exit 0 }
if (Test-Path $data) { Remove-Item -Recurse -Force $data }
Push-Location "$root/backend"; & $venvPy -m alembic upgrade head; Pop-Location
Write-Host "Local data reset." -ForegroundColor Cyan

# Starts THE HOST's backend: the FastAPI app and the Gemini Live agent, on
# http://127.0.0.1:8000 (GET / is a one-line status page; THE HOST runs on /display).
#
# Reads no configuration itself. The backend loads backend/.env on its own, and
# nothing here ever prints or echoes it.

$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $repo ".venv\Scripts\Activate.ps1"
$backend = Join-Path $repo "backend"

if (-not (Test-Path $venv)) {
    Write-Error "No virtual environment at .venv. Create one first: python -m venv .venv"
    exit 1
}

Write-Host "Activating .venv" -ForegroundColor DarkGray
& $venv

Set-Location $backend
Write-Host "THE HOST backend on http://127.0.0.1:8000/ -- Ctrl+C to stop" -ForegroundColor Green
python -m uvicorn main:app --host 127.0.0.1 --port 8000

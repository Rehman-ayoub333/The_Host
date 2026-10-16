# Runs the full backend test suite. It must run from backend/, because the
# tests import the backend's own modules by name.
#
# Reads no configuration itself, and never prints or echoes any .env file.
# Any extra arguments are passed straight through to pytest.

$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo ".venv\Scripts\python.exe"
$backend = Join-Path $repo "backend"

if (-not (Test-Path $python)) {
    Write-Error "No virtual environment at .venv. Create one first: python -m venv .venv"
    exit 1
}

Set-Location $backend
& $python -m pytest @args
exit $LASTEXITCODE

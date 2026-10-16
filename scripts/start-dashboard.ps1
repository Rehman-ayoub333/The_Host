# Starts the operator dashboard and the public display (TanStack Start, run
# with bun). Installs the dependencies first if they are missing.
#
# Reads no configuration itself, and never prints or echoes any .env file.

$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$dashboard = Join-Path $repo "dashboard"

if (-not (Get-Command bun -ErrorAction SilentlyContinue)) {
    Write-Error "bun is not on PATH. Install it from https://bun.sh and try again."
    exit 1
}

Set-Location $dashboard

if (-not (Test-Path (Join-Path $dashboard "node_modules"))) {
    Write-Host "node_modules is missing -- running bun install" -ForegroundColor DarkGray
    bun install
    if ($LASTEXITCODE -ne 0) {
        Write-Error "bun install failed."
        exit $LASTEXITCODE
    }
}

Write-Host "Dashboard starting -- Ctrl+C to stop" -ForegroundColor Green
bun run dev

# Starts the operator dashboard and the public display (TanStack Start, built
# with bun). At the gala this is the PRODUCTION build: it starts in about a
# second instead of the development server's cold compile, and it serves the
# production React build rather than on-demand transforms (16 section 2r item
# 3). The address stays http://localhost:8080 and the dashboard behaves exactly
# as before.
#
# -Dev keeps the old development server (`bun run dev`) for everyday work.
#
# Reads no configuration itself, and never prints or echoes any .env file.

[CmdletBinding()]
param([switch]$Dev)

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

if ($Dev) {
    Write-Host "Dashboard starting -- DEVELOPMENT server, not for the gala -- Ctrl+C to stop" -ForegroundColor Yellow
    bun run dev
    exit $LASTEXITCODE
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Error "node is not on PATH, and the production dashboard runs on it. Install Node.js, or start with -Dev."
    exit 1
}

# Nitro's zero-config target detection honours NITRO_PRESET, so the node server
# is pinned here rather than in the dashboard's own config. Without it `bun run
# build` emits a Cloudflare Workers bundle, whose entry exports a fetch handler
# and cannot be started on this laptop at all.
$env:NITRO_PRESET = "node-server"

$output = Join-Path $dashboard ".output"
$marker = Join-Path $output "nitro.json"
$sourceDir = Join-Path $dashboard "src"
$entry = Join-Path $output "server\index.mjs"

$needsBuild = $false
$reason = ""

if (-not (Test-Path $marker)) {
    $needsBuild = $true
    $reason = ".output is missing"
} else {
    $builtAt = (Get-Item $marker).LastWriteTime
    $newer = Get-ChildItem $sourceDir -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -gt $builtAt } |
        Select-Object -First 1
    if ($newer) {
        $needsBuild = $true
        $reason = "$($newer.Name) under src is newer than the build"
    } elseif (-not (Test-Path $entry)) {
        $needsBuild = $true
        $reason = "the build has no server entry"
    } else {
        # A build left behind for a different target cannot be started here, so
        # for this script's purposes it is no build at all.
        $preset = ""
        try {
            $preset = (Get-Content $marker -Raw | ConvertFrom-Json).preset
        } catch {
            $preset = ""
        }
        if ($preset -ne "node-server") {
            $needsBuild = $true
            $reason = "the existing build targets '$preset', not a local server"
        }
    }
}

if ($needsBuild) {
    Write-Host "Building the dashboard -- $reason" -ForegroundColor DarkGray
    bun run build
    if ($LASTEXITCODE -ne 0) {
        Write-Error "bun run build failed."
        exit $LASTEXITCODE
    }
} else {
    Write-Host "The dashboard build is up to date" -ForegroundColor DarkGray
}

if (-not (Test-Path $entry)) {
    Write-Error "The build did not produce .output\server\index.mjs, so there is nothing to start."
    exit 1
}

$env:PORT = "8080"
Write-Host "Dashboard on http://localhost:8080/ (production) -- Ctrl+C to stop" -ForegroundColor Green
node $entry
exit $LASTEXITCODE

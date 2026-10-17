# One command that answers "is the stall ready?" (16 section 2q item 3).
#
# Prints one PASS / FAIL / WARN line per check, then a summary, and exits 1 if
# any check FAILed. A WARN never fails the run: it is something to look at, not
# something that stops the gala.
#
# It reads no configuration: backend/.env is only tested for EXISTENCE, never
# opened, and no operator token is read, sent or printed. Every request it makes
# is to an endpoint that needs no token.

$repo = Split-Path -Parent $PSScriptRoot
$script:fails = 0
$script:warns = 0
$script:passes = 0

function Report {
    param([string]$Status, [string]$Name, [string]$Detail = "")
    switch ($Status) {
        "PASS" { $colour = "Green";  $script:passes++ }
        "WARN" { $colour = "Yellow"; $script:warns++ }
        default { $colour = "Red";   $script:fails++ }
    }
    $line = "{0,-5} {1}" -f $Status, $Name
    if ($Detail) { $line = "$line  --  $Detail" }
    Write-Host $line -ForegroundColor $colour
}

Write-Host ""
Write-Host "THE HOST -- preflight" -ForegroundColor Cyan
Write-Host ("-" * 68) -ForegroundColor DarkGray

# ----------------------------------------------------------------- the laptop

$python = Join-Path $repo ".venv\Scripts\python.exe"
if (Test-Path $python) { Report "PASS" "Python virtual environment" ".venv\Scripts\python.exe" }
else { Report "FAIL" "Python virtual environment" "no .venv\Scripts\python.exe -- python -m venv .venv" }

# Existence only. The file is never opened and its contents are never read.
$envFile = Join-Path $repo "backend\.env"
if (Test-Path $envFile) { Report "PASS" "backend\.env present" "existence only; never opened" }
else { Report "FAIL" "backend\.env present" "copy backend\.env.example to backend\.env and fill it in" }

$bun = Get-Command bun -ErrorAction SilentlyContinue
if ($bun) { Report "PASS" "bun on PATH" $bun.Source }
else { Report "FAIL" "bun on PATH" "install bun, or open a new terminal" }

$nodeModules = Join-Path $repo "dashboard\node_modules"
if (Test-Path $nodeModules) { Report "PASS" "dashboard dependencies" "dashboard\node_modules" }
else { Report "FAIL" "dashboard dependencies" "run: bun install  (in dashboard)" }

# ---------------------------------------------------------------- the internet

# Any HTTP answer means the network reaches Google. The status code does not
# matter: an unauthenticated request is expected to be refused, and a refusal
# still proves reachability. No key and no token is sent.
try {
    $response = Invoke-WebRequest -Uri "https://generativelanguage.googleapis.com" `
        -Method Get -TimeoutSec 8 -UseBasicParsing -ErrorAction Stop
    Report "PASS" "Internet to the AI service" "HTTP $([int]$response.StatusCode)"
} catch {
    $status = $null
    if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
    if ($status) { Report "PASS" "Internet to the AI service" "HTTP $status" }
    else { Report "FAIL" "Internet to the AI service" "no answer within 8 s -- check wi-fi or switch to the hotspot" }
}

# ----------------------------------------------------------------- the backend

$health = $null
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 8 -ErrorAction Stop
    Report "PASS" "Backend answering" "http://127.0.0.1:8000/health"
} catch {
    Report "FAIL" "Backend answering" "no answer -- run scripts\start-backend.ps1"
}

if ($health) {
    if ($health.status -eq "ok") { Report "PASS" "Backend status" "ok" }
    else { Report "FAIL" "Backend status" "status=$($health.status)" }

    if ($health.components.ai_agent -eq "online") { Report "PASS" "AI agent" "online" }
    else { Report "FAIL" "AI agent" "ai_agent=$($health.components.ai_agent)" }

    if ($health.components.database -eq "ok") { Report "PASS" "Database" "ok" }
    else { Report "FAIL" "Database" "database=$($health.components.database)" }

    if ([int]$health.menu_items -gt 0) { Report "PASS" "Menu loaded" "$([int]$health.menu_items) items" }
    else { Report "FAIL" "Menu loaded" "menu_items=0 -- the stall must never open without a menu" }

    if ($health.operational_mode -eq "ONLINE") { Report "PASS" "Operational mode" "ONLINE" }
    else { Report "WARN" "Operational mode" "$($health.operational_mode) -- resume THE HOST from the dashboard" }
} else {
    Report "FAIL" "Backend status"     "backend not answering"
    Report "FAIL" "AI agent"           "backend not answering"
    Report "FAIL" "Database"           "backend not answering"
    Report "FAIL" "Menu loaded"        "backend not answering"
    Report "WARN" "Operational mode"   "backend not answering"
}

# GET /api/menu needs no token.
try {
    $menu = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/menu" -TimeoutSec 8 -ErrorAction Stop
    $count = @($menu.menu).Count
    if ($count -ge 1) { Report "PASS" "Menu endpoint" "$count items" }
    else { Report "FAIL" "Menu endpoint" "the menu came back empty" }
} catch {
    Report "FAIL" "Menu endpoint" "GET /api/menu did not answer"
}

try {
    $booth = Invoke-WebRequest -Uri "http://127.0.0.1:8000/" -TimeoutSec 8 -UseBasicParsing -ErrorAction Stop
    if ([int]$booth.StatusCode -eq 200) { Report "PASS" "Voice page" "HTTP 200 at http://127.0.0.1:8000/" }
    else { Report "FAIL" "Voice page" "HTTP $([int]$booth.StatusCode)" }
} catch {
    Report "FAIL" "Voice page" "the voice page did not answer"
}

# --------------------------------------------------------------- the dashboard

try {
    $dash = Invoke-WebRequest -Uri "http://localhost:8080/" -TimeoutSec 8 -UseBasicParsing -ErrorAction Stop
    Report "PASS" "Dashboard" "HTTP $([int]$dash.StatusCode) at http://localhost:8080/"
} catch {
    Report "WARN" "Dashboard" "not running -- run scripts\start-dashboard.ps1"
}

# ---------------------------------------------------------------- the hardware

try {
    $drive = (Get-Item $repo).PSDrive
    $freeGb = [math]::Round($drive.Free / 1GB, 1)
    if ($freeGb -ge 1) { Report "PASS" "Free disk space" "$freeGb GB on $($drive.Name):" }
    else { Report "WARN" "Free disk space" "$freeGb GB on $($drive.Name): -- under 1 GB" }
} catch {
    Report "WARN" "Free disk space" "could not be measured"
}

# -------------------------------------------------------------------- summary

Write-Host ("-" * 68) -ForegroundColor DarkGray
$summary = "$script:passes passed, $script:fails failed, $script:warns warnings"
if ($script:fails -gt 0) {
    Write-Host "NOT READY  --  $summary" -ForegroundColor Red
    exit 1
}
if ($script:warns -gt 0) {
    Write-Host "READY, with warnings  --  $summary" -ForegroundColor Yellow
    exit 0
}
Write-Host "READY  --  $summary" -ForegroundColor Green
exit 0

# Starts the gala with an empty database (16 section 2q item 2).
#
# The live database is never deleted: it is copied to backend/data/backups/,
# and then the live file itself is MOVED there too, so the backend finds no
# database at startup and builds a fresh, empty one (its init_db creates every
# table and seeds the menu and the stall information from backend/data/).
#
# Backups are never removed by this script.
# It reads no configuration: backend/.env is never opened, and no operator
# token is read, asked for or printed.

$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$dataDir = Join-Path $repo "backend\data"
$live = Join-Path $dataDir "the_host.db"
$backupDir = Join-Path $dataDir "backups"

# 1. The backend must not be holding the database open.
$listening = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($listening) {
    Write-Host "Stop the backend first." -ForegroundColor Red
    exit 1
}

# 2. A deliberate, typed confirmation.
Write-Host ""
Write-Host "This starts the gala with an empty database." -ForegroundColor Yellow
Write-Host "The current database is kept as a backup, never deleted." -ForegroundColor DarkGray
Write-Host ""
$answer = Read-Host "Type RESET to start the gala with an empty database"
if ($answer -cne "RESET") {
    Write-Host "Nothing was changed." -ForegroundColor DarkGray
    exit 0
}

New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"

if (Test-Path $live) {
    $copy = Join-Path $backupDir "the_host-$stamp.db"
    $moved = Join-Path $backupDir "the_host-$stamp-replaced.db"

    Copy-Item -Path $live -Destination $copy
    Write-Host ""
    Write-Host "Backup copy   : $copy" -ForegroundColor Green

    Move-Item -Path $live -Destination $moved
    Write-Host "Live file kept: $moved" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "There was no database to back up; the next start creates one." -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Start the backend: it creates a fresh, empty database." -ForegroundColor Cyan
exit 0

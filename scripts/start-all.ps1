# Starts the backend and the dashboard together, each in its own window, so
# both can be watched and stopped independently.
#
# Reads no configuration itself, and never prints or echoes any .env file.

$ErrorActionPreference = "Stop"

$backendScript = Join-Path $PSScriptRoot "start-backend.ps1"
$dashboardScript = Join-Path $PSScriptRoot "start-dashboard.ps1"

Write-Host "Opening the backend window" -ForegroundColor Green
Start-Process powershell -ArgumentList @(
    "-NoExit", "-ExecutionPolicy", "Bypass", "-File", $backendScript
)

Write-Host "Opening the dashboard window" -ForegroundColor Green
Start-Process powershell -ArgumentList @(
    "-NoExit", "-ExecutionPolicy", "Bypass", "-File", $dashboardScript
)

Write-Host ""
Write-Host "Backend:        http://127.0.0.1:8000/" -ForegroundColor Cyan
Write-Host "Dashboard:      http://localhost:8080/" -ForegroundColor Cyan
Write-Host "Display screen: http://localhost:8080/display" -ForegroundColor Cyan
Write-Host "Close either window to stop that half." -ForegroundColor DarkGray

# Opens the TV's browser for THE HOST (16 section 2zf item 8(e)).
#
# The display screen is a full-screen Chrome window on the second monitor, with
# no tabs, no address bar and nothing a guest could press. It uses a profile of
# its own under the repository (.display-profile, git-ignored), so the camera
# and microphone permission is granted ONCE, the first time, and every later
# start is silent -- and so is every reload, which is what makes the
# dashboard's "Reload display screen" button work without anybody walking over.
#
# -X is the left edge of the second screen. The default 1920 is a 1920-wide
# laptop screen with the TV to the right of it; use -X 0 to open it on the
# laptop itself while testing.
#
# Reads no configuration, and never prints or echoes any .env file.

[CmdletBinding()]
param(
    [int]$X = 1920,
    [string]$Url = "http://localhost:8080/display"
)

$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$profileDir = Join-Path $repo ".display-profile"

$chrome = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $chrome) {
    Write-Error "Google Chrome was not found. Install it, or open $Url by hand."
    exit 1
}

if (-not (Test-Path $profileDir)) {
    New-Item -ItemType Directory -Path $profileDir | Out-Null
    Write-Host "Made a new browser profile for the TV at .display-profile" -ForegroundColor DarkGray
    Write-Host "The first start will ask once for the camera and microphone -- allow both." -ForegroundColor Yellow
}

# --kiosk is the full screen with no controls; --autoplay-policy lets the page
# start its own audio, so the TV never shows "Tap to begin" after a reload
# (16 section 2zf item 8(d)).
$arguments = @(
    "--kiosk",
    "--autoplay-policy=no-user-gesture-required",
    "--user-data-dir=$profileDir",
    "--window-position=$X,0",
    $Url
)

Write-Host "Opening the display screen at $Url on the screen starting at x=$X" -ForegroundColor Green
Write-Host "Press Alt+F4 on that window to close it." -ForegroundColor DarkGray
Start-Process -FilePath $chrome -ArgumentList $arguments

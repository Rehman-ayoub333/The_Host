# Stops both halves of THE HOST: whatever is listening on port 8000 (the
# backend) and on 8080 (the dashboard, which serves the display screen).
#
# 16 section 2x item 4(d): closing the two windows start-all.ps1 opens does NOT
# stop the servers -- the python and node processes they launched keep the ports
# open, which is how the 7h check found an old backend still answering. This
# script stops the processes themselves.
#
# Reads no configuration itself: backend/.env is never opened, and no operator
# token is read, asked for or printed.

$ErrorActionPreference = "Stop"

foreach ($port in 8000, 8080) {
    $listening = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    if (-not $listening) {
        Write-Host "nothing listening on $port" -ForegroundColor DarkGray
        continue
    }
    foreach ($id in ($listening | ForEach-Object { $_.OwningProcess } | Sort-Object -Unique)) {
        $process = Get-Process -Id $id -ErrorAction SilentlyContinue
        if (-not $process) {
            Write-Host "nothing listening on $port" -ForegroundColor DarkGray
            continue
        }
        $name = $process.ProcessName
        try {
            Stop-Process -Id $id -Force -ErrorAction Stop
            Write-Host "stopped $name (pid $id) on $port" -ForegroundColor Green
        } catch {
            Write-Host "could not stop $name (pid $id) on $port" -ForegroundColor Red
        }
    }
}

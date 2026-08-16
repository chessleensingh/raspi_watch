# Shuts everything down cleanly.
#
#   .\scripts\stop_all.ps1
#
# Closes the windows rather than killing them, which matters more than it
# sounds: Chromium writes cookies to disk on a clean shutdown, and force-killing
# it discards whatever is still in memory. That is how a working YouTube sign-in
# was thrown away once already -- the browser looked signed in, and the next
# launch had never heard of it.
#
# Force is still the fallback, because a hung browser should not need a reboot.

param(
    [int]$Port = 8000
)

$profiles = @("ti_watchtest_profile", "ti_viewer_profile", "ti_scoreboard_profile")

function Get-OurBrowsers {
    Get-CimInstance Win32_Process |
        Where-Object { $_.Name -in @("brave.exe", "chrome.exe", "msedge.exe") } |
        Where-Object { $cl = $_.CommandLine; $profiles | Where-Object { $cl -like "*$_*" } }
}

$browsers = Get-OurBrowsers
if ($browsers) {
    Write-Output "Closing $(($browsers | Measure-Object).Count) browser process(es)..."
    foreach ($p in $browsers) {
        $h = Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue
        if ($h -and $h.MainWindowHandle -ne 0) { $null = $h.CloseMainWindow() }
    }

    $closed = $false
    foreach ($i in 1..15) {
        Start-Sleep -Seconds 1
        if (-not (Get-OurBrowsers)) { $closed = $true; break }
    }

    if (-not $closed) {
        Write-Warning "Some windows did not close on their own; forcing them."
        Get-OurBrowsers | ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
} else {
    Write-Output "No viewer or scoreboard windows were open."
}

$serverPid = (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue).OwningProcess
if ($serverPid) {
    Stop-Process -Id $serverPid -Force -ErrorAction SilentlyContinue
    Write-Output "Stopped the scoreboard server (pid $serverPid)."
} else {
    Write-Output "No server was listening on port $Port."
}

Write-Output ""
Write-Output "Done. Start again with:  .\scripts\start_all.ps1"

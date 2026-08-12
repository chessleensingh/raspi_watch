# Starts the scoreboard and opens it fullscreen on the secondary display.
#
# Run this on the Windows box each day. Without --start-fullscreen the taskbar
# clips the bottom row of tiles.
#
# Usage:  .\scripts\open_scoreboard.ps1
#         .\scripts\open_scoreboard.ps1 -NoServer   # server already running

param(
    [switch]$NoServer,
    [int]$Port = 8000,
    [string]$Browser = ""
)

Add-Type -AssemblyName System.Windows.Forms

$root = Split-Path $PSScriptRoot -Parent

if (-not $NoServer) {
    Start-Process python -ArgumentList "-m", "scoreboard.server" -WorkingDirectory $root
    Start-Sleep -Seconds 5
}

try {
    $null = Invoke-WebRequest "http://127.0.0.1:$Port/api/games" -UseBasicParsing -TimeoutSec 10
} catch {
    Write-Error "Scoreboard server is not answering on port $Port. Start it with: python -m scoreboard.server"
    exit 1
}

# Prefer a second display; fall back to the primary if only one is attached.
$screen = [System.Windows.Forms.Screen]::AllScreens | Where-Object { -not $_.Primary } | Select-Object -First 1
if (-not $screen) {
    $screen = [System.Windows.Forms.Screen]::PrimaryScreen
    Write-Warning "No secondary display found; opening on the primary."
}
$b = $screen.Bounds

# Brave first by preference. All of these are Chromium, so the flags below are
# identical across them.
$candidates = @(
    "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    "$env:LOCALAPPDATA\BraveSoftware\Brave-Browser\Application\brave.exe",
    "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "C:\Program Files\Google\Chrome\Application\chrome.exe"
)
if ($Browser) { $candidates = @($Browser) + $candidates }

$browser = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $browser) { Write-Error "No Brave, Edge or Chrome found."; exit 1 }

# --app strips the browser chrome; --start-fullscreen then fills the display the
# window was positioned on, so the taskbar stops clipping the bottom tiles.
Start-Process $browser -ArgumentList @(
    "--new-window",
    "--app=http://localhost:$Port",
    "--window-position=$($b.X),$($b.Y)",
    "--window-size=$($b.Width),$($b.Height)",
    "--start-fullscreen"
)

Write-Output "Scoreboard opened in $(Split-Path $browser -Leaf) on $($screen.DeviceName) ($($b.Width)x$($b.Height) at $($b.X),$($b.Y))"
Write-Output "Press F11 in the window if it did not go fullscreen. Alt+F4 to close."

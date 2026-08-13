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
#
# --user-data-dir is not optional here either: Chromium applies flags only to
# the process that starts, so with a browser already running the window opens
# from that process and --start-fullscreen is silently ignored. Its own profile
# directory forces its own process, and keeps this off your everyday browsing.
$profileDir = Join-Path $env:LOCALAPPDATA "ti_scoreboard_profile"

# A browser that was killed rather than closed leaves SingletonLock/Cookie/Socket
# behind. The next launch sees them, tries to hand the URL to an instance that is
# no longer alive, and exits without ever loading the page -- a window may even
# appear, but nothing is requested from the server. Clearing them is safe: this
# profile directory is used by nothing else.
if (Test-Path $profileDir) {
    Get-ChildItem -Path $profileDir -Filter "Singleton*" -Force -ErrorAction SilentlyContinue |
        Remove-Item -Force -Recurse -ErrorAction SilentlyContinue
}

# NOT --start-fullscreen, for the same reason open_viewer.ps1 avoids it:
# Chromium fullscreens on whichever display the window manager placed the window
# on, which is not reliably the one --window-position asked for. The scoreboard
# then fullscreens over the main screen, invisible behind the viewer, while
# still running perfectly -- so it looks like it never opened.
Start-Process $browser -ArgumentList @(
    "--user-data-dir=$profileDir",
    "--new-window",
    "--app=http://localhost:$Port",
    "--window-position=$($b.X),$($b.Y)",
    "--window-size=$($b.Width),$($b.Height)",
    "--no-first-run",
    "--no-default-browser-check"
)

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class WinSb {
  [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr h, int x, int y, int w, int t, bool repaint);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
}
"@

$handle = [IntPtr]::Zero
foreach ($attempt in 1..40) {
    Start-Sleep -Milliseconds 500
    $window = Get-Process brave -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowTitle -and $_.MainWindowHandle -ne 0 } |
        Sort-Object StartTime -Descending | Select-Object -First 1
    if ($window) { $handle = $window.MainWindowHandle; break }
}

if ($handle -ne [IntPtr]::Zero) {
    [void][WinSb]::MoveWindow($handle, $b.X, $b.Y, $b.Width, $b.Height, $true)
    [void][WinSb]::SetForegroundWindow($handle)
    Start-Sleep -Milliseconds 400
    [System.Windows.Forms.SendKeys]::SendWait("{F11}")
} else {
    Write-Warning "Could not find the scoreboard window to position it. Drag it to the small screen and press F11."
}

Write-Output "Scoreboard opened in $(Split-Path $browser -Leaf) on $($screen.DeviceName) ($($b.Width)x$($b.Height) at $($b.X),$($b.Y))"
Write-Output "Alt+F4 to close."

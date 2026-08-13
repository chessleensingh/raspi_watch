# Opens the stream viewer fullscreen on the MAIN screen.
#
# Companion to open_scoreboard.ps1, which takes the small second screen. Run
# that one first: it starts the server this page talks to.
#
# Usage:  .\scripts\open_viewer.ps1
#         .\scripts\open_viewer.ps1 -Display 2   # if it picks the wrong screen

param(
    [int]$Port = 8000,
    [int]$Display = 0,
    [string]$Browser = ""
)

Add-Type -AssemblyName System.Windows.Forms

try {
    $null = Invoke-WebRequest "http://127.0.0.1:$Port/api/viewer" -UseBasicParsing -TimeoutSec 10
} catch {
    Write-Error "Scoreboard server is not answering on port $Port. Start it with: python -m scoreboard.server"
    exit 1
}

$screens = [System.Windows.Forms.Screen]::AllScreens
if ($Display -gt 0) {
    if ($Display -gt $screens.Count) {
        Write-Error "No display $Display; $($screens.Count) attached."
        exit 1
    }
    $screen = $screens[$Display - 1]
} else {
    # The primary display is the big one -- the opposite of the scoreboard,
    # which deliberately takes the secondary.
    $screen = [System.Windows.Forms.Screen]::PrimaryScreen
}
$b = $screen.Bounds

$candidates = @(
    "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    "$env:LOCALAPPDATA\BraveSoftware\Brave-Browser\Application\brave.exe",
    "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "C:\Program Files\Google\Chrome\Application\chrome.exe"
)
if ($Browser) { $candidates = @($Browser) + $candidates }

$browser = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $browser) { Write-Error "No Brave, Edge or Chrome found."; exit 1 }

# --user-data-dir is what makes the rest of these flags work at all.
#
# Chromium applies command-line flags only to the process that STARTS. Launch a
# URL while a browser is already running and the existing process just opens a
# window, silently ignoring every flag below -- so --autoplay-policy is dropped,
# the four players never preload, and the screen sits black. A separate profile
# directory forces its own process, so the flags always apply.
#
# It also keeps this window away from your everyday browsing: no shared tabs, no
# shared session, and closing one does not disturb the other.
#
# --autoplay-policy: without it Chromium blocks the muted autoplay of streams
# the page has not been interacted with, and all four tiles sit black. Sound
# still needs the click on the page -- this only allows the silent preload.
$profileDir = Join-Path $env:LOCALAPPDATA "ti_viewer_profile"

Start-Process $browser -ArgumentList @(
    "--user-data-dir=$profileDir",
    "--new-window",
    "--app=http://localhost:$Port/viewer",
    "--window-position=$($b.X),$($b.Y)",
    "--window-size=$($b.Width),$($b.Height)",
    "--start-fullscreen",
    "--autoplay-policy=no-user-gesture-required",
    "--no-first-run",
    "--no-default-browser-check"
)

Write-Output "Viewer opened in $(Split-Path $browser -Leaf) on $($screen.DeviceName) ($($b.Width)x$($b.Height) at $($b.X),$($b.Y))"
Write-Output "Click once on the page to turn sound on. Keys: 1-4 pick a stream, M mute, F fullscreen."

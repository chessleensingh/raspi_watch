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
    [string]$Browser = "",
    # Cookie stores are encrypted per browser: a profile signed in with Brave is
    # not readable by Chrome, which then launches signed OUT while looking
    # identical. So the profile has to follow the browser.
    #
    # The name is historical -- this directory started as a throwaway test of
    # whether a plain watch page would play. It is the one that carries the
    # working YouTube sign-in, and renaming it risks the sign-in it exists for,
    # so it keeps the awkward name.
    [string]$Profile = "ti_watchtest_profile"
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

# Chrome FIRST here, unlike the scoreboard.
#
# YouTube refuses to play these live streams in Brave even with that profile
# signed in -- presumably its fingerprinting defences -- while the same streams
# play in signed-in Chrome. The scoreboard loads no third-party video and stays
# on Brave quite happily.
$candidates = @(
    "C:\Program Files\Google\Chrome\Application\chrome.exe",
    "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    "$env:LOCALAPPDATA\BraveSoftware\Brave-Browser\Application\brave.exe"
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
$profileLeaf = $Profile
$profileDir = Join-Path $env:LOCALAPPDATA $profileLeaf

# NOT --start-fullscreen. Chromium fullscreens on whichever display the window
# manager happened to place the window on, and on a fresh profile that is not
# reliably the one --window-position asked for -- the viewer landed on the small
# screen. So: open windowed, move the window ourselves, and only then fullscreen
# it, by which point "whichever display it is on" is the right one.
# A browser that was killed rather than closed leaves SingletonLock/Cookie/Socket
# behind. The next launch sees them, tries to hand the URL to an instance that is
# no longer alive, and exits without ever loading the page -- a window may even
# appear, but nothing is requested from the server. Clearing them is safe: this
# profile directory is used by nothing else.
if (Test-Path $profileDir) {
    Get-ChildItem -Path $profileDir -Filter "Singleton*" -Force -ErrorAction SilentlyContinue |
        Remove-Item -Force -Recurse -ErrorAction SilentlyContinue
}

$proc = # NOTE the quotes around the path. This machine's profile directory contains
# a space, and an unquoted --user-data-dir is split at it: Brave sees a
# nonsense path, silently falls back to the DEFAULT profile, and hands the URL
# to whatever Brave is already running. Every symptom of that is misleading --
# flags ignored, window on the wrong screen, the process untrackable and
# unkillable by profile -- and none of them point at quoting.
Start-Process $browser -PassThru -ArgumentList @(
    "--user-data-dir=`"$profileDir`"",
    "--new-window",
    "--app=http://localhost:$Port/viewer",
    "--window-position=$($b.X),$($b.Y)",
    "--window-size=$($b.Width),$($b.Height)",
    "--autoplay-policy=no-user-gesture-required",
    "--no-first-run",
    "--no-default-browser-check"
)

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win {
  [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr h, int x, int y, int w, int t, bool repaint);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
}
"@

# Brave forks; the window belongs to whichever process wins, so poll for it.
# Find OUR window, not merely the newest one with a title.
#
# Picking the newest Brave window is wrong whenever the two launchers run close
# together: the second one starts while the first window is still the newest, so
# the scoreboard grabs the VIEWER's window and moves it to the small screen and
# fullscreens it there. Matching on the profile directory in the command line
# makes each script only ever touch the window it started.
$handle = [IntPtr]::Zero
foreach ($attempt in 1..40) {
    Start-Sleep -Milliseconds 500
    $ourPids = (Get-CimInstance Win32_Process |
                Where-Object { $_.Name -in @("brave.exe", "chrome.exe", "msedge.exe") } |
                Where-Object { $_.CommandLine -like "*$profileLeaf*" }).ProcessId
    if (-not $ourPids) { continue }
    $window = Get-Process -Id $ourPids -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowTitle -and $_.MainWindowHandle -ne 0 } |
        Select-Object -First 1
    if ($window) { $handle = $window.MainWindowHandle; break }
}

if ($handle -ne [IntPtr]::Zero) {
    [void][Win]::MoveWindow($handle, $b.X, $b.Y, $b.Width, $b.Height, $true)
    [void][Win]::SetForegroundWindow($handle)
    Start-Sleep -Milliseconds 400
    # F11 now fullscreens onto the display the window actually sits on.
    [System.Windows.Forms.SendKeys]::SendWait("{F11}")
} else {
    Write-Warning "Could not find the viewer window to position it. Drag it to the main screen and press F11."
}

Write-Output "Viewer opened in $(Split-Path $browser -Leaf) on $($screen.DeviceName) ($($b.Width)x$($b.Height) at $($b.X),$($b.Y))"
Write-Output "Click once on the page to turn sound on. Keys: 1-4 pick a stream, M mute, F fullscreen."

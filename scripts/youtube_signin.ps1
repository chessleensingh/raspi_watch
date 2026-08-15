# Signs the VIEWER's browser profile in to YouTube, and CONFIRMS it stuck.
#
#   .\scripts\youtube_signin.ps1
#
# Why this is needed: the viewer runs in its own profile with no cookies and no
# history, then opens four live embeds at once. That is a fair description of a
# bot, and YouTube answers it with "Sign in to confirm you're not a bot" where
# the video should be.
#
# Why it did not stick the first time: Chromium writes cookies on a CLEAN
# shutdown, and the restart script was force-killing the browser. A sign-in made
# minutes earlier was discarded before it ever reached disk, which is invisible
# -- you sign in, it works, and the next launch has never heard of you. This
# script watches the cookie file and tells you when the sign-in is actually
# safe, rather than leaving you to guess.

param(
    [string]$Browser = "",
    [string]$Url = "https://www.youtube.com/",
    [int]$WaitMinutes = 10
)

$profileLeaf = "ti_viewer_profile"
$profileDir = Join-Path $env:LOCALAPPDATA $profileLeaf
$cookieFile = Join-Path $profileDir "Default\Network\Cookies"

function Get-ViewerProcesses {
    Get-CimInstance Win32_Process -Filter "Name='brave.exe'" |
        Where-Object { $_.CommandLine -like "*$profileLeaf*" }
}

# The viewer holds this profile's lock while running, so a second launch against
# it would just be handed to the running instance.
$running = Get-ViewerProcesses
if ($running) {
    Write-Output "Closing the viewer first (it holds this profile)..."
    foreach ($p in $running) {
        $h = Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue
        if ($h -and $h.MainWindowHandle -ne 0) { $null = $h.CloseMainWindow() }
    }
    foreach ($i in 1..15) {
        Start-Sleep -Seconds 1
        if (-not (Get-ViewerProcesses)) { break }
    }
    Get-ViewerProcesses | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}

if (Test-Path $profileDir) {
    Get-ChildItem -Path $profileDir -Filter "Singleton*" -Force -ErrorAction SilentlyContinue |
        Remove-Item -Force -Recurse -ErrorAction SilentlyContinue
}

$before = if (Test-Path $cookieFile) { (Get-Item $cookieFile).LastWriteTime } else { [datetime]::MinValue }

$candidates = @(
    "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    "$env:LOCALAPPDATA\BraveSoftware\Brave-Browser\Application\brave.exe",
    "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "C:\Program Files\Google\Chrome\Application\chrome.exe"
)
if ($Browser) { $candidates = @($Browser) + $candidates }
$browser = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $browser) { Write-Error "No Brave, Edge or Chrome found."; exit 1 }

# A normal window, not --app: the sign-in flow needs an address bar and tabs.
# The path is quoted because this profile lives under a home directory with a
# space in it, and unquoted it splits -- silently signing in to the DEFAULT
# profile instead, which looks like the sign-in simply never worked.
Start-Process $browser -ArgumentList @(
    "--user-data-dir=`"$profileDir`"",
    "--new-window",
    "--no-first-run",
    "--no-default-browser-check",
    $Url
)

Write-Output ""
Write-Output "A normal browser window is opening on the VIEWER's profile."
Write-Output "  1. Sign in to YouTube."
Write-Output "  2. Play any video for a few seconds, so YouTube sets its cookies."
Write-Output "  3. CLOSE THE WINDOW NORMALLY (Alt+F4 or the X). Do not leave it open."
Write-Output ""
Write-Output "Waiting for the cookies to be written to disk..."

$deadline = (Get-Date).AddMinutes($WaitMinutes)
$confirmed = $false
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 5
    if (Test-Path $cookieFile) {
        $now = (Get-Item $cookieFile).LastWriteTime
        # Only counts once the browser has exited: cookies live in memory until
        # a clean shutdown flushes them, so a newer timestamp while it is still
        # running proves nothing about what survives.
        if ($now -gt $before -and -not (Get-ViewerProcesses)) {
            $confirmed = $true
            break
        }
    }
}

Write-Output ""
if ($confirmed) {
    Write-Output "CONFIRMED: cookies written at $((Get-Item $cookieFile).LastWriteTime)."
    Write-Output "The sign-in will survive restarts. Now run:"
    Write-Output "    .\scripts\start_all.ps1 -Restart"
} else {
    Write-Warning "Not confirmed. Either the window is still open, or nothing was saved."
    Write-Warning "Close the browser window normally and re-run this script to check."
    exit 1
}

# Opens the VIEWER's browser profile as a normal window, so you can sign in to
# YouTube once.
#
#   .\scripts\youtube_signin.ps1
#
# Why this is needed: the viewer runs in its own throwaway-looking profile with
# no cookies and no history, and then opens four live embeds at once. That is a
# good description of a bot, and YouTube answers it with "Sign in to confirm
# you're not a bot" instead of video.
#
# Signing in here fixes it for good, because the profile directory persists --
# start_all.ps1 -Restart only stops processes, it does not delete profiles.
# Deleting C:\Users\<you>\AppData\Local\ti_viewer_profile undoes this.
#
# Nothing about this touches your everyday browser: it is a separate profile
# that only the viewer uses.

param(
    [string]$Browser = "",
    [string]$Url = "https://www.youtube.com/"
)

$profileLeaf = "ti_viewer_profile"
$profileDir = Join-Path $env:LOCALAPPDATA $profileLeaf

# The viewer holds the profile lock while running; a second instance against the
# same directory would be handed to it and open nothing useful.
$running = Get-CimInstance Win32_Process -Filter "Name='brave.exe'" |
    Where-Object { $_.CommandLine -like "*$profileLeaf*" }
if ($running) {
    Write-Output "Closing the viewer first (it holds this profile)..."
    $running | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    foreach ($i in 1..20) {
        Start-Sleep -Seconds 1
        $left = (Get-CimInstance Win32_Process -Filter "Name='brave.exe'" |
                 Where-Object { $_.CommandLine -like "*$profileLeaf*" } | Measure-Object).Count
        if ($left -eq 0) { break }
    }
}

if (Test-Path $profileDir) {
    Get-ChildItem -Path $profileDir -Filter "Singleton*" -Force -ErrorAction SilentlyContinue |
        Remove-Item -Force -Recurse -ErrorAction SilentlyContinue
}

$candidates = @(
    "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    "$env:LOCALAPPDATA\BraveSoftware\Brave-Browser\Application\brave.exe",
    "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "C:\Program Files\Google\Chrome\Application\chrome.exe"
)
if ($Browser) { $candidates = @($Browser) + $candidates }
$browser = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $browser) { Write-Error "No Brave, Edge or Chrome found."; exit 1 }

# A normal window, not --app: you need the address bar and the sign-in flow.
# Quoted path -- this profile directory sits under a home directory containing a
# space, and unquoted it is split, silently falling back to the default profile
# and signing you in to the wrong one entirely.
Start-Process $browser -ArgumentList @(
    "--user-data-dir=`"$profileDir`"",
    "--new-window",
    "--no-first-run",
    "--no-default-browser-check",
    $Url
)

Write-Output ""
Write-Output "A normal browser window is opening on the viewer's profile."
Write-Output "  1. Sign in to YouTube (or just browse a video for a minute)."
Write-Output "  2. Close that window."
Write-Output "  3. Run:  .\scripts\start_all.ps1 -Restart"
Write-Output ""
Write-Output "The sign-in persists; it only goes away if the profile directory is deleted."

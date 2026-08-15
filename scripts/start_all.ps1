# Brings the whole setup up, and CHECKS it came up.
#
#   .\scripts\start_all.ps1          # real Valve data
#   .\scripts\start_all.ps1 -Demo    # invented games, for testing the clicks
#   .\scripts\start_all.ps1 -Restart # kill what is running first
#
# The check is the point. A browser window can open, sit there looking correct,
# and never load the page -- which happened repeatedly during TI's first round
# and is indistinguishable from a working screen until you try to use it. The
# server log settles it: a live viewer polls ~2/second, a live scoreboard
# ~1 every 3 seconds. Zero means the page never started.

param(
    [switch]$Demo,
    [switch]$Restart,
    [int]$Port = 8000
)

$root = Split-Path $PSScriptRoot -Parent
$log = Join-Path $env:TEMP "ti_server.err"

function Get-ServerPid {
    (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue).OwningProcess
}

function Stop-BrowsersGracefully($patterns) {
    # CloseMainWindow, not Stop-Process -Force.
    #
    # Chromium writes cookies to disk on a CLEAN shutdown. Force-killing it
    # discards whatever is still in memory -- which silently threw away a
    # YouTube sign-in made minutes earlier, and made the bot check look
    # unfixable. Force is still the fallback, because a hung browser must not
    # block a restart during a match.
    $procs = Get-CimInstance Win32_Process -Filter "Name='brave.exe'" |
        Where-Object { $cl = $_.CommandLine; $patterns | Where-Object { $cl -like "*$_*" } }
    if (-not $procs) { return }

    foreach ($p in $procs) {
        $handle = Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue
        if ($handle -and $handle.MainWindowHandle -ne 0) { $null = $handle.CloseMainWindow() }
    }

    foreach ($i in 1..12) {
        Start-Sleep -Seconds 1
        $left = (Get-CimInstance Win32_Process -Filter "Name='brave.exe'" |
                 Where-Object { $cl = $_.CommandLine; $patterns | Where-Object { $cl -like "*$_*" } } |
                 Measure-Object).Count
        if ($left -eq 0) { return }
    }

    Get-CimInstance Win32_Process -Filter "Name='brave.exe'" |
        Where-Object { $cl = $_.CommandLine; $patterns | Where-Object { $cl -like "*$_*" } } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}

function Count-Requests($pattern) {
    if (-not (Test-Path $log)) { return 0 }
    (Get-Content $log -ErrorAction SilentlyContinue | Select-String $pattern | Measure-Object).Count
}

if ($Restart) {
    $existing = Get-ServerPid
    if ($existing) { Stop-Process -Id $existing -Force; Write-Output "stopped server $existing" }
    # Closes cleanly and waits. Relaunching while the browser is still shutting
    # down leaves a fresh lock behind and the next window loads nothing.
    Stop-BrowsersGracefully @("ti_viewer_profile", "ti_scoreboard_profile")
}

if (-not (Get-ServerPid)) {
    $serverArgs = @("-m", "scoreboard.server")
    if ($Demo) { $serverArgs += "--demo" }
    Start-Process python -ArgumentList $serverArgs -WorkingDirectory $root `
        -RedirectStandardOutput (Join-Path $env:TEMP "ti_server.log") `
        -RedirectStandardError $log -WindowStyle Minimized
    foreach ($i in 1..20) {
        Start-Sleep -Seconds 1
        if (Get-ServerPid) { break }
    }
}

if (-not (Get-ServerPid)) {
    Write-Error "Server did not start. Last lines of ${log}:"
    Get-Content $log -Tail 15 -ErrorAction SilentlyContinue
    exit 1
}
Write-Output "server up on port $Port$(if ($Demo) { '  (DEMO - games are invented)' })"

& (Join-Path $PSScriptRoot "open_viewer.ps1") -Port $Port | Out-Null
Start-Sleep -Seconds 3
& (Join-Path $PSScriptRoot "open_scoreboard.ps1") -NoServer -Port $Port | Out-Null

# Measure repeatedly rather than once. A cold profile -- the first launch after
# the directory is deleted -- can take most of a minute to paint a page, and a
# single early sample calls that a failure when it is merely slow. Keep
# sampling until both look alive, or until it is genuinely too long to be
# waiting on startup.
$viewer = 0
$board = 0
foreach ($round in 1..6) {
    $v1 = Count-Requests "GET /api/viewer"
    $g1 = Count-Requests "GET /api/games"
    Start-Sleep -Seconds 9
    $viewer = (Count-Requests "GET /api/viewer") - $v1
    $board = (Count-Requests "GET /api/games") - $g1
    if ($viewer -ge 1 -and $board -ge 2) { break }
    if ($round -lt 6) { Write-Output "  still starting up (viewer $viewer, scoreboard $board)..." }
}

Write-Output ""
# A live viewer in the foreground polls ~18 per 9s. Behind another window
# Chromium throttles its timers hard, down to one or two -- still alive, still
# switching when you click. Only zero means the page never started, so that is
# the line the check draws. Reporting the rate as well keeps the difference
# visible rather than hidden behind a verdict.
$viewerVerdict = if ($viewer -ge 5) { "OK" } elseif ($viewer -ge 1) { "OK (throttled - window is behind another)" } else { "NOT LOADING" }
Write-Output "viewer     : $viewer requests in 9s  $viewerVerdict"
Write-Output "scoreboard : $board requests in 9s  $(if ($board -ge 2) { 'OK' } else { 'NOT LOADING' })"

if ($viewer -lt 1 -or $board -lt 2) {
    Write-Output ""
    Write-Warning "A page is not loading. Re-run with -Restart; if it persists, delete"
    Write-Warning "$env:LOCALAPPDATA\ti_viewer_profile and ti_scoreboard_profile."
    exit 1
}

Write-Output ""
Write-Output "Viewer keys: 1-4 stream, M mute, L sync to live, R reload streams, F fullscreen."

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

function Count-Requests($pattern) {
    if (-not (Test-Path $log)) { return 0 }
    (Get-Content $log -ErrorAction SilentlyContinue | Select-String $pattern | Measure-Object).Count
}

if ($Restart) {
    $existing = Get-ServerPid
    if ($existing) { Stop-Process -Id $existing -Force; Write-Output "stopped server $existing" }
    Get-CimInstance Win32_Process -Filter "Name='brave.exe'" |
        Where-Object { $_.CommandLine -like "*ti_viewer_profile*" -or $_.CommandLine -like "*ti_scoreboard_profile*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    # Wait for the browser to actually exit. Relaunching while it is still
    # shutting down leaves a fresh lock behind and the next window loads nothing.
    foreach ($i in 1..20) {
        Start-Sleep -Seconds 1
        $left = (Get-CimInstance Win32_Process -Filter "Name='brave.exe'" |
                 Where-Object { $_.CommandLine -like "*ti_viewer_profile*" -or $_.CommandLine -like "*ti_scoreboard_profile*" } |
                 Measure-Object).Count
        if ($left -eq 0) { break }
    }
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

# Give both pages time to load, then measure whether they are really talking.
Start-Sleep -Seconds 10
$v1 = Count-Requests "GET /api/viewer"
$g1 = Count-Requests "GET /api/games"
Start-Sleep -Seconds 9
$viewer = (Count-Requests "GET /api/viewer") - $v1
$board = (Count-Requests "GET /api/games") - $g1

Write-Output ""
Write-Output "viewer     : $viewer requests in 9s  $(if ($viewer -ge 5) { 'OK' } else { 'NOT LOADING' })"
Write-Output "scoreboard : $board requests in 9s  $(if ($board -ge 2) { 'OK' } else { 'NOT LOADING' })"

if ($viewer -lt 5 -or $board -lt 2) {
    Write-Output ""
    Write-Warning "A page is not loading. Re-run with -Restart; if it persists, delete"
    Write-Warning "$env:LOCALAPPDATA\ti_viewer_profile and ti_scoreboard_profile."
    exit 1
}

Write-Output ""
Write-Output "Viewer keys: 1-4 stream, M mute, R reload streams, F fullscreen."

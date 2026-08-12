# Opens an SSH tunnel to the wall's remote control on the Mac, so clicking a
# game on the scoreboard can switch which stream has audio.
#
# Why a tunnel rather than talking to the Mac directly: the macOS Application
# Firewall is enabled and only allows inbound connections for binaries on its
# list. /usr/local/bin/python3.12 is not on it, so connections to
# http://macbook-pro:8777 are accepted and then immediately dropped
# ("Socket is not connected" on the Mac side). Forwarding to 127.0.0.1 on the
# Mac avoids the firewall completely and leaves no port open to the network.
#
# Alternative, if you would rather not run a tunnel -- allow the binary once,
# on the Mac:
#
#   sudo /usr/libexec/ApplicationFirewall/socketfilterfw \
#        --add /usr/local/bin/python3.12 --unblockapp /usr/local/bin/python3.12
#
# then set [wall] url to http://macbook-pro:8777 instead.
#
# Usage:  .\scripts\wall_tunnel.ps1        (leave it running)
#         .\scripts\wall_tunnel.ps1 -Stop

param(
    [int]$Port = 8777,
    [string]$Host_ = "mac-ti",
    [switch]$Stop
)

$existing = Get-CimInstance Win32_Process -Filter "Name='ssh.exe'" |
            Where-Object { $_.CommandLine -like "*${Port}:127.0.0.1:${Port}*" }

if ($Stop) {
    if ($existing) {
        $existing | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
        Write-Output "tunnel closed"
    } else {
        Write-Output "no tunnel running"
    }
    exit 0
}

if ($existing) {
    Write-Output "tunnel already running (pid $($existing.ProcessId))"
} else {
    Start-Process ssh -ArgumentList "-N", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
                                    "-L", "${Port}:127.0.0.1:${Port}", $Host_ -WindowStyle Hidden
    Start-Sleep -Seconds 4
    Write-Output "tunnel opened: localhost:$Port -> ${Host_}:$Port"
}

try {
    $status = (Invoke-WebRequest "http://127.0.0.1:$Port/status" -UseBasicParsing -TimeoutSec 6).Content
    Write-Output "wall says: $status"
} catch {
    Write-Warning "Tunnel is up but the wall is not answering. Is wall.py running on the Mac?"
}

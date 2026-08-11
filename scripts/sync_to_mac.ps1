# Pushes the wall to the Mac over Tailscale.
#
# Why not scp/rsync/sftp: the Mac's shell rc prints a "Biostar command logging"
# banner on non-interactive sessions. All three of those tools speak a binary
# protocol over the same channel, and the banner corrupts it. Piping base64 over
# stdin is immune, because the banner lands on our terminal instead of the file.
#
# Two Windows-side gotchas, both confirmed with `od -c` on the receiving end:
#   1. Windows PowerShell 5.1 prepends a UTF-8 BOM (EF BB BF) to anything piped
#      to a native command. Setting [Console]::OutputEncoding does NOT stop it.
#   2. It appends CRLF.
# `tr -cd 'A-Za-z0-9+/='` keeps only base64 characters, dropping all three.
#
# Mostly superseded: the Mac now has a git clone at ~/raspi_watch, so
# `git -C ~/raspi_watch pull` is the normal way to update it. Use this only to
# push uncommitted work-in-progress you want to try on the TV before committing.
#
# Usage:  .\scripts\sync_to_mac.ps1

param(
    [string]$Src  = (Split-Path $PSScriptRoot -Parent),
    [string]$Host_ = "mac-ti",
    [string]$Dest = "raspi_watch"
)

$files = @("wall.py", "find_streams.py", "streams.toml")

# Mirrors the repo layout: files land in ~/ti_wall/wall/, not flat in ~/ti_wall.
# wall.py reads streams.toml relative to its OWN path, so flattening would make
# it read the wrong config -- or a stale duplicate.
ssh -o BatchMode=yes $Host_ "mkdir -p ~/$Dest/wall" | Out-Null

foreach ($name in $files) {
    $path = Join-Path $Src "wall\$name"
    if (-not (Test-Path $path)) { Write-Error "missing: $path"; continue }

    $b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($path))
    $b64 | ssh -o BatchMode=yes $Host_ "tr -cd 'A-Za-z0-9+/=' | base64 -D > ~/$Dest/wall/$name"
}

# Verify sizes rather than trusting the transfer: a silently truncated wall.py
# is much worse than a failed copy.
Write-Output "local:"
foreach ($name in $files) {
    Write-Output ("  {0,-18} {1,7}" -f $name, (Get-Item (Join-Path $Src "wall\$name")).Length)
}
Write-Output "remote:"
ssh -o BatchMode=yes $Host_ "cd ~/$Dest/wall && wc -c $($files -join ' ')"

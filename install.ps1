# gurt on Windows 🪟 — gurt runs inside WSL (Windows Subsystem for Linux), this sets it all up
# usage (PowerShell):  irm https://raw.githubusercontent.com/clrealy/GURT/main/install.ps1 | iex
#
# what it does:
#   1. no WSL yet? installs WSL + Ubuntu (asks for admin; Windows may want a reboot)
#   2. installs gurt inside your WSL distro (the normal install.sh)
#   3. puts a `gurt` command on your Windows PATH (gurt install firefox works from PowerShell/cmd)
#   4. adds GURT to your Start menu (the app opens through WSLg)
# pick a distro other than your default one with:  $env:GURT_WSL_DISTRO = "Debian"

function Install-Gurt {
  $ErrorActionPreference = 'Stop'
  $raw = if ($env:GURT_RAW) { $env:GURT_RAW } else { 'https://raw.githubusercontent.com/clrealy/GURT/main' }
  function Say($m)  { Write-Host "==> $m" -ForegroundColor Green }
  function Info($m) { Write-Host "  -> $m" }
  function Nah($m)  { Write-Host "==> nah: $m" -ForegroundColor Red }

  if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    Nah "this Windows doesn't have WSL — gurt needs Windows 10 (2004 or newer) or Windows 11"; return
  }
  $env:WSL_UTF8 = '1'   # newer WSL prints UTF-8 with this; older prints UTF-16, so nulls get stripped below
  $distros = @(& wsl.exe --list --quiet 2>$null | ForEach-Object { ($_ -replace "`0", '').Trim() } | Where-Object { $_ })

  if ($distros.Count -eq 0) {
    Say "you don't have a Linux distro in WSL yet — installing WSL + Ubuntu (Windows will ask for admin)"
    try {
      Start-Process wsl.exe -ArgumentList '--install', '-d', 'Ubuntu' -Verb RunAs -Wait
    } catch {
      Nah "couldn't start the WSL install ($($_.Exception.Message)) — run this in an admin PowerShell: wsl --install -d Ubuntu"; return
    }
    Say "WSL is installing 🐧 when it's done:"
    Info "reboot if Windows asks you to"
    Info "open 'Ubuntu' from the Start menu once and make your Linux username + password"
    Info "then run this again:  irm $raw/install.ps1 | iex"
    return
  }

  $distro = if ($env:GURT_WSL_DISTRO) { $env:GURT_WSL_DISTRO } else { '' }
  if ($distro -and $distros -notcontains $distro) { Nah "no WSL distro called '$distro' (you have: $($distros -join ', '))"; return }
  $pick = if ($distro) { @('-d', $distro) } else { @() }
  Say "installing gurt inside WSL$(if ($distro) { " ($distro)" } else { ' (your default distro)' }) — it may ask for your Linux password"
  & wsl.exe @pick -e bash -lc "command -v curl >/dev/null || { sudo apt-get update -qq && sudo apt-get install -y -qq curl git; }; curl -fsSL '$raw/install.sh' | sh"
  if ($LASTEXITCODE -ne 0) { Nah "gurt's Linux installer failed inside WSL (scroll up for why)"; return }

  # `gurt` on the Windows side → runs the real one in WSL
  $home_ = Join-Path $env:LOCALAPPDATA 'gurt'
  $bin = Join-Path $home_ 'bin'
  New-Item -ItemType Directory -Force -Path $bin | Out-Null
  $wslArgs = if ($distro) { "-d `"$distro`" " } else { '' }
  Set-Content -Path (Join-Path $bin 'gurt.cmd') -Encoding ASCII -Value "@echo off`r`nwsl.exe $($wslArgs)-e /usr/local/bin/gurt %*"
  $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
  if (($userPath -split ';') -notcontains $bin) {
    [Environment]::SetEnvironmentVariable('Path', ($(if ($userPath) { "$userPath;" } else { '' }) + $bin), 'User')
    Info "added $bin to your PATH (open a new terminal to use it)"
  }
  $env:Path = "$env:Path;$bin"

  # Start menu: GURT app
  try {
    $ico = Join-Path $home_ 'gurt.ico'
    Invoke-WebRequest -UseBasicParsing -Uri "$raw/site/favicon.ico" -OutFile $ico
    $lnk = Join-Path ([Environment]::GetFolderPath('Programs')) 'GURT.lnk'
    $sc = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
    $sc.TargetPath = (Get-Command wsl.exe).Source
    $sc.Arguments = "$($wslArgs)-e /usr/local/bin/gurt gui"
    $sc.IconLocation = $ico
    $sc.Description = "GURT — every distro's packages"
    $sc.WindowStyle = 7   # minimized: you see the app, not a console
    $sc.Save()
    Info "added GURT to your Start menu"
  } catch {
    Info "couldn't make the Start menu shortcut ($($_.Exception.Message)) — run: gurt gui"
  }

  Say "gurt is on Windows 🦆🪟"
  Info "open a new terminal, then:  gurt install firefox   (or: gurt gui)"
  Info "Linux apps you install show up in your Start menu (WSLg, Windows 11 or Windows 10 21H2+)"
}
Install-Gurt

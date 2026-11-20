# gurt on Windows: native. Windows apps come from winget / scoop / Chocolatey; Linux-only apps go to WSL, which gurt
# offers to set up the first time you ask for one (nothing about WSL happens here).
# usage (PowerShell):  irm https://raw.githubusercontent.com/clrealy/GURT/main/install.ps1 | iex
#   (GURTSetupWizard.exe runs this too, next to its own copies of gurt.ps1 and the app)
#
# what it does:
#   1. puts gurt (gurt.ps1 + a gurt.cmd) in %LOCALAPPDATA%\gurt\bin and on your PATH
#   2. puts GURT's app there too (gurt-app.exe) and in your Start menu
#   3. downloads Main GURT's app list
#   4. opens the GURT Setup Wizard

function Install-Gurt {
  $ErrorActionPreference = 'Stop'
  $raw = if ($env:GURT_RAW) { $env:GURT_RAW } else { 'https://raw.githubusercontent.com/clrealy/GURT/main' }
  $rel = if ($env:GURT_RELEASE) { $env:GURT_RELEASE } else { 'https://github.com/clrealy/GURT/releases/latest/download' }
  function Say($m)  { Write-Host "==> $m" -ForegroundColor Green }
  function Info($m) { Write-Host "  -> $m" }
  function Nah($m)  { Write-Host "==> nah: $m" -ForegroundColor Red }
  # next to this script (GURTSetupWizard.exe unpacks them there), else from the internet
  $here = if ($PSScriptRoot) { $PSScriptRoot } else { '' }
  function Get-File($name, $url, $to) {
    if ($here -and (Test-Path (Join-Path $here $name))) { Copy-Item -Force (Join-Path $here $name) $to; return $true }
    try { Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $to; return $true } catch { return $false }
  }

  $home_ = Join-Path $env:LOCALAPPDATA 'gurt'
  $bin = Join-Path $home_ 'bin'
  New-Item -ItemType Directory -Force -Path $bin | Out-Null

  Say 'installing gurt for Windows'
  if (-not (Get-File 'gurt.ps1' "$raw/gurt.ps1" (Join-Path $bin 'gurt.ps1'))) { Nah "couldn't get gurt.ps1"; throw 'gurt.ps1 missing' }
  # `gurt` from cmd and PowerShell alike
  Set-Content -Path (Join-Path $bin 'gurt.cmd') -Encoding ASCII -Value "@echo off`r`npowershell.exe -NoProfile -ExecutionPolicy Bypass -File `"%~dp0gurt.ps1`" %*"
  foreach ($m in 'packs.map', 'vibes.map') { $null = Get-File $m "$raw/$m" (Join-Path $home_ $m) }
  $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
  if (($userPath -split ';') -notcontains $bin) {
    [Environment]::SetEnvironmentVariable('Path', ($(if ($userPath) { "$userPath;" } else { '' }) + $bin), 'User')
    Info "added $bin to your PATH (open a new terminal to use it)"
  }
  $env:Path = "$env:Path;$bin"

  # GURT's app, native
  $app = Join-Path $bin 'gurt-app.exe'
  if (Get-File 'gurt-app.exe' "$rel/gurt-app-windows-x86_64.exe" $app) { Info "GURT's app is in $bin" }
  else { Info "couldn't get GURT's app (gurt works without it, from any terminal)" }
  $ico = Join-Path $home_ 'gurt.ico'
  $null = Get-File 'gurt.ico' "$raw/site/favicon.ico" $ico

  if (Test-Path $app) {
    try {
      $lnk = Join-Path ([Environment]::GetFolderPath('Programs')) 'GURT.lnk'
      $sc = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
      $sc.TargetPath = $app
      $sc.Arguments = "--gurt `"$(Join-Path $bin 'gurt.ps1')`""
      if (Test-Path $ico) { $sc.IconLocation = $ico }
      $sc.Description = 'GURT: every app, from wherever it is'
      $sc.Save()
      Info 'added GURT to your Start menu'
    } catch { Info "couldn't make the Start menu shortcut ($($_.Exception.Message)), run: gurt gui" }
  }

  Say "getting Main GURT's app list"
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $bin 'gurt.ps1') sync | Out-Host

  Say 'gurt is on Windows'
  if ((Test-Path $app) -and -not $env:GURT_NO_WIZARD) {
    Say 'opening the GURT Setup Wizard'
    Start-Process -FilePath $app -ArgumentList '--gurt', "`"$(Join-Path $bin 'gurt.ps1')`"", '--wizard'
  }
  Info 'open a new terminal, then:  gurt install firefox   (or: gurt gui)'
  Info 'apps that only exist for Linux go in WSL: gurt sets it up the first time you ask for one'
}
Install-Gurt

# gurt for Windows: native. Windows apps come from winget, then scoop, then Chocolatey. Apps that only exist for
# Linux go to WSL (gurt runs in there too, and offers to set WSL up the first time you need it).
#   gurt install firefox        winget -> scoop -> choco -> WSL, first one that has it
#   gurt install winget/Mozilla.Firefox  scoop/neovim  choco/7zip   one source on purpose
#   gurt install apt/cowsay  aur/yay  flatpak/org.gimp.GIMP          Linux sources: WSL
# It keeps its own list of what it installed in %LOCALAPPDATA%\gurt\db (gurt list / remove / upgrade use it).
# Plain ASCII on purpose: Windows PowerShell 5.1 reads a file without a BOM as ANSI.
$ErrorActionPreference = 'Stop'
$GURT_VERSION = '1.5.0'

$GHome  = if ($env:GURT_HOME) { $env:GURT_HOME } else { Join-Path $env:LOCALAPPDATA 'gurt' }
$Bin    = Join-Path $GHome 'bin'
$DB     = Join-Path $GHome 'db'
$Repo   = if ($env:GURT_REPO_DIR) { $env:GURT_REPO_DIR } else { Join-Path $GHome 'repo' }
$Cache  = Join-Path $GHome 'cache'
$RepoUrl = if ($env:GURT_REPO_URL) { $env:GURT_REPO_URL } else { 'https://github.com/clrealy/GURT' }
$Raw    = if ($env:GURT_RAW) { $env:GURT_RAW } else { 'https://raw.githubusercontent.com/clrealy/GURT/main' }
$Distro = if ($env:GURT_WSL_DISTRO) { $env:GURT_WSL_DISTRO } else { '' }
$WinSources = @('winget', 'scoop', 'choco')
# everything else gurt knows is Linux: WSL handles it
$LinuxSources = @('gurt', 'main', 'dirt', 'aur', 'apt', 'dnf', 'zypper', 'pacman', 'apk', 'xbps', 'eopkg', 'gentoo', 'flatpak',
  'snap', 'gh', 'pip', 'npm', 'cargo', 'appimage', 'brew', 'nix', 'android', 'git', 'file')
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { $null = $_ }
$Script:Yes = $false

function Say($m)  { Write-Host "==> $m" -ForegroundColor Green }
function Info($m) { Write-Host "  -> $m" }
function Warn($m) { Write-Host "==> heads up: $m" -ForegroundColor Yellow }
$Script:Multi = $false   # installing a few at once: one that fails skips to the next instead of stopping everything
function Die($m)  { Write-Host "==> nah: $m" -ForegroundColor Red; if ($Script:Multi) { throw "gurt: $m" }; exit 1 }
function Ask($q) {
  if ($Script:Yes) { return $true }
  if (-not [Environment]::UserInteractive -or [Console]::IsInputRedirected) { return $true }
  $a = Read-Host ":: $q [Y/n]"
  return ($a -eq '' -or $a -match '^[yY]')
}
function Have($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

# -- the list of what gurt installed: db\<source>@<id>\info ("key = value" lines, like gurt's db on Linux) --
function KeyDir($src, $id) { return Join-Path $DB ("$src@$id" -replace '[\\/:*?"<>|]', '_') }
function Record($src, $id, $ver, $desc, $recipe) {
  $d = KeyDir $src $id
  New-Item -ItemType Directory -Force -Path $d | Out-Null
  $lines = @("pkgname = $id", "pkgver = $(if ($ver) { $ver } else { 'latest' })", "pkgdesc = $desc", "gurtsource = $src")
  if ($recipe) { $lines += "recipe = $recipe" }
  Set-Content -Path (Join-Path $d 'info') -Value $lines -Encoding UTF8
  Set-Content -Path (Join-Path $d 'reason') -Value 'explicit' -Encoding ASCII
}
function InfoGet($file, $key) {
  if (-not (Test-Path $file)) { return '' }
  foreach ($l in Get-Content $file) { if ($l.StartsWith("$key = ")) { return $l.Substring($key.Length + 3) } }
  return ''
}
function Installed {
  if (-not (Test-Path $DB)) { return @() }
  return @(Get-ChildItem $DB -Directory | ForEach-Object {
    $src, $id = $_.Name -split '@', 2
    $f = Join-Path $_.FullName 'info'
    [pscustomobject]@{ Src = $src; Id = $id; Dir = $_.FullName; Ver = (InfoGet $f 'pkgver'); Desc = (InfoGet $f 'pkgdesc'); Recipe = (InfoGet $f 'recipe') }
  })
}

# -- Main GURT: the recipes, for their names + Windows pins (win_winget / win_scoop / win_choco) --
function Sync-Main {
  if (Have git) {
    if (Test-Path (Join-Path $Repo '.git')) { Say 'syncing main GURT repo'; & git -C $Repo pull -q --ff-only; return }
    if (Test-Path $Repo) { Remove-Item -Recurse -Force $Repo }
    Say "cloning main GURT repo from $RepoUrl"
    # just the recipes and the lists: the site has a folder too deep for Windows paths
    & git clone -q --depth 1 --filter=blob:none --sparse "$RepoUrl.git" $Repo
    & git -C $Repo sparse-checkout set packages dirt
    return
  }
  Say 'downloading main GURT (no git here, so the zip)'
  New-Item -ItemType Directory -Force -Path $Cache | Out-Null
  $zip = Join-Path $Cache 'repo.zip'
  Invoke-WebRequest -UseBasicParsing -Uri "$RepoUrl/archive/refs/heads/main.zip" -OutFile $zip
  $new = "$Repo.new"; if (Test-Path $new) { Remove-Item -Recurse -Force $new }
  New-Item -ItemType Directory -Force -Path $new | Out-Null
  # Windows' own tar reads zips, and can take just the recipes + lists
  & tar.exe -xf $zip -C $new --strip-components=1 '*/packages/*' '*/*.map' 2>$null
  if (-not (Test-Path (Join-Path $new 'packages'))) { Die "couldn't unpack Main GURT" }
  if (Test-Path $Repo) { Remove-Item -Recurse -Force $Repo }
  Move-Item $new $Repo
  Remove-Item -Force $zip
}
function Ensure-Main { if (-not (Test-Path (Join-Path $Repo 'packages'))) { Sync-Main } }
function Recipe($name) {
  $f = Join-Path $Repo "packages\$name\.gurtinfo"
  if (Test-Path $f) { return $f }
  # an alias (vscode -> visual-studio-code-bin)
  $hit = Get-ChildItem (Join-Path $Repo 'packages') -Filter '.gurtinfo' -Recurse -Depth 1 -Force -ErrorAction SilentlyContinue |
    Where-Object { (Get-Content $_.FullName) -contains "alias = $name" } | Select-Object -First 1
  if ($hit) { return $hit.FullName }
  return $null
}

# -- winget --
$WG = @('--accept-source-agreements', '--disable-interactivity')
function WG-Find($name) { # -> winget id, or $null. exact id, then moniker, then exact name
  if (-not (Have winget)) { return $null }
  foreach ($how in @('--id', '--moniker', '--name')) {
    $out = & winget show $how $name --exact @WG 2>$null
    if ($LASTEXITCODE -eq 0) {
      $line = $out | Where-Object { $_ -match '^Found .+\[(.+)\]\s*$' } | Select-Object -First 1
      if ($line -and $line -match '\[(.+)\]\s*$') { return $Matches[1] }
      if ($how -eq '--id') { return $name }
    }
  }
  return $null
}
function WG-Version($id) {
  $out = & winget show --id $id --exact @WG 2>$null
  $v = $out | Where-Object { $_ -match '^\s*Version:\s*(.+)$' } | Select-Object -First 1
  if ($v -and $v -match '^\s*Version:\s*(.+)$') { return $Matches[1].Trim() }
  return ''
}
# (native programs' output goes to the screen with Out-Host: in a function, anything not captured becomes its return value)
function WG-Install($id) { & winget install --id $id --exact --silent --accept-package-agreements @WG | Out-Host; return ($LASTEXITCODE -eq 0) }
function WG-Remove($id) { & winget uninstall --id $id --exact --silent @WG | Out-Host; return ($LASTEXITCODE -eq 0) }
function WG-Upgrade($id) { & winget upgrade --id $id --exact --silent --accept-package-agreements @WG | Out-Host; return ($LASTEXITCODE -eq 0 -or $LASTEXITCODE -eq -1978335189) }   # that one: nothing newer

# -- scoop (no admin: installs into your user folder) --
function Ensure-Scoop {
  if (Have scoop) { return $true }
  if (-not (Ask 'scoop isn''t here. install it? (no admin, into your user folder)')) { return $false }
  Say 'installing scoop'
  $inst = Invoke-RestMethod -UseBasicParsing https://get.scoop.sh
  if (Is-Admin) { Invoke-Expression "& {$inst} -RunAsAdmin" | Out-Host } else { Invoke-Expression $inst | Out-Host }
  $env:Path = "$env:USERPROFILE\scoop\shims;$env:Path"
  return (Have scoop)
}
function Scoop-Buckets { if (Have scoop) { $b = @(& scoop bucket list 6>$null | ForEach-Object { "$($_.Name)" }); foreach ($x in @('extras')) { if ($b -notcontains $x) { & scoop bucket add $x 6>$null | Out-Null } } } }
function Scoop-Find($name) {
  if (-not (Have scoop)) { return $null }
  $out = & scoop info $name 6>$null 2>$null   # scoop is a PowerShell script: its exit code isn't reliable, its object is
  if ($out -and $out.Name) { return "$($out.Name)" }
  return $null
}
function Scoop-Installed($name) { return (Test-Path (Join-Path $env:USERPROFILE "scoop\apps\$name\current")) -or ($env:SCOOP -and (Test-Path (Join-Path $env:SCOOP "apps\$name\current"))) }
function Scoop-Version($name) { $i = & scoop info $name 6>$null 2>$null; if ($i -and $i.Version) { return "$($i.Version)" }; return '' }

# -- Chocolatey (needs admin, so it asks Windows for it) --
function Choco-Find($name) {
  if (-not (Have choco)) { return $null }
  $l = & choco search $name --exact --limit-output 2>$null | Select-Object -First 1
  if ($l -and $l -match '^([^|]+)\|') { return $Matches[1] }
  return $null
}
function Choco-Version($name) { $l = & choco search $name --exact --limit-output 2>$null | Select-Object -First 1; if ($l -match '\|(.+)$') { return $Matches[1] }; return '' }
function Is-Admin { return ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }
function Choco-Run([string[]]$a) {
  if (Is-Admin) { & choco @a -y | Out-Host; return ($LASTEXITCODE -eq 0) }
  Info 'Chocolatey needs admin, so Windows asks you'
  $p = Start-Process choco -ArgumentList ($a + '-y') -Verb RunAs -Wait -PassThru
  return ($p.ExitCode -eq 0)
}

# -- WSL: Linux apps --
function WSL-Distros {
  # from the registry, never `wsl.exe --list`: without WSL, wsl.exe is a stub that waits for "press any key to install"
  $k = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'
  if (-not (Test-Path $k)) { return @() }
  return @(Get-ChildItem $k -ErrorAction SilentlyContinue | ForEach-Object { (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).DistributionName } | Where-Object { $_ })
}
function WSL-Args { $env:WSL_UTF8 = '1'; if ($Distro) { return @('-d', $Distro) } else { return @() } }
function WSL-HasGurt { $a = WSL-Args; & wsl.exe @a -e sh -c 'command -v gurt >/dev/null' 2>$null; return ($LASTEXITCODE -eq 0) }
function Ensure-WSL {
  if (-not (Have wsl.exe)) { Die 'this Windows has no WSL, and Linux-only apps need it (Windows 10 2004+ or Windows 11)' }
  $d = WSL-Distros
  if ($d.Count -eq 0) {
    # setting up WSL wants admin + maybe a reboot: only when someone is at a terminal to say yes (not from the app, not -y in a script)
    if ([Console]::IsInputRedirected -or -not [Environment]::UserInteractive) { Die "that's Linux-only, so it needs WSL, which isn't set up. run the same gurt install in PowerShell and gurt offers to set WSL up" }
    $Script:Yes = $false
    if (-not (Ask 'that app is Linux-only, so it needs WSL (Linux inside Windows). set up WSL + Ubuntu now? (Windows asks for admin, may want a reboot)')) { Die 'no WSL, no Linux apps' }
    Start-Process wsl.exe -ArgumentList '--install', '-d', 'Ubuntu' -Verb RunAs -Wait
    Say 'WSL is installing. when it is done:'
    Info 'reboot if Windows asks you to'
    Info "open 'Ubuntu' from the Start menu once and make your Linux username + password"
    Info 'then run the same gurt command again'
    exit 0
  }
  if ($Distro -and $d -notcontains $Distro) { Die "no WSL distro called '$Distro' (you have: $($d -join ', '))" }
  if (-not (WSL-HasGurt)) {
    Say 'setting up gurt inside WSL (it may ask for your Linux password)'
    $a = WSL-Args
    & wsl.exe @a -e bash -lc "command -v curl >/dev/null || { sudo apt-get update -qq && sudo apt-get install -y -qq curl git; }; curl -fsSL '$Raw/install.sh' | GURT_WIZARD=0 sh" | Out-Host
    if ($LASTEXITCODE -ne 0) { Die "gurt's Linux installer failed inside WSL (scroll up for why)" }
  }
}
function WSL-Gurt([string[]]$a) {
  Ensure-WSL
  $w = WSL-Args
  $y = @(if ($Script:Yes) { '-y' })
  & wsl.exe @w -e /usr/local/bin/gurt @y @a | Out-Host
  return $LASTEXITCODE
}

# -- install: one spec --
function Split-Spec($spec) {
  if ($spec -match '^([A-Za-z0-9-]+)/(.+)$') { return @($Matches[1].ToLower(), $Matches[2]) }
  return @('', $spec)
}
function Install-One($spec) {
  $src, $name = Split-Spec $spec
  if ($src -eq 'wsl') { return ((WSL-Gurt @('install', $name)) -eq 0) }
  if ($src -and $LinuxSources -contains $src) { return ((WSL-Gurt @('install', $spec)) -eq 0) }
  if ($src -and $WinSources -notcontains $src) { Die "unknown source '$src' (Windows: winget scoop choco; Linux ones go to WSL: $($LinuxSources -join ' '))" }

  $recipe = ''; $desc = ''; $pins = @{}
  if (-not $src) {
    Ensure-Main
    $r = Recipe $name
    if ($r) {
      $recipe = InfoGet $r 'pkgname'; $desc = InfoGet $r 'pkgdesc'
      foreach ($s in $WinSources) { $p = InfoGet $r "win_$s"; if ($p) { $pins[$s] = $p } }
      if ((InfoGet $r 'win') -eq 'no') { Info "$name is a Linux app (its recipe says so), so: WSL"; return ((WSL-Gurt @('install', $name)) -eq 0) }
    }
  }
  $already = Installed | Where-Object { ($_.Recipe -and $_.Recipe -eq $name) -or $_.Id -eq $name -or ("$($_.Src)/$($_.Id)" -eq $spec) } | Select-Object -First 1
  if ($already) {
    # already here: bring it up to date instead (GURT's app's "update" button does this)
    Say "$($already.Src)/$($already.Id) is already installed ($($already.Ver)), updating it"
    switch ($already.Src) {
      'winget' { if (WG-Upgrade $already.Id) { Record 'winget' $already.Id (WG-Version $already.Id) $already.Desc $already.Recipe } }
      'scoop'  { & scoop update $already.Id | Out-Host; Record 'scoop' $already.Id (Scoop-Version $already.Id) $already.Desc $already.Recipe }
      'choco'  { if (Choco-Run @('upgrade', $already.Id)) { Record 'choco' $already.Id (Choco-Version $already.Id) $already.Desc $already.Recipe } }
    }
    return $true
  }

  $order = @(if ($src) { $src } else { $WinSources })
  foreach ($s in $order) {
    $want = if ($pins[$s]) { $pins[$s] } else { $name }
    switch ($s) {
      'winget' {
        if (-not (Have winget)) { if ($src) { Die 'winget isn''t here (it comes with Windows 10/11 as "App Installer" in the Microsoft Store)' }; continue }
        $id = WG-Find $want
        if (-not $id) { if ($src) { Die "winget has no $want (try: gurt search $want)" }; continue }
        if (-not (Ask "install $id from winget?")) { Die 'aborted' }
        Say "installing $id (winget)"
        if (-not (WG-Install $id)) { Warn "winget couldn't install $id"; if ($src) { return $false }; continue }
        Record 'winget' $id (WG-Version $id) $desc $recipe; Say "winget/$id installed"; return $true
      }
      'scoop' {
        if (-not (Have scoop)) { if (-not $src -or -not (Ensure-Scoop)) { continue } }
        Scoop-Buckets
        $n = Scoop-Find $want
        if (-not $n) { if ($src) { Die "scoop has no $want" }; continue }
        if (-not (Ask "install $n from scoop?")) { Die 'aborted' }
        Say "installing $n (scoop)"
        & scoop install $n | Out-Host
        if (-not (Scoop-Installed $n)) { Warn "scoop couldn't install $n"; if ($src) { return $false }; continue }
        Record 'scoop' $n (Scoop-Version $n) $desc $recipe; Say "scoop/$n installed"; return $true
      }
      'choco' {
        if (-not (Have choco)) { if ($src) { Die 'Chocolatey isn''t here (https://chocolatey.org/install)' }; continue }
        $n = Choco-Find $want
        if (-not $n) { if ($src) { Die "Chocolatey has no $want" }; continue }
        if (-not (Ask "install $n from Chocolatey?")) { Die 'aborted' }
        Say "installing $n (Chocolatey)"
        if (-not (Choco-Run @('install', $n))) { Warn "Chocolatey couldn't install $n"; if ($src) { return $false }; continue }
        Record 'choco' $n (Choco-Version $n) $desc $recipe; Say "choco/$n installed"; return $true
      }
    }
  }
  # nothing for Windows has it: a Linux app, so WSL
  Info "no Windows version of $name (winget, scoop, Chocolatey), so it goes in WSL (Linux inside Windows)"
  return ((WSL-Gurt @('install', $name)) -eq 0)
}

function Find-Installed($spec) {
  $src, $name = Split-Spec $spec
  return @(Installed | Where-Object { ((-not $src -or $_.Src -eq $src) -and ($_.Id -eq $name -or $_.Recipe -eq $name)) })
}
function Remove-One($spec) {
  $src, $name = Split-Spec $spec
  if ($src -eq 'wsl' -or ($src -and $LinuxSources -contains $src)) { $s = if ($src -eq 'wsl') { $name } else { $spec }; return ((WSL-Gurt @('remove', $s)) -eq 0) }
  $hit = Find-Installed $spec
  if ($hit.Count -eq 0) {
    if ((WSL-Distros).Count -gt 0 -and (WSL-HasGurt)) { return ((WSL-Gurt @('remove', $spec)) -eq 0) }
    Die "$spec isn't installed (gurt list shows what is)"
  }
  if ($hit.Count -gt 1) { Die "$spec is installed from more than one place: $(($hit | ForEach-Object { "$($_.Src)/$($_.Id)" }) -join ', '). say which" }
  $p = $hit[0]
  if (-not (Ask "remove $($p.Src)/$($p.Id)?")) { Die 'aborted' }
  Say "removing $($p.Src)/$($p.Id)"
  $ok = switch ($p.Src) {
    'winget' { WG-Remove $p.Id }
    'scoop'  { & scoop uninstall $p.Id | Out-Host; -not (Scoop-Installed $p.Id) }
    'choco'  { Choco-Run @('uninstall', $p.Id) }
    default  { $false }
  }
  if (-not $ok) { Warn "$($p.Src) couldn't remove $($p.Id) (already gone?)" }
  Remove-Item -Recurse -Force $p.Dir
  Say "$($p.Src)/$($p.Id) removed"
  return $true
}

function Cmd-List {
  foreach ($p in Installed) { Write-Host ("{0,-40} {1}{2}" -f "$($p.Src)/$($p.Id)", $p.Ver, $(if ($p.Recipe) { "  (from GURT: $($p.Recipe))" } else { '' })) }
  if ((WSL-Distros).Count -gt 0 -and (WSL-HasGurt)) {
    $w = WSL-Args
    & wsl.exe @w -e /usr/local/bin/gurt list 2>$null | ForEach-Object { Write-Host "wsl: $_" }
  }
}
# search results, the way Linux gurt prints them (GURT's app reads this): "source/name version", then "    description"
function Out-Hit($src, $name, $ver, $desc) {
  $v = if ($ver) { ($ver -replace '\s', '') } else { 'latest' }
  Write-Output "$src/$name $v"
  if ($desc) { Write-Output "    $desc" }
}
function WG-Search($term) {
  if (-not (Have winget)) { return }
  $lines = @(& winget search $term @WG 2>$null | ForEach-Object { ($_ -split "`r")[-1] })
  $hi = -1
  for ($i = 0; $i -lt $lines.Count; $i++) { if ($lines[$i] -match '^-{5,}') { $hi = $i - 1; break } }
  if ($hi -lt 0) { return }
  # the columns start where the header's words do (Name Id Version ..., in your language)
  $starts = @([regex]::Matches($lines[$hi], '\S+') | ForEach-Object { $_.Index })
  if ($starts.Count -lt 3) { return }
  foreach ($l in $lines[($hi + 2)..($lines.Count - 1)]) {
    if (-not $l -or $l.Length -le $starts[2]) { continue }
    $name = $l.Substring(0, $starts[1]).Trim()
    $id = $l.Substring($starts[1], $starts[2] - $starts[1]).Trim()
    $end = if ($starts.Count -gt 3 -and $l.Length -gt $starts[3]) { $starts[3] } else { $l.Length }
    $ver = $l.Substring($starts[2], $end - $starts[2]).Trim()
    if ($id -and $id -notmatch '\s') { Out-Hit 'winget' $id $ver $name }
  }
}
function Cmd-Search([string[]]$a) {
  $a = @($a | Where-Object { $_ -ne '-a' -and $_ -ne '--all' })
  $term = $a -join ' '
  if (-not $term) { Die 'usage: gurt search <term>  (or winget/<term>, scoop/<term>, choco/<term>)' }
  $src, $t = Split-Spec $term
  if ($src -and $LinuxSources -contains $src) { $null = WSL-Gurt @('search', $term); return }
  if ($src -and $WinSources -notcontains $src) { $src = ''; $t = $term }
  if (-not $src) {
    Ensure-Main
    foreach ($h in @(Get-ChildItem (Join-Path $Repo 'packages') -Directory | Where-Object { $_.Name -like "*$t*" } | Select-Object -First 15)) {
      Out-Hit 'gurt' $h.Name 'latest' (InfoGet (Join-Path $h.FullName '.gurtinfo') 'pkgdesc')
    }
  }
  if (-not $src -or $src -eq 'winget') { WG-Search $t | Select-Object -First 40 }
  if ((-not $src -or $src -eq 'scoop') -and (Have scoop)) {
    & scoop search $t 6>$null 2>$null | Select-Object -First 15 | ForEach-Object { Out-Hit 'scoop' $_.Name $_.Version "from scoop's $($_.Source) bucket" }
  }
  if ((-not $src -or $src -eq 'choco') -and (Have choco)) {
    & choco search $t --limit-output 2>$null | Select-Object -First 15 | ForEach-Object { $n, $v = $_ -split '\|'; Out-Hit 'choco' $n $v '' }
  }
}
# what's outdated, the way Linux gurt's `gurt update` says it (GURT's app reads "  -> src/name old -> new")
function Latest-Gurt {
  try { return ((Invoke-RestMethod -UseBasicParsing -TimeoutSec 8 -Uri 'https://api.github.com/repos/clrealy/GURT/releases/latest').tag_name -replace '^v', '') } catch { return '' }
}
function Cmd-Update {
  Say 'checking for updates'
  $new = Latest-Gurt
  if ($new -and $new -ne $GURT_VERSION -and ([version]($new -replace '[^0-9.].*$', '') -gt [version]($GURT_VERSION -replace '[^0-9.].*$', ''))) {
    Warn "gurt $new is out (you have $GURT_VERSION): gurt self-update"
  }
  $all = Installed
  $wg = @($all | Where-Object { $_.Src -eq 'winget' } | ForEach-Object { $_.Id })
  if ($wg.Count -and (Have winget)) {
    $lines = @(& winget upgrade @WG 2>$null | ForEach-Object { ($_ -split "`r")[-1] })
    $hi = -1; for ($i = 0; $i -lt $lines.Count; $i++) { if ($lines[$i] -match '^-{5,}') { $hi = $i - 1; break } }
    if ($hi -ge 0) {
      $st = @([regex]::Matches($lines[$hi], '\S+') | ForEach-Object { $_.Index })
      foreach ($l in $lines[($hi + 2)..($lines.Count - 1)]) {
        if ($st.Count -lt 4 -or -not $l -or $l.Length -le $st[3]) { continue }
        $id = $l.Substring($st[1], $st[2] - $st[1]).Trim()
        $old = $l.Substring($st[2], $st[3] - $st[2]).Trim()
        $end = if ($st.Count -gt 4 -and $l.Length -gt $st[4]) { $st[4] } else { $l.Length }
        $newv = $l.Substring($st[3], $end - $st[3]).Trim()
        if ($wg -contains $id) { Info "winget/$id $($old -replace '\s','') -> $($newv -replace '\s','')" }
      }
    }
  }
  if ((Have scoop) -and ($all | Where-Object { $_.Src -eq 'scoop' })) {
    & scoop status 6>$null 2>$null | Where-Object { $_.'Latest Version' } | ForEach-Object { Info "scoop/$($_.Name) $($_.'Installed Version') -> $($_.'Latest Version')" }
  }
  $ch = @($all | Where-Object { $_.Src -eq 'choco' } | ForEach-Object { $_.Id })
  if ($ch.Count -and (Have choco)) {
    & choco outdated --limit-output 2>$null | ForEach-Object { $n, $o, $v = $_ -split '\|'; if ($ch -contains $n) { Info "choco/$n $o -> $v" } }
  }
}
function Cmd-SelfUpdate {
  $new = Latest-Gurt
  if (-not $new) { Die "couldn't ask GitHub what the newest gurt is" }
  if ($new -eq $GURT_VERSION) { Say "gurt $GURT_VERSION is already the newest"; return }
  Say "updating gurt $GURT_VERSION -> $new"
  # the installer from that release: gurt.ps1, the app, the lists
  $env:GURT_RAW = "https://raw.githubusercontent.com/clrealy/GURT/v$new"
  $env:GURT_RELEASE = "https://github.com/clrealy/GURT/releases/download/v$new"
  $env:GURT_NO_WIZARD = '1'
  Invoke-Expression (Invoke-RestMethod -UseBasicParsing "$env:GURT_RAW/install.ps1") | Out-Host
}
function Cmd-Upgrade {
  $all = Installed
  foreach ($p in $all) {
    switch ($p.Src) {
      'winget' { Say "updating winget/$($p.Id)"; if (WG-Upgrade $p.Id) { Record 'winget' $p.Id (WG-Version $p.Id) $p.Desc $p.Recipe } }
      'scoop'  { Say "updating scoop/$($p.Id)"; & scoop update $p.Id | Out-Host; Record 'scoop' $p.Id (Scoop-Version $p.Id) $p.Desc $p.Recipe }
      'choco'  { Say "updating choco/$($p.Id)"; if (Choco-Run @('upgrade', $p.Id)) { Record 'choco' $p.Id (Choco-Version $p.Id) $p.Desc $p.Recipe } }
    }
  }
  if ((WSL-Distros).Count -gt 0 -and (WSL-HasGurt)) { Say 'and inside WSL'; $null = WSL-Gurt @('upgrade') }
  Say 'all up to date'
}
function Cmd-Info($spec) {
  if (-not $spec) { Die 'usage: gurt info <name>' }
  $src, $name = Split-Spec $spec
  if ($src -and $LinuxSources -contains $src) { $null = WSL-Gurt @('info', $spec); return }
  $hit = Find-Installed $spec
  if ($hit) { foreach ($p in $hit) { Write-Host "installed     : $($p.Src)/$($p.Id) $($p.Ver)" } } else { Write-Host 'installed     : no' }
  Ensure-Main
  $r = Recipe $name
  if ($r) { Write-Host "Main GURT     : $(InfoGet $r 'pkgname') - $(InfoGet $r 'pkgdesc')" }
  $id = WG-Find $name; if ($id) { Write-Host "winget        : $id" }
  $n = Scoop-Find $name; if ($n) { Write-Host "scoop         : $n" }
  $c = Choco-Find $name; if ($c) { Write-Host "Chocolatey    : $c" }
  if (-not ($id -or $n -or $c)) { Write-Host 'Windows       : none of winget / scoop / Chocolatey has it, so gurt install puts it in WSL' }
}
function Cmd-Pack([string[]]$a) {
  Ensure-Main
  $map = @(Join-Path $Repo 'packs.map'; Join-Path $GHome 'packs.map') | Where-Object { Test-Path $_ } | Select-Object -First 1
  if (-not $map) { Die "couldn't find packs.map (gurt sync fetches it)" }
  $rows = Get-Content $map | Where-Object { $_ -and -not $_.StartsWith('#') -and $_.Contains('|') } | ForEach-Object { $i, $n, $d, $apps = $_ -split '\|', 4; [pscustomobject]@{ Id = $i; Name = $n; Desc = $d; Apps = @($apps -split '\s+' | Where-Object { $_ }) } }
  if ($a.Count -eq 0 -or $a[0] -eq 'list') { Say 'package packs: gurt pack <name>'; foreach ($r in $rows) { Write-Host ("  {0,-10} {1} ({2} apps): {3}" -f $r.Id, $r.Name, $r.Apps.Count, ($r.Apps -join ' ')) }; return }
  $p = $rows | Where-Object { $_.Id -eq $a[0] } | Select-Object -First 1
  if (-not $p) { Die "no pack called '$($a[0])' (gurt pack list shows them)" }
  if (-not (Ask "install the $($p.Name) pack: $($p.Apps -join ' ')?")) { Die 'aborted' }
  $was = $Script:Yes; $Script:Yes = $true; $Script:Multi = $true; $failed = @()
  foreach ($x in $p.Apps) { try { if (-not (Install-One $x)) { $failed += $x } } catch { $failed += $x } }
  $Script:Yes = $was; $Script:Multi = $false
  if ($failed) { Warn "these didn't install: $($failed -join ' ')"; exit 1 }
  Say "$($p.Name) pack installed"
}
function Cmd-Gui([string[]]$a) {
  $app = Join-Path $Bin 'gurt-app.exe'
  if (-not (Test-Path $app)) { Die "GURT's app isn't installed ($app). run GURTSetupWizard.exe again" }
  Start-Process -FilePath $app -ArgumentList (@('--gurt', $PSCommandPath) + $a)
}
function Cmd-Paths {
  $wsl = if ((WSL-Distros).Count -gt 0) { 'yes' } else { 'no' }
  $pm = if (Have winget) { 'winget' } elseif (Have scoop) { 'scoop' } elseif (Have choco) { 'choco' } else { 'none' }
  "version=$GURT_VERSION", "repo=$Repo", "db=$DB", "cache=$Cache", 'dirt=off', "pm=$pm", 'wsl=no', "wsldistro=$wsl", 'cros=no', 'dev=no', 'nix=no', 'hook=off', 'windows=yes' | ForEach-Object { Write-Output $_ }
}
function Cmd-Help {
  @"
gurt $GURT_VERSION for Windows: every app, from wherever it is

  gurt install <app...>     the Windows version from winget, else scoop, else Chocolatey, else (Linux-only) WSL
  gurt install winget/<Id>  scoop/<name>  choco/<name>      from that one
  gurt install apt/<pkg>  aur/<pkg>  flatpak/<id>  ...      Linux sources: inside WSL
  gurt remove <app>         take it off again (through whatever installed it)
  gurt search <term>        Main GURT, winget, scoop and Chocolatey
  gurt info <app>           where gurt would get it
  gurt list                 what gurt installed (and what gurt installed inside WSL)
  gurt update               what has an update waiting
  gurt upgrade              update everything gurt installed
  gurt self-update          the newest gurt
  gurt pack [name]          package packs: a bunch of apps for one thing
  gurt sync                 refresh Main GURT's app list
  gurt gui                  GURT's app
  gurt wsl <anything>       run Linux gurt inside WSL
  gurt version
  -y                        don't ask
"@ | Write-Host
}

# -- main --
$rest = @()
foreach ($x in $args) {
  if ($x -eq '-y' -or $x -eq '--yes' -or $x -eq '--noconfirm') { $Script:Yes = $true }
  elseif ($x -in '-a', '--all', '--nodeps', '--no-system', '--force') { }   # Linux gurt's flags: nothing to do here
  else { $rest += "$x" }
}
$cmd = if ($rest.Count) { $rest[0] } else { 'help' }
$a = @($rest | Select-Object -Skip 1)   # always a list: $rest[1..1] would be one string, and $a[0] its first letter
switch -Regex ($cmd) {
  '^(install|i|get|add)$' {
    if ($a.Count -eq 0) { Die 'install what tho' }
    $failed = @()
    if ($a.Count -eq 1) { if (-not (Install-One $a[0])) { exit 1 } }
    else {
      $Script:Multi = $true
      foreach ($s in $a) { try { if (-not (Install-One $s)) { $failed += $s } } catch { $failed += $s } }
      $Script:Multi = $false
    }
    if ($failed) { Die "$($a.Count - $failed.Count) of $($a.Count) installed. these didn't: $($failed -join ' ')" }
  }
  '^(remove|rm|uninstall|yeet)$' { if ($a.Count -eq 0) { Die 'remove what tho' }; foreach ($s in $a) { $null = Remove-One $s } }
  '^(search|s)$'           { Cmd-Search $a }
  '^(info)$'               { Cmd-Info ($a | Select-Object -First 1) }
  '^(list|ls)$'            { Cmd-List }
  '^(upgrade|up)$'         { Cmd-Upgrade }
  '^(update|check)$'       { Cmd-Update }
  '^self-update$'          { Cmd-SelfUpdate }
  '^(pack|packs)$'         { Cmd-Pack $a }
  '^(sync|refresh)$'       { Sync-Main; Say "$(@(Get-ChildItem (Join-Path $Repo 'packages') -Directory).Count) packages in Main GURT" }
  '^(gui|app)$'            { Cmd-Gui $a }
  '^(setup|wizard)$'       { Cmd-Gui (@('--wizard') + $a) }
  '^wsl$'                  { exit (WSL-Gurt $a) }
  '^(version|-v|--version)$' { Write-Output "gurt $GURT_VERSION (Windows)" }
  '^(help|-h|--help)$'     { Cmd-Help }
  '^__paths$'              { Cmd-Paths }
  '^__achieve$'            { exit 0 }
  default {
    # the rest of gurt (convert, hogs, lottery, ...) is the Linux one
    if ((WSL-Distros).Count -gt 0) { exit (WSL-Gurt $rest) }
    Die "'$cmd' is a Linux gurt thing, and there's no WSL here. gurt help shows what works on Windows"
  }
}

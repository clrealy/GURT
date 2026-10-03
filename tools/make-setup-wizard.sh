#!/usr/bin/env bash
# builds the GURTSetupWizard installers: gurt + the app + a menu entry + a one-time wizard at login,
# as every distro's own package, made by gurt convert itself (signed with your gurt key unless --no-sign)
#   tools/make-setup-wizard.sh [out-dir] [--no-sign]   → GURTSetupWizard.deb .rpm .pkg.tar.zst .apk .xbps .eopkg
#   tools/make-setup-wizard.sh [out-dir] --dev[=N]     → GURTSetupWizard-dev.rpm: version <ver>+dev.N, and it adds the
#     gurt-dev repo to zypper/dnf, so every new dev build arrives with zypper up / dnf upgrade
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
out=$root/dist sign=() dev=""
for a; do case $a in --no-sign) sign=(--no-sign) ;; --dev) dev=$(date -u +%Y%m%d%H%M) ;; --dev=*) dev=${a#--dev=} ;; *) out=$a ;; esac; done
ver=$(sed -n 's/^GURT_VERSION="\(.*\)"/\1/p' "$root/gurt")
[[ -n $ver ]] || { echo "couldn't read GURT_VERSION" >&2; exit 1; }
[[ -z $dev || $dev =~ ^[0-9]+$ ]] || { echo "--dev=N takes a number" >&2; exit 1; }
DEV_URL=https://clrealy.github.io/GURT/dev/rpm
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
t=$tmp/tree
mkdir -p "$out"; out=$(cd "$out" && pwd)

# what the package puts on your system (all owned by your package manager)
install -Dm755 "$root/gurt"                             "$t/usr/bin/gurt"
install -Dm644 "$root/deps.map"                         "$t/usr/share/gurt/deps.map"
install -Dm644 "$root/vibes.map"                        "$t/usr/share/gurt/vibes.map"
install -Dm644 "$root/gui/gurt-gui.py"                  "$t/usr/share/gurt/gurt-gui.py"
install -Dm644 "$root/assets/wilhelm.mp3"               "$t/usr/share/gurt/wilhelm.mp3"
install -Dm644 "$root/site/assets/apple-touch-icon.png" "$t/usr/share/gurt/gurt.png"
install -Dm644 "$root/site/assets/apple-touch-icon.png" "$t/usr/share/icons/hicolor/256x256/apps/gurt.png"
install -Dm644 "$root/site/assets/favicon.svg"          "$t/usr/share/icons/hicolor/scalable/apps/gurt.svg"
install -Dm644 /dev/stdin "$t/usr/share/applications/gurt.desktop" <<'DESK'
[Desktop Entry]
Type=Application
Name=GURT
GenericName=Package Manager
Comment=every distro's packages, on every distro
Exec=gurt gui %f
Icon=gurt
Terminal=false
StartupWMClass=gurt
Categories=System;Settings;PackageManager;
Keywords=packages;install;aur;apt;flatpak;setup;wizard;
MimeType=application/x-gurt-package;
DESK
# at your next login: the setup wizard, once (gurt gui --first-run does nothing after you finished it)
install -Dm644 /dev/stdin "$t/etc/xdg/autostart/gurt-setup-wizard.desktop" <<'DESK'
[Desktop Entry]
Type=Application
Name=GURT Setup Wizard
Comment=finish setting up GURT
Exec=gurt gui --first-run
Icon=gurt
Terminal=false
NoDisplay=true
X-GNOME-Autostart-Delay=8
DESK

# the dev build: + the gurt-dev repo, so zypper / dnf keep it updated (signed repo when there's a signing key)
if [[ -n $dev ]]; then
  ver="$ver+dev.$dev"
  sed -i "s/^GURT_VERSION=\".*\"/GURT_VERSION=\"$ver\"/" "$t/usr/bin/gurt"   # so gurt version says which dev build this is
  if (( ${#sign[@]} )); then gpg="gpgcheck=0
repo_gpgcheck=0"; else gpg="gpgcheck=1
repo_gpgcheck=1
gpgkey=$DEV_URL/gurt-key.asc"; fi
  for f in etc/zypp/repos.d/gurt-dev.repo etc/yum.repos.d/gurt-dev.repo; do
    install -Dm644 /dev/stdin "$t/$f" <<REPO
[gurt-dev]
name=GURT dev builds
baseurl=$DEV_URL
enabled=1
autorefresh=1
metadata_expire=1h
type=rpm-md
$gpg
REPO
  done
fi

cat > "$t/.PKGINFO" <<INFO
pkgname = gurt
pkgver = $ver
pkgrel = 1
pkgdesc = GURT Setup Wizard: every distro's packages, on every distro
url = https://github.com/clrealy/GURT
license = MIT
arch = any
depends = bash
depends = git
depends = tar
depends = curl
depends = python3
INFO
( cd "$t" && tar -czf "$tmp/gurt-$ver-1-any.gurt" .PKGINFO usr etc )

declare -A ext=([deb]=deb [rpm]=rpm [pacman]=pkg.tar.zst [apk]=apk [xbps]=xbps [eopkg]=eopkg)
fmts=(deb rpm pacman apk xbps eopkg) name=GURTSetupWizard
[[ -n $dev ]] && fmts=(rpm) name=GURTSetupWizard-dev
for fmt in "${fmts[@]}"; do
  rm -rf "$tmp/o"; mkdir -p "$tmp/o"
  "$root/gurt" -y convert "$tmp/gurt-$ver-1-any.gurt" "$fmt" -o "$tmp/o" "${sign[@]}" >"$tmp/$fmt.log" 2>&1 || { tail -5 "$tmp/$fmt.log" >&2; exit 1; }
  for f in "$tmp/o"/*; do   # the package, and its signature next to it (if it has one) → GURTSetupWizard.<ext>[.sig…]
    case $f in *.sig|*.sig2|*.asc) mv "$f" "$out/$name.${ext[$fmt]}.${f##*.}" ;; *) mv "$f" "$out/$name.${ext[$fmt]}" ;; esac
  done
  echo "made $name.${ext[$fmt]} ($ver)"
done
echo "all in $out"

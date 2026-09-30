#!/bin/sh
# gurt installer — works on any distro with sh + git
# usage: curl -fsSL https://raw.githubusercontent.com/clrealy/GURT/main/install.sh | sh
set -eu
REPO="${GURT_REPO_URL:-https://github.com/clrealy/GURT.git}"
BIN="${GURT_BIN:-/usr/local/bin}"
SHARE="${GURT_SHARE:-/usr/local/share/gurt}"
say() { printf '\033[32m==>\033[0m %s\n' "$*"; }
die() { printf '\033[31m==> nah:\033[0m %s\n' "$*" >&2; exit 1; }
if [ "$(id -u)" -eq 0 ]; then SUDO=""; elif command -v sudo >/dev/null; then SUDO=sudo; elif command -v doas >/dev/null; then SUDO=doas; else die "need sudo or doas"; fi
for t in bash git; do command -v "$t" >/dev/null || die "install $t first, then rerun"; done
tar --version 2>/dev/null | grep -q GNU || die "gurt needs GNU tar (Alpine: apk add tar)"
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
say "grabbing gurt"
git clone -q --depth 1 "$REPO" "$tmp/gurt"
$SUDO install -Dm755 "$tmp/gurt/gurt" "$BIN/gurt"
$SUDO install -Dm644 "$tmp/gurt/deps.map" "$SHARE/deps.map"
$SUDO install -Dm644 "$tmp/gurt/gui/gurt-gui.py" "$SHARE/gurt-gui.py"
[ -f /etc/gurt.conf ] || $SUDO install -Dm644 "$tmp/gurt/gurt.conf" /etc/gurt.conf
say "gurt installed to $BIN/gurt 🦆"
"$BIN/gurt" yo
echo "next: gurt sync && gurt search   (or open the app: gurt gui)"

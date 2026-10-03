#!/bin/sh
# gurt installer — works on any distro with sh + git
# GURTSetupWizard.exe runs this inside WSL (people install with the GURTSetupWizard downloads, not this)
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
$SUDO install -Dm644 "$tmp/gurt/vibes.map" "$SHARE/vibes.map"
$SUDO install -Dm644 "$tmp/gurt/gui/gurt-gui.py" "$SHARE/gurt-gui.py"
$SUDO install -Dm644 "$tmp/gurt/assets/wilhelm.mp3" "$SHARE/wilhelm.mp3"
$SUDO install -Dm644 "$tmp/gurt/site/assets/apple-touch-icon.png" "$SHARE/gurt.png"
[ -f /etc/gurt.conf ] || $SUDO install -Dm644 "$tmp/gurt/gurt.conf" /etc/gurt.conf
say "gurt installed to $BIN/gurt 🦆"
"$BIN/gurt" yo
# Donk OS 🫏 runs on gurt, so gurt sets up the utilities apps need right away (everywhere else: gurt utils)
if [ -r /etc/os-release ] && (. /etc/os-release; case " ${ID:-} ${ID_LIKE:-} " in *" donkos "*|*" donk "*) exit 0 ;; *) exit 1 ;; esac); then
  say "Donk OS detected 🫏 installing the utilities apps need"
  "$BIN/gurt" -y utils || say "couldn't get every utility, run: gurt utils"
fi

# 🧙 the setup wizard: installing gurt = setting it up. GURT_WIZARD=0 skips it (scripts, CI, the website's one-liners)
case "${GURT_WIZARD:-1}" in 0|no|off|false)
  echo "next: gurt setup (the setup wizard) · or: gurt search · gurt gui"; exit 0 ;;
esac
if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && [ "$(id -u)" -ne 0 ]; then
  say "🧙 setting up the GURT app (its own window + a menu entry)"
  "$BIN/gurt" gui --setup </dev/tty || say "no app window this time, so GURT opens in your browser instead"
  say "🧙 opening the GURT Setup Wizard"
  if command -v setsid >/dev/null; then setsid "$BIN/gurt" gui --wizard >/dev/null 2>&1 &
  else nohup "$BIN/gurt" gui --wizard >/dev/null 2>&1 & fi
  echo "  the wizard is opening in its own window 👀  (nothing showed up? run: gurt setup)"
elif [ -r /dev/tty ] && (exec </dev/tty) 2>/dev/null; then
  say "🧙 no desktop here, so the setup wizard runs right in this terminal"
  "$BIN/gurt" setup </dev/tty || echo "the wizard stopped early. run it again anytime: gurt setup"
else
  echo "next: gurt setup (the setup wizard) · or: gurt search · gurt gui"
fi

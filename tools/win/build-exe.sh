#!/usr/bin/env bash
# builds GURTSetupWizard.exe with NSIS (works on Linux: apt install nsis)
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd); root=$(cd "$here/../.." && pwd)
out=${1:-$root/dist}; mkdir -p "$out"; out=$(cd "$out" && pwd)
ver=$(sed -n 's/^GURT_VERSION="\(.*\)"/\1/p' "$root/gurt")
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
# Windows PowerShell 5.1 reads a .ps1 without a BOM as ANSI, so the packed copy gets one
printf '\xef\xbb\xbf' > "$tmp/install.ps1"; cat "$root/install.ps1" >> "$tmp/install.ps1"
cd "$here" && makensis -V2 -DVERSION="$ver" -DOUTDIR="$out" -DPS1="$tmp/install.ps1" GURTSetupWizard.nsi
echo "made $out/GURTSetupWizard.exe"

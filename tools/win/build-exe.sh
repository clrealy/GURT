#!/usr/bin/env bash
# builds GURTSetupWizard.exe with NSIS (works on Linux: apt install nsis)
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd); root=$(cd "$here/../.." && pwd)
out=${1:-$root/dist}; mkdir -p "$out"; out=$(cd "$out" && pwd)
ver=$(sed -n 's/^GURT_VERSION="\(.*\)"/\1/p' "$root/gurt")
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
# Windows PowerShell 5.1 reads a .ps1 without a BOM as ANSI, so the packed copy gets one
printf '\xef\xbb\xbf' > "$tmp/install.ps1"; cat "$root/install.ps1" >> "$tmp/install.ps1"
# Windows wants 4 plain numbers: 1.0.0 → 1.0.0.0, 1.0.0+hotfix1 → 1.0.0.1
base=${ver%%+*}; extra=""; [[ $ver == *+* ]] && extra=$(grep -o '[0-9]*$' <<<"${ver#*+}" || true)
numver="$base.${extra:-0}"
cd "$here" && makensis -V2 -DVERSION="$ver" -DNUMVER="$numver" -DOUTDIR="$out" -DPS1="$tmp/install.ps1" GURTSetupWizard.nsi
echo "made $out/GURTSetupWizard.exe"

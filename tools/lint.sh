#!/usr/bin/env bash
# checks every recipe in packages/ — CI runs this on every PR
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
fail=0
bad() { echo "❌ $1: $2"; fail=1; }
for d in packages/*/; do
  n=$(basename "$d")
  [[ -f $d/GURTBUILD ]] || { bad "$n" "no GURTBUILD"; continue; }
  bash -n "$d/GURTBUILD" 2>/dev/null || { bad "$n" "GURTBUILD has a syntax error"; continue; }
  info=$(./gurt srcinfo "$d" 2>&1) || { bad "$n" "$info"; continue; }
  name=$(awk -F' = ' '$1=="pkgname"{print $2}' <<<"$info")
  [[ $name == "$n" ]] || bad "$n" "folder name must match pkgname ($name)"
  if [[ ! -f $d/.gurtinfo ]]; then bad "$n" "missing .gurtinfo — run: ./gurt srcinfo $d > $d.gurtinfo"
  elif ! diff -q <(echo "$info") "$d/.gurtinfo" >/dev/null; then bad "$n" ".gurtinfo is stale — run: ./gurt srcinfo $d > $d.gurtinfo"; fi
  for dep in $(awk -F' = ' '$1=="depends"||$1=="makedepends"{print $2}' <<<"$info"); do
    [[ $dep == */* ]] && continue   # cross-source dep (aur/…, apt/…)
    awk -v d="$dep" '$1==d{f=1} END{exit !f}' deps.map || [[ -d packages/$dep ]] ||
      echo "⚠️  $n: dep '$dep' isn't in deps.map or gurt — it'll be passed to the distro as-is"
  done
  grep -qE '(^|[^$])\b(sudo|doas)\b' "$d/GURTBUILD" && bad "$n" "recipes must never call sudo/doas"
  grep -qE 'curl[^|]*\|[[:space:]]*(ba)?sh' "$d/GURTBUILD" && bad "$n" "no curl | sh in recipes 💀"
  (( fail )) || echo "✅ $n"
done
exit $fail

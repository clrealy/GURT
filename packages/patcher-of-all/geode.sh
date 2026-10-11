# patcher-of-all recipe: geode  (ported from geode-patcher)
DESC="Geode mod loader for Geometry Dash on Linux (Steam/Flatpak/Snap, Proton)"
URL="https://geode-sdk.org"
# settings the GUI shows: VAR|type|label|extra|saved-in-file  (types: choice text dir check secret edit)
OPTIONS=(
  'GD_DIR|dir|Geometry Dash folder (blank = find it)||geode-dir'
  'GEODE_VERSION|text|Geode version (blank = latest)|'
  'GEODE_WIPE|check|Revert also deletes mods|'
)
# optional: GD_DIR=/path/to/Geometry\ Dash   GEODE_VERSION=v4.4.0   GEODE_WIPE=1 (revert also deletes mods)

_GD_EXE="GeometryDash.exe"
_GEODE_LAUNCH='WINEDLLOVERRIDES="xinput1_4=n,b" %command%'
_GEODE_FILES=(Geode.dll Geode.pdb xinput1_4.dll XInput1_4.dll GeodeUpdater.exe GeodeUninstaller.exe)

_gd() {
  local d; d="$(poa_setting GD_DIR geode-dir)"
  if [[ -n "$d" ]]; then [[ -f "$d/$_GD_EXE" ]] && echo "$d"; return; fi
  poa_steam_game 322170 "$_GD_EXE" "Geometry Dash"
}

poa_detect() { _gd >/dev/null; }
poa_check()  { local g; g="$(_gd)" && [[ -f "$g/Geode.dll" ]]; }

poa_apply() {
  local g tmp url api
  g="$(_gd)" || return 1
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' RETURN
  if [[ -n "${GEODE_VERSION:-}" ]]; then
    api="https://api.github.com/repos/geode-sdk/geode/releases/tags/$GEODE_VERSION"
  else
    api="https://api.github.com/repos/geode-sdk/geode/releases/latest"
  fi
  url="$(curl -fsSL -H "Accept: application/vnd.github+json" "$api" \
        | grep -o '"browser_download_url":[[:space:]]*"[^"]*"' | sed 's/.*"\(http[^"]*\)"/\1/' \
        | grep -Ei 'win[^/]*\.zip$' | grep -vi installer | head -n1)"
  [[ -n "$url" ]] || { echo "couldn't find a Geode Windows zip on GitHub (rate limited?)"; return 1; }
  echo "downloading $(basename "$url")..."
  curl -fL --progress-bar "$url" -o "$tmp/geode.zip" || return 1
  echo "extracting into $g"
  poa_unzip "$tmp/geode.zip" "$g" || return 1
  echo
  echo "last step: set Geometry Dash's Steam launch option to"
  echo "  $_GEODE_LAUNCH"
  poa_clip "$_GEODE_LAUNCH"
}

poa_revert() {
  local g f removed=()
  g="$(_gd)" || return 1
  for f in "${_GEODE_FILES[@]}"; do [[ -e "$g/$f" ]] && rm -f "$g/$f" && removed+=("$f"); done
  if [[ "${GEODE_WIPE:-0}" == 1 && -d "$g/geode" ]]; then rm -rf "$g/geode"; removed+=("geode/"); fi
  if [[ ${#removed[@]} -gt 0 ]]; then
    echo "removed ${removed[*]}. u can clear the Steam launch option now"
    [[ -d "$g/geode" ]] && echo "(ur mods in geode/ are still there, run with GEODE_WIPE=1 to delete them too)"
  else
    echo "nothing to remove, Geode wasn't installed there"
  fi
  return 0
}

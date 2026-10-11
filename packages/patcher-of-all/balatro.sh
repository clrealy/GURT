# patcher-of-all recipe: balatro
DESC="Balatro modding: lovely injector + Steamodded on Linux (Proton), launch option on ur clipboard"
URL="https://github.com/Steamodded/smods"
# settings the GUI shows: VAR|type|label|extra|saved-in-file  (types: choice text dir check secret edit)
OPTIONS=(
  'BALATRO_DIR|dir|Balatro folder (blank = find it)||balatro-dir'
  'SMODS_DEV|check|Use Steamodded dev branch|'
)
# optional: BALATRO_DIR=/path/to/Balatro   SMODS_DEV=1 (grab Steamodded's dev branch instead of latest release)

_BAL_APPID=2379780
_BAL_EXE="Balatro.exe"

_bal_dir() {
  local d; d="$(poa_setting BALATRO_DIR balatro-dir)"
  if [[ -n "$d" ]]; then [[ -f "$d/$_BAL_EXE" ]] && echo "$d"; return; fi
  poa_steam_game "$_BAL_APPID" "$_BAL_EXE" "Balatro"
}
_bal_mods() {
  local pfx; pfx="$(poa_steam_prefix "$_BAL_APPID")" || return 1
  echo "$pfx/drive_c/users/steamuser/AppData/Roaming/Balatro/Mods"
}
_bal_dll() { # which proxy dll lovely is using (newer: version.dll, older: winmm.dll / dwmapi.dll)
  local g d; g="$(_bal_dir)" || return 1
  d="$(cat "$POA_BACKUP/lovely-dll" 2>/dev/null)" && [[ -n "$d" && -f "$g/$d" ]] && echo "$d"
}

poa_detect() { _bal_dir >/dev/null; }

poa_check() {
  local m; m="$(_bal_mods)" || return 1
  _bal_dll >/dev/null && [[ -f "$m/smods/lovely.toml" || -d "$m/smods/lovely" ]]
}

poa_apply() {
  local g m tmp url dll dll_name inner launch
  g="$(_bal_dir)" || return 1
  m="$(_bal_mods)" || { echo "no Proton prefix for Balatro yet, launch it once from Steam then run this again"; return 1; }
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' RETURN

  echo "grabbing lovely injector..."
  url="$(poa_gh_asset ethangreen-dev/lovely-injector 'windows-msvc\.zip$')"
  [[ -n "$url" ]] || url="https://github.com/ethangreen-dev/lovely-injector/releases/latest/download/lovely-x86_64-pc-windows-msvc.zip"
  curl -fL --progress-bar "$url" -o "$tmp/lovely.zip" || return 1
  poa_unzip "$tmp/lovely.zip" "$tmp/lovely" || return 1
  dll="$(find "$tmp/lovely" -maxdepth 2 -iname '*.dll' -print -quit)"
  [[ -n "$dll" ]] || { echo "no dll in the lovely zip?? weird"; return 1; }
  dll_name="$(basename "$dll" | tr 'A-Z' 'a-z')"
  [[ -f "$g/$dll_name" && ! -f "$POA_BACKUP/lovely-dll" ]] && cp "$g/$dll_name" "$POA_BACKUP/$dll_name.orig"
  cp "$dll" "$g/$dll_name"
  echo "$dll_name" > "$POA_BACKUP/lovely-dll"
  echo "put $dll_name in $g"

  echo "grabbing Steamodded..."
  if [[ "${SMODS_DEV:-0}" == 1 ]]; then
    url="https://github.com/Steamodded/smods/archive/refs/heads/main.zip"
  else
    url="$(curl -fsSL -H "Accept: application/vnd.github+json" https://api.github.com/repos/Steamodded/smods/releases/latest \
          | grep -o '"tag_name":[[:space:]]*"[^"]*"' | sed 's/.*"\([^"]*\)"$/\1/')"
    url="${url:+https://github.com/Steamodded/smods/archive/refs/tags/$url.zip}"
    url="${url:-https://github.com/Steamodded/smods/archive/refs/heads/main.zip}"
  fi
  curl -fL --progress-bar "$url" -o "$tmp/smods.zip" || return 1
  poa_unzip "$tmp/smods.zip" "$tmp/smods" || return 1
  inner="$(find "$tmp/smods" -mindepth 1 -maxdepth 1 -type d -print -quit)"
  [[ -n "$inner" ]] || { echo "Steamodded zip was empty??"; return 1; }
  mkdir -p "$m"
  [[ -d "$m/smods" ]] && rm -rf "$m/smods"   # replacing an old Steamodded, ur other mods stay put
  mv "$inner" "$m/smods"
  echo "put Steamodded in $m/smods"

  launch="WINEDLLOVERRIDES=\"${dll_name%.dll}=n,b\" %command%"
  echo
  echo "last step: set Balatro's Steam launch option to"
  echo "  $launch"
  poa_clip "$launch"
}

poa_revert() {
  local g m d
  g="$(_bal_dir)" || return 1
  if d="$(cat "$POA_BACKUP/lovely-dll" 2>/dev/null)"; then
    rm -f "$g/$d"
    [[ -f "$POA_BACKUP/$d.orig" ]] && mv "$POA_BACKUP/$d.orig" "$g/$d"
    rm -f "$POA_BACKUP/lovely-dll"
    echo "removed lovely ($d)"
  fi
  if m="$(_bal_mods)" && [[ -d "$m/smods" ]]; then rm -rf "$m/smods"; echo "removed Steamodded (other mods left alone)"; fi
  echo "u can clear Balatro's launch option now"
}

# patcher-of-all recipe: photogimp  (ported from photogimp-patcher)
DESC="PhotoGIMP: make GIMP 3 look + feel like Photoshop (native + Flatpak, config backed up)"
URL="https://github.com/Diolinux/PhotoGIMP"

_PG_ZIP="https://github.com/Diolinux/PhotoGIMP/releases/latest/download/PhotoGIMP-linux.zip"
_PG_MARK=".patcher-of-all-photogimp"

_pg_native() { # newest gimp-3.x on PATH beats plain gimp
  local best
  best="$(compgen -c gimp-3 2>/dev/null | sort -V | tail -n1)"
  [[ -n "$best" ]] && command -v "$best" || command -v gimp
}
_pg_flatpak() { command -v flatpak >/dev/null && flatpak info org.gimp.GIMP >/dev/null 2>&1; }

_pg_flatpak_shares_host() { # the Flatpak usually reads ~/.config/GIMP like native
  flatpak info --show-permissions org.gimp.GIMP 2>/dev/null \
    | grep '^filesystems=' | tr ';' '\n' | sed 's/^filesystems=//; s/:.*//' \
    | grep -qE '^(xdg-config|home|host|xdg-config/GIMP.*)$'
}

_pg_newest() { find "$1" -maxdepth 1 -mindepth 1 -type d -name '3.*' 2>/dev/null | sort -V | tail -n1; }

# prints one config dir per GIMP install found
_pg_targets() {
  local cfg="${XDG_CONFIG_HOME:-$HOME/.config}/GIMP" bin ver base
  bin="$(_pg_native)"
  if [[ -n "$bin" ]]; then
    ver="$("$bin" --version 2>/dev/null | grep -oE '\b3\.[0-9]+' | head -n1)"
    if [[ -n "$ver" ]]; then echo "$cfg/$ver"; else _pg_newest "$cfg" || echo "$cfg/3.0"; fi
  fi
  if _pg_flatpak || [[ -d "$HOME/.var/app/org.gimp.GIMP/config/GIMP" ]]; then
    base="$HOME/.var/app/org.gimp.GIMP/config/GIMP"
    _pg_flatpak && _pg_flatpak_shares_host && base="$cfg"
    ver="$(_pg_flatpak && timeout 60 flatpak run org.gimp.GIMP --version 2>/dev/null | grep -oE '\b3\.[0-9]+' | head -n1)"
    if [[ -n "$ver" ]]; then echo "$base/$ver"
    else local n; n="$(_pg_newest "$base")"; echo "${n:-$base/3.0}"; fi
  fi | awk '!seen[$0]++'
}

poa_detect() { [[ -n "$(_pg_native)" ]] || _pg_flatpak || [[ -d "$HOME/.var/app/org.gimp.GIMP/config/GIMP" ]]; }

poa_check() {
  local t any=0
  while IFS= read -r t; do any=1; [[ -f "$t/$_PG_MARK" ]] || return 1; done < <(_pg_targets)
  [[ $any == 1 ]]
}

poa_apply() {
  if pgrep -x 'gimp(-3(\.[0-9]+)?)?' >/dev/null 2>&1 || pgrep -f 'org.gimp.GIMP' >/dev/null 2>&1; then
    echo "close GIMP first, it overwrites its config when it quits"; return 1
  fi
  local tmp root t stamp
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' RETURN
  echo "downloading latest PhotoGIMP..."
  curl -fL --progress-bar "$_PG_ZIP" -o "$tmp/pg.zip" || return 1
  poa_unzip "$tmp/pg.zip" "$tmp/x" || return 1
  root="$(find "$tmp/x" -type d -path '*/.config/GIMP/3.0' -print -quit)"
  [[ -n "$root" ]] || { echo "that zip doesn't look like a PhotoGIMP Linux release"; return 1; }
  stamp="$(date +%Y%m%d-%H%M%S)"
  while IFS= read -r t; do
    if [[ -d "$t" && -n "$(ls -A "$t" 2>/dev/null)" && ! -f "$t/$_PG_MARK" ]]; then
      local tag; tag="$( [[ "$t" == *"/.var/app/"* ]] && echo flatpak || echo native )"
      mkdir -p "$POA_BACKUP/$tag-$(basename "$t")-$stamp"
      cp -a "$t/." "$POA_BACKUP/$tag-$(basename "$t")-$stamp/"
      echo "backed up $t"
    fi
    mkdir -p "$t"
    cp -a "$root/." "$t/"
    printf '%s\n' "$t" > "$t/$_PG_MARK"
    echo "patched $t"
    # PhotoGIMP's launcher/icon is Flatpak-only (it runs flatpak run org.gimp.GIMP)
    if [[ "$t" == *"/.var/app/"* ]] || _pg_flatpak; then
      local share; share="$(dirname "$(dirname "$(dirname "$root")")")/.local/share"
      if [[ -d "$share" ]] && _pg_flatpak; then
        cp -a "$share/." "$HOME/.local/share/"
        update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1
        gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1
        echo "installed the PhotoGIMP icon + launcher"
      fi
    fi
  done < <(_pg_targets)
}

poa_revert() {
  local t tag b
  # every GIMP config folder we ever patched (old versions too) + the current ones
  { find "${XDG_CONFIG_HOME:-$HOME/.config}/GIMP" "$HOME/.var/app/org.gimp.GIMP/config/GIMP" \
         -mindepth 2 -maxdepth 2 -name "$_PG_MARK" -printf '%h\n' 2>/dev/null
    _pg_targets; } | awk '!seen[$0]++' | while IFS= read -r t; do
    [[ -f "$t/$_PG_MARK" ]] || continue   # not patched, leave it alone
    tag="$( [[ "$t" == *"/.var/app/"* ]] && echo flatpak || echo native )"
    b="$(find "$POA_BACKUP" -maxdepth 1 -type d -name "$tag-$(basename "$t")-*" 2>/dev/null | sort | tail -n1)"
    if [[ -n "$b" ]]; then
      rm -rf "$t" && mkdir -p "$t" && cp -a "$b/." "$t/" && echo "restored $t from $(basename "$b")"
    elif [[ -f "$t/$_PG_MARK" ]]; then
      mv "$t" "$POA_BACKUP/patched-$(basename "$t")-$(date +%Y%m%d-%H%M%S)" \
        && echo "no backup for $t (it was empty before), moved it aside so GIMP starts fresh"
    fi
  done
  return 0
}

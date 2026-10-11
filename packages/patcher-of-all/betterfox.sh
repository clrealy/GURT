# patcher-of-all recipe: betterfox
DESC="Betterfox user.js for Firefox (speed + privacy tweaks), backs up ur old one"
URL="https://github.com/yokoffing/Betterfox"

_ff_root() {
  local r
  for r in "$HOME/.mozilla/firefox" "$HOME/.var/app/org.mozilla.firefox/.mozilla/firefox" \
           "$HOME/snap/firefox/common/.mozilla/firefox"; do
    [[ -f "$r/profiles.ini" ]] && { echo "$r"; return; }
  done
  return 1
}

# default profile: [Install...] Default= wins, else the [Profile] with Default=1
_ff_profile() {
  local root rel
  root="$(_ff_root)" || return 1
  rel="$(awk -F= '
    /^\[Install/ {inst=1; next}
    /^\[/        {inst=0}
    inst && $1=="Default" {print $2; exit}' "$root/profiles.ini")"
  if [[ -z "$rel" ]]; then
    rel="$(awk -F= '
      /^\[Profile/ {p=""; d=0}
      $1=="Path"    {p=$2}
      $1=="Default" && $2=="1" {d=1}
      d && p {print p; exit}' "$root/profiles.ini")"
  fi
  [[ -n "$rel" ]] || return 1
  [[ "$rel" == /* ]] && echo "$rel" || echo "$root/$rel"
}

poa_detect() { _ff_profile >/dev/null; }

poa_check() {
  local p; p="$(_ff_profile)" || return 1
  grep -qi "betterfox" "$p/user.js" 2>/dev/null
}

poa_apply() {
  local p; p="$(_ff_profile)" || return 1
  if pgrep -x firefox >/dev/null || pgrep -f firefox-bin >/dev/null; then
    echo "heads up: close Firefox first or it'll ignore the new user.js till restart"
  fi
  if [[ -f "$p/user.js" ]] && ! grep -qi betterfox "$p/user.js"; then
    cp "$p/user.js" "$POA_BACKUP/user.js.orig"
  fi
  curl -fsSL https://raw.githubusercontent.com/yokoffing/Betterfox/main/user.js -o "$p/user.js.new" \
    && mv "$p/user.js.new" "$p/user.js"
}

poa_revert() {
  local p; p="$(_ff_profile)" || return 1
  if [[ -f "$POA_BACKUP/user.js.orig" ]]; then
    mv "$POA_BACKUP/user.js.orig" "$p/user.js"
  else
    rm -f "$p/user.js"
  fi
  echo "note: firefox keeps old prefs in prefs.js; reset any u care about in about:config"
}

# patcher-of-all recipe: spicetify
DESC="Spicetify themes + extensions for Spotify (auto re-applies after Spotify updates)"
URL="https://spicetify.app"

export PATH="$HOME/.spicetify:$PATH"

_spotify_path() {
  local p
  p="$(spicetify config spotify_path 2>/dev/null | tail -n1)"
  [[ -n "$p" && -d "$p" ]] && { echo "$p"; return; }
  for p in /opt/spotify /usr/share/spotify /usr/lib/spotify \
           "$HOME/.local/share/flatpak/app/com.spotify.Client/current/active/files/extra/share/spotify" \
           /var/lib/flatpak/app/com.spotify.Client/current/active/files/extra/share/spotify; do
    [[ -d "$p" ]] && { echo "$p"; return; }
  done
  return 1
}

poa_detect() {
  command -v spotify >/dev/null || _spotify_path >/dev/null
}

poa_check() {
  command -v spicetify >/dev/null || return 1
  local p; p="$(_spotify_path)" || return 1
  # spicetify unpacks xpui.spa into an xpui/ folder when applied
  [[ -d "$p/Apps/xpui" && ! -f "$p/Apps/xpui.spa" ]]
}

poa_apply() {
  if ! command -v spicetify >/dev/null; then
    echo "spicetify not found, installing it with its official installer..."
    local inst; inst="$(mktemp)"
    curl -fsSL https://raw.githubusercontent.com/spicetify/cli/main/install.sh -o "$inst" \
      && sh "$inst"; local rc=$?; rm -f "$inst"; [[ $rc -eq 0 ]] || return 1
  fi
  local p; p="$(_spotify_path)"
  if [[ -n "$p" && ! -w "$p/Apps" ]]; then
    echo "spotify folder isn't writable, fixing perms (needs sudo)..."
    sudo chmod a+wr "$p" && sudo chmod a+wr -R "$p/Apps" || return 1
  fi
  spicetify backup apply 2>/dev/null || spicetify restore backup apply
}

poa_revert() {
  spicetify restore
}

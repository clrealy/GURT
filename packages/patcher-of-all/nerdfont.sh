# patcher-of-all recipe: nerdfont
DESC="Nerd Fonts (icon-patched fonts for terminals + rices), JetBrainsMono by default"
URL="https://www.nerdfonts.com"
# pick fonts: NERDFONTS="JetBrainsMono FiraCode Hack"  or one per line in ~/.config/patcher-of-all/nerdfonts.list
# names = release asset names from github.com/ryanoasis/nerd-fonts/releases (case matters)

_NF_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/fonts/NerdFonts"

_nf_list() {
  if [[ -n "${NERDFONTS:-}" ]]; then
    mkdir -p "$POA_CONFIG"; tr ' ,' '\n\n' <<<"$NERDFONTS" | sed '/^$/d' > "$POA_CONFIG/nerdfonts.list"
    cat "$POA_CONFIG/nerdfonts.list"
  elif [[ -f "$POA_CONFIG/nerdfonts.list" ]]; then cat "$POA_CONFIG/nerdfonts.list"
  else echo JetBrainsMono; fi | sed 's/#.*//; s/[[:space:]]//g; /^$/d'
}

poa_detect() { command -v fc-cache >/dev/null; }

poa_check() {
  local f any=0
  while read -r f; do any=1; compgen -G "$_NF_DIR/$f/*.[ot]tf" >/dev/null || return 1; done < <(_nf_list)
  [[ $any == 1 ]]
}

poa_apply() {
  local f tmp
  poa_need tar || return 1
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' RETURN
  while read -r f; do
    [[ "$f" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "skipping weird font name '$f'"; continue; }
    echo "grabbing $f Nerd Font..."
    if ! curl -fL --progress-bar "https://github.com/ryanoasis/nerd-fonts/releases/latest/download/$f.tar.xz" -o "$tmp/$f.tar.xz"; then
      echo "no Nerd Font called '$f' (check the exact name on the releases page)"; return 1
    fi
    rm -rf "${_NF_DIR:?}/$f"; mkdir -p "$_NF_DIR/$f"
    tar -xJf "$tmp/$f.tar.xz" -C "$_NF_DIR/$f" || return 1
    find "$_NF_DIR/$f" -type f ! -iname '*.ttf' ! -iname '*.otf' -delete
    echo "installed $f"
  done < <(_nf_list)
  fc-cache -f "$_NF_DIR" >/dev/null && echo "font cache refreshed, pick it in ur terminal settings"
}

poa_revert() {
  local f
  while read -r f; do [[ -n "$f" && -d "$_NF_DIR/$f" ]] && rm -rf "${_NF_DIR:?}/$f" && echo "removed $f"; done < <(_nf_list)
  rmdir "$_NF_DIR" 2>/dev/null
  fc-cache -f >/dev/null 2>&1
  return 0
}

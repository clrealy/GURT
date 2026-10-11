# patcher-of-all recipe: msfonts
DESC="Microsoft core fonts (Arial, Times New Roman, Verdana...) so school/work docs don't look busted"
URL="https://corefonts.sourceforge.net"

_MS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/fonts/ms-corefonts"
_MS_FILES=(andale32 arial32 arialb32 comic32 courie32 georgi32 impact32 times32 trebuc32 verdan32 webdin32)

poa_detect() { command -v fc-cache >/dev/null; }

poa_check() { compgen -G "$_MS_DIR/[Aa]rial*.[Tt][Tt][Ff]" >/dev/null && compgen -G "$_MS_DIR/[Tt]imes*.[Tt][Tt][Ff]" >/dev/null; }

poa_apply() {
  local f tmp n=0
  poa_need cabextract || return 1
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' RETURN
  mkdir -p "$_MS_DIR"
  echo "heads up: these come with Microsoft's EULA (corefonts.sourceforge.net/eula.htm), installing = accepting it"
  for f in "${_MS_FILES[@]}"; do
    echo "grabbing $f..."
    if curl -fsSL --retry 3 "https://downloads.sourceforge.net/corefonts/$f.exe" -o "$tmp/$f.exe"; then
      cabextract -q -F '*.[Tt][Tt][Ff]' -d "$_MS_DIR" "$tmp/$f.exe" && n=$((n + 1))
    else
      echo "  couldn't download $f, skipping"
    fi
  done
  [[ $n -gt 0 ]] || { echo "didn't get any fonts, sourceforge might be down"; return 1; }
  fc-cache -f "$_MS_DIR" >/dev/null
  echo "installed $n/${#_MS_FILES[@]} font packs"
}

poa_revert() {
  rm -rf "${_MS_DIR:?}" && fc-cache -f >/dev/null 2>&1
  echo "removed the Microsoft fonts"
}

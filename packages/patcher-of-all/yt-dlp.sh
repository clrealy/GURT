# patcher-of-all recipe: yt-dlp
DESC="Always-fresh yt-dlp (official build, checksum-verified) that auto-updates, and mpv uses it too"
URL="https://github.com/yt-dlp/yt-dlp"
# settings the GUI shows: VAR|type|label|extra|saved-in-file  (types: choice text dir check secret edit)
OPTIONS=(
  'YTDLP_CHANNEL|choice|Release channel|stable,nightly|ytdlp-channel'
  'YTDLP_EVERY|text|Check for updates every N days|3|ytdlp-every'
)
# old yt-dlp is the #1 reason downloads break ("Sign in to confirm", missing formats), and
# distro packages lag weeks behind. this keeps ~/.local/bin/yt-dlp current: with autopatch on,
# repatch grabs a new build every YTDLP_EVERY days

_YT_BIN="$HOME/.local/bin/yt-dlp"
_YT_MPV="${XDG_CONFIG_HOME:-$HOME/.config}/mpv/mpv.conf"
_YT_MARK="# patcher-of-all: yt-dlp"

_yt_asset() {
  case "$(uname -m)" in
    x86_64|amd64)  echo yt-dlp_linux ;;
    aarch64|arm64) echo yt-dlp_linux_aarch64 ;;
    *)             echo yt-dlp ;;   # zipapp, runs on anything with python3
  esac
}
_yt_repo() {
  case "$(poa_setting YTDLP_CHANNEL ytdlp-channel stable)" in
    nightly) echo yt-dlp/yt-dlp-nightly-builds ;;
    *)       echo yt-dlp/yt-dlp ;;
  esac
}
_yt_mpv() { command -v mpv >/dev/null; }

poa_detect() { return 0; }

poa_check() {
  [[ -x "$_YT_BIN" && -f "$POA_BACKUP/ours" ]] || return 1
  if _yt_mpv; then grep -qF "$_YT_MARK" "$_YT_MPV" 2>/dev/null || return 1; fi
  # "fresh" = we looked for an update in the last N days (not the build's age,
  # or repatch would re-download the same build every hour between releases)
  local every last now
  every="$(poa_setting YTDLP_EVERY ytdlp-every 3)"; [[ "$every" =~ ^[0-9]+$ ]] || every=3
  last="$(cat "$POA_BACKUP/checked" 2>/dev/null || echo 0)"; now="$(date +%s)"
  (( now - last < every * 86400 )) || return 2   # 2 = installed, just due for an update check
  return 0
}

poa_apply() {
  local tmp asset repo base want got old new
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' RETURN
  asset="$(_yt_asset)"; repo="$(_yt_repo)"
  base="https://github.com/$repo/releases/latest/download"
  [[ "$asset" == yt-dlp ]] && { poa_need python3 || return 1; }

  echo "grabbing $asset from $repo..."
  curl -fL --progress-bar "$base/$asset" -o "$tmp/$asset" || return 1
  curl -fsSL "$base/SHA2-256SUMS" -o "$tmp/sums" || { echo "couldn't get the checksums, not installing an unverified binary"; return 1; }
  want="$(awk -v a="$asset" '$2 == a || $2 == "*"a {print $1; exit}' "$tmp/sums")"
  got="$(sha256sum "$tmp/$asset" | awk '{print $1}')"
  [[ -n "$want" && "$want" == "$got" ]] || { echo "checksum mismatch, refusing to install it ⚠️"; return 1; }
  echo "checksum ok ✓"

  mkdir -p "$(dirname "$_YT_BIN")"
  # someone else's yt-dlp already lives there? keep it for revert
  if [[ -e "$_YT_BIN" && ! -f "$POA_BACKUP/ours" && ! -f "$POA_BACKUP/yt-dlp.orig" ]]; then
    cp -p "$_YT_BIN" "$POA_BACKUP/yt-dlp.orig"
  fi
  old="$("$_YT_BIN" --version 2>/dev/null)"
  install -m755 "$tmp/$asset" "$_YT_BIN"
  touch "$POA_BACKUP/ours"
  new="$("$_YT_BIN" --version 2>/dev/null)"
  if [[ -n "$old" && "$old" == "$new" ]]; then echo "already on the newest: $new"
  else echo "yt-dlp ${old:+$old → }$new"; fi
  date +%s > "$POA_BACKUP/checked"

  if _yt_mpv && ! grep -qF "$_YT_MARK" "$_YT_MPV" 2>/dev/null; then
    mkdir -p "$(dirname "$_YT_MPV")"
    printf '%s\nscript-opts-append=ytdl_hook-ytdl_path=%s\n' "$_YT_MARK" "$_YT_BIN" >> "$_YT_MPV"
    echo "pointed mpv at it, so YouTube links in mpv use the fresh one"
  fi

  command -v ffmpeg >/dev/null || echo "heads up: no ffmpeg, so best-quality video+audio can't be merged (gurt install ffmpeg)"
  local found; found="$(command -v yt-dlp)"
  if [[ "$found" != "$_YT_BIN" ]]; then
    if [[ -n "$found" ]]; then echo "heads up: typing yt-dlp still runs the old one at $found"
    else echo "heads up: ~/.local/bin isn't in ur PATH yet"; fi
    echo '  fix: put  export PATH="$HOME/.local/bin:$PATH"  in ~/.bashrc'
  fi
}

poa_revert() {
  if [[ -f "$POA_BACKUP/ours" ]]; then
    rm -f "$_YT_BIN" "$POA_BACKUP/ours"
    if [[ -f "$POA_BACKUP/yt-dlp.orig" ]]; then mv "$POA_BACKUP/yt-dlp.orig" "$_YT_BIN"; echo "put ur old yt-dlp back"
    else echo "removed the fresh yt-dlp (ur system one is still there if u had one)"; fi
  fi
  rm -f "$POA_BACKUP/checked"
  if [[ -f "$_YT_MPV" ]] && grep -qF "$_YT_MARK" "$_YT_MPV"; then
    # drop our marker line and the line right after it
    awk -v m="$_YT_MARK" '$0 == m {skip = 1; next} skip {skip = 0; next} {print}' "$_YT_MPV" > "$_YT_MPV.tmp" \
      && mv "$_YT_MPV.tmp" "$_YT_MPV"
    [[ -s "$_YT_MPV" ]] || rm -f "$_YT_MPV"
    echo "mpv is back to its own yt-dlp"
  fi
  return 0
}

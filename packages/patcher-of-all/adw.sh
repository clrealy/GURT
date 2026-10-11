# patcher-of-all recipe: adw
DESC="Theme libadwaita / GTK4 apps (the hole Gradience left): gurt, catppuccin, dracula, nord, gruvbox or ur own css"
URL=""
# settings the GUI shows: VAR|type|label|extra|saved-in-file  (types: choice text dir check secret edit)
OPTIONS=(
  'ADW_THEME|choice|Theme|gurt,catppuccin,dracula,nord,gruvbox,custom|adw-theme'
  'adw.css|edit|Custom theme css|'
)
# pick: ADW_THEME=dracula  or write the name into ~/.config/patcher-of-all/adw-theme
# custom: put @define-color lines in ~/.config/patcher-of-all/adw.css and use ADW_THEME=custom

_ADW_MARK="/* patcher-of-all: adw"
_ADW_CFG="${XDG_CONFIG_HOME:-$HOME/.config}"

_adw_theme() { poa_setting ADW_THEME adw-theme gurt; }

# name -> "bg view headerbar card fg accent accent_fg"
_adw_palette() {
  case "$1" in
    gurt)        echo "#1b1b1b #121212 #222222 #262626 #eaeaea #ffc629 #111111" ;;
    catppuccin)  echo "#1e1e2e #181825 #11111b #313244 #cdd6f4 #cba6f7 #11111b" ;;
    dracula)     echo "#282a36 #21222c #191a21 #44475a #f8f8f2 #bd93f9 #282a36" ;;
    nord)        echo "#2e3440 #3b4252 #272c36 #434c5e #eceff4 #88c0d0 #2e3440" ;;
    gruvbox)     echo "#282828 #1d2021 #32302f #3c3836 #ebdbb2 #fabd2f #282828" ;;
    *) return 1 ;;
  esac
}

_adw_css() {
  local t; t="$(_adw_theme)"
  echo "$_ADW_MARK $t */"
  if [[ "$t" == custom ]]; then
    cat "$POA_CONFIG/adw.css" || return 1; return 0
  fi
  local p bg view hb card fg acc accfg
  p="$(_adw_palette "$t")" || { echo "unknown theme '$t' (gurt, catppuccin, dracula, nord, gruvbox, custom)" >&2; return 1; }
  read -r bg view hb card fg acc accfg <<<"$p"
  cat <<EOF
@define-color accent_color $acc;
@define-color accent_bg_color $acc;
@define-color accent_fg_color $accfg;
@define-color window_bg_color $bg;
@define-color window_fg_color $fg;
@define-color view_bg_color $view;
@define-color view_fg_color $fg;
@define-color headerbar_bg_color $hb;
@define-color headerbar_fg_color $fg;
@define-color headerbar_backdrop_color $bg;
@define-color sidebar_bg_color $hb;
@define-color sidebar_fg_color $fg;
@define-color sidebar_backdrop_color $bg;
@define-color secondary_sidebar_bg_color $bg;
@define-color card_bg_color $card;
@define-color card_fg_color $fg;
@define-color popover_bg_color $card;
@define-color popover_fg_color $fg;
@define-color dialog_bg_color $bg;
@define-color dialog_fg_color $fg;
@define-color thumbnail_bg_color $card;
EOF
}

poa_detect() { return 0; }   # any desktop with GTK apps

poa_check() {
  local want; want="$(_adw_theme)"
  head -n1 "$_ADW_CFG/gtk-4.0/gtk.css" 2>/dev/null | grep -qF "$_ADW_MARK $want */"
}

poa_apply() {
  local css v d
  css="$(_adw_css)" || return 1
  for v in gtk-4.0 gtk-3.0; do
    d="$_ADW_CFG/$v"; mkdir -p "$d"
    if [[ -f "$d/gtk.css" ]] && ! head -n1 "$d/gtk.css" | grep -qF "$_ADW_MARK" && [[ ! -f "$POA_BACKUP/$v.css" ]]; then
      cp "$d/gtk.css" "$POA_BACKUP/$v.css"
    fi
    printf '%s\n' "$css" > "$d/gtk.css"
  done
  if command -v flatpak >/dev/null; then
    flatpak override --user --filesystem=xdg-config/gtk-4.0:ro --filesystem=xdg-config/gtk-3.0:ro 2>/dev/null \
      && touch "$POA_BACKUP/flatpak-override" && echo "let Flatpak apps see the theme too"
  fi
  if command -v gsettings >/dev/null && [[ ! -f "$POA_BACKUP/color-scheme" ]]; then
    gsettings get org.gnome.desktop.interface color-scheme > "$POA_BACKUP/color-scheme" 2>/dev/null \
      && gsettings set org.gnome.desktop.interface color-scheme prefer-dark 2>/dev/null
  fi
  echo "themed with '$(_adw_theme)', restart ur GTK apps to see it"
}

poa_revert() {
  local v d
  for v in gtk-4.0 gtk-3.0; do
    d="$_ADW_CFG/$v"
    if [[ -f "$POA_BACKUP/$v.css" ]]; then mv "$POA_BACKUP/$v.css" "$d/gtk.css"
    elif head -n1 "$d/gtk.css" 2>/dev/null | grep -qF "$_ADW_MARK"; then rm -f "$d/gtk.css"; fi
  done
  if [[ -f "$POA_BACKUP/flatpak-override" ]]; then
    flatpak override --user --nofilesystem=xdg-config/gtk-4.0 --nofilesystem=xdg-config/gtk-3.0 2>/dev/null
    rm -f "$POA_BACKUP/flatpak-override"
  fi
  if [[ -f "$POA_BACKUP/color-scheme" ]]; then
    gsettings set org.gnome.desktop.interface color-scheme "$(tr -d "'" < "$POA_BACKUP/color-scheme")" 2>/dev/null
    rm -f "$POA_BACKUP/color-scheme"
  fi
  echo "GTK apps back to stock"
}

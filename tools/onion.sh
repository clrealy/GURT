#!/usr/bin/env bash
# tools/onion.sh: gurtproject.org on Tor, as gurtpm….onion
#
# run it once, as root, on a computer that stays on (a VPS, a Raspberry Pi, a home server):
#   curl -fsSL https://raw.githubusercontent.com/clrealy/GURT/main/tools/onion.sh | sudo bash
#   (or from a clone: sudo tools/onion.sh)
# it:
#   1. installs Tor (Debian / Ubuntu / Fedora / Arch / openSUSE)
#   2. mines an onion address that starts with "gurtpm" with mkp224o (a few minutes on a normal CPU), once.
#      ONION_PREFIX=gurt picks another start (every letter more takes ~32x longer; 8 letters is about a day)
#   3. builds the site from the repo (like the pages job, minus the dev builds) into /var/lib/gurt-onion/site
#   4. serves it on 127.0.0.1:8099 (gurt-onion-web.service), and Tor serves that as the onion (port 80)
#   5. rebuilds the site every 6 hours (gurt-onion-update.timer)
# run it again any time: it keeps the address and just updates everything.
#
# the onion's secret key is /var/lib/tor/gurt-onion/hs_ed25519_secret_key: whoever has it IS the onion.
# back it up somewhere safe and never put it in the repo (like the package signing key).
set -euo pipefail

PREFIX=${ONION_PREFIX:-gurtpm}
REPO=${GURT_REPO_URL:-https://github.com/clrealy/GURT.git}
HOME_DIR=/var/lib/gurt-onion
HS_DIR=/var/lib/tor/gurt-onion
PORT=8099

say()  { printf '\e[1m==> %s\e[0m\n' "$*"; }
die()  { printf '\e[31m==> nah: %s\e[0m\n' "$*" >&2; exit 1; }
(( EUID == 0 )) || die "run it as root: sudo $0"
[[ $PREFIX =~ ^[a-z2-7]+$ ]] || die "ONION_PREFIX can only have a-z and 2-7 (onion addresses are base32)"
command -v systemctl >/dev/null || die "this needs systemd (to keep the site + Tor running)"

# ── 1. packages ──
if command -v apt-get >/dev/null; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq && apt-get install -y -qq tor git python3 gcc make autoconf libsodium-dev >/dev/null
  TOR_USER=debian-tor
elif command -v dnf >/dev/null; then
  dnf install -y -q tor git python3 gcc make autoconf libsodium-devel; TOR_USER=toranon
elif command -v pacman >/dev/null; then
  pacman -S --needed --noconfirm tor git python gcc make autoconf libsodium; TOR_USER=tor
elif command -v zypper >/dev/null; then
  zypper -n -q install tor git python3 gcc make autoconf libsodium-devel; TOR_USER=tor
else die "don't know this distro's package manager (needs: tor git python3 gcc make autoconf libsodium)"; fi
id "$TOR_USER" >/dev/null 2>&1 || TOR_USER=$(ps -o user= -C tor 2>/dev/null | head -n1 || true)
id "${TOR_USER:-x}" >/dev/null 2>&1 || die "couldn't find the user Tor runs as"

# ── 2. the address (mined once, then kept) ──
if [[ -s $HS_DIR/hs_ed25519_secret_key ]]; then
  say "keeping your onion address: $(cat "$HS_DIR/hostname")"
else
  say "mining an onion address that starts with \"$PREFIX\" ⛏️ (one time, uses every CPU core)"
  work=$(mktemp -d)
  git clone -q --depth 1 https://github.com/cathugger/mkp224o.git "$work/mkp224o"
  ( cd "$work/mkp224o" && ./autogen.sh >/dev/null && ./configure -q >/dev/null && make -s >/dev/null )
  "$work/mkp224o/mkp224o" -q -n 1 -d "$work/keys" "$PREFIX"
  key=$(find "$work/keys" -mindepth 1 -maxdepth 1 -type d -name "$PREFIX*.onion" | head -n1)
  [[ -n $key ]] || die "mkp224o didn't find an address"
  install -d -m 700 -o "$TOR_USER" -g "$TOR_USER" "$HS_DIR"
  install -m 600 -o "$TOR_USER" -g "$TOR_USER" "$key"/hs_ed25519_secret_key "$key"/hs_ed25519_public_key "$key"/hostname "$HS_DIR"/
  rm -rf "$work"
  say "your onion: $(cat "$HS_DIR/hostname") 🧅"
fi

# ── 3. the site, built from the repo (the updater runs this part again) ──
install -d "$HOME_DIR"
cat > "$HOME_DIR/build.sh" <<EOF
#!/usr/bin/env bash
# rebuilds the onion copy of gurtproject.org from the repo (gurt-onion-update.service runs it)
set -euo pipefail
cd "$HOME_DIR"
if [[ -d repo/.git ]]; then git -C repo fetch -q --depth 1 origin main && git -C repo reset -q --hard origin/main
else git clone -q --depth 1 "$REPO" repo; fi
cd repo
python3 tools/gen-index.py >/dev/null
cp install.sh gurt deps.map vibes.map gh-only.map keys.map packs.map site/ 2>/dev/null || true
rm -rf "$HOME_DIR/site.new" && cp -r site "$HOME_DIR/site.new"
rm -rf "$HOME_DIR/site.old"; [[ -d $HOME_DIR/site ]] && mv "$HOME_DIR/site" "$HOME_DIR/site.old"
mv "$HOME_DIR/site.new" "$HOME_DIR/site"; rm -rf "$HOME_DIR/site.old"
EOF
chmod 755 "$HOME_DIR/build.sh"
say "building the site from $REPO"
"$HOME_DIR/build.sh"

# ── 4. serve it: a small web server on localhost, Tor in front ──
cat > /etc/systemd/system/gurt-onion-web.service <<EOF
[Unit]
Description=gurtproject.org's onion copy (local web server, Tor serves it)
After=network.target
[Service]
ExecStart=/usr/bin/env python3 -m http.server $PORT --bind 127.0.0.1 --directory $HOME_DIR/site
DynamicUser=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
NoNewPrivileges=yes
Restart=always
[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/gurt-onion-update.service <<EOF
[Unit]
Description=rebuild gurtproject.org's onion copy from the repo
After=network-online.target
[Service]
Type=oneshot
ExecStart=$HOME_DIR/build.sh
EOF
cat > /etc/systemd/system/gurt-onion-update.timer <<EOF
[Unit]
Description=rebuild gurtproject.org's onion copy every 6 hours
[Timer]
OnBootSec=5min
OnUnitActiveSec=6h
RandomizedDelaySec=20min
[Install]
WantedBy=timers.target
EOF

TORRC=/etc/tor/torrc; [[ -f $TORRC ]] || TORRC=/etc/tor/torrc.d/gurt-onion.conf
mkdir -p "${TORRC%/*}"; touch "$TORRC"
if ! grep -q "HiddenServiceDir $HS_DIR" "$TORRC"; then
  printf '\n# gurtproject.org on Tor (tools/onion.sh)\nHiddenServiceDir %s/\nHiddenServicePort 80 127.0.0.1:%s\n' "$HS_DIR" "$PORT" >> "$TORRC"
fi

systemctl daemon-reload
systemctl enable --now gurt-onion-web.service gurt-onion-update.timer >/dev/null
systemctl enable tor >/dev/null 2>&1 || true
systemctl restart tor
sleep 3
systemctl is-active -q gurt-onion-web.service || die "the web server didn't start: journalctl -u gurt-onion-web"
systemctl is-active -q tor || die "Tor didn't start: journalctl -u tor"

ONION=$(cat "$HS_DIR/hostname")
say "gurtproject.org is on Tor ✅ (it can take a minute or two to show up)"
cat <<EOF

  open it in Tor Browser:   http://$ONION
  install GURT over Tor:    torsocks curl -fsSL http://$ONION/install.sh | sh

  back up $HS_DIR (the secret key): it's the only copy of this address.
  to have Tor Browser offer it on gurtproject.org, put this in site/index.html's <head>:
    <meta http-equiv="onion-location" content="http://$ONION">
EOF

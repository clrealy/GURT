# patcher-of-all recipe: steam-shortcuts
DESC="Add non-Steam games to Steam in one go (+ artwork from SteamGridDB if u have a key)"
URL="https://www.steamgriddb.com"
# settings the GUI shows: VAR|type|label|extra|saved-in-file  (types: choice text dir check secret edit)
OPTIONS=(
  'steam-shortcuts.list|edit|Games list|'
  'STEAMGRIDDB_KEY|secret|SteamGridDB API key (for artwork)||steamgriddb.key'
)
# games go in ~/.config/patcher-of-all/steam-shortcuts.list, one per line:
#   Name | /path/to/game-or-launcher | optional launch options
# artwork: put a SteamGridDB API key (steamgriddb.com/profile/preferences/api) in
#   ~/.config/patcher-of-all/steamgriddb.key   or set STEAMGRIDDB_KEY

_SS_LIST="$POA_CONFIG/steam-shortcuts.list"

_ss_roots() {
  local r
  for r in "$HOME/.steam/steam" "$HOME/.local/share/Steam" \
           "$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam" \
           "$HOME/snap/steam/common/.local/share/Steam"; do
    [[ -d "$r/userdata" ]] && readlink -f "$r"
  done | awk '!seen[$0]++'
}

_ss_steam_running() { pgrep -x steam >/dev/null 2>&1 || pgrep -x steamwebhelper >/dev/null 2>&1; }

_ss_py() { # _ss_py <apply|check|revert>
  local key="${STEAMGRIDDB_KEY:-}" roots
  [[ -z "$key" && -f "$POA_CONFIG/steamgriddb.key" ]] && key="$(tr -d '[:space:]' < "$POA_CONFIG/steamgriddb.key")"
  mapfile -t roots < <(_ss_roots)
  SS_KEY="$key" python3 -I - "$1" "$_SS_LIST" "$POA_BACKUP" "${roots[@]}" <<'PY'
import sys, os, zlib, json, shutil, urllib.request, urllib.parse, time
mode, listfile, backup, roots = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
TAG = "patcher-of-all"

# ---- binary vdf: entries are [key, type, value]; type 0=map 1=str 2=int32 3=float 7=uint64
def rstr(b, i):
    j = b.index(b"\0", i); return b[i:j].decode("utf-8", "replace"), j + 1
def rmap(b, i):
    out = []
    while True:
        t = b[i]; i += 1
        if t == 8: return out, i
        k, i = rstr(b, i)
        if t == 0:   v, i = rmap(b, i)
        elif t == 1: v, i = rstr(b, i)
        elif t == 2: v = int.from_bytes(b[i:i+4], "little", signed=True); i += 4
        elif t == 3: v = b[i:i+4]; i += 4
        elif t == 7: v = int.from_bytes(b[i:i+8], "little"); i += 8
        else: raise ValueError(f"unknown vdf type {t}")
        out.append([k, t, v])
def wmap(m):
    o = bytearray()
    for k, t, v in m:
        o.append(t); o += k.encode() + b"\0"
        if t == 0:   o += wmap(v)
        elif t == 1: o += v.encode() + b"\0"
        elif t == 2: o += int(v).to_bytes(4, "little", signed=True)
        elif t == 3: o += v
        elif t == 7: o += int(v).to_bytes(8, "little")
    o.append(8); return bytes(o)
def get(m, k, d=None):
    for e in m:
        if e[0].lower() == k.lower(): return e[2]
    return d

def load(path):
    if not os.path.exists(path): return [["shortcuts", 0, []]]
    b = open(path, "rb").read()
    return rmap(b, 0)[0] if b else [["shortcuts", 0, []]]
def save(path, top):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"; open(tmp, "wb").write(wmap(top)); os.replace(tmp, path)

def wanted():
    out = []
    if not os.path.exists(listfile): return out
    for line in open(listfile):
        line = line.split("#", 1)[0].strip()
        if not line: continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2 or not parts[0] or not parts[1]: continue
        out.append((parts[0], os.path.expanduser(parts[1]), parts[2] if len(parts) > 2 else ""))
    return out

def appid(exe_q, name):
    return zlib.crc32((exe_q + name).encode()) | 0x80000000
def signed(u): return u - 2**32 if u >= 2**31 else u

def ours(e): return TAG in [x[2] for x in get(e[2], "tags", [])]

def users():
    for r in roots:
        ud = os.path.join(r, "userdata")
        for u in sorted(os.listdir(ud)):
            if u.isdigit() and u != "0": yield os.path.join(ud, u, "config")

KEY = os.environ.get("SS_KEY", "")
def sgdb(path):
    req = urllib.request.Request("https://www.steamgriddb.com/api/v2" + path,
                                 headers={"Authorization": "Bearer " + KEY, "User-Agent": "patcher-of-all"})
    with urllib.request.urlopen(req, timeout=20) as r: return json.load(r)
def art(name, aid, griddir, made):
    if not KEY: return None
    try:
        res = sgdb("/search/autocomplete/" + urllib.parse.quote(name)).get("data") or []
        if not res: print(f"  no SteamGridDB match for {name}"); return None
        gid, icon = res[0]["id"], None
        kinds = [("/grids/game/%d?dimensions=600x900", "p"), ("/grids/game/%d?dimensions=920x430,460x215", ""),
                 ("/heroes/game/%d", "_hero"), ("/logos/game/%d", "_logo"), ("/icons/game/%d", "_icon")]
        os.makedirs(griddir, exist_ok=True)
        for url, suf in kinds:
            d = (sgdb(url % gid).get("data") or [])
            if not d: continue
            src = d[0]["url"]; ext = os.path.splitext(urllib.parse.urlparse(src).path)[1] or ".png"
            dest = os.path.join(griddir, f"{aid}{suf}{ext}")
            with urllib.request.urlopen(urllib.request.Request(src, headers={"User-Agent": "patcher-of-all"}), timeout=30) as r, open(dest, "wb") as f:
                shutil.copyfileobj(r, f)
            made.append(dest)
            if suf == "_icon": icon = dest
        print(f"  artwork for {name} ✓")
        return icon
    except Exception as e:
        print(f"  artwork for {name} failed: {e}"); return None

games = wanted()
if mode == "check":
    if not games: sys.exit(1)
    for cfg in users():
        names = {get(e[2], "AppName") or get(e[2], "appname") for e in get(load(os.path.join(cfg, "shortcuts.vdf")), "shortcuts", []) if ours(e)}
        if any(g[0] not in names for g in games if os.path.exists(g[1])): sys.exit(1)
    sys.exit(0)

manifest_path = os.path.join(backup, "artwork.json")
made = json.load(open(manifest_path)) if os.path.exists(manifest_path) else []

for cfg in users():
    path = os.path.join(cfg, "shortcuts.vdf")
    bk = os.path.join(backup, cfg.replace("/", "_") + ".vdf")
    top = load(path); sc = get(top, "shortcuts")
    if sc is None: sc = []; top = [["shortcuts", 0, sc]]
    if mode == "apply" and os.path.exists(path) and not os.path.exists(bk): shutil.copy2(path, bk)
    if mode == "revert":
        kept = [e for e in sc if not ours(e)]; gone = len(sc) - len(kept)
        sc[:] = kept
        for i, e in enumerate(sc): e[0] = str(i)
        save(path, top); print(f"removed {gone} shortcut(s) from {cfg}")
        continue
    have = {get(e[2], "AppName") or get(e[2], "appname") for e in sc if ours(e)}
    for name, exe, opts in games:
        if name in have: continue
        if not os.path.exists(exe): print(f"  {exe} doesn't exist, skipping {name}"); continue
        exe_q = '"%s"' % exe; aid = appid(exe_q, name)
        icon = art(name, aid, os.path.join(cfg, "grid"), made) or ""
        sc.append([str(len(sc)), 0, [
            ["appid", 2, signed(aid)], ["AppName", 1, name], ["Exe", 1, exe_q],
            ["StartDir", 1, '"%s"' % os.path.dirname(exe)], ["icon", 1, icon], ["ShortcutPath", 1, ""],
            ["LaunchOptions", 1, opts], ["IsHidden", 2, 0], ["AllowDesktopConfig", 2, 1], ["AllowOverlay", 2, 1],
            ["OpenVR", 2, 0], ["Devkit", 2, 0], ["DevkitGameID", 1, ""], ["DevkitOverrideAppID", 2, 0],
            ["LastPlayTime", 2, 0], ["FlatpakAppID", 1, ""], ["tags", 0, [["0", 1, TAG]]]]])
        print(f"added {name}")
    save(path, top)

if mode == "revert":
    for f in made:
        try: os.remove(f)
        except OSError: pass
    made = []
json.dump(made, open(manifest_path, "w"))
PY
}

poa_detect() { [[ -n "$(_ss_roots)" ]] && command -v python3 >/dev/null; }

poa_check() { [[ -f "$_SS_LIST" ]] && _ss_py check; }

poa_apply() {
  if [[ ! -s "$_SS_LIST" ]]; then
    mkdir -p "$POA_CONFIG"
    printf '%s\n' "# Name | /path/to/game-or-launcher | optional launch options" \
                  "# Minecraft | /usr/bin/prismlauncher" > "$_SS_LIST"
    echo "made $_SS_LIST, add ur games there then run apply again"; return 1
  fi
  _ss_steam_running && { echo "close Steam first, it overwrites shortcuts when it quits"; return 1; }
  _ss_py apply && echo "done, open Steam to see them"
}

poa_revert() {
  _ss_steam_running && { echo "close Steam first"; return 1; }
  _ss_py revert
}

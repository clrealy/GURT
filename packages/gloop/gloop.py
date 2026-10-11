#!/usr/bin/env python3
"""
Gloop - one-click mashups & mods for Linux (melty.gg-style).

  gloop                 open the app window (falls back to `list` with no display)
  gloop gui --browser   open it in your browser instead
  gloop web [--port N]  just run the server and open a browser tab
  gloop list            show available mashups
  gloop play <id>       install (if needed) + launch a mashup
  gloop install <id>    install without launching
  gloop uninstall <id>  remove it and put every file back how it was
  gloop add <file|url>  add a mashup manifest (.json)

Mashups live in ~/.local/share/gloop/mashups/*.json. Two kinds:

  Minecraft (Fabric):
    {"id": "speed-craft", "name": "Speed Craft", "type": "minecraft",
     "minecraft_version": "latest",          # or e.g. "1.21.1"
     "mods": ["fabric-api", "sodium"]}       # Modrinth slugs

  Steam game (works with Proton games too):
    {"id": "my-mod", "name": "My Mod", "type": "steam", "steam_appid": 400,
     "files": [{"url": "https://...", "dest": "portal/custom/thing.vpk",
                "sha256": "optional"}]}

Minecraft mashups get their own isolated instance folder + launcher profile,
so your normal .minecraft never gets touched. Steam mashups back up any file
they overwrite and restore it on uninstall.
"""
import argparse
import http.server
import secrets
import webbrowser
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

APP = "gloop"
VERSION = "0.2.0"
UA = f"gloop/{VERSION} (linux mashup launcher)"
DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / APP
MASHUP_DIR = DATA / "mashups"
INST_DIR = DATA / "instances"
BACKUP_DIR = DATA / "backups"
STATE_FILE = DATA / "state.json"

FABRIC_META = "https://meta.fabricmc.net/v2"
MODRINTH = "https://api.modrinth.com/v2"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

SAMPLES = {
    "speed-craft.json": {
        "id": "speed-craft",
        "name": "Speed Craft",
        "type": "minecraft",
        "description": "Latest Minecraft on Fabric with performance mods. Good first test.",
        "games": [{"name": "Minecraft"}],
        "minecraft_version": "latest",
        "mods": ["fabric-api", "sodium", "lithium"],
    },
    "_example-steam.json": {
        "id": "example-steam",
        "name": "Example Steam Mashup (template)",
        "type": "steam",
        "description": "Template - files starting with _ are ignored. Copy + edit me.",
        "steam_appid": 400,
        "files": [{"url": "https://example.com/mod.vpk", "dest": "portal/custom/mod.vpk"}],
    },
}

_log_hook = None


def log(msg):
    line = f"[gloop] {msg}"
    print(line, flush=True)
    if _log_hook:
        _log_hook(line)


# ---------------------------------------------------------------- utils

def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def download(url, dest, sha512=None, sha256=None):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    h512, h256 = hashlib.sha512(), hashlib.sha256()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        while chunk := r.read(65536):
            f.write(chunk)
            h512.update(chunk)
            h256.update(chunk)
    if sha512 and h512.hexdigest() != sha512.lower():
        tmp.unlink()
        raise RuntimeError(f"hash mismatch for {dest.name} (sha512) - refusing to install")
    if sha256 and h256.hexdigest() != sha256.lower():
        tmp.unlink()
        raise RuntimeError(f"hash mismatch for {dest.name} (sha256) - refusing to install")
    tmp.replace(dest)


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"installed": {}}


def save_state(state):
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_FILE)


def validate(m):
    if not isinstance(m, dict):
        raise ValueError("manifest must be a JSON object")
    if not ID_RE.match(str(m.get("id", ""))):
        raise ValueError("manifest needs an 'id' (lowercase letters, numbers, dashes)")
    if m.get("type") == "minecraft":
        if not isinstance(m.get("mods"), list) or not m["mods"]:
            raise ValueError("minecraft mashup needs a 'mods' list of Modrinth slugs")
    elif m.get("type") == "steam":
        if not isinstance(m.get("steam_appid"), int):
            raise ValueError("steam mashup needs a numeric 'steam_appid'")
        if not isinstance(m.get("files"), list) or not m["files"]:
            raise ValueError("steam mashup needs a 'files' list")
    else:
        raise ValueError("'type' must be 'minecraft' or 'steam'")
    m.setdefault("name", m["id"])
    return m


def load_mashups():
    MASHUP_DIR.mkdir(parents=True, exist_ok=True)
    for fname, data in SAMPLES.items():
        p = MASHUP_DIR / fname
        if not p.exists():
            p.write_text(json.dumps(data, indent=2))
    out = {}
    for p in sorted(MASHUP_DIR.glob("*.json")):
        if p.name.startswith("_"):
            continue
        try:
            m = validate(json.loads(p.read_text()))
            out[m["id"]] = m
        except (ValueError, json.JSONDecodeError) as e:
            log(f"skipping {p.name}: {e}")
    return out


# ------------------------------------------------------------ minecraft

def mc_dir():
    return Path(os.environ.get("GLOOP_MINECRAFT_DIR", Path.home() / ".minecraft"))


def latest_stable(url):
    for v in http_json(url):
        if v.get("stable"):
            return v["version"]
    raise RuntimeError(f"no stable version found at {url}")


def install_minecraft(m):
    game = m.get("minecraft_version", "latest")
    if game in (None, "", "latest"):
        game = latest_stable(f"{FABRIC_META}/versions/game")
    loader = latest_stable(f"{FABRIC_META}/versions/loader")
    log(f"Minecraft {game} + Fabric loader {loader}")

    vid = f"fabric-loader-{loader}-{game}"
    vdir = mc_dir() / "versions" / vid
    created_version = False
    if not (vdir / f"{vid}.json").exists():
        profile = http_json(f"{FABRIC_META}/versions/loader/{game}/{loader}/profile/json")
        vdir.mkdir(parents=True, exist_ok=True)
        (vdir / f"{vid}.json").write_text(json.dumps(profile, indent=2))
        created_version = True

    inst = INST_DIR / m["id"]
    mods = inst / "mods"
    mods.mkdir(parents=True, exist_ok=True)
    rec = {"type": "minecraft", "instance": str(inst), "profile": f"gloop-{m['id']}",
           "version_id": vid, "created_version": created_version, "mods": []}
    try:
        for slug in m["mods"]:
            q = urllib.parse.urlencode({"loaders": json.dumps(["fabric"]),
                                        "game_versions": json.dumps([game])})
            try:
                vers = http_json(f"{MODRINTH}/project/{urllib.parse.quote(slug)}/version?{q}")
            except urllib.error.HTTPError as e:
                log(f"  ! {slug}: not found on Modrinth ({e.code}), skipping")
                continue
            if not vers:
                log(f"  ! {slug}: no Fabric build for {game} yet, skipping")
                continue
            files = vers[0]["files"]
            f = next((x for x in files if x.get("primary")), files[0])
            download(f["url"], mods / f["filename"], sha512=f.get("hashes", {}).get("sha512"))
            rec["mods"].append(f["filename"])
            log(f"  + {slug} ({f['filename']}) verified")

        lp = mc_dir() / "launcher_profiles.json"
        data = json.loads(lp.read_text()) if lp.exists() else {"profiles": {}, "version": 3}
        data.setdefault("profiles", {})[rec["profile"]] = {
            "name": f"{m['name']} [gloop]", "type": "custom", "lastVersionId": vid,
            "gameDir": str(inst), "icon": "Crafting_Table",
            "created": now_iso(), "lastUsed": now_iso(),
        }
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text(json.dumps(data, indent=2))
    except Exception:
        uninstall_minecraft(rec, {})
        raise
    return rec


def uninstall_minecraft(rec, others):
    shutil.rmtree(rec["instance"], ignore_errors=True)
    lp = mc_dir() / "launcher_profiles.json"
    if lp.exists():
        try:
            data = json.loads(lp.read_text())
            if data.get("profiles", {}).pop(rec["profile"], None) is not None:
                lp.write_text(json.dumps(data, indent=2))
        except json.JSONDecodeError:
            log("couldn't read launcher_profiles.json, left it alone")
    still_used = any(o.get("version_id") == rec["version_id"] for o in others.values())
    if rec.get("created_version") and not still_used:
        shutil.rmtree(mc_dir() / "versions" / rec["version_id"], ignore_errors=True)


def launch_minecraft(m, rec):
    for cmd in ("minecraft-launcher", "minecraft"):
        if shutil.which(cmd):
            subprocess.Popen([cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            log(f"opened the launcher - pick the '{m['name']} [gloop]' profile and hit Play")
            return
    log(f"no Minecraft launcher found on PATH. open yours and pick '{m['name']} [gloop]'")
    log(f"(Prism/MultiMC: make a Fabric {rec['version_id'].split('-')[-1]} instance and "
        f"point it at {rec['instance']})")


# ---------------------------------------------------------------- steam

def steam_roots():
    home = Path.home()
    cands = [home / ".steam/steam", home / ".local/share/Steam",
             home / ".var/app/com.valvesoftware.Steam/.local/share/Steam"]
    if os.environ.get("GLOOP_STEAM_DIR"):
        cands.insert(0, Path(os.environ["GLOOP_STEAM_DIR"]))
    seen, out = set(), []
    for c in cands:
        if c.exists():
            r = c.resolve()
            if r not in seen:
                seen.add(r)
                out.append(r)
    return out


def library_paths():
    libs = []
    for root in steam_roots():
        libs.append(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            libs += [Path(p) for p in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(errors="ignore"))]
    out = []
    for lib in libs:
        if lib not in out:
            out.append(lib)
    return out


def find_game(appid):
    for lib in library_paths():
        acf = lib / "steamapps" / f"appmanifest_{appid}.acf"
        if acf.exists():
            mm = re.search(r'"installdir"\s+"([^"]+)"', acf.read_text(errors="ignore"))
            if mm:
                return lib / "steamapps" / "common" / mm.group(1)
    return None


def install_steam(m):
    game = find_game(m["steam_appid"])
    if not game or not game.exists():
        url = f"https://store.steampowered.com/app/{m['steam_appid']}"
        raise RuntimeError(f"game {m['steam_appid']} isn't installed. grab it: {url}")
    game = game.resolve()
    backup = BACKUP_DIR / m["id"]
    rec = {"type": "steam", "appid": m["steam_appid"], "game": str(game),
           "backup": str(backup), "files": []}
    try:
        for f in m["files"]:
            dest = (game / f["dest"]).resolve()
            if game not in dest.parents:
                raise RuntimeError(f"blocked sketchy path outside the game folder: {f['dest']}")
            rel = dest.relative_to(game)
            entry = {"rel": str(rel), "backed_up": False}
            if dest.exists():
                (backup / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, backup / rel)
                entry["backed_up"] = True
            rec["files"].append(entry)
            download(f["url"], dest, sha256=f.get("sha256"))
            log(f"  + {rel}")
    except Exception:
        uninstall_steam(rec, {})
        raise
    return rec


def uninstall_steam(rec, _others):
    game, backup = Path(rec["game"]), Path(rec["backup"])
    for e in reversed(rec["files"]):
        dest = game / e["rel"]
        if e["backed_up"] and (backup / e["rel"]).exists():
            shutil.copy2(backup / e["rel"], dest)
        else:
            dest.unlink(missing_ok=True)
    shutil.rmtree(backup, ignore_errors=True)


def launch_steam(m, _rec):
    url = f"steam://rungameid/{m['steam_appid']}"
    opener = shutil.which("xdg-open") or shutil.which("steam")
    if not opener:
        raise RuntimeError(f"couldn't find xdg-open or steam - open Steam and launch app {m['steam_appid']}")
    subprocess.Popen([opener, url],stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    log("launching through Steam")


# ------------------------------------------------------------- actions

INSTALLERS = {"minecraft": install_minecraft, "steam": install_steam}
UNINSTALLERS = {"minecraft": uninstall_minecraft, "steam": uninstall_steam}
LAUNCHERS = {"minecraft": launch_minecraft, "steam": launch_steam}


def get(mid):
    ms = load_mashups()
    if mid not in ms:
        raise RuntimeError(f"no mashup called '{mid}'. try `gloop list`")
    return ms[mid]


def do_install(mid):
    m = get(mid)
    state = load_state()
    if mid in state["installed"]:
        log(f"{m['name']} already installed")
        return m, state["installed"][mid]
    log(f"installing {m['name']}...")
    rec = INSTALLERS[m["type"]](m)
    state["installed"][mid] = rec
    save_state(state)
    log(f"{m['name']} installed")
    return m, rec


def do_play(mid):
    m, rec = do_install(mid)
    LAUNCHERS[m["type"]](m, rec)


def do_uninstall(mid):
    state = load_state()
    rec = state["installed"].pop(mid, None)
    if not rec:
        log(f"'{mid}' isn't installed")
        return
    UNINSTALLERS[rec["type"]](rec, state["installed"])
    save_state(state)
    log(f"uninstalled '{mid}' - everything's back how it was")


def do_add(src):
    if re.match(r"^https?://", src):
        req = urllib.request.Request(src, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            m = json.load(r)
    else:
        m = json.loads(Path(src).read_text())
    m = validate(m)
    MASHUP_DIR.mkdir(parents=True, exist_ok=True)
    (MASHUP_DIR / f"{m['id']}.json").write_text(json.dumps(m, indent=2))
    log(f"added '{m['id']}' - run `gloop play {m['id']}`")


def do_list():
    ms, installed = load_mashups(), load_state()["installed"]
    if not ms:
        print("no mashups yet. add one with `gloop add file.json`")
    for mid, m in ms.items():
        tag = "installed" if mid in installed else m["type"]
        print(f"  {mid:<22} {m['name']}  [{tag}]")
        if m.get("description"):
            print(f"  {'':<22} {m['description']}")




# -------------------------------------------------------------- web app

LOGS = []
JOBS = {}
JOB_LOCK = threading.Lock()
TOKEN = secrets.token_urlsafe(24)
BUSY = ("installing", "starting", "removing")

AGENT_INSTRUCTIONS = """You are building a mashup for Gloop, a Linux mod launcher.
Reply with ONE JSON object only, no extra text. Pick the shape that fits:

Minecraft (Fabric) mashup:
{"id": "lowercase-with-dashes", "name": "Cool Name", "type": "minecraft",
 "description": "one sentence on what it plays like",
 "games": [{"name": "Minecraft"}],
 "minecraft_version": "latest",
 "mods": ["fabric-api", "<more Modrinth project slugs>"]}

Steam game mashup:
{"id": "lowercase-with-dashes", "name": "Cool Name", "type": "steam",
 "description": "one sentence",
 "games": [{"name": "Game", "steam_appid": 123}],
 "steam_appid": 123,
 "files": [{"url": "https://direct-download-link", "dest": "path/inside/game/folder",
            "sha256": "hash of the file"}]}

Rules:
- Only use Modrinth slugs for real Fabric mods (check modrinth.com). Always include fabric-api.
- Steam "dest" paths are relative to the game's install folder and can't leave it.
- Only link files from places the mod author publishes them, and include sha256.
- Keep "id" short, lowercase, letters/numbers/dashes.

What I want:
"""


def web_log(line):
    LOGS.append(line)


def cover_for(m):
    if m.get("cover"):
        return m["cover"]
    appids = [g.get("steam_appid") for g in m.get("games", []) if isinstance(g, dict)]
    appids.append(m.get("steam_appid"))
    for a in appids:
        if isinstance(a, int):
            return f"https://cdn.cloudflare.steamstatic.com/steam/apps/{a}/header.jpg"
    return None


def mashup_views():
    installed = load_state()["installed"]
    out = []
    for mid, m in load_mashups().items():
        games = [g.get("name", "?") for g in m.get("games", []) if isinstance(g, dict)]
        out.append({"id": mid, "name": m["name"], "type": m["type"],
                    "description": m.get("description", ""), "games": games,
                    "cover": cover_for(m), "installed": mid in installed,
                    "job": JOBS.get(mid, {"state": "idle", "msg": ""})})
    return out


def start_job(mid, action):
    with JOB_LOCK:
        if JOBS.get(mid, {}).get("state") in BUSY:
            return False
        JOBS[mid] = {"state": "installing" if action == "play" else "removing", "msg": ""}

    def setj(state, msg=""):
        JOBS[mid] = {"state": state, "msg": msg}

    def work():
        try:
            if action == "play":
                m, rec = do_install(mid)
                setj("starting")
                LAUNCHERS[m["type"]](m, rec)
                setj("launched")
            else:
                do_uninstall(mid)
                setj("idle")
        except Exception as e:
            log(f"error: {e}")
            setj("error", str(e))
    threading.Thread(target=work, daemon=True).start()
    return True


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        if ctype == "application/json":
            body = json.dumps(body)
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(data)

    def host_ok(self):
        # blocks DNS-rebinding: only answer to requests addressed to localhost
        return self.headers.get("Host", "").rsplit(":", 1)[0] in ("127.0.0.1", "localhost")

    def do_GET(self):
        if not self.host_ok():
            return self.send(403, {"error": "forbidden"})
        u = urllib.parse.urlparse(self.path)
        if u.path == "/":
            return self.send(200, PAGE.replace("__TOKEN__", TOKEN), "text/html")
        if u.path == "/api/mashups":
            return self.send(200, {"mashups": mashup_views()})
        if u.path == "/api/logs":
            q = urllib.parse.parse_qs(u.query)
            since = int(q.get("since", ["0"])[0] or 0)
            return self.send(200, {"lines": LOGS[since:], "next": len(LOGS)})
        if u.path == "/api/agent":
            return self.send(200, AGENT_INSTRUCTIONS, "text/plain")
        self.send(404, {"error": "not found"})

    def do_POST(self):
        # every action needs the per-session token, so random websites can't poke gloop
        if not self.host_ok() or self.headers.get("X-Gloop-Token") != TOKEN:
            return self.send(403, {"error": "forbidden"})
        n = int(self.headers.get("Content-Length") or 0)
        if n > 1_000_000:
            return self.send(413, {"error": "too big"})
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self.send(400, {"error": "bad json"})
        parts = urllib.parse.urlparse(self.path).path.strip("/").split("/")
        try:
            if len(parts) == 3 and parts[:2] in (["api", "play"], ["api", "uninstall"]):
                mid = urllib.parse.unquote(parts[2])
                get(mid)
                ok = start_job(mid, parts[1])
                return self.send(200 if ok else 409, {"ok": ok})
            if parts == ["api", "create"]:
                m = validate(body)
                MASHUP_DIR.mkdir(parents=True, exist_ok=True)
                (MASHUP_DIR / f"{m['id']}.json").write_text(json.dumps(m, indent=2))
                log(f"created mashup '{m['id']}'")
                return self.send(200, {"ok": True, "id": m["id"]})
        except (ValueError, RuntimeError) as e:
            return self.send(400, {"error": str(e)})
        self.send(404, {"error": "not found"})


# ------------------------------------------------------ native window
# a real app window: GTK WebKit (most desktops) or Qt WebEngine (KDE), then pywebview.
# no toolkit? a chromium-style --app window, then your normal browser.

def find_toolkit():
    kde = "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
    for tk in (["qt", "gtk", "pywebview"] if kde else ["gtk", "qt", "pywebview"]):
        try:
            if tk == "gtk":
                import gi
                gi.require_version("Gtk", "3.0")
                for v in ("4.1", "4.0"):
                    try:
                        gi.require_version("WebKit2", v)
                        break
                    except ValueError:
                        continue
                else:
                    raise ImportError("no WebKit2")
                from gi.repository import Gtk, WebKit2  # noqa: F401
                return "gtk"
            if tk == "qt":
                try:
                    from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
                    return "qt6"
                except ImportError:
                    from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
                    return "pyside6"
            if tk == "pywebview":
                import webview  # noqa: F401
                return "pywebview"
        except Exception:
            continue
    return None


def app_icon():
    here = Path(__file__).resolve().parent
    for c in (here / "gloop.png", here.parent / "share/pixmaps/gloop.png",
              Path("/usr/local/share/pixmaps/gloop.png"), Path("/usr/share/pixmaps/gloop.png")):
        if c.is_file():
            return str(c)
    return None


def native_window(tk, url):
    title, w, h, icon = "Gloop", 1180, 800, app_icon()
    if tk == "gtk":
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import GLib, Gtk, WebKit2
        GLib.set_prgname("gloop")
        GLib.set_application_name(title)
        win = Gtk.Window(title=title)
        win.set_default_size(w, h)
        if icon:
            try:
                win.set_icon_from_file(icon)
            except Exception:
                pass
        view = WebKit2.WebView()
        view.get_settings().set_enable_developer_extras(False)
        view.load_uri(url)
        win.add(view)

        def on_close(*_):
            try:   # end WebKit's page process first: some Mesa versions crash on exit otherwise
                view.terminate_web_process()
            except Exception:
                pass
            return False
        win.connect("delete-event", on_close)
        win.connect("destroy", Gtk.main_quit)
        win.show_all()
        Gtk.main()
    elif tk in ("qt6", "pyside6"):
        if tk == "qt6":
            from PyQt6.QtCore import QUrl
            from PyQt6.QtGui import QIcon
            from PyQt6.QtWebEngineWidgets import QWebEngineView
            from PyQt6.QtWidgets import QApplication
        else:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QIcon
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from PySide6.QtWidgets import QApplication
        app = QApplication(["gloop"])
        app.setApplicationName(title)
        app.setDesktopFileName("gloop")
        if icon:
            app.setWindowIcon(QIcon(icon))
        view = QWebEngineView()
        view.setWindowTitle(title)
        view.resize(w, h)
        view.load(QUrl(url))
        view.show()
        app.exec()
    elif tk == "pywebview":
        import webview
        webview.create_window(title, url, width=w, height=h)
        webview.start()


def open_app_window(url):
    for b in ("chromium", "chromium-browser", "google-chrome-stable", "google-chrome",
              "brave", "brave-browser", "microsoft-edge-stable", "vivaldi-stable"):
        if shutil.which(b):
            subprocess.Popen([b, f"--app={url}", "--window-size=1180,800", "--class=gloop"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return
    webbrowser.open(url)


def run_web(port=7777, open_browser=True, native=False):
    global _log_hook
    _log_hook = web_log
    load_mashups()
    try:
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    tk = find_toolkit() if native else None
    print(f"[gloop] running at {url}" + (f" (app window: {tk})" if tk else "  (ctrl+c to quit)"), flush=True)
    if tk:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            native_window(tk, url)   # blocks until the window closes, then gloop quits
            return
        except Exception as e:
            print(f"[gloop] app window failed ({e}), using a browser window instead", flush=True)
            open_app_window(url)
            try:
                threading.Event().wait()
            except KeyboardInterrupt:
                print("\n[gloop] bye")
            return
    if open_browser:
        threading.Timer(0.4, lambda: (open_app_window if native else webbrowser.open)(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[gloop] bye")


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gloop</title>
<style>
:root{--bg:#0e0c14;--panel:#17141f;--panel2:#211c2d;--ink:#f3f0fa;--dim:#9d95b3;--goo:#b6ff3b;--goo2:#6be04a;--bad:#ff5d73;--r:16px}
*{box-sizing:border-box}html,body{margin:0}[hidden]{display:none!important}
body{background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;min-height:100vh}
a{color:var(--goo)}
header{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:22px;padding:14px 28px;background:rgba(14,12,20,.85);backdrop-filter:blur(10px);border-bottom:1px solid #ffffff10}
.logo{font-weight:900;font-size:24px;letter-spacing:-1px;color:var(--goo);display:flex;align-items:center;gap:8px}
.blob{width:26px;height:26px;border-radius:46% 54% 60% 40%/50% 40% 60% 50%;background:radial-gradient(circle at 35% 30%,#eaffb5,var(--goo) 40%,var(--goo2));box-shadow:0 0 18px #b6ff3b66;animation:wob 4s ease-in-out infinite}
@keyframes wob{50%{border-radius:58% 42% 40% 60%/45% 60% 40% 55%}}
nav{display:flex;gap:6px}
nav button{background:none;border:0;color:var(--dim);font:inherit;font-weight:600;padding:8px 14px;border-radius:999px;cursor:pointer}
nav button.on{background:var(--panel2);color:var(--ink)}
.spacer{flex:1}
.logbtn{background:var(--panel2);border:0;color:var(--dim);border-radius:999px;padding:8px 14px;cursor:pointer;font:inherit}
.hero{padding:56px 28px 24px;max-width:1180px;margin:auto}
.hero h1{font-size:clamp(34px,6vw,64px);line-height:1;margin:0 0 14px;letter-spacing:-2px}
.hero h1 span{color:var(--goo)}
.hero p{color:var(--dim);max-width:560px;margin:0;font-size:17px}
main{max-width:1180px;margin:auto;padding:12px 28px 120px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:20px}
.card{background:var(--panel);border-radius:var(--r);overflow:hidden;display:flex;flex-direction:column;border:1px solid #ffffff0d;transition:transform .15s,border-color .15s}
.card:hover{transform:translateY(-3px);border-color:#b6ff3b55}
.cover{aspect-ratio:460/215;background:#221d30 center/cover no-repeat;position:relative}
.cover.mc{background:linear-gradient(#5fae3b 0 30%,#4a8a2e 30% 34%,#8b5a2b 34%);}
.cover.mc::after{content:"";position:absolute;inset:0;background-image:linear-gradient(90deg,#0000001a 50%,transparent 50%),linear-gradient(#0000001a 50%,transparent 50%);background-size:24px 24px}
.cover.none{background:radial-gradient(circle at 30% 30%,#3a2f55,#17141f)}
.badge{position:absolute;top:10px;left:10px;background:#000a;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:700;z-index:1}
.badge.inst{background:var(--goo);color:#111}
.body{padding:14px 16px 16px;display:flex;flex-direction:column;gap:6px;flex:1}
.title{font-weight:800;font-size:18px}
.games{color:var(--goo);font-size:13px;font-weight:600}
.desc{color:var(--dim);font-size:14px;flex:1}
.row{display:flex;gap:8px;margin-top:8px;align-items:center}
.play{flex:1;border:0;border-radius:12px;padding:11px;font:inherit;font-weight:800;cursor:pointer;background:var(--goo);color:#111;transition:filter .15s}
.play:hover{filter:brightness(1.1)}
.play[disabled]{background:var(--panel2);color:var(--ink);cursor:progress}
.play.err{background:var(--bad);color:#fff}
.ghost{border:1px solid #ffffff22;background:none;color:var(--dim);border-radius:12px;padding:10px 12px;cursor:pointer;font:inherit}
.ghost:hover{color:var(--ink);border-color:#ffffff55}
.err-msg{color:var(--bad);font-size:13px}
.empty{color:var(--dim);text-align:center;padding:60px 0}
.panel{background:var(--panel);border-radius:var(--r);padding:22px;border:1px solid #ffffff0d;margin-bottom:20px}
.panel h2{margin:0 0 4px}.panel p{color:var(--dim);margin:0 0 16px}
label{display:block;font-size:13px;color:var(--dim);margin:12px 0 4px;font-weight:600}
input,select,textarea{width:100%;background:var(--bg);border:1px solid #ffffff1f;color:var(--ink);border-radius:10px;padding:10px 12px;font:inherit}
textarea{min-height:90px;font-family:ui-monospace,monospace;font-size:13px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:20px}
@media(max-width:800px){.two{grid-template-columns:1fr}header{padding:12px 16px;gap:10px}.hero,main{padding-left:16px;padding-right:16px}}
#logs{position:fixed;left:0;right:0;bottom:0;height:0;overflow:hidden;background:#07060b;border-top:1px solid #ffffff1a;transition:height .2s;z-index:6}
#logs.open{height:220px}
#logs pre{margin:0;padding:12px 20px;height:100%;overflow:auto;font-size:12px;color:#c9c2dc}
#toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%) translateY(80px);background:var(--goo);color:#111;padding:10px 18px;border-radius:999px;font-weight:700;transition:transform .2s;z-index:7}
#toast.show{transform:translateX(-50%) translateY(0)}
</style></head><body>
<header>
  <div class="logo"><div class="blob"></div>gloop</div>
  <nav>
    <button data-tab="discover" class="on">Discover</button>
    <button data-tab="mine">My mashups</button>
    <button data-tab="create">Create</button>
  </nav>
  <div class="spacer"></div>
  <button class="logbtn" id="logbtn">Logs</button>
</header>
<section class="hero" id="hero">
  <h1>Mash your games <span>together.</span></h1>
  <p>Hit Play and Gloop grabs what it needs, sets it up and launches the game. Uninstall puts every file back.</p>
</section>
<main>
  <div class="grid" id="grid"></div>
  <div id="create" hidden>
    <div class="two">
      <div class="panel">
        <h2>Make one yourself</h2><p>Fill this in and it shows up in Discover.</p>
        <label>Name</label><input id="c-name" placeholder="Speedy Skyblock">
        <label>Description</label><input id="c-desc" placeholder="What it plays like">
        <label>Type</label>
        <select id="c-type"><option value="minecraft">Minecraft (Fabric mods)</option><option value="steam">Steam game (files)</option></select>
        <div id="c-mc">
          <label>Minecraft version</label><input id="c-ver" value="latest">
          <label>Modrinth mod slugs (comma or new line)</label><textarea id="c-mods">fabric-api</textarea>
        </div>
        <div id="c-steam" hidden>
          <label>Steam app ID</label><input id="c-appid" placeholder="400">
          <label>Files: one per line as  url | path/in/game | sha256</label><textarea id="c-files"></textarea>
        </div>
        <div class="row"><button class="play" id="c-save">Create mashup</button></div>
      </div>
      <div class="panel">
        <h2>Build it with your AI</h2><p>Copy the instructions, paste them into Claude (or any AI) with your idea, then paste back the JSON it gives you.</p>
        <div class="row"><button class="ghost" id="c-copy">Copy AI instructions</button></div>
        <label>Paste the JSON here</label><textarea id="c-json" style="min-height:220px" placeholder='{"id": "...", ...}'></textarea>
        <div class="row"><button class="play" id="c-import">Import mashup</button></div>
      </div>
    </div>
  </div>
</main>
<div id="logs"><pre id="logtext"></pre></div>
<div id="toast"></div>
<script>
const TOKEN="__TOKEN__";
let tab="discover",data=[],logNext=0;
const $=s=>document.querySelector(s);
const LABEL={idle:"▶ Play",installing:"Installing…",starting:"Starting…",launched:"✓ Launched — play again",removing:"Removing…",error:"Retry"};
function toast(t){const e=$("#toast");e.textContent=t;e.classList.add("show");clearTimeout(e._t);e._t=setTimeout(()=>e.classList.remove("show"),2600)}
function mk(tag,cls,txt){const e=document.createElement(tag);if(cls)e.className=cls;if(txt!=null)e.textContent=txt;return e}
async function post(url,body){const r=await fetch(url,{method:"POST",headers:{"X-Gloop-Token":TOKEN,"Content-Type":"application/json"},body:JSON.stringify(body||{})});let j={};try{j=await r.json()}catch(e){}if(!r.ok)throw new Error(j.error||("HTTP "+r.status));return j}
async function load(){try{data=(await (await fetch("/api/mashups")).json()).mashups;render()}catch(e){}}
function card(m){
  const c=mk("div","card"),cv=mk("div","cover");
  if(m.cover){cv.style.backgroundImage=`url("${encodeURI(m.cover)}")`}else cv.classList.add(m.type==="minecraft"?"mc":"none");
  const b=mk("span","badge"+(m.installed?" inst":""),m.installed?"Installed":(m.type==="minecraft"?"Minecraft":"Steam"));cv.append(b);
  const body=mk("div","body");
  body.append(mk("div","title",m.name));
  if(m.games.length)body.append(mk("div","games",m.games.join(" + ")));
  body.append(mk("div","desc",m.description||""));
  const st=m.job.state,row=mk("div","row"),p=mk("button","play"+(st==="error"?" err":""),LABEL[st]||"▶ Play");
  if(["installing","starting","removing"].includes(st))p.disabled=true;
  p.onclick=()=>act(m.id,"play");row.append(p);
  if(m.installed){const u=mk("button","ghost","Uninstall");u.onclick=()=>{if(confirm(`Uninstall ${m.name}? Every file goes back how it was.`))act(m.id,"uninstall")};row.append(u)}
  body.append(row);
  if(st==="error"&&m.job.msg)body.append(mk("div","err-msg",m.job.msg));
  c.append(cv,body);return c}
function render(){
  const g=$("#grid");$("#create").hidden=tab!=="create";g.hidden=tab==="create";$("#hero").hidden=tab!=="discover";
  if(tab==="create")return;
  const list=tab==="mine"?data.filter(m=>m.installed):data;g.replaceChildren();
  if(!list.length){g.append(mk("div","empty",tab==="mine"?"Nothing installed yet. Hit Play on something in Discover.":"No mashups yet. Make one in Create."));return}
  list.forEach(m=>g.append(card(m)))}
async function act(id,a){try{await post(`/api/${a}/${encodeURIComponent(id)}`);load()}catch(e){toast(e.message)}}
async function logs(){try{const j=await (await fetch("/api/logs?since="+logNext)).json();if(j.lines.length){const pre=$("#logtext");pre.textContent+=j.lines.join("\n")+"\n";pre.scrollTop=pre.scrollHeight}logNext=j.next}catch(e){}}
document.querySelectorAll("nav button").forEach(b=>b.onclick=()=>{document.querySelectorAll("nav button").forEach(x=>x.classList.toggle("on",x===b));tab=b.dataset.tab;render()});
$("#logbtn").onclick=()=>$("#logs").classList.toggle("open");
$("#c-type").onchange=e=>{$("#c-mc").hidden=e.target.value!=="minecraft";$("#c-steam").hidden=e.target.value==="minecraft"};
const slug=s=>s.toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-+|-+$/g,"").slice(0,60);
async function create(m){try{const j=await post("/api/create",m);toast(`Added ${j.id} ✨`);await load();document.querySelector('nav button[data-tab="discover"]').click()}catch(e){toast(e.message)}}
$("#c-save").onclick=()=>{
  const name=$("#c-name").value.trim();if(!name)return toast("give it a name first");
  const m={id:slug(name),name,description:$("#c-desc").value.trim(),type:$("#c-type").value};
  if(m.type==="minecraft"){m.games=[{name:"Minecraft"}];m.minecraft_version=$("#c-ver").value.trim()||"latest";m.mods=$("#c-mods").value.split(/[\s,]+/).filter(Boolean)}
  else{m.steam_appid=parseInt($("#c-appid").value,10);m.games=[{name:name,steam_appid:m.steam_appid}];
    m.files=$("#c-files").value.split("\n").map(l=>l.split("|").map(s=>s.trim())).filter(p=>p[0]).map(([url,dest,sha256])=>sha256?{url,dest,sha256}:{url,dest})}
  create(m)};
$("#c-copy").onclick=async()=>{const t=await (await fetch("/api/agent")).text();try{await navigator.clipboard.writeText(t);toast("Copied — paste it into your AI 📋")}catch(e){$("#c-json").value=t;toast("Couldn't copy, it's in the box")}};
$("#c-import").onclick=()=>{let m;try{m=JSON.parse($("#c-json").value.replace(/^```(json)?|```$/gm,""))}catch(e){return toast("that JSON is busted")}create(m)};
load();logs();setInterval(load,1500);setInterval(logs,1500);
</script></body></html>
"""


# ------------------------------------------------------------------ CLI

def main(argv=None):
    p = argparse.ArgumentParser(prog="gloop", description="one-click mashups & mods for linux")
    p.add_argument("--version", action="version", version=f"gloop {VERSION}")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("list")
    w = sub.add_parser("web")
    w.add_argument("--port", type=int, default=7777)
    w.add_argument("--no-browser", action="store_true")
    g = sub.add_parser("gui")
    g.add_argument("--browser", action="store_true", help="use your browser instead of an app window")
    for name in ("play", "install", "uninstall"):
        sub.add_parser(name).add_argument("id")
    sub.add_parser("add").add_argument("source")
    a = p.parse_args(argv)

    try:
        if a.cmd == "web":
            return run_web(a.port, not a.no_browser)
        if a.cmd in (None, "gui"):
            if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
                return run_web(0, True, native=not getattr(a, "browser", False))
            return do_list()
        if a.cmd == "list":
            return do_list()
        if a.cmd == "add":
            return do_add(a.source)
        {"play": do_play, "install": do_install, "uninstall": do_uninstall}[a.cmd](a.id)
    except (RuntimeError, ValueError, OSError, urllib.error.URLError) as e:
        log(f"error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main() or 0)

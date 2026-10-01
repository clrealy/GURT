#!/usr/bin/env python3
"""GURT GUI 🦆 — a tiny local app for gurt.

Runs a web server on 127.0.0.1 only (random port + secret token), opens it in an app window,
and runs the real `gurt` CLI for everything. No extra packages: just python3 + a browser.
Started by:  gurt gui
"""
import argparse, json, os, re, secrets, shutil, stat, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

TOKEN = secrets.token_urlsafe(24)
GURT = "gurt"
JOBS, JOBS_LOCK = {}, threading.Lock()
LAST_PING = [time.time()]
SPEC_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+°:@/-]{0,200}$")
# files you can drop into the app (same list gurt outsource understands)
DROP_RE = re.compile(r"\.(deb|rpm|pkg\.tar(\.[a-z0-9]+)?|apk|xbps|eopkg|appimage|dmg|exe|msi|snap|flatpak|flatpakref|"
                     r"tar(\.[a-z0-9]+)?|tgz|tbz2?|txz|tzst|zip|7z|gz|xz|bz2|zst)$", re.I)
DROP_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,200}$")
DROP_MAX = 8 << 30   # 8 GiB


def drops_dir():
    d = os.path.join(paths().get("cache") or os.path.expanduser("~/.cache/gurt"), "drops")
    os.makedirs(d, exist_ok=True)
    return d
URL_RE = re.compile(r"^(https?://|git@)[A-Za-z0-9._~:/?#@!$&'()*+,;=%-]{3,300}$|^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
ALLOWED = {  # command → (needs a package arg?, extra flags)
    "install": True, "remove": True, "rollback": True, "hold": True, "unhold": True, "info": True,
    "search": True, "sync": False, "update": False, "upgrade": False, "self-update": False, "outsource": True, "sysup": False,
}
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


# ───────────────────────── jobs ─────────────────────────
class Job:
    def __init__(self, jid, argv, stdin_text=None):
        self.id, self.argv, self.stdin_text = jid, argv, stdin_text
        self.lines, self.done, self.rc = [], False, None
        self.ask = None                 # sudo password prompt waiting for the browser
        self.answer, self.answered = None, threading.Event()
        self.proc = None

    def run(self, askpass):
        env = dict(os.environ, GURT_GUI="1", NO_COLOR="1", SUDO_ASKPASS=askpass,
                   GURT_GUI_URL=f"http://127.0.0.1:{PORT}", GURT_GUI_TOKEN=TOKEN, GURT_GUI_JOB=self.id)
        self.lines.append("$ " + " ".join(["gurt"] + self.argv[1:]))
        try:
            self.proc = subprocess.Popen(self.argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         stdin=subprocess.PIPE if self.stdin_text else subprocess.DEVNULL,
                                         env=env, text=True, bufsize=1,
                                         start_new_session=True)   # no controlling tty → sudo uses askpass
            if self.stdin_text:
                self.proc.stdin.write(self.stdin_text)
                self.proc.stdin.close()
            for line in self.proc.stdout:
                self.lines.append(ANSI.sub("", line.rstrip("\n")))
            self.rc = self.proc.wait()
        except Exception as e:  # noqa
            self.lines.append(f"==> nah: {e}")
            self.rc = 1
        self.done = True


def start_job(argv, stdin_text=None):
    jid = secrets.token_hex(6)
    job = Job(jid, argv, stdin_text)
    with JOBS_LOCK:
        JOBS[jid] = job
    threading.Thread(target=job.run, args=(ASKPASS,), daemon=True).start()
    return job


def write_askpass():
    """sudo -A runs this; it asks the GUI for the password and prints it."""
    d = tempfile.mkdtemp(prefix="gurt-gui-")
    path = os.path.join(d, "askpass")
    with open(path, "w") as f:
        f.write(f"""#!{sys.executable}
import json, os, sys, urllib.request
prompt = " ".join(sys.argv[1:]) or "password"
req = urllib.request.Request(os.environ["GURT_GUI_URL"] + "/askpass?job=" + os.environ.get("GURT_GUI_JOB", ""),
    data=json.dumps({{"prompt": prompt}}).encode(), headers={{"X-Gurt-Token": os.environ["GURT_GUI_TOKEN"], "Content-Type": "application/json"}})
try:
    with urllib.request.urlopen(req, timeout=600) as r:
        ans = json.load(r)
except Exception:
    sys.exit(1)
if ans.get("cancel"):
    sys.exit(1)
sys.stdout.write(ans.get("password", "") + "\\n")
""")
    os.chmod(path, stat.S_IRWXU)
    return path


# ───────────────────────── state (read straight from gurt's files) ─────────────────────────
def kv(path):
    out = {}
    try:
        for line in open(path, encoding="utf-8", errors="replace"):
            if " = " in line:
                k, v = line.rstrip("\n").split(" = ", 1)
                if k in ("alias", "depends", "arch"):
                    out.setdefault(k, []).append(v)
                else:
                    out[k] = v
    except OSError:
        pass
    return out


CONF = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "gurt", "gui.json")


def conf():
    try:
        with open(CONF) as f:
            return json.load(f)
    except Exception:
        return {}


def save_conf(**kw):
    c = conf(); c.update(kw)
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    with open(CONF, "w") as f:
        json.dump(c, f)


def theme():
    t = conf().get("theme")
    return t if t in ("light", "dark") else "auto"


SKINS = ("gurt", "win11", "xp", "w95")


def skin():
    s = conf().get("skin")
    return s if s in SKINS else "gurt"


def paths():
    out = subprocess.run([GURT, "__paths"], capture_output=True, text=True, env=dict(os.environ, NO_COLOR="1")).stdout
    return dict(l.split("=", 1) for l in out.splitlines() if "=" in l)


def state():
    p = paths()
    repo, db = p.get("repo", ""), p.get("db", "")
    main = []
    pkgdir = os.path.join(repo, "packages")
    if os.path.isdir(pkgdir):
        for name in sorted(os.listdir(pkgdir)):
            info = kv(os.path.join(pkgdir, name, ".gurtinfo"))
            if not info or info.get("hidden") == "true" or info.get("secret") == "true":
                continue
            vt, vp, vr = info.get("via_type", ""), info.get("via_pkg", ""), info.get("via_repo", "")
            # where it lands once installed: Flathub/snap/official-repo recipes are kept under that source
            ikey = f"{vt}:{vp}" if vt in ("flatpak", "snap") else f"{vr}:{vp or name}" if vr else name
            main.append({"ikey": ikey, "flatpak": vp if vt == "flatpak" else "", "name": info.get("pkgname", name), "ver": "latest" if info.get("via_repo") else f"{info.get('pkgver','')}-{info.get('pkgrel','')}",
                         "desc": info.get("pkgdesc", ""), "alias": info.get("alias", []), "maintainer": info.get("maintainer", ""),
                         "official": bool(info.get("via_repo")), "category": info.get("category", "")})
    dirt = []
    dirtdir = os.path.join(repo, "dirt")
    if os.path.isdir(dirtdir):
        for name in sorted(os.listdir(dirtdir)):
            info = kv(os.path.join(dirtdir, name, ".gurtinfo"))
            if not info or info.get("hidden") == "true" or info.get("secret") == "true":
                continue
            dirt.append({"name": info.get("pkgname", name), "ver": f"{info.get('pkgver','')}-{info.get('pkgrel','')}",
                         "desc": info.get("pkgdesc", ""), "alias": info.get("alias", []), "maintainer": info.get("maintainer", "")})
    by_ikey = {p["ikey"]: p["name"] for p in main if p["ikey"] != p["name"]}
    installed = []
    if os.path.isdir(db):
        for key in sorted(os.listdir(db)):
            info = kv(os.path.join(db, key, "info"))
            try:
                reason = open(os.path.join(db, key, "reason")).read().strip()
            except OSError:
                reason = ""
            src, name = key.split(":", 1) if ":" in key else ("gurt", key)
            rel = info.get("pkgrel")
            via = ""
            recipe = info.get("recipe") or by_ikey.get(key)   # came from a Main GURT recipe → its origin is GURT
            if recipe and src != "gurt":
                via, src, name = f"{src}/{name}", "gurt", recipe
            installed.append({"key": key, "via": via, "spec": key if src == "gurt" and not via else name if via else f"{src}/{name}", "name": name, "src": src,
                              "ver": info.get("pkgver", "?") + (f"-{rel}" if rel else ""), "desc": info.get("pkgdesc", ""),
                              "reason": reason, "held": os.path.exists(os.path.join(db, key, "held"))})
    # flatpaks you installed without gurt still count as installed
    flatpaks = []
    if shutil.which("flatpak"):
        try:
            flatpaks = subprocess.run(["flatpak", "list", "--app", "--columns=application"], capture_output=True,
                                      text=True, timeout=15).stdout.split()
        except Exception:
            pass
    return {"version": p.get("version", "?"), "pm": p.get("pm", "?"), "dirt": p.get("dirt") == "on", "flatpaks": flatpaks, "wsl": p.get("wsl") == "yes",
            "main": main, "dirtpkgs": dirt, "installed": installed}


# ───────────────────────── http ─────────────────────────
class H(BaseHTTPRequestHandler):
    server_version = "gurt-gui"

    def log_message(self, *a):
        pass

    def _host_ok(self):
        return self.headers.get("Host", "") in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")

    def _auth(self):
        return self._host_ok() and secrets.compare_digest(self.headers.get("X-Gurt-Token", ""), TOKEN)

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else (json.dumps(body) if ctype == "application/json" else body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 65536:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            if not self._host_ok() or not secrets.compare_digest((q.get("t") or [""])[0], TOKEN):
                return self._send(403, "nope 🔒 open GURT with: gurt gui", "text/plain")
            return self._send(200, PAGE.replace("__TOKEN__", TOKEN).replace("__MODE__", MODE).replace("__THEME__", theme()).replace("__SKIN__", skin()).replace("__SFX__", "off" if conf().get("sfx") is False else "on"), "text/html")
        if u.path in ("/icon.png", "/logo.png", "/dirt-logo.png"):
            repo = paths().get("repo", "")
            want = {"/logo.png": "gurt-logo.png", "/dirt-logo.png": "dirt-logo.png"}.get(u.path, "apple-touch-icon.png")
            for f in [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "site", "assets", want),
                      os.path.join(repo, "site", "assets", want)] + (ICONS if want == "apple-touch-icon.png" else []):
                if os.path.isfile(f):
                    return self._send(200, open(f, "rb").read(), "image/png")
            return self._send(404, b"", "image/png")
        if not self._auth():
            return self._send(403, {"error": "bad token"})
        if u.path == "/api/state":
            return self._send(200, state())
        if u.path == "/api/ping":
            LAST_PING[0] = time.time()
            return self._send(200, {"ok": True})
        m = re.fullmatch(r"/api/job/([0-9a-f]+)", u.path)
        if m:
            job = JOBS.get(m.group(1))
            if not job:
                return self._send(404, {"error": "no such job"})
            since = int((q.get("from") or ["0"])[0])
            return self._send(200, {"lines": job.lines[since:], "next": len(job.lines), "done": job.done,
                                    "rc": job.rc, "ask": job.ask})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        if not self._auth():
            return self._send(403, {"error": "bad token"})
        if u.path == "/api/drop":   # a file dropped into the app → saved to the cache, then gurt outsource installs it
            name = re.sub(r"[^A-Za-z0-9._+-]", "_", os.path.basename(unquote(self.headers.get("X-Filename", ""))))[:200].lstrip("._-")
            if not DROP_NAME_RE.match(name) or not DROP_RE.search(name):
                return self._send(400, {"error": "gurt can't install that kind of file 🤔 (.deb .rpm .AppImage .tar.gz .exe .dmg …)"})
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > DROP_MAX:
                return self._send(400, {"error": "that file's empty or way too big"})
            path, left = os.path.join(drops_dir(), name), n
            with open(path + ".part", "wb") as f:
                while left:
                    chunk = self.rfile.read(min(left, 1 << 20))
                    if not chunk:
                        break
                    f.write(chunk); left -= len(chunk)
            if left:
                os.remove(path + ".part")
                return self._send(400, {"error": "the upload got cut off"})
            os.replace(path + ".part", path)
            return self._send(200, {"name": name})
        body = self._body()
        if u.path == "/api/run":
            cmd, arg = body.get("cmd"), (body.get("arg") or "").strip()
            if cmd == "de-list":
                job = start_job([GURT, "de", "list"])
                return self._send(200, {"job": job.id})
            if cmd == "de":
                if not re.fullmatch(r"[a-z0-9]{1,20}", arg):
                    return self._send(400, {"error": "that desktop name looks sus"})
                job = start_job([GURT, "-y", "de", "install", arg])
                return self._send(200, {"job": job.id})
            if cmd == "install-many":
                names = arg.split()
                if not names or len(names) > 200 or any(n.startswith("-") or not SPEC_RE.match(n) for n in names):
                    return self._send(400, {"error": "those names look sus"})
                job = start_job([GURT, "-y", "install", *names])
                return self._send(200, {"job": job.id})
            if cmd == "dropped":
                p = os.path.join(drops_dir(), arg)
                if not DROP_NAME_RE.match(arg) or not DROP_RE.search(arg) or not os.path.isfile(p):
                    return self._send(400, {"error": "that dropped file is gone"})
                job = start_job([GURT, "-y", "outsource", p])
                return self._send(200, {"job": job.id})
            if cmd == "gui-setup":
                job = start_job([GURT, "-y", "gui", "--setup"])
                return self._send(200, {"job": job.id})
            if cmd == "dirt":
                if arg not in ("on", "off"):
                    return self._send(400, {"error": "not allowed"})
                job = start_job([GURT, "dirt", arg], "yes\n" if arg == "on" else None)
                return self._send(200, {"job": job.id})
            if cmd not in ALLOWED:
                return self._send(400, {"error": "not allowed"})
            argv = [GURT, "-y"]
            if body.get("all") and cmd == "search":
                argv.append("-a")
            argv.append(cmd)
            if ALLOWED[cmd]:
                ok = URL_RE.match(arg) if cmd == "outsource" else SPEC_RE.match(arg)
                if not arg or not ok or arg.startswith("-"):
                    return self._send(400, {"error": "that name looks sus"})
                argv.append(arg)
            job = start_job(argv)
            return self._send(200, {"job": job.id})
        if u.path == "/api/sfx":
            save_conf(sfx=bool(body.get("on")))
            return self._send(200, {"ok": True})
        if u.path == "/api/skin":
            if body.get("skin") not in SKINS:
                return self._send(400, {"error": "unknown skin"})
            save_conf(skin=body["skin"])
            return self._send(200, {"ok": True})
        if u.path == "/api/theme":
            t = body.get("theme")
            if t not in ("light", "dark", "auto"):
                return self._send(400, {"error": "light or dark tho"})
            save_conf(theme=t)
            return self._send(200, {"ok": True})
        if u.path == "/api/relaunch":   # reopen as a real app window, then this browser copy bows out
            subprocess.Popen([GURT, "gui"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL, start_new_session=True)
            threading.Timer(3, lambda: os._exit(0)).start()
            return self._send(200, {"ok": True})
        m = re.fullmatch(r"/api/job/([0-9a-f]+)/(pass|cancel)", u.path)
        if m:
            job = JOBS.get(m.group(1))
            if not job:
                return self._send(404, {"error": "no such job"})
            if m.group(2) == "pass":
                job.answer = {"password": str(body.get("password", ""))}
            else:
                job.answer = {"cancel": True}
                if job.proc and job.proc.poll() is None and not job.ask:
                    try:
                        os.killpg(job.proc.pid, 15)
                    except OSError:
                        pass
            job.answered.set()
            return self._send(200, {"ok": True})
        if u.path == "/askpass":   # called by the askpass helper (sudo -A), blocks until you answer in the app
            job = JOBS.get((parse_qs(u.query).get("job") or [""])[0])
            if not job:
                return self._send(404, {"cancel": True})
            job.answered.clear()
            job.answer = None
            job.ask = (body.get("prompt") or "password").strip()
            job.answered.wait(600)
            ans, job.ask, job.answer = job.answer or {"cancel": True}, None, None
            return self._send(200, ans)
        return self._send(404, {"error": "not found"})


# ───────────────────────── a real app window ─────────────────────────
# tries Qt (KDE) → GTK WebKit → pywebview. returns a function that opens the window and blocks until it closes.
def find_toolkit():
    kde = "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
    order = ["qt", "gtk", "pywebview"] if kde else ["gtk", "qt", "pywebview"]
    for tk in order:
        try:
            if tk == "qt":
                try:
                    from PyQt6.QtWidgets import QApplication  # noqa
                    from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa
                    return "qt6"
                except ImportError:
                    from PySide6.QtWidgets import QApplication  # noqa
                    from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa
                    return "pyside6"
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
                from gi.repository import Gtk, WebKit2  # noqa
                return "gtk"
            if tk == "pywebview":
                import webview  # noqa
                return "pywebview"
        except Exception:  # missing bindings, no display, etc
            continue
    return None


def native_window(tk, url, icon):
    title, w, h = "GURT", 1100, 760
    if tk == "gtk":
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk, WebKit2, GLib
        GLib.set_prgname("gurt")
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
        win.connect("destroy", Gtk.main_quit)
        win.show_all()
        Gtk.main()
    elif tk in ("qt6", "pyside6"):
        if tk == "qt6":
            from PyQt6.QtWidgets import QApplication
            from PyQt6.QtWebEngineWidgets import QWebEngineView
            from PyQt6.QtCore import QUrl
            from PyQt6.QtGui import QIcon
        else:
            from PySide6.QtWidgets import QApplication
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QIcon
        app = QApplication(["gurt"])
        app.setApplicationName(title)
        app.setDesktopFileName("gurt")
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


def open_window(url):
    # gurt on Windows (WSL): open it in the Windows browser
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        for cmd in (["wslview", url], ["cmd.exe", "/c", "start", "", url], ["explorer.exe", url]):
            if shutil.which(cmd[0]):
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                return
    for b in ("chromium", "chromium-browser", "google-chrome-stable", "google-chrome", "brave", "brave-browser",
              "microsoft-edge-stable", "vivaldi-stable"):
        if shutil.which(b):
            subprocess.Popen([b, f"--app={url}", "--window-size=1100,760", f"--class=gurt"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return
    opener = shutil.which("xdg-open") or shutil.which("open")
    if opener:
        subprocess.Popen([opener, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    else:
        print(f"open this in your browser: {url}")


def watchdog(server):
    """quit when the window's been closed for a bit (and nothing is running)."""
    while True:
        time.sleep(5)
        busy = any(not j.done for j in JOBS.values())
        if not busy and time.time() - LAST_PING[0] > 45:
            server.shutdown()
            return


def main():
    global GURT, PORT, ASKPASS, ICONS
    ap = argparse.ArgumentParser()
    ap.add_argument("--gurt", default=shutil.which("gurt") or "gurt")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--no-window", action="store_true")
    ap.add_argument("--browser", action="store_true", help="use a browser window even if a native one is possible")
    ap.add_argument("--probe", action="store_true", help="exit 0 if a native app window is possible")
    a = ap.parse_args()
    if a.probe:
        tk = find_toolkit()
        print(tk or "none")
        sys.exit(0 if tk else 1)
    GURT = a.gurt
    here = os.path.dirname(os.path.abspath(__file__))
    ICONS = [os.path.join(here, "..", "site", "assets", "apple-touch-icon.png"), os.path.join(here, "gurt.png"),
             "/usr/local/share/gurt/gurt.png", "/usr/share/gurt/gurt.png",
             os.path.expanduser("~/.local/share/icons/hicolor/256x256/apps/gurt.png")]
    server = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    PORT = server.server_address[1]
    ASKPASS = write_askpass()
    tk = None if (a.no_window or a.browser) else find_toolkit()
    global MODE
    MODE = "native" if tk else "browser"
    url = f"http://127.0.0.1:{PORT}/?t={TOKEN}"
    print(f"GURT is running at {url}" + (f" (app window: {tk})" if tk else ""), flush=True)
    icon = next((f for f in ICONS if os.path.isfile(f)), None)
    try:
        if tk:
            # native window: the server runs in the background, the window owns the main thread
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                native_window(tk, url, icon)
            except Exception as e:  # window toolkit blew up → fall back to a browser window
                print(f"app window failed ({e}), using your browser instead", flush=True)
                MODE = "browser"
                open_window(url)
                watchdog(server)
            if any(not j.done for j in JOBS.values()):
                print("finishing what gurt was doing before quitting…", flush=True)
                while any(not j.done for j in JOBS.values()):
                    time.sleep(0.5)
            server.shutdown()
        else:
            if not a.no_window:
                open_window(url)
            threading.Thread(target=watchdog, args=(server,), daemon=True).start()
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        shutil.rmtree(os.path.dirname(ASKPASS), ignore_errors=True)


PORT, ASKPASS, ICONS, MODE = 0, "", [], "browser"

PAGE = r"""<!doctype html>
<html lang="en" data-theme="__THEME__" data-skin="__SKIN__" data-sfx="__SFX__"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>GURT</title><link rel="icon" href="/icon.png">
<style>
:root{--bg:#f6f5f0;--panel:#fff;--ink:#16161a;--muted:#6b6b76;--line:#e3e1d8;--accent:#f5b400;--accent-ink:#1a1400;--tag:#efece2;--code:#f1efe7;--good:#1f8a4c;--bad:#d12f3f;
  --g:#16161a;--u:#e00000;--r:#00b300;--t:#0038ff}
:root{color-scheme:light dark}:root[data-theme=light]{color-scheme:light}:root[data-theme=dark]{color-scheme:dark}
@media (prefers-color-scheme: dark){:root:not([data-theme=light]){--bg:#0f0f12;--panel:#17171c;--ink:#ecebe6;--muted:#9a99a3;--line:#2a2a31;--accent:#ffc629;--tag:#23232a;--code:#101014;--good:#46c37b;--bad:#ff5a6a;
  --g:#ecebe6;--u:#ff3b3b;--r:#33e06b;--t:#4f7bff}}
:root[data-theme=dark]{--bg:#0f0f12;--panel:#17171c;--ink:#ecebe6;--muted:#9a99a3;--line:#2a2a31;--accent:#ffc629;--tag:#23232a;--code:#101014;--good:#46c37b;--bad:#ff5a6a;
  --g:#ecebe6;--u:#ff3b3b;--r:#33e06b;--t:#4f7bff}
*{box-sizing:border-box}[hidden]{display:none!important}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,"Segoe UI",sans-serif;height:100vh;display:flex;flex-direction:column}
code,.mono{font-family:ui-monospace,"JetBrains Mono","DejaVu Sans Mono",monospace}
header{display:flex;align-items:center;gap:18px;padding:14px 20px;border-bottom:1px solid var(--line);background:var(--panel)}
.logo{font:700 30px/1 Georgia,"Times New Roman",serif;letter-spacing:-.5px}
.logoimg{display:block;height:64px;width:auto;margin:-10px -8px -8px -10px}
@media (prefers-color-scheme: dark){:root:not([data-theme=light]) .logoimg{filter:drop-shadow(0 0 1.5px rgba(255,255,255,.9)) drop-shadow(0 0 1px rgba(255,255,255,.9))}}
:root[data-theme=dark] .logoimg{filter:drop-shadow(0 0 1.5px rgba(255,255,255,.9)) drop-shadow(0 0 1px rgba(255,255,255,.9))}
.srcs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.srcs button{font:13px ui-monospace,monospace;background:var(--panel);border:1px solid var(--line);color:var(--ink);border-radius:999px;padding:5px 12px;cursor:pointer}
.srcs button small{font-family:system-ui,sans-serif;color:var(--muted);margin-left:4px}
.srcs button:hover{border-color:var(--muted)}
.srcs button.on{background:var(--accent);border-color:var(--accent);color:var(--accent-ink);font-weight:700}
.srcs button.on small{color:var(--accent-ink);opacity:.75}
.blurb{color:var(--muted);margin:0 2px 12px}
.srcs button.dirtbtn{background:#141012;color:#f1e9ea;border-color:#3a2a2e}
.srcs button.dirtbtn small{color:#e0314b}
.srcs button.dirtbtn:hover{border-color:#e0314b}
.srcs button.dirtbtn.on{background:#e0314b;border-color:#e0314b;color:#fff}
.srcs button.dirtbtn.on small{color:#fff}
:root.dirt{--bg:#0a0708;--panel:#140d0f;--ink:#f1e9ea;--muted:#a3898d;--line:#332226;--tag:#24161a;--code:#1a1013;--accent:#e0314b;--accent-ink:#fff;--good:#ff7a8c;color-scheme:dark}
.dirtlogo{display:none;height:40px;width:auto;margin:4px 0 6px}
:root.dirt .logoimg{display:none}:root.dirt .dirtlogo{display:block}
#gate .box{background:#120b0d;color:#f1e9ea;text-align:center;border:1px solid #3a2226}
#gate .g18{display:inline-block;font-weight:700;border:2px solid #e0314b;color:#e0314b;border-radius:999px;padding:2px 12px;margin-bottom:12px;font-size:14px}
#gate p{color:#c9b3b7}
#gate .row{justify-content:center}
#gate .yeah{background:#e0314b;color:#fff}#gate .nah{background:#1d1417;color:#f1e9ea}
.logo .g{color:var(--g)}.logo .u{color:var(--u)}.logo .r{color:var(--r)}.logo .t{color:var(--t)}
.ver{color:var(--muted);font-size:12px}
nav{display:flex;gap:6px;margin-left:8px}
nav button{font:inherit;background:none;border:1px solid transparent;color:var(--muted);padding:6px 14px;border-radius:999px;cursor:pointer;white-space:nowrap}
nav button:hover{color:var(--ink);background:var(--tag)}
nav button.on{background:var(--accent);color:var(--accent-ink);font-weight:700}
nav .badge{background:var(--bad);color:#fff;border-radius:999px;font-size:11px;padding:0 6px;margin-left:4px}
.spacer{flex:1}
#appbar{background:var(--tag);color:var(--muted);font-size:13px;padding:6px 20px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
#appbar code{color:var(--ink)}
.btn{font:inherit;font-weight:600;background:var(--accent);color:var(--accent-ink);border:none;border-radius:10px;padding:7px 14px;cursor:pointer;white-space:nowrap}
.btn:hover{filter:brightness(1.06)}.btn:disabled{opacity:.5;cursor:default}
.btn.ghost{background:var(--tag);color:var(--ink)}
.btn.danger{background:var(--bad);color:#fff}
.btn.small{padding:4px 10px;font-size:13px}
main{flex:1;overflow:auto;padding:18px 20px 30px}
.search{display:flex;gap:8px;margin-bottom:14px}
.search input{flex:1;font:inherit;font-size:16px;padding:11px 14px;border-radius:12px;border:2px solid var(--line);background:var(--panel);color:var(--ink);outline:none}
.search input:focus{border-color:var(--accent)}
.hint{color:var(--muted);font-size:13px;margin:-6px 2px 12px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:10px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 14px;display:flex;flex-direction:column;gap:6px}
.card .top{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.name{font-weight:700;font-size:16px}.src{font-family:ui-monospace,monospace;font-size:12px;color:var(--muted)}
.v{font-family:ui-monospace,monospace;font-size:12px;color:var(--good)}
.desc{color:var(--muted);font-size:13.5px;flex:1}
.row{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.chip{background:var(--tag);border-radius:999px;padding:1px 9px;font-size:12px}
.chip.ok{background:color-mix(in srgb,var(--good) 20%,transparent);color:var(--good)}
.empty{color:var(--muted);text-align:center;padding:40px 0}
h2{font-size:18px;margin:4px 0 12px}
#console{border-top:1px solid var(--line);background:var(--code);height:0;transition:height .2s;display:flex;flex-direction:column}
#console.open{height:230px}
#console .bar{display:flex;align-items:center;gap:10px;padding:6px 14px;border-bottom:1px solid var(--line);font-size:13px}
#console pre{margin:0;flex:1;overflow:auto;padding:8px 14px;font-size:12.5px;white-space:pre-wrap;word-break:break-word}
.dot{width:9px;height:9px;border-radius:50%;background:var(--muted)}.dot.run{background:var(--accent);animation:p 1s infinite}.dot.ok{background:var(--good)}.dot.bad{background:var(--bad)}
@keyframes p{50%{opacity:.3}}
dialog{border:none;border-radius:16px;padding:22px;max-width:420px;width:calc(100% - 32px);background:var(--panel);color:var(--ink)}
dialog::backdrop{background:rgba(0,0,0,.55)}
dialog h3{margin:0 0 6px;font-size:20px}dialog p{color:var(--muted);margin:0 0 16px}
dialog input{width:100%;font:inherit;padding:10px 12px;border-radius:10px;border:2px solid var(--line);background:var(--bg);color:var(--ink);margin-bottom:14px;outline:none}
dialog input:focus{border-color:var(--accent)}
dialog .row{justify-content:flex-end}
.lottobtn{background:linear-gradient(90deg,#ff3b3b,#ffc629,#33e06b,#4f7bff);color:#111;font-weight:800}
.btn.big{font-size:16px;padding:12px 20px}
.setuphead{display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:10px}
.setuphead h2{margin:0}
#t-setup .btn.big{background:linear-gradient(90deg,#ff3b3b,#ffc629,#33e06b,#4f7bff);color:#111;font-weight:800}
.bcats{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0 10px}
.bcat{font:inherit;font-size:13px;background:var(--tag);border:1px solid var(--line);color:var(--ink);border-radius:999px;padding:4px 12px;cursor:pointer}
.bcat.on{background:var(--accent);border-color:var(--accent);color:var(--accent-ink);font-weight:700}
.bgroup h3{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:16px 0 8px}
.bgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:8px}
.bapp{display:flex;gap:8px;align-items:flex-start;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:8px 10px;cursor:pointer;font-size:14px;line-height:1.3;min-width:0}
.bapp:hover{border-color:var(--muted)}
.bapp input{margin:2px 0 0;accent-color:var(--accent);flex:none}
.bapp b{display:block;overflow-wrap:anywhere}
.bapp small{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;color:var(--muted);font-size:12px;line-height:1.35;margin-top:2px}
.bapp.on{border-color:var(--accent);background:color-mix(in srgb,var(--accent) 12%,var(--panel))}
.bapp.done{opacity:.6;cursor:default}
#cartcount{flex:1;min-width:0;font-size:14px;line-height:1.35}
#cartbar{position:sticky;bottom:0;display:flex;align-items:center;gap:8px;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin-top:14px;box-shadow:0 -4px 18px rgba(0,0,0,.1)}
#lottowin2{border:2px dashed var(--accent);border-radius:12px;padding:14px;margin-bottom:14px;text-align:center}
#lottowin2 .spin{font:700 20px ui-monospace,monospace;margin-bottom:6px}
#lottowin2 .card{text-align:left;max-width:520px;margin:8px auto 0}
#dropzone{position:fixed;inset:0;z-index:50;display:flex;align-items:center;justify-content:center;background:color-mix(in srgb,var(--bg) 82%,transparent);backdrop-filter:blur(3px);pointer-events:none}
#dropzone div{border:4px dashed var(--accent);border-radius:24px;padding:48px 64px;text-align:center;background:var(--panel);font-size:22px;font-weight:700}
#dropzone small{display:block;font-size:14px;font-weight:400;color:var(--muted);margin-top:8px}
#lottowin{border:2px dashed var(--accent);border-radius:12px;padding:14px;margin-bottom:14px;text-align:center}
#lottowin .spin{font:700 20px ui-monospace,monospace;margin-bottom:6px}
#lottowin .card{text-align:left;max-width:520px;margin:8px auto 0}
.cicada{text-align:center;font:600 14px ui-monospace,monospace;margin:30px 0 10px}

/* ── 🪟 skins ── */
#skinsel{font:inherit;font-size:13px;background:var(--tag);color:var(--ink);border:1px solid var(--line);border-radius:999px;padding:5px 10px;cursor:pointer}
/* Windows 11: Segoe, soft Mica greys, blue accent, follows light/dark */
:root[data-skin=win11]{--bg:#f3f3f3;--panel:#fbfbfb;--ink:#1b1b1b;--muted:#5d5d5d;--line:#e5e5e5;--accent:#005fb8;--accent-ink:#fff;--tag:#f0f0f0;--code:#f9f9f9}
@media (prefers-color-scheme: dark){:root[data-skin=win11]:not([data-theme=light]){--bg:#202020;--panel:#2b2b2b;--ink:#fff;--muted:#c5c5c5;--line:#3a3a3a;--accent:#60cdff;--accent-ink:#000;--tag:#373737;--code:#1c1c1c}}
:root[data-skin=win11][data-theme=dark]{--bg:#202020;--panel:#2b2b2b;--ink:#fff;--muted:#c5c5c5;--line:#3a3a3a;--accent:#60cdff;--accent-ink:#000;--tag:#373737;--code:#1c1c1c}
:root[data-skin=win11] body{font-family:"Segoe UI Variable","Segoe UI",system-ui,sans-serif}
:root[data-skin=win11] header{background:color-mix(in srgb,var(--panel) 85%,transparent);backdrop-filter:blur(30px)}
:root[data-skin=win11] .btn,:root[data-skin=win11] nav button,:root[data-skin=win11] .srcs button,:root[data-skin=win11] .bcat,:root[data-skin=win11] #skinsel{border-radius:4px}
:root[data-skin=win11] .card,:root[data-skin=win11] .bapp,:root[data-skin=win11] .search input{border-radius:8px}
:root[data-skin=win11] .card{box-shadow:0 2px 4px rgba(0,0,0,.04)}
/* Windows XP: Luna blue + that green start button 💀 (always light) */
:root[data-skin=xp]{--bg:#ece9d8;--panel:#fff;--ink:#000;--muted:#444;--line:#7f9db9;--accent:#3c8d0d;--accent-ink:#fff;--tag:#f4f3ee;--code:#fff;--good:#2c7a0b;--bad:#c4271b;color-scheme:light}
:root[data-skin=xp] body{font:13px/1.4 Tahoma,"Trebuchet MS",Verdana,sans-serif}
:root[data-skin=xp] header{background:linear-gradient(#0058ee,#3a93ff 8%,#2e7cf5 40%,#0f5ee6 88%,#0d56d8);border-bottom:2px solid #003c9e;color:#fff}
:root[data-skin=xp] header .ver,:root[data-skin=xp] nav button{color:#fff}
:root[data-skin=xp] nav button:hover{background:rgba(255,255,255,.18)}
:root[data-skin=xp] nav button.on{background:linear-gradient(#5eac56,#3c8d0d 50%,#2f7a0a);border:1px solid #1d5b06;border-radius:0 10px 10px 0;font-style:italic;box-shadow:inset 0 1px 0 rgba(255,255,255,.4)}
:root[data-skin=xp] .btn{border-radius:3px;border:1px solid #003c74;background:linear-gradient(#fff,#ece9d8 85%,#d6d0c5);color:#000;font-weight:400}
:root[data-skin=xp] .btn:not(.ghost):not(.danger):not(.lottobtn){background:linear-gradient(#7ac25d,#3c8d0d 50%,#2f7a0a);color:#fff;border-color:#1d5b06}
:root[data-skin=xp] .card,:root[data-skin=xp] .bapp{border-radius:3px;border:1px solid #7f9db9;box-shadow:inset 0 1px 0 #fff}
:root[data-skin=xp] .card .top{background:linear-gradient(90deg,#d6dff7,#fff);margin:-12px -14px 0;padding:6px 14px;border-bottom:1px solid #b4c8f0}
:root[data-skin=xp] .search input,:root[data-skin=xp] .srcs button,:root[data-skin=xp] .bcat,:root[data-skin=xp] .chip,:root[data-skin=xp] #skinsel{border-radius:2px}
:root[data-skin=xp] #console{background:#000;color:#c0c0c0}
/* Windows 95: grey bevels, navy title bar, teal desktop, zero rounded corners */
:root[data-skin=w95]{--bg:#008080;--panel:#c0c0c0;--ink:#000;--muted:#222;--line:#808080;--accent:#000080;--accent-ink:#fff;--tag:#c0c0c0;--code:#fff;--good:#006400;--bad:#a00000;color-scheme:light}
:root[data-skin=w95] body{font:12px/1.35 "MS Sans Serif","Microsoft Sans Serif",Tahoma,Arial,sans-serif;-webkit-font-smoothing:none}
:root[data-skin=w95] *{border-radius:0!important}
:root[data-skin=w95] header{background:linear-gradient(90deg,#000080,#1084d0);color:#fff;border-bottom:2px solid #000}
:root[data-skin=w95] header .ver,:root[data-skin=w95] nav button{color:#fff}
:root[data-skin=w95] .btn,:root[data-skin=w95] nav button.on,:root[data-skin=w95] .srcs button,:root[data-skin=w95] .bcat,:root[data-skin=w95] #skinsel{background:#c0c0c0;color:#000;font-weight:400;border:2px solid;border-color:#fff #000 #000 #fff;box-shadow:inset -1px -1px #808080,inset 1px 1px #dfdfdf}
:root[data-skin=w95] .btn:active,:root[data-skin=w95] .srcs button.on,:root[data-skin=w95] .bcat.on{border-color:#000 #fff #fff #000;box-shadow:inset 1px 1px #808080}
:root[data-skin=w95] .card,:root[data-skin=w95] .bapp,:root[data-skin=w95] #cartbar,:root[data-skin=w95] dialog{background:#c0c0c0;border:2px solid;border-color:#dfdfdf #000 #000 #dfdfdf;box-shadow:inset -1px -1px #808080,inset 1px 1px #fff}
:root[data-skin=w95] .card .top{background:linear-gradient(90deg,#000080,#1084d0);color:#fff;margin:-12px -14px 0;padding:3px 8px}
:root[data-skin=w95] .card .top .src,:root[data-skin=w95] .card .top .v{color:#dfdfdf}
:root[data-skin=w95] .search input{background:#fff;border:2px solid;border-color:#808080 #fff #fff #808080}
:root[data-skin=w95] h2,:root[data-skin=w95] .hint,:root[data-skin=w95] .blurb,:root[data-skin=w95] .cicada,:root[data-skin=w95] .bgroup h3,:root[data-skin=w95] .setuphead p{color:#fff}
:root[data-skin=xp] .logoimg,:root[data-skin=w95] .logoimg{filter:drop-shadow(0 0 1.5px #fff) drop-shadow(0 0 1px #fff)}
.out-line-err{color:var(--bad)}.out-line-ok{color:var(--good)}
@media (max-width:640px){header{flex-wrap:wrap}nav{margin-left:0}}
</style></head><body>
<header>
  <div><img class="logoimg" src="/logo.png" alt="gurt" onerror="this.hidden=true;this.nextElementSibling.nextElementSibling.hidden=false"><img class="dirtlogo" src="/dirt-logo.png" alt="dirt."><div class="logo" hidden><span class="g">g</span><span class="u">u</span><span class="r">r</span><span class="t">t</span></div><div class="ver" id="ver"></div></div>
  <nav>
    <button data-tab="discover" class="on">🔍 Discover</button>
    <button data-tab="installed">📦 Installed</button>
    <button data-tab="updates">⬆️ Updates<span class="badge" id="ubadge" hidden></span></button>
    <button data-tab="setup">🧰 Setup</button>
    <button data-tab="desktops">🖥️ Desktops</button>
  </nav>
  <div class="spacer"></div>
  <select id="skinsel" title="skin">
    <option value="gurt">🦆 GURT</option><option value="win11">🪟 Windows 11</option><option value="xp">🟩 Windows XP</option><option value="w95">💾 Windows 95</option>
  </select>
  <button class="btn ghost small" id="sfxbtn" title="sound effects"></button>
  <button class="btn ghost small" id="themebtn" title="light / dark"></button>
  <button class="btn ghost small" id="syncbtn" title="gurt sync">↻ sync</button>
</header>
<div id="appbar" hidden><span id="appbartxt">GURT is running in your browser 🌐 want it as a real app window?</span><button class="btn small" id="appbarinst">install app window</button><button class="btn ghost small" id="appbarx">×</button></div>
<main>
  <section id="t-discover">
    <div class="srcs" id="srcs" role="tablist" aria-label="sources">
      <button data-src="gurt" class="on">gurt/ <small>Main GURT</small></button>
      <button data-src="aur">aur/ <small>Arch User Repo</small></button>
      <button data-src="apt">apt/ <small>Debian · Ubuntu</small></button>
      <button data-src="dnf">dnf/ <small>Fedora</small></button>
      <button data-src="zypper">zypper/ <small>openSUSE</small></button>
      <button data-src="pacman">pacman/ <small>Arch</small></button>
      <button data-src="flatpak">flatpak/ <small>Flathub</small></button>
      <button data-src="snap">snap/ <small>Snap Store</small></button>
      <button data-src="dirt" class="dirtbtn">dirt/ <small>18+</small></button>
    </div>
    <p class="blurb" id="blurb" hidden></p>
    <div class="search"><input id="q" placeholder="search Main GURT… (Enter searches every source)" autocomplete="off"><button class="btn" id="qall">search everywhere</button><button class="btn lottobtn" id="lotto" title="win a random app">🎰 lottery</button><button class="btn ghost" id="dropbtn" title="install a .deb, .rpm, AppImage, .exe… you downloaded">📥 install a file</button><input type="file" id="dropin" hidden></div>
    <p class="hint">tip: <code>aur/yay</code>, <code>apt/cowsay</code>, <code>flatpak/gimp</code>… type a full name with a source and hit install</p>
    <div id="direct" hidden class="row" style="margin-bottom:12px"><button class="btn" id="directbtn"></button></div>
    <div id="allres" hidden><h2>everywhere</h2><div class="grid" id="allgrid"></div><h2 style="margin-top:18px">Main GURT</h2></div>
    <div id="lottowin" hidden></div>
    <div class="grid" id="maingrid"></div>
    <div class="grid" id="srcgrid" hidden></div>
    <p class="cicada">Could prime Wifies solve Cicada 3301?</p>
  </section>
  <section id="t-installed" hidden>
    <div class="search"><input id="iq" placeholder="filter installed…" autocomplete="off"></div>
    <div class="grid" id="igrid"></div>
  </section>
  <section id="t-updates" hidden>
    <div class="row" style="margin-bottom:14px"><button class="btn ghost" id="checkbtn">check for updates</button><button class="btn" id="upbtn">⬆️ update everything</button><button class="btn ghost" id="selfbtn">update gurt itself</button></div>
    <div class="grid" id="ugrid"><div class="empty">hit "check for updates" 👆</div></div>
  </section>
  <section id="t-setup" hidden>
    <div class="setuphead"><div><h2>🧰 Build your setup</h2><p class="blurb">tick everything you want, hit install once. works the same on every distro.</p></div>
      <button class="btn big" id="lotto2">🎰 spin the app lottery</button></div>
    <div id="lottowin2" hidden></div>
    <div class="bcats" id="bcats"></div>
    <div id="bgroups"></div>
    <div id="cartbar" hidden><span id="cartcount"></span><span class="spacer"></span><button class="btn ghost small" id="cartclear">clear</button><button class="btn" id="cartgo">install them</button></div>
  </section>
  <section id="t-desktops" hidden>
    <p class="blurb">Desktop environments come straight from your own distro's repos (never from another distro, that breaks stuff). After installing, log out and pick it on the login screen.</p>
    <div class="grid" id="dgrid"><div class="empty">loading desktops… 🖥️</div></div>
  </section>
</main>
<div id="console"><div class="bar"><span class="dot" id="cdot"></span><b id="ctitle">activity</b><span class="spacer"></span><button class="btn ghost small" id="cstop" hidden>stop</button><button class="btn ghost small" id="chide">hide</button></div><pre id="cout"></pre></div>

<div id="dropzone" hidden><div>📥 drop it to install<small>.deb · .rpm · .pkg.tar.zst · AppImage · .tar.gz · .zip · .flatpak · .exe · .dmg — any distro, no box</small></div></div>
<dialog id="confirm"><h3 id="ctitle2"></h3><p id="cbody"></p><div class="row"><button class="btn ghost" id="cno">Nah</button><button class="btn" id="cyes">Yeah</button></div></dialog>
<dialog id="gate" style="padding:0;background:transparent"><div class="box" style="padding:26px 22px"><div class="g18">18+</div><h3>Are you sure?</h3>
  <p>This section of the GURT Repository is 18+ ONLY. Explore at your own risk.</p>
  <div class="row"><button class="btn nah" id="gnah">Nah</button><button class="btn yeah" id="gyeah">Yeah</button></div></div></dialog>
<dialog id="pw"><h3>🔒 password needed</h3><p id="pwprompt">gurt needs your password (sudo) to put files in system folders.</p>
  <form id="pwform"><input type="password" id="pwin" autocomplete="current-password" placeholder="your password"><div class="row"><button type="button" class="btn ghost" id="pwno">cancel</button><button class="btn" type="submit">ok</button></div></form></dialog>

<script>
const T = "__TOKEN__", MODE = "__MODE__";
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const api = (p, body) => fetch(p, body ? {method:"POST", headers:{"X-Gurt-Token":T,"Content-Type":"application/json"}, body:JSON.stringify(body)} : {headers:{"X-Gurt-Token":T}}).then(r => r.json());
let S = {main:[], installed:[]}, busy = false, cur = null;

// ── state ──
async function load(){ S = await api("/api/state"); $("#ver").textContent = `v${S.version} · ${S.pm}${S.wsl ? " · 🪟 Windows" : ""}`;
  document.querySelector('nav button[data-tab="desktops"]').hidden = S.wsl;   /* no Linux desktops on Windows */ renderMain(); renderInstalled(); if (!$("#t-setup").hidden) renderBuilder(); if (typeof SRC !== "undefined" && SRC === "dirt") renderDirt(); }
const inst = spec => {
  const m = S.main.find(p => p.name === spec);
  return S.installed.find(i => i.spec === spec || i.key === spec || (m && i.key === m.ikey) || (i.src === "gurt" && i.name === spec))
    || (m && m.flatpak && (S.flatpaks || []).includes(m.flatpak) ? {external: true} : null);
};

function card({name, src="gurt", ver, desc, extra="", actions=""}){
  return `<div class="card"><div class="top"><span class="name">${esc(name)}</span><span class="src">${esc(src)}/</span><span class="v">${esc(ver||"")}</span></div>
    <div class="desc">${esc(desc||"")}</div>${extra}<div class="row">${actions}</div></div>`;
}
const actBtn = (label, cmd, arg, cls="") => `<button class="btn small ${cls}" data-cmd="${cmd}" data-arg="${esc(arg)}">${label}</button>`;
function installBtns(spec){
  const i = inst(spec);
  if (i && i.external) return `<span class="chip ok" title="installed with flatpak, outside gurt">installed ✓ (flatpak)</span>`;
  return i ? `<span class="chip ok">installed ✓</span>${actBtn("remove","remove",spec,"ghost")}` : actBtn("install","install",spec);
}
function renderMain(){
  const q = $("#q").value.trim().toLowerCase();
  const hits = S.main.filter(p => !q || (p.name+" "+p.desc+" "+p.alias.join(" ")).toLowerCase().includes(q));
  $("#maingrid").innerHTML = hits.length ? hits.map(p => card({name:p.name, ver:p.ver, desc:p.desc,
      extra: p.official ? `<div class="row"><span class="chip">official repo 🔏</span></div>` : "", actions: installBtns(p.name)})).join("")
    : `<div class="empty">nothing in Main GURT matched 😔 — try "search everywhere"</div>`;
  const direct = /^[a-z0-9-]+\/[A-Za-z0-9._+-]+$/.test($("#q").value.trim()) && !/^(https?:)/.test($("#q").value);
  $("#direct").hidden = !direct; if (direct) $("#directbtn").textContent = `install ${$("#q").value.trim()}`;
}
function renderInstalled(){
  const q = $("#iq").value.trim().toLowerCase();
  const list = S.installed.filter(i => !q || (i.spec+" "+i.desc).toLowerCase().includes(q));
  $("#igrid").innerHTML = list.length ? list.map(i => card({name:i.name, src:i.src, ver:i.ver, desc:i.desc,
      extra:`<div class="row">${i.via?`<span class="chip" title="${esc(i.via)}">from GURT 🦆 · via ${esc(i.via.split("/")[0])}</span>`:""}${i.reason==="dep"?'<span class="chip">dependency</span>':""}${i.held?'<span class="chip">held 📌</span>':""}</div>`,
      actions: actBtn("remove","remove",i.spec,"danger") + actBtn("rollback","rollback",i.spec,"ghost") +
        (i.held ? actBtn("unhold","unhold",i.spec,"ghost") : actBtn("hold","hold",i.spec,"ghost"))})).join("")
    : `<div class="empty">${S.installed.length ? "nothing matched" : "nothing installed with gurt yet 👀"}</div>`;
}

// ── running gurt ──
const VERB = {dropped:"Install", de:"Install the desktop", install:"Install", "install-many":"Install", sysup:"Update your whole system", remove:"Remove", rollback:"Roll back", hold:"Hold", unhold:"Unhold", upgrade:"Update everything (your system + apps)", "self-update":"Update gurt", outsource:"Build + install"};
function ask(title, body){ return new Promise(res => { $("#ctitle2").textContent = title; $("#cbody").textContent = body; const d=$("#confirm");
  const done = v => { d.close(); $("#cyes").onclick = $("#cno").onclick = null; res(v); };
  $("#cyes").onclick = () => done(true); $("#cno").onclick = () => done(false); d.onclose = () => res(false); d.showModal(); }); }

async function run(cmd, arg="", {all=false, quiet=false, confirm=true} = {}){
  if (busy) { alert("gurt's still busy with the last thing, hold up ⏳"); return null; }
  if (confirm && VERB[cmd]) {
    const warn = cmd === "outsource" ? " This builds + runs code from that repo — only do it if you trust it." :
                 /^aur\//.test(arg) ? " AUR packages are built from random people's recipes — make sure you trust it." : "";
    if (!await ask(`${VERB[cmd]}${arg ? " " + arg : ""}?`, `gurt will ${cmd} ${arg || ""}.${warn}`)) return null;
  }
  busy = true; setBusyUI(true);
  const r = await api("/api/run", {cmd, arg, all});
  if (r.error) { busy = false; setBusyUI(false); alert(r.error); return null; }
  cur = r.job; let from = 0, lines = [];
  $("#ctitle").textContent = `gurt ${cmd} ${arg}`; $("#cdot").className = "dot run"; if (!quiet) $("#console").classList.add("open");
  if (!quiet) $("#cout").textContent = "";
  let pwShown = false;
  while (true) {
    const j = await api(`/api/job/${cur}?from=${from}`);
    from = j.next; lines.push(...j.lines);
    if (!quiet && j.lines.length) { const o = $("#cout"); o.textContent += j.lines.join("\n") + "\n"; o.scrollTop = o.scrollHeight; }
    if (j.ask && !pwShown) { pwShown = true; askPassword(j.ask); }
    if (!j.ask) pwShown = false;
    if (j.done) { $("#cdot").className = "dot " + (j.rc === 0 ? "ok" : "bad"); if (!quiet) SFX.play(j.rc === 0 ? "ok" : "err"); busy = false; setBusyUI(false); cur = null; await load(); return {rc:j.rc, lines}; }
    await new Promise(r => setTimeout(r, 300));
  }
}
function setBusyUI(on){ $("#cstop").hidden = !on; document.querySelectorAll("[data-cmd], #upbtn, #checkbtn, #selfbtn, #syncbtn, #qall").forEach(b => b.disabled = on); }
function askPassword(prompt){ $("#pwprompt").textContent = "gurt needs your password (sudo) to put files in system folders. " + (prompt.includes("password") ? "" : prompt);
  $("#pwin").value = ""; $("#pw").showModal(); $("#pwin").focus(); }
$("#pwform").addEventListener("submit", async e => { e.preventDefault(); const v = $("#pwin").value; $("#pwin").value = ""; $("#pw").close(); if (cur) await api(`/api/job/${cur}/pass`, {password:v}); });
$("#pwno").addEventListener("click", async () => { $("#pw").close(); if (cur) await api(`/api/job/${cur}/cancel`, {}); });
$("#cstop").addEventListener("click", async () => { if (cur) await api(`/api/job/${cur}/cancel`, {}); });
$("#chide").addEventListener("click", () => $("#console").classList.toggle("open"));

document.addEventListener("click", e => { const b = e.target.closest("[data-cmd]"); if (b && !b.disabled) run(b.dataset.cmd, b.dataset.arg); });

// ── search everywhere (parses `gurt search -a`) ──
// ── source tabs: search one distro's repos ──
const BLURB = {
  aur: "The Arch User Repository — PKGBUILDs gurt builds from source, on any distro.",
  apt: "Debian's packages (.deb). gurt downloads, checks and installs them on whatever you run.",
  dnf: "Fedora's packages (.rpm), installable anywhere.",
  zypper: "openSUSE Tumbleweed's packages — yes, even on Red Star OS 💀",
  pacman: "Arch's official binary packages, installable on non-Arch distros.",
  flatpak: "Flathub apps, sandboxed. gurt sets up flatpak + Flathub for you.",
  snap: "Snap Store apps. gurt sets up snapd for you."};
BLURB.dirt = "DIRT is GURT's mature section (18+). Packages here install with gurt install dirt/<name>.";
let SRC = "gurt";
function renderDirt(){
  const q = $("#q").value.trim().toLowerCase().replace(/^dirt\//, "");
  const list = (S.dirtpkgs || []).filter(p => !q || (p.name + " " + p.desc + " " + (p.alias||[]).join(" ")).toLowerCase().includes(q));
  $("#srcgrid").innerHTML = list.length ? list.map(p => card({name:p.name, src:"dirt", ver:p.ver, desc:p.desc, actions: installBtns(`dirt/${p.name}`)})).join("")
    : `<div class="empty">${(S.dirtpkgs || []).length ? "nothing in DIRT matched" : "DIRT is empty rn 🫥"}</div>`;
}
async function openDirt(){
  const g = $("#gate"); g.showModal(); $("#gnah").focus();
  const yes = await new Promise(res => { $("#gyeah").onclick = () => res(true); $("#gnah").onclick = () => res(false); g.oncancel = () => res(false); });
  g.close(); if (!yes) return;
  if (!S.dirt) { const r = await run("dirt", "on", {quiet:true, confirm:false}); if (!r || r.rc !== 0) return; }
  setSrc("dirt", true);
}
function setSrc(src, gated){
  if (src === "dirt" && !gated) return openDirt();
  SRC = src;
  document.documentElement.classList.toggle("dirt", src === "dirt");
  document.querySelectorAll("#srcs button").forEach(b => b.classList.toggle("on", b.dataset.src === src));
  const main = src === "gurt";
  $("#maingrid").hidden = !main; $("#srcgrid").hidden = main; $("#allres").hidden = true; $("#qall").hidden = !main; $("#lotto").hidden = !main; $("#lottowin").hidden = true;
  $("#blurb").hidden = main; $("#blurb").textContent = BLURB[src] || "";
  $("#q").placeholder = main ? "search Main GURT… (Enter searches every source)" : `search ${src}/… and hit Enter`;
  if (src === "dirt") { renderDirt(); renderMain(); return; }
  if (!main) $("#srcgrid").innerHTML = `<div class="empty">type something and hit Enter to search ${esc(src)} 🔎</div>`;
  if (!main && $("#q").value.trim()) searchSrc();
  renderMain();
}
function parseSearch(lines){
  const res = []; let last = null;
  for (const l of lines) {
    const m = l.match(/^([a-z0-9-]+)\/(\S+) (\S+)(?: \[installed\])?$/);
    if (m) { last = {src:m[1], name:m[2], ver:m[3]}; res.push(last); }
    else if (last && /^ {4}/.test(l)) { last.desc = l.trim(); last = null; }
  }
  return res;
}
async function searchSrc(){
  if (SRC === "dirt") return renderDirt();
  const t = $("#q").value.trim().replace(/^[a-z]+\//, ""); if (!t) return;
  $("#srcgrid").innerHTML = `<div class="empty">searching ${esc(SRC)}… 🔎</div>`;
  const r = await run("search", `${SRC}/${t}`, {quiet:true, confirm:false}); if (!r) return;
  const res = parseSearch(r.lines);
  $("#srcgrid").innerHTML = res.length ? res.slice(0, 120).map(p => card({name:p.name, src:p.src, ver:p.ver, desc:p.desc,
      actions: installBtns(`${p.src}/${p.name}`)})).join("")
    : `<div class="empty">nothing on ${esc(SRC)} matched "${esc(t)}" 😔 ${r.lines.some(l => /unreachable|couldn.t|==> nah:|no package index/.test(l)) ? "(couldn't reach it — check your internet)" : "womp womp"}</div>`;
}
document.querySelectorAll("#srcs button").forEach(b => b.addEventListener("click", () => setSrc(b.dataset.src)));

async function searchAll(){
  if (SRC !== "gurt") return searchSrc();
  const t = $("#q").value.trim(); if (!t) return;
  if (/^(https?:\/\/|git@)/.test(t)) { run("outsource", t); return; }
  $("#allres").hidden = false; $("#allgrid").innerHTML = `<div class="empty">searching every source… 🔎</div>`;
  const r = await run("search", t, {all:true, quiet:true, confirm:false}); if (!r) return;
  const res = parseSearch(r.lines);
  $("#allgrid").innerHTML = res.length ? res.slice(0, 120).map(p => card({name:p.name, src:p.src, ver:p.ver, desc:p.desc,
      actions: installBtns(p.src === "gurt" ? p.name : `${p.src}/${p.name}`)})).join("") : `<div class="empty">nothing anywhere matched "${esc(t)}" 😔 womp womp</div>`;
}
$("#q").addEventListener("input", () => { if (SRC === "dirt") renderDirt(); if (SRC === "gurt") renderMain(); if (!$("#q").value) $("#allres").hidden = true; });
$("#q").addEventListener("keydown", e => { if (e.key === "Enter") searchAll(); });

// ── 🔊 sfx: tiny synth bleeps (WebAudio, no sound files), 🔇 button mutes them ──
const SFX = (() => {
  let ctx = null, on = document.documentElement.dataset.sfx !== "off";
  const tone = (f, t, dur, type = "square", vol = 0.05, f2 = 0) => {
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = type; o.frequency.setValueAtTime(f, t); if (f2) o.frequency.exponentialRampToValueAtTime(f2, t + dur);
    g.gain.setValueAtTime(vol, t); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(ctx.destination); o.start(t); o.stop(t + dur + 0.02);
  };
  const sounds = {
    click:   t => tone(620, t, 0.045, "square", 0.03),
    tick:    t => tone(700 + Math.random() * 600, t, 0.03, "square", 0.025),
    jackpot: t => [523, 659, 784, 1047, 1319].forEach((f, i) => tone(f, t + i * 0.08, 0.18, "triangle", 0.06)),
    copy:    t => { tone(988, t, 0.06, "sine", 0.06); tone(1480, t + 0.06, 0.1, "sine", 0.06); },
    pick:    t => tone(660, t, 0.07, "triangle", 0.05, 990),
    unpick:  t => tone(660, t, 0.07, "triangle", 0.05, 440),
    ok:      t => [784, 1047, 1568].forEach((f, i) => tone(f, t + i * 0.07, 0.14, "triangle", 0.06)),
    err:     t => { tone(196, t, 0.18, "sawtooth", 0.05); tone(147, t + 0.16, 0.28, "sawtooth", 0.05); },
    theme:   t => tone(300, t, 0.22, "sine", 0.05, 900),
    pop:     t => tone(400, t, 0.09, "sine", 0.07, 1200),
  };
  const play = name => {
    if (!on || !sounds[name]) return;
    try {
      ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
      if (ctx.state === "suspended") ctx.resume();
      sounds[name](ctx.currentTime);
    } catch {}
  };
  return { play, get on() { return on; }, set(v) { on = v; } };
})();
const SFX_ROLES = {copy:"copy", scopy:"copy", cartcopy:"copy", lotto:"", lotto2:"", themebtn:"theme", sfxbtn:""};
document.addEventListener("click", e => {
  const b = e.target.closest("button, .src, .bcat, .pkg, nav button, summary");
  if (!b) return;
  const role = b.id in SFX_ROLES ? SFX_ROLES[b.id] : "click";
  if (role) SFX.play(role);
}, true);

$("#sfxbtn").addEventListener("click", () => { SFX.set(!SFX.on); $("#sfxbtn").textContent = SFX.on ? "🔊" : "🔇"; api("/api/sfx", {on:SFX.on}).catch(() => {}); SFX.play("pop"); });
$("#sfxbtn").textContent = SFX.on ? "🔊" : "🔇";
$("#bgroups").addEventListener("change", e => { if (e.target.dataset.n) SFX.play(e.target.checked ? "pick" : "unpick"); });
$("#qall").addEventListener("click", searchAll);
// ── 📥 drop in foreign files (or pick one): gurt figures out what it is and installs it ──
const DROPPABLE = /\.(deb|rpm|pkg\.tar(\.[a-z0-9]+)?|apk|xbps|eopkg|appimage|dmg|exe|msi|snap|flatpak|flatpakref|tar(\.[a-z0-9]+)?|tgz|tbz2?|txz|tzst|zip|7z|gz|xz|bz2|zst)$/i;
async function installFile(f){
  if (!f) return;
  if (!DROPPABLE.test(f.name)) { alert(`gurt can't install "${f.name}" 🤔 — try a .deb, .rpm, AppImage, .tar.gz, .exe, .dmg…`); return; }
  if (busy) { alert("gurt's still busy with the last thing, hold up ⏳"); return; }
  if (!await ask(`Install ${f.name}?`, `gurt figures out what it is and installs it straight onto your system (no box). ${(f.size / 1048576).toFixed(1)} MB. Only install files you trust.`)) return;
  $("#ctitle").textContent = `uploading ${f.name}…`; $("#cdot").className = "dot run"; $("#console").classList.add("open");
  const r = await fetch("/api/drop", {method:"POST", headers:{"X-Gurt-Token":T, "X-Filename":encodeURIComponent(f.name)}, body:f}).then(x => x.json()).catch(() => ({error:"upload failed"}));
  if (r.error) { $("#cdot").className = "dot bad"; alert(r.error); return; }
  await run("dropped", r.name, {confirm:false});
}
$("#dropbtn").addEventListener("click", () => $("#dropin").click());
$("#dropin").addEventListener("change", e => { installFile(e.target.files[0]); e.target.value = ""; });
let dragDepth = 0;
const hasFiles = e => [...(e.dataTransfer?.types || [])].includes("Files");
addEventListener("dragenter", e => { if (!hasFiles(e)) return; e.preventDefault(); if (!dragDepth++) SFX.play("pop"); $("#dropzone").hidden = false; });
addEventListener("dragover", e => { if (hasFiles(e)) e.preventDefault(); });
addEventListener("dragleave", e => { if (hasFiles(e) && --dragDepth <= 0) { dragDepth = 0; $("#dropzone").hidden = true; } });
addEventListener("drop", e => { if (!hasFiles(e)) return; e.preventDefault(); dragDepth = 0; $("#dropzone").hidden = true; installFile(e.dataTransfer.files[0]); });
// 🎰 lottery: spin through Main GURT, land on one, install it if you dare
let spinning = false;
function spinLottery(box, show, after){
  if (spinning || !S.main.length) return;
  const pool = S.main, win = pool[Math.floor(Math.random() * pool.length)];
  box.hidden = false; spinning = true; let i = 0;
  const tick = () => {
    if (i++ < 18) { SFX.play("tick"); box.innerHTML = `<div class="spin">🎰 ${esc(pool[Math.floor(Math.random() * pool.length)].name)}</div>`; return setTimeout(tick, 40 + i * 6); }
    spinning = false; SFX.play("jackpot"); box.innerHTML = show(win); after && after(win);
  };
  tick();
}
$("#lotto").addEventListener("click", () => spinLottery($("#lottowin"),
  win => `<div class="spin">🎉 jackpot!</div>` + card({name:win.name, ver:win.ver, desc:win.desc, actions: installBtns(win.name)})));
// ── 🧰 setup builder: pick a bunch, install them in one go ──
const CATS = {browsers:"🌐 Browsers", chat:"💬 Chat & email", media:"🎬 Media", creative:"🎨 Creative", office:"📚 Office & notes",
  dev:"🧑‍💻 Dev", cli:"⌨️ Terminal tools", gaming:"🎮 Gaming", internet:"📡 Files & remote", system:"⚙️ System", security:"🔐 Security", fun:"🤪 Fun", other:"📦 Other"};
const PICKED = new Set(); let BCAT = "all";
const catOf = p => CATS[p.category] ? p.category : "other";
function renderBuilder(){
  const have = [...new Set(S.main.map(catOf))].sort((a, b) => Object.keys(CATS).indexOf(a) - Object.keys(CATS).indexOf(b));
  $("#bcats").innerHTML = [`<button class="bcat${BCAT === "all" ? " on" : ""}" data-c="all">all (${S.main.length})</button>`]
    .concat(have.map(c => `<button class="bcat${BCAT === c ? " on" : ""}" data-c="${c}">${CATS[c]}</button>`)).join("");
  $("#bgroups").innerHTML = have.filter(c => BCAT === "all" || BCAT === c).map(c => `<div class="bgroup"><h3>${CATS[c]}</h3><div class="bgrid">${
    S.main.filter(p => catOf(p) === c).map(p => {
      const done = inst(p.name), on = PICKED.has(p.name), d = (p.desc || "").replace(/\s*\((Flathub|official repo[^)]*)\)\s*$/, "").replace(/^[^—]*—\s*/, "");
      return `<label class="bapp${on ? " on" : ""}${done ? " done" : ""}" title="${esc(p.desc)}"><input type="checkbox" data-n="${esc(p.name)}"${on || done ? " checked" : ""}${done ? " disabled" : ""}><span><b>${esc(p.name)}</b><small>${done ? "installed ✓" : esc(d)}</small></span></label>`;
    }).join("")}</div></div>`).join("");
  renderCart();
}
function renderCart(){
  const n = PICKED.size; $("#cartbar").hidden = !n;
  $("#cartcount").innerHTML = `<b>${n} app${n === 1 ? "" : "s"} picked</b> · ${esc([...PICKED].sort().join(", "))}`;
}
$("#bcats").addEventListener("click", e => { const b = e.target.closest(".bcat"); if (b) { BCAT = b.dataset.c; renderBuilder(); } });
$("#bgroups").addEventListener("change", e => { const n = e.target.dataset.n; if (!n) return;
  e.target.checked ? PICKED.add(n) : PICKED.delete(n); e.target.closest(".bapp").classList.toggle("on", e.target.checked); renderCart(); });
$("#cartclear").addEventListener("click", () => { PICKED.clear(); renderBuilder(); });
$("#cartgo").addEventListener("click", async () => {
  const names = [...PICKED].sort(); if (!names.length) return;
  const r = await run("install-many", names.join(" "));
  if (r && r.rc === 0) PICKED.clear();
  renderBuilder();
});
// the Setup tab's lottery: lands on an app and ticks it for you
$("#lotto2").addEventListener("click", () => spinLottery($("#lottowin2"), win => {
  return `<div class="spin">🎉 jackpot!</div>` + card({name:win.name, ver:win.ver, desc:win.desc,
    actions: installBtns(win.name) + (inst(win.name) ? "" : ` <button class="btn ghost small" id="lwpick">＋ add to my setup</button>`)});
}, win => { const b = $("#lwpick"); if (b) b.onclick = () => { PICKED.add(win.name); BCAT = catOf(win); renderBuilder(); b.textContent = "added ✓"; }; }));

$("#directbtn").addEventListener("click", () => run("install", $("#q").value.trim()));
$("#iq").addEventListener("input", renderInstalled);

// ── updates ──
async function check(){
  $("#ugrid").innerHTML = `<div class="empty">checking… ⏳</div>`;
  const r = await run("update", "", {confirm:false}); if (!r) return;
  const ups = r.lines.map(l => l.match(/^\s*->\s*(\S+)\s+(\S+) -> (\S+)$/)).filter(Boolean);
  // gurt itself counts as an update too (and goes first — the new gurt might be needed for the rest)
  const selfUp = r.lines.find(l => /is out \(you have|gurt self-update/.test(l));
  const sysM = r.lines.map(l => l.match(/(\d+) system update\(s\) waiting from (\S+)/)).find(Boolean);
  const n = ups.length + (selfUp ? 1 : 0) + (sysM ? 1 : 0);
  $("#ubadge").hidden = !n; $("#ubadge").textContent = n;
  const sv = selfUp && selfUp.match(/gurt (\S+) is out \(you have (\S+)\)/);
  $("#ugrid").innerHTML = !n ? `<div class="empty">everything's up to date, you're chillin 😎</div>`
    : (selfUp ? card({name:"gurt", ver: sv ? `${sv[2]} → ${sv[1]}` : "new version", desc:"gurt itself has an update 🦆", actions: actBtn("update gurt","self-update","")}) : "")
      + (sysM ? card({name:"your system", src:sysM[2], ver:`${sysM[1]} update${sysM[1] === "1" ? "" : "s"}`, desc:`${sysM[1]} package${sysM[1] === "1" ? "" : "s"} from your distro (${sysM[2]}) — "update everything" installs them too`, actions: actBtn("🐧 update system","sysup","")}) : "")
      + ups.map(m => card({name:m[1].split("/").pop(), src:m[1].includes("/") ? m[1].split("/")[0] : "gurt", ver:`${m[2]} → ${m[3]}`, desc:"update available", actions: actBtn("update","install",m[1])})).join("");
}
$("#checkbtn").addEventListener("click", check);
$("#upbtn").addEventListener("click", async () => { if (await run("upgrade")) check(); });
$("#selfbtn").addEventListener("click", () => run("self-update"));
$("#syncbtn").addEventListener("click", () => run("sync", "", {confirm:false}));
// ── light / dark ── (starts on your system's theme, remembers what you pick)
const darkMQ = matchMedia("(prefers-color-scheme: dark)");
const isDark = () => { const t = document.documentElement.dataset.theme; return t === "dark" || (t !== "light" && darkMQ.matches); };
const themeIcon = () => { $("#themebtn").textContent = isDark() ? "☀️ light" : "🌙 dark"; };
$("#themebtn").addEventListener("click", () => {
  const t = isDark() ? "light" : "dark";
  document.documentElement.dataset.theme = t; themeIcon(); api("/api/theme", {theme:t}).catch(() => {});
});
darkMQ.addEventListener("change", themeIcon); themeIcon();
// ── 🪟 skins ── (XP + 95 are always light, like the real thing)
const applySkin = s => { document.documentElement.dataset.skin = s; $("#skinsel").value = s; $("#themebtn").hidden = s === "xp" || s === "w95"; };
$("#skinsel").addEventListener("change", e => { applySkin(e.target.value); api("/api/skin", {skin:e.target.value}).catch(() => {}); });
applySkin(document.documentElement.dataset.skin || "gurt");

// ── tabs ──
document.querySelectorAll("nav button").forEach(b => b.addEventListener("click", () => {
  document.querySelectorAll("nav button").forEach(x => x.classList.toggle("on", x === b));
  for (const t of ["discover","installed","updates","setup","desktops"]) $("#t-"+t).hidden = b.dataset.tab !== t;
  if (b.dataset.tab === "setup") renderBuilder();
  if (b.dataset.tab === "desktops" && !deLoaded) loadDesktops();
}));

// ── desktops (gurt de) ──
let deLoaded = false;
async function loadDesktops(){
  deLoaded = true;
  const r = await run("de-list", "", {quiet:true, confirm:false}); if (!r) { deLoaded = false; return; }
  const des = r.lines.map(l => l.match(/^  (\S+)\s+(.+?)(  \(not in your distro's repos\))?$/)).filter(Boolean)
    .map(m => { const [title, ...rest] = m[2].split(" — "); return {name:m[1], title, desc:rest.join(" — "), ok:!m[3]}; });
  const dm = (r.lines.find(l => /your login screen:/.test(l)) || "").replace(/.*your login screen: /, "").replace(/\)$/, "");
  $("#dgrid").innerHTML = des.length ? des.map(d => card({name:d.title, src:d.name, ver:"", desc:d.desc,
      actions: d.ok ? actBtn("install","de",d.name) : `<span class="chip">not in your distro's repos</span>`})).join("") +
      `<div class="empty" style="grid-column:1/-1;padding:14px 0">your login screen: <b>${esc(dm || "none found")}</b></div>`
    : `<div class="empty">couldn't list desktops 😔</div>`;
}

setInterval(() => api("/api/ping").catch(() => {}), 5000); api("/api/ping");
if (MODE === "browser") {
  $("#appbar").hidden = false; $("#appbarx").onclick = () => $("#appbar").hidden = true;
  $("#appbarinst").onclick = async () => {
    const r = await run("gui-setup", "", {confirm:false}); if (!r) return;
    if (r.rc === 0) {
      $("#appbartxt").textContent = "app window installed ✅ reopening GURT as a real app…"; $("#appbarinst").hidden = true;
      await api("/api/relaunch", {});
      setTimeout(() => { document.body.innerHTML = `<div class="empty" style="padding:80px 20px">GURT reopened in its own window 🦆 you can close this tab</div>`; }, 1500);
    } else { $("#appbartxt").textContent = "couldn't install the app window 😔 check the activity log below"; }
  };
}
load();
</script></body></html>"""

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""GURT GUI 🦆 — a tiny local app for gurt.

Runs a web server on 127.0.0.1 only (random port + secret token), opens it in an app window,
and runs the real `gurt` CLI for everything. No extra packages: just python3 + a browser.
Started by:  gurt gui
"""
import argparse, json, os, re, secrets, shutil, stat, subprocess, sys, tempfile, threading, time, zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

TOKEN = secrets.token_urlsafe(24)
GURT = "gurt"
JOBS, JOBS_LOCK = {}, threading.Lock()
LAST_PING = [time.time()]
LAST_DROP = [0.0, []]   # [when, paths]: files dropped on the app window (WebKitGTK won't hand them to the page)
OPEN_FILE = [""]        # a file GURT was opened with (double-clicking a .gurt)
SPEC_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+°:@/-]{0,200}$")
# files you can drop into the app (same list gurt outsource understands)
DROP_RE = re.compile(r"\.(deb|rpm|pkg\.tar(\.[a-z0-9]+)?|apk|xbps|eopkg|gurt|chrot|appimage|dmg|exe|msi|snap|flatpak|flatpakref|"
                     r"tar(\.[a-z0-9]+)?|tgz|tbz2?|txz|tzst|zip|7z|gz|xz|bz2|zst)$", re.I)
CONV_FMTS = ("deb", "rpm", "pacman", "apk", "xbps", "eopkg", "appimage", "gurt", "chrot", "tar.gz", "zip")
DROP_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,200}$")
DROP_MAX = 8 << 30   # 8 GiB


CONV_EXT = {"deb": ".deb", "rpm": ".rpm", "pacman": ".pkg.tar.zst", "apk": ".apk", "xbps": ".xbps", "eopkg": ".eopkg",
            "appimage": ".AppImage", "gurt": ".gurt", "chrot": ".chrot", "tar.gz": ".tar.gz", "zip": ".zip"}
PKG_EXT_RE = re.compile(r"\.(pkg\.tar(\.[a-z0-9]+)?|tar\.[a-z0-9]+|tgz|deb|rpm|apk|xbps|eopkg|appimage|gurt|chrot|zip|exe|msi|7z)$", re.I)


def zone_dir():   # the Download Zone™: where The Congurter™ drops what it makes
    d = os.path.join(paths().get("cache") or os.path.expanduser("~/.cache/gurt"), "zone")
    os.makedirs(d, exist_ok=True)
    return d


SIG_EXTS = (".sig", ".sig2", ".asc")   # signatures gurt convert puts next to what it makes


def zone_signed(path):   # how a converted file is signed: "inside" it, the ext of the signature next to it, or None
    for ext in SIG_EXTS:
        if os.path.isfile(path + ext):
            return ext
    try:
        with open(path, "rb") as f:
            head = f.read(4 << 20)
        low = path.lower()
        if low.endswith(".deb") and b"_gpgorigin " in head:
            return "inside"
        if low.endswith(".rpm") and head[96:99] == b"\x8e\xad\xe8":   # signature header: look for an RSA/DSA signature tag
            n = int.from_bytes(head[104:108], "big")
            if any(int.from_bytes(head[112 + i * 16:116 + i * 16], "big") in (267, 268) for i in range(min(n, 64))):
                return "inside"
        if low.endswith(".apk") and zlib.decompressobj(31).decompress(head[:65536], 512)[:6] == b".SIGN.":
            return "inside"
        if low.endswith(".appimage") and b"BEGIN PGP SIGNATURE" in head:
            return "inside"
    except (OSError, zlib.error):
        pass
    return None


CROS_DOWNLOADS = "/mnt/chromeos/MyFiles/Downloads"   # ChromeOS's Downloads, once it's shared with Linux


def downloads_dir():
    if os.path.isdir(CROS_DOWNLOADS):
        return CROS_DOWNLOADS
    d = os.path.expanduser("~/Downloads")
    return d if os.path.isdir(d) else os.path.expanduser("~")


def unique_path(d, name):
    stem, ext = name, ""
    m = PKG_EXT_RE.search(name)
    if m:
        stem, ext = name[:m.start()], name[m.start():]
    p, i = os.path.join(d, name), 2
    while os.path.exists(p):
        p = os.path.join(d, f"{stem}-{i}{ext}"); i += 1
    return p


def html_attr(v):
    return v.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def drop_name(path):
    return re.sub(r"[^A-Za-z0-9._+-]", "_", os.path.basename(path))[:200].lstrip("._-")


def drops_dir():
    d = os.path.join(paths().get("cache") or os.path.expanduser("~/.cache/gurt"), "drops")
    os.makedirs(d, exist_ok=True)
    return d
URL_RE = re.compile(r"^(https?://|git@)[A-Za-z0-9._~:/?#@!$&'()*+,;=%-]{3,300}$|^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
ALLOWED = {  # command → (needs a package arg?, extra flags)
    "install": True, "remove": True, "rollback": True, "undo": False, "hold": True, "unhold": True, "info": True,
    "search": True, "sync": False, "update": False, "upgrade": False, "self-update": False, "outsource": True, "sysup": False,
}
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
TOSS_RE = re.compile(r"^(gurt-cache|gurt-rollback|trash|pm-cache|journal|coredumps|cache:[A-Za-z0-9][A-Za-z0-9._+-]{0,100})$")


# ───────────────────────── jobs ─────────────────────────
class Job:
    def __init__(self, jid, argv, stdin_text=None):
        self.id, self.argv, self.stdin_text = jid, argv, stdin_text
        self.lines, self.done, self.rc = [], False, None
        self.ask = None                 # sudo password prompt waiting for the browser
        self.answer, self.answered = None, threading.Event()
        self.proc = None
        # one job can run sudo several times, and sudo's own "remember the password" doesn't always cover all of
        # them (it's per process on some distros), so the job remembers it, in memory, until it ends
        self.pw, self.pw_sudo = None, None

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
        self.pw = self.pw_sudo = None   # forget the password the moment the job's over
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
    data=json.dumps({{"prompt": prompt, "sudo": os.getppid()}}).encode(), headers={{"X-Gurt-Token": os.environ["GURT_GUI_TOKEN"], "Content-Type": "application/json"}})
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


def theme():   # dark by default; "auto" (match the system) and light are still a click away
    t = conf().get("theme", "dark")
    return t if t in ("light", "dark", "auto") else "dark"


SKINS = ("gurt", "win11", "xp", "w95", "vapor", "hacker")
TRACKS = ("auto", "shop", "lofi", "chip", "synth")
LEGENDARY = ("hpa2", "tsudore", "opsec", "oneko", "zsnes", "frozen-bubble")
ACH_IDS = ("legendary", "streak7", "lottery", "compare", "v1", "wizard")
SYNC_SRCS = ("aur", "apt", "dnf", "zypper", "pacman")


def skin():
    s = conf().get("skin")
    return s if s in SKINS else "gurt"


def paths():
    out = subprocess.run([GURT, "__paths"], capture_output=True, text=True, env=dict(os.environ, NO_COLOR="1")).stdout
    return dict(l.split("=", 1) for l in out.splitlines() if "=" in l)


def lotto_spin():   # the same streak file `gurt lottery` uses, so CLI + app share one streak
    import datetime, random
    cfg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    f = os.path.join(cfg, "gurt", "lottery")
    st = {}
    try:
        st = dict(l.strip().split("=", 1) for l in open(f) if "=" in l)
    except OSError:
        pass
    today = datetime.date.today()
    streak, best, last = int(st.get("streak") or 0), int(st.get("best") or 0), st.get("last", "")
    if last != today.isoformat():
        streak = streak + 1 if last == (today - datetime.timedelta(days=1)).isoformat() else 1
    best = max(best, streak)
    os.makedirs(os.path.dirname(f), exist_ok=True)
    with open(f, "w") as fh:
        fh.write(f"last={today.isoformat()}\nstreak={streak}\nbest={best}\n")
    r, leg = random.randrange(1000), min(10 + 5 * (streak - 1), 50)   # legendary: 1% + 0.5%/streak day, max 5%
    rarity = "legendary" if r < leg else "epic" if r < leg + 70 else "rare" if r < leg + 290 else "common"
    return {"streak": streak, "best": best, "rarity": rarity, "legendary": LEGENDARY}


CLOSED_RE = re.compile(r"proprietary|^custom$|licenseref-(?!kde-accepted)|sspl|(^|[- ])n[cd]([- ]|$)|sul-1|freeware|shareware", re.I)
def foss_class(lic):   # same rule as gurt's foss_class: foss | closed | unknown
    l = (lic or "").strip().lower()
    return "unknown" if not l or l.startswith("see ") or l in ("unknown", "other") else "closed" if CLOSED_RE.search(l) else "foss"


def foss_strict():   # gurt foss on
    v = os.environ.get("GURT_FOSS")
    if v is None:
        try:
            v = open(os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "gurt", "foss")).read().strip()
        except OSError:
            v = ""
    return v == "on"


def recipe_trust(info):   # how a Main GURT app gets onto your computer → the badge on its card
    if info.get("via_type") == "flatpak":
        return "flathub"
    if info.get("via_type") == "snap":
        return "snap"
    if info.get("via_repo"):
        return "official"
    src = info.get("source", [])
    src = " ".join(src) if isinstance(src, list) else src
    if "git+" in src:
        return "source"
    if "://" in src:
        return "prebuilt"
    return "gurt"


# ── 🖼 app logos: Flathub's icon or the recipe's icon= (the page loads those); else the app's own desktop icon on this
#    computer (from its .desktop file + your icon theme), served by /appicon/<name>; else the page shows a letter ──
FLATHUB_ICON = "https://dl.flathub.org/repo/appstream/x86_64/icons/128x128/{}.png"   # also in tools/gen-index.py
APP_INDEX = {}    # name → (flatpak id, aliases), filled by state()
ICON_CACHE = {}   # name → (path or None, when)
HOME_DIR = os.path.expanduser("~")
DESKTOP_DIRS = [f"{HOME_DIR}/.local/share/applications", "/usr/local/share/applications", "/usr/share/applications",
                f"{HOME_DIR}/.local/share/flatpak/exports/share/applications", "/var/lib/flatpak/exports/share/applications",
                "/var/lib/snapd/desktop/applications"]
ICON_BASES = [f"{HOME_DIR}/.local/share/icons", f"{HOME_DIR}/.icons", "/usr/local/share/icons", "/usr/share/icons",
              f"{HOME_DIR}/.local/share/flatpak/exports/share/icons", "/var/lib/flatpak/exports/share/icons"]
ICON_SIZES = ("scalable", "256x256", "128x128", "96x96", "64x64", "48x48", "512x512", "32x32")


def theme_icon(name):
    """an icon name (Icon=firefox) → the best file for it in any installed icon theme, or pixmaps"""
    if os.path.isabs(name):
        return name if os.path.isfile(name) and name.lower().endswith((".png", ".svg")) else None
    for base in ICON_BASES:
        try:
            themes = ["hicolor"] + sorted(t for t in os.listdir(base) if t != "hicolor")
        except OSError:
            continue
        for t in themes:
            for size in ICON_SIZES:
                for ext in ("svg", "png") if size == "scalable" else ("png", "svg"):
                    f = os.path.join(base, t, size, "apps", f"{name}.{ext}")
                    if os.path.isfile(f):
                        return f
    for ext in ("png", "svg"):
        f = f"/usr/share/pixmaps/{name}.{ext}"
        if os.path.isfile(f):
            return f
    return None


def desktop_icon(name):
    """the icon of the app called name, from its .desktop file (or an icon that's simply called that)"""
    hit = ICON_CACHE.get(name)
    if hit and (hit[0] or time.time() - hit[1] < 60):
        return hit[0]
    fid, aliases = APP_INDEX.get(name, ("", []))
    want = [w.lower() for w in [fid, name] + list(aliases) if w]
    found = None
    for d in DESKTOP_DIRS:
        try:
            files = [f for f in os.listdir(d) if f.endswith(".desktop")]
        except OSError:
            continue
        for f in files:
            stem = f[:-8].lower()
            if stem in want or any(stem.endswith("." + w) or stem.endswith("_" + w) for w in want):
                try:
                    icon = re.search(r"^Icon=(.+)$", open(os.path.join(d, f), errors="replace").read(), re.M)
                except OSError:
                    icon = None
                found = icon and theme_icon(icon.group(1).strip())
                if found:
                    break
        if found:
            break
    if not found:
        for w in want:
            found = theme_icon(w)
            if found:
                break
    ICON_CACHE[name] = (found, time.time())
    return found


# ── apps you got without gurt (zypper / apt / dnf…, flatpak, snap, a downloaded AppImage, /opt) still count ──
SYS_PKGS = {"key": None, "names": set()}
PM_LIST = {   # pm → (list every installed package's name, the package database to watch for changes)
    "zypper": (["rpm", "-qa", "--qf", "%{NAME}\n"], ("/usr/lib/sysimage/rpm", "/var/lib/rpm")),
    "dnf": (["rpm", "-qa", "--qf", "%{NAME}\n"], ("/usr/lib/sysimage/rpm", "/var/lib/rpm")),
    "yum": (["rpm", "-qa", "--qf", "%{NAME}\n"], ("/var/lib/rpm",)),
    "apt": (["dpkg-query", "-W", "-f=${Package}\n"], ("/var/lib/dpkg/status",)),
    "pacman": (["pacman", "-Qq"], ("/var/lib/pacman/local",)),
    "apk": (["apk", "info"], ("/lib/apk/db/installed",)),
    "xbps": (["xbps-query", "-l"], ("/var/db/xbps",)),
    "eopkg": (["eopkg", "li"], ("/var/lib/eopkg",)),
}


def native_pkgs(pm):
    """every package your distro's package manager installed (cached until its database changes)"""
    cmd, dbs = PM_LIST.get(pm, (None, ()))
    if not cmd or not shutil.which(cmd[0]):
        return set()
    key = (pm, tuple(os.path.getmtime(d) for d in dbs if os.path.exists(d)))
    if SYS_PKGS["key"] == key:
        return SYS_PKGS["names"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return SYS_PKGS["names"]
    names = set()
    for line in out.splitlines():
        w = line.split()
        if not w:
            continue
        n = w[1] if pm == "xbps" and len(w) > 1 else w[0]
        if pm in ("xbps", "apk"):
            n = re.sub(r"-[0-9][^-]*(_[0-9]+)?$", "", n) if pm == "xbps" else n
        names.add(n.lower())
    SYS_PKGS.update(key=key, names=names)
    return names


def owned_by_pm(pm, path):
    """did your package manager put this file there? (so zypper's libreoffice says zypper, not just 'on your PATH')"""
    cmd = {"apt": ["dpkg", "-S"], "zypper": ["rpm", "-qf"], "dnf": ["rpm", "-qf"], "yum": ["rpm", "-qf"],
           "pacman": ["pacman", "-Qo"], "apk": ["apk", "info", "--who-owns"], "xbps": ["xbps-query", "-o"]}.get(pm)
    if not cmd or not shutil.which(cmd[0]):
        return False
    for f in dict.fromkeys((path, os.path.realpath(path))):
        try:
            if subprocess.run(cmd + [f], capture_output=True, timeout=10).returncode == 0:
                return True
        except Exception:
            pass
    return False


def outside_apps(main, pm, flatpaks):
    """Main GURT apps that are on this computer but not from gurt → {name: how}"""
    native = native_pkgs(pm)
    snaps = set()
    if shutil.which("snap"):
        try:
            snaps = {l.split()[0].lower() for l in subprocess.run(["snap", "list"], capture_output=True, text=True, timeout=15).stdout.splitlines()[1:] if l.split()}
        except Exception:
            pass
    onpath = set()
    for d in os.environ.get("PATH", "").split(":"):
        try:
            onpath.update(f.lower() for f in os.listdir(d))
        except OSError:
            pass
    home = os.path.expanduser("~")
    images = []   # AppImages you downloaded yourself
    for d in ("Applications", "Apps", ".local/bin", "bin", "Downloads", "Desktop", "AppImages"):
        try:
            # Obsidian-1.6.7.AppImage → obsidian (the name before the version / arch)
            images += [re.sub(r"[^a-z0-9]", "", re.split(r"[-_ .](?=v?\d|x86|amd64|aarch64|arm64|linux)", f.lower()[:-9])[0])
                       for f in os.listdir(os.path.join(home, d)) if f.lower().endswith(".appimage")]
        except OSError:
            pass
    try:
        opt = {f.lower() for f in os.listdir("/opt")}
    except OSError:
        opt = set()
    fl = set(flatpaks)
    out = {}
    for a in main:
        names = [a["name"].lower()] + [x.lower() for x in a.get("alias", []) if x]
        vp = (a.get("vpkg") or "").lower()
        if a.get("flatpak") and a["flatpak"] in fl:
            out[a["name"]] = "flatpak"
        elif a.get("vtype") == "snap" and vp in snaps:
            out[a["name"]] = "snap"
        elif (vp and a.get("vtype") == "repo" and vp in native) or any(n in native for n in names):
            out[a["name"]] = pm
        elif any(n in snaps for n in names):
            out[a["name"]] = "snap"
        elif any(n in onpath for n in names):
            exe = next(shutil.which(n) for n in names if n in onpath)
            out[a["name"]] = pm if exe and owned_by_pm(pm, exe) else "on your PATH"
        elif any(n in opt for n in names):
            out[a["name"]] = "/opt"
        else:
            squashed = {re.sub(r"[^a-z0-9]", "", n) for n in names}
            if squashed & set(images):
                out[a["name"]] = "AppImage"
    return out


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
            icon = info.get("icon", "") or (FLATHUB_ICON.format(vp) if vt == "flatpak" and vp else "")
            main.append({"ikey": ikey, "flatpak": vp if vt == "flatpak" else "", "vpkg": vp, "icon": icon, "vtype": vt or ("repo" if vr else ""), "name": info.get("pkgname", name), "ver": "latest" if info.get("via_repo") else f"{info.get('pkgver','')}-{info.get('pkgrel','')}",
                         "desc": info.get("pkgdesc", ""), "alias": info.get("alias", []), "maintainer": info.get("maintainer", ""),
                         "official": bool(info.get("via_repo")), "category": info.get("category", ""), "trust": recipe_trust(info),
                         "license": info.get("license", ""), "foss": foss_class(info.get("license")), "url": info.get("url", "")})
    strict = foss_strict()   # mostly free software: closed-source apps come after the free ones, and gurt foss on hides them
    main = sorted((m for m in main if not (strict and m["foss"] != "foss")), key=lambda m: m["foss"] == "closed")
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
    APP_INDEX.update({a["name"]: (a.get("flatpak", ""), a.get("alias", [])) for a in main})
    gurt_keys = {i["key"] for i in installed} | {i["name"] for i in installed if i["src"] == "gurt"}
    outside = {n: how for n, how in outside_apps(main, p.get("pm", ""), flatpaks).items()
               if n not in gurt_keys and not any(a["name"] == n and a["ikey"] in gurt_keys for a in main)}
    return {"version": p.get("version", "?"), "pm": p.get("pm", "?"), "dirt": p.get("dirt") == "on", "flatpaks": flatpaks, "outside": outside, "wsl": p.get("wsl") == "yes", "cros": p.get("cros") == "yes", "audio": audio_ok(),
            "main": main, "fossonly": strict, "dirtpkgs": dirt, "installed": installed, "vibes": vibes(repo), "notify": notify_on(), "dev": p.get("dev", "no")}


def vibes(repo):   # vibes.map: "photoshop|photo editor: gimp krita …" → {"photoshop": [...], "photo editor": [...]}
    out = {}
    for f in (os.path.join(repo, "vibes.map"), os.path.join(os.path.dirname(os.path.abspath(GURT)), "vibes.map")):
        if os.path.isfile(f):
            for line in open(f, encoding="utf-8", errors="replace"):
                if line.startswith("#") or ":" not in line:
                    continue
                keys, apps = line.split(":", 1)
                for k in keys.split("|"):
                    out[k.strip().lower()] = apps.split()
            break
    return out


def notify_on():   # are gurt's update alerts scheduled?
    cfg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    if os.path.exists(os.path.join(cfg, "systemd", "user", "gurt-notify.timer")):
        return True
    try:
        return "gurt notify now" in subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return False


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
                return self._send(403, "nope, open GURT with: gurt gui", "text/plain")
            return self._send(200, PAGE.replace("__TOKEN__", TOKEN).replace("__MODE__", MODE).replace("__THEME__", theme()).replace("__SKIN__", skin()).replace("__SFX__", "off" if conf().get("sfx") is False else "on").replace("__MUSIC__", "off" if conf().get("music") is False else "on").replace("__TRACK__", conf().get("track") if conf().get("track") in TRACKS else "auto").replace("__SEEN__", html_attr(str(conf().get("seen", "")))).replace("__WIZ__", "new" if not conf() or (WIZARD[0] and conf().get("wizard") != "done") else str(conf().get("wizard", ""))).replace("__APP__", "setup" if WIZARD[0] else "gurt").replace("__FROM__", "app" if WIZARD[1] else "").replace("__OPEN__", html_attr(OPEN_FILE[0])), "text/html")
        if u.path in ("/icon.png", "/logo.png", "/dirt-logo.png"):
            repo = paths().get("repo", "")
            want = {"/logo.png": "gurt-logo.png", "/dirt-logo.png": "dirt-logo.png"}.get(u.path, "apple-touch-icon.png")
            for f in [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "site", "assets", want),
                      os.path.join(repo, "site", "assets", want)] + (ICONS if want == "apple-touch-icon.png" else []):
                if os.path.isfile(f):
                    return self._send(200, open(f, "rb").read(), "image/png")
            return self._send(404, b"", "image/png")
        if u.path.startswith("/appicon/"):   # an app's desktop icon from this computer (for the page's logos)
            if not self._host_ok() or not secrets.compare_digest((q.get("t") or [""])[0], TOKEN):
                return self._send(403, b"", "image/png")
            f = desktop_icon(unquote(u.path[9:]))
            if not f:
                return self._send(404, b"", "image/png")
            try:
                return self._send(200, open(f, "rb").read(), "image/svg+xml" if f.endswith(".svg") else "image/png")
            except OSError:
                return self._send(404, b"", "image/png")
        if not self._auth():
            return self._send(403, {"error": "bad token"})
        if u.path == "/api/gurtd":   # GURTd: running? its settings, the end of its log
            running = DAEMON[0]
            if not running:
                try:
                    running = subprocess.run(["systemctl", "--user", "is-active", "--quiet", "gurtd"], timeout=5).returncode == 0
                except Exception:
                    running = False
                running = running or os.path.exists(URL_FILE)
            try:
                log = "".join(open(DAEMON_LOG).readlines()[-12:])
            except OSError:
                log = ""
            c = dconf()
            return self._send(200, {"running": running, "attached": DAEMON[0], "autoupdate": c["autoupdate"] == "on",
                                    "fresh": c["fresh"] == "on", "watch": c["watch"] == "on", "saver": c["saver"] == "on",
                                    "quiet": c["quiet"], "holding": saver_reason(c), "log": log})
        if u.path == "/api/state":
            return self._send(200, state())
        if u.path == "/api/doctor":   # what the setup wizard's system check shows
            env = dict(os.environ, NO_COLOR="1")
            out = subprocess.run([GURT, "utils", "list"], capture_output=True, text=True, timeout=120, env=env)
            utils = [{"name": m.group(2), "ok": m.group(1) == "✓"} for m in re.finditer(r"^\s*([✓✗])\s+(\S+)", out.stdout + out.stderr, re.M)]
            distro = ""
            try:
                osr = dict(l.rstrip("\n").split("=", 1) for l in open("/etc/os-release") if "=" in l)
                distro = osr.get("PRETTY_NAME", osr.get("ID", "")).strip('"')
            except OSError:
                pass
            p = paths()
            return self._send(200, {"distro": distro, "pm": p.get("pm", "?"), "wsl": p.get("wsl") == "yes", "cros": p.get("cros") == "yes", "mode": MODE, "audio": audio_ok(),
                                    "sudo": os.geteuid() == 0 or bool(shutil.which("sudo") or shutil.which("doas")), "utils": utils,
                                    "notify": notify_on(), "version": p.get("version", "?")})
        if u.path == "/api/history":   # gurt history: date \t install|remove \t app \t version [\t txn \t replaced version]
            f = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "gurt", "history")
            try:
                with open(f, encoding="utf-8", errors="replace") as h: lines = h.read().splitlines()[-300:]
            except OSError: lines = []
            items = [dict(zip(("when", "what", "app", "ver", "tx", "was"), l.split("\t"))) for l in lines if l.count("\t") >= 3]
            return self._send(200, {"items": items[::-1]})
        if u.path == "/api/achievements":
            out = subprocess.run([GURT, "achievements", "--tsv"], capture_output=True, text=True, timeout=30, env=dict(os.environ, NO_COLOR="1")).stdout
            items = [dict(zip(("id", "title", "what", "got"), l.split("\t"))) for l in out.splitlines() if l.count("\t") == 3]
            return self._send(200, {"items": items})
        if u.path == "/api/disk":   # free up space: junk you can toss (gurt hogs junk) + the biggest things on the disk (gurt -a hogs)
            env = dict(os.environ, NO_COLOR="1")
            junk = [dict(zip(("what", "bytes", "desc", "root"), l.split("\t"))) for l in
                    subprocess.run([GURT, "hogs", "junk", "--tsv"], capture_output=True, text=True, timeout=300, env=env).stdout.splitlines() if l.count("\t") == 3]
            big = [dict(zip(("bytes", "name"), l.split("\t"))) for l in
                   subprocess.run([GURT, "-a", "hogs", "--tsv"], capture_output=True, text=True, timeout=300, env=env).stdout.splitlines()[:25] if l.count("\t") == 1]
            for j in junk + big:
                j["bytes"] = int(j["bytes"]) if j["bytes"].isdigit() else 0
            for j in junk:
                j["root"] = j["root"] == "1"
            return self._send(200, {"junk": junk, "big": big})
        if u.path == "/api/sizes":   # how much disk each installed app uses (gurt hogs)
            out = subprocess.run([GURT, "hogs", "--tsv"], capture_output=True, text=True, timeout=300, env=dict(os.environ, NO_COLOR="1")).stdout
            sizes = {}
            for line in out.splitlines():
                b, _, k = line.partition("\t")
                if b.isdigit() and k:
                    sizes[k] = int(b)
            return self._send(200, {"sizes": sizes})
        if u.path == "/api/lastdrop":   # what the app window saw dropped (the page only sees "a link")
            when, dropped = LAST_DROP
            LAST_DROP[:] = [0.0, []]
            return self._send(200, {"paths": dropped if time.time() - when < 15 else []})
        if u.path == "/api/zone":
            z = zone_dir()
            items = [{"name": n, "size": os.path.getsize(os.path.join(z, n)), "time": os.path.getmtime(os.path.join(z, n)),
                      "signed": zone_signed(os.path.join(z, n))}
                     for n in os.listdir(z) if os.path.isfile(os.path.join(z, n)) and not n.endswith((".part",) + SIG_EXTS)]
            return self._send(200, {"items": sorted(items, key=lambda x: -x["time"])})
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
        if u.path == "/api/droppath":   # a file already on this computer: link it in instead of uploading it
            path = os.path.realpath(str(self._body().get("path", "")))
            name = drop_name(path)
            if not os.path.isfile(path) or not DROP_NAME_RE.match(name) or not DROP_RE.search(name):
                return self._send(400, {"error": f"gurt can't open {os.path.basename(path)}"})
            dst = os.path.join(drops_dir(), name)
            if os.path.lexists(dst):
                os.remove(dst)
            os.symlink(path, dst)
            return self._send(200, {"name": name, "orig": os.path.basename(path), "size": os.path.getsize(path)})
        if u.path == "/api/listup":   # a package list to import (plain text, small)
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > (1 << 20):
                return self._send(400, {"error": "that list is empty or way too big"})
            name = f"list-{int(time.time() * 1000)}.txt"
            with open(os.path.join(drops_dir(), name), "wb") as f:
                f.write(self.rfile.read(n))
            return self._send(200, {"name": name})
        if u.path == "/api/zone/retrieve":   # Download Zone™ → your Downloads folder
            name = self._body().get("name", "")
            src = os.path.join(zone_dir(), name)
            if not DROP_NAME_RE.match(name) or not os.path.isfile(src):
                return self._send(400, {"error": "that's not in the Download Zone™"})
            dst = unique_path(downloads_dir(), name)
            shutil.copy2(src, dst)
            for ext in SIG_EXTS:   # its signature comes along, named to match
                if os.path.isfile(src + ext):
                    shutil.copy2(src + ext, dst + ext)
            return self._send(200, {"path": dst})
        if u.path == "/api/zone/delete":
            name = self._body().get("name", "")
            src = os.path.join(zone_dir(), name)
            if DROP_NAME_RE.match(name) and os.path.isfile(src):
                os.remove(src)
                for ext in SIG_EXTS:
                    if os.path.isfile(src + ext):
                        os.remove(src + ext)
            return self._send(200, {"ok": True})
        if u.path == "/api/opendir":
            subprocess.Popen(["xdg-open", downloads_dir()], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return self._send(200, {"ok": True})
        if u.path == "/api/drop":   # a file dropped into the app → saved to the cache, then gurt outsource installs it
            name = re.sub(r"[^A-Za-z0-9._+-]", "_", os.path.basename(unquote(self.headers.get("X-Filename", ""))))[:200].lstrip("._-")
            if not DROP_NAME_RE.match(name) or not DROP_RE.search(name):
                return self._send(400, {"error": "gurt can't install that kind of file (.deb .rpm .AppImage .tar.gz .exe .dmg …)"})
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
            if cmd == "devunlock":   # 🔒 the dev build's password, handed to gurt on stdin (never on the command line)
                pw = str(body.get("password", ""))[:200].replace("\n", "")
                job = start_job([GURT, "__devunlock"], stdin_text=pw + "\n")
                return self._send(200, {"job": job.id})
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
                job = start_job([GURT, "-y", "add" if arg.lower().endswith(".gurt") else "outsource", p])
                return self._send(200, {"job": job.id})
            if cmd == "convert":   # a dropped file → another package format, saved to your Downloads
                p = os.path.join(drops_dir(), arg)
                if not DROP_NAME_RE.match(arg) or not DROP_RE.search(arg) or not os.path.isfile(p):
                    return self._send(400, {"error": "that file is gone"})
                if body.get("fmt") not in CONV_FMTS:
                    return self._send(400, {"error": "gurt can't make that format"})
                out = unique_path(zone_dir(), PKG_EXT_RE.sub("", arg) + "-converted" + CONV_EXT[body["fmt"]])
                job = start_job([GURT, "-y", "convert", p, out])
                return self._send(200, {"job": job.id})
            if cmd == "export":   # your package list → a text file in Downloads
                out = unique_path(downloads_dir(), time.strftime("gurt-list-%Y-%m-%d.txt"))
                job = start_job([GURT, "export", out])
                return self._send(200, {"job": job.id})
            if cmd == "import":
                p = os.path.join(drops_dir(), arg)
                if not re.fullmatch(r"list-[0-9]+\.txt", arg) or not os.path.isfile(p):
                    return self._send(400, {"error": "that list is gone"})
                job = start_job([GURT, "-y", "import", p])
                return self._send(200, {"job": job.id})
            if cmd == "gui-setup":
                job = start_job([GURT, "-y", "gui", "--setup"])
                return self._send(200, {"job": job.id})
            if cmd == "utils":
                job = start_job([GURT, "-y", "utils"])
                return self._send(200, {"job": job.id})
            if cmd == "sync-src":
                if arg not in SYNC_SRCS:
                    return self._send(400, {"error": "unknown source"})
                job = start_job([GURT, "sync", arg])
                return self._send(200, {"job": job.id})
            if cmd == "gurtd":   # GURTd's settings (gurt gurtd …)
                ok = {"on": ["on"], "off": ["off"], "quiet-off": ["quiet", "off"]} | {f"{k}-{v}": [k, v] for k in ("autoupdate", "watch", "fresh", "saver") for v in ("on", "off")}
                q = re.match(r"^quiet-(\d{1,2}-\d{1,2})$", arg)
                if q and QUIET_RE.match(q.group(1)):
                    ok[arg] = ["quiet", q.group(1)]
                if arg not in ok:
                    return self._send(400, {"error": "not allowed"})
                job = start_job([GURT, "gurtd"] + ok[arg])
                return self._send(200, {"job": job.id})
            if cmd == "android":   # Android apps through Waydroid (gurt android setup|fdroid|open)
                if arg not in ("setup", "fdroid", "open"):
                    return self._send(400, {"error": "not allowed"})
                job = start_job([GURT, "-y", "android", arg])
                return self._send(200, {"job": job.id})
            if cmd == "foss":   # FOSS-only mode (gurt foss on|off)
                if arg not in ("on", "off"):
                    return self._send(400, {"error": "not allowed"})
                job = start_job([GURT, "foss", arg])
                return self._send(200, {"job": job.id})
            if cmd == "toss":   # free up space: gurt hogs clean <what>
                if not TOSS_RE.match(arg):
                    return self._send(400, {"error": "not allowed"})
                job = start_job([GURT, "-y", "hogs", "clean", arg])
                return self._send(200, {"job": job.id})
            if cmd == "notify":
                if arg not in ("on", "off"):
                    return self._send(400, {"error": "not allowed"})
                job = start_job([GURT, "notify", arg])
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
        if u.path == "/api/lotto":
            return self._send(200, lotto_spin())
        if u.path == "/api/achieve":
            a = body.get("id")
            if a not in ACH_IDS:
                return self._send(400, {"error": "nope"})
            r = subprocess.run([GURT, "__achieve", a], capture_output=True, text=True, timeout=20, env=dict(os.environ, NO_COLOR="1"))
            return self._send(200, {"line": ANSI.sub("", r.stderr).strip()})
        if u.path == "/api/wizard":   # the setup wizard ran (or was skipped): don't pop it up again
            save_conf(wizard="done", seen=str(body.get("v", ""))[:20])
            return self._send(200, {"ok": True})
        if u.path == "/api/seen":   # the "welcome to a new version" card shows once per version
            save_conf(seen=str(body.get("v", ""))[:20])
            return self._send(200, {"ok": True})
        if u.path == "/api/track":
            if body.get("track") not in TRACKS:
                return self._send(400, {"error": "unknown track"})
            save_conf(track=body["track"])
            return self._send(200, {"ok": True})
        if u.path == "/api/sfx":
            save_conf(sfx=bool(body.get("on")))
            return self._send(200, {"ok": True})
        if u.path == "/api/music":
            save_conf(music=bool(body.get("on")))
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
        if u.path == "/api/setup-app":   # 🧙 the setup wizard is its own app: open it in its own window
            subprocess.Popen([GURT, "gui", "--wizard", "--from-app"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL, start_new_session=True)
            return self._send(200, {"ok": True})
        if u.path == "/api/close":   # the setup wizard's Finish / Cancel: close its window (+ open GURT if you asked)
            if body.get("open"):
                subprocess.Popen([GURT, "gui"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 stdin=subprocess.DEVNULL, start_new_session=True)
            if not DAEMON[0]:
                threading.Timer(0.3, close_window).start()
            return self._send(200, {"ok": True})
        if u.path == "/api/relaunch":   # reopen as a real app window, then this browser copy bows out
            subprocess.Popen([GURT, "gui"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL, start_new_session=True)
            if not DAEMON[0]:
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
            sudo = body.get("sudo")
            if job.pw is not None and sudo != job.pw_sudo:
                job.pw_sudo = sudo   # a new sudo in the same job: hand it the password you already typed
                return self._send(200, {"password": job.pw})
            job.pw = job.pw_sudo = None   # the same sudo asking again = that password was wrong, so ask you
            job.answered.clear()
            job.answer = None
            job.ask = (body.get("prompt") or "password").strip()
            job.answered.wait(600)
            ans, job.ask, job.answer = job.answer or {"cancel": True}, None, None
            if not ans.get("cancel") and isinstance(ans.get("password"), str) and not job.done:
                job.pw, job.pw_sudo = ans["password"], sudo
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


def close_window():
    """close the app window (or, in a browser, quit the server: the page already says you can close the tab)"""
    if CLOSE[0]:
        try:
            return CLOSE[0]()
        except Exception:
            pass
    os._exit(0)


def native_window(tk, url, icon):
    # the setup wizard is its own app: its own title, size and window class (gurt-setup.desktop), so docks show it apart
    title, w, h, wmclass = ("GURT Setup Wizard", 900, 640, "gurt-setup") if WIZARD[0] else ("GURT", 1100, 760, "gurt")
    if tk == "gtk":
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk, WebKit2, GLib
        GLib.set_prgname(wmclass)
        GLib.set_application_name(title)
        win = Gtk.Window(title=title)
        win.set_default_size(w, h)
        if icon:
            try:
                win.set_icon_from_file(icon)
            except Exception:
                pass
        try:   # let the music start by itself (WebKitGTK 2.30+); older ones start it on your first click
            view = WebKit2.WebView(website_policies=WebKit2.WebsitePolicies(autoplay=WebKit2.AutoplayPolicy.ALLOW))
        except Exception:
            view = WebKit2.WebView()
        def on_drag_data(_w, _ctx, _x, _y, data, *_):   # runs before WebKit's own handler; the page asks for these
            try:
                uris = data.get_uris() or [u for u in (data.get_text() or "").split() if u.startswith("file://")]
                paths = [GLib.filename_from_uri(u)[0] for u in uris if u.startswith("file://")]
                if paths:
                    LAST_DROP[:] = [time.time(), paths]
            except Exception:
                pass
        view.connect("drag-data-received", on_drag_data)
        st = view.get_settings()
        st.set_enable_developer_extras(False)
        # sounds + music: WebKitGTK needs web audio switched on, and lets the page play without waiting for a click
        for name, val in (("set_enable_webaudio", True), ("set_enable_media", True), ("set_media_playback_requires_user_gesture", False)):
            if hasattr(st, name):
                getattr(st, name)(val)
        view.load_uri(url)
        win.add(view)
        # WebKitGTK + newer Mesa crash on the way out (a double free in libgallium's exit handlers → a core dump every
        # time GURT closes), so the page process gets ended on close instead of running them. the GPU stays on (off = laggy)
        def on_close(*_):   # end WebKit's page process ourselves, so it never runs the exit code that crashes
            try:
                view.terminate_web_process()
            except Exception:
                pass
            return False    # then the window closes like normal
        win.connect("delete-event", on_close)
        win.connect("destroy", Gtk.main_quit)
        CLOSE[0] = lambda: GLib.idle_add(lambda: (on_close(), win.destroy(), False)[-1])
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
        app.setDesktopFileName(wmclass)
        if icon:
            app.setWindowIcon(QIcon(icon))
        view = QWebEngineView()
        try:   # let the page play sounds/music without waiting for a click
            from_settings = view.settings()
            attr = type(from_settings).WebAttribute.PlaybackRequiresUserGesture if hasattr(type(from_settings), "WebAttribute") else from_settings.PlaybackRequiresUserGesture
            from_settings.setAttribute(attr, False)
        except Exception:
            pass
        view.setWindowTitle(title)
        view.resize(w, h)
        view.load(QUrl(url))
        view.show()
        if tk == "qt6":
            from PyQt6.QtCore import QTimer
        else:
            from PySide6.QtCore import QTimer
        want = []
        CLOSE[0] = lambda: want.append(1)   # Qt wants it done on its own thread: a timer there checks
        tick = QTimer()
        tick.timeout.connect(lambda: want and view.close())
        tick.start(200)
        app.exec()
    elif tk == "pywebview":
        import webview
        win = webview.create_window(title, url, width=w, height=h)
        CLOSE[0] = win.destroy
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
            size, cls = ("900,640", "gurt-setup") if WIZARD[0] else ("1100,760", "gurt")
            subprocess.Popen([b, f"--app={url}", f"--window-size={size}", f"--class={cls}"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return
    opener = shutil.which("xdg-open") or shutil.which("open")
    if opener:
        subprocess.Popen([opener, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    elif "CHROMEOS_RELEASE_NAME=" in (open("/etc/lsb-release").read() if os.path.isfile("/etc/lsb-release") else ""):
        print(f"open this in Chrome (Ctrl + click it): {url}", flush=True)   # ChromeOS itself: Linux can't open Chrome
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



# ───────────────────────── GURTd: gurt's background daemon (gurt daemon on) ─────────────────────────
# keeps the package lists fresh, checks for updates (and installs them if you turned auto-update on), offers to
# install packages that land in ~/Downloads, and keeps this server running so `gurt gui` opens instantly
CFG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "gurt")
DAEMON_CONF = os.path.join(CFG_DIR, "daemon.conf")          # autoupdate= watch= fresh= saver=on|off · quiet=22-8|off
RUN_DIR = os.environ.get("XDG_RUNTIME_DIR") or os.path.expanduser("~/.cache/gurt")
URL_FILE = os.path.join(RUN_DIR, "gurt-gui.url")              # where `gurt gui` finds the running server (0600)
DAEMON_LOG = os.path.expanduser("~/.cache/gurt/gurtd.log")
DAEMON = [False]
REFRESH_EVERY, CHECK_EVERY = 3 * 3600, 6 * 3600


QUIET_RE = re.compile(r"^([01]?\d|2[0-3])-([01]?\d|2[0-3])$")


def dconf():
    c = {"autoupdate": "off", "watch": "on", "fresh": "on", "saver": "on", "quiet": "off"}
    try:
        for line in open(DAEMON_CONF):
            k, _, v = line.strip().partition("=")
            if k in c and (v in ("on", "off") if k != "quiet" else v == "off" or QUIET_RE.match(v)):
                c[k] = v
    except OSError:
        pass
    return c


def in_quiet(c):
    """quiet hours (quiet=22-8): GURTd still checks, but holds its notifications until they end"""
    m = QUIET_RE.match(c.get("quiet", ""))
    if not m:
        return False
    a, b, h = int(m.group(1)), int(m.group(2)), time.localtime().tm_hour
    return a <= h < b if a < b else (h >= a or h < b) if a != b else False


def on_battery():
    """unplugged and running on battery (any charger plugged in = no)"""
    base, bat = "/sys/class/power_supply", False
    try:
        for d in os.listdir(base):
            r = lambda f: open(os.path.join(base, d, f)).read().strip()
            try:
                kind = r("type")
                if kind in ("Mains", "USB", "USB_C") and r("online") == "1":
                    return False
                if kind == "Battery" and r("status") == "Discharging":
                    try:
                        if r("scope") == "Device":
                            continue   # a mouse or headset battery, not this computer's
                    except OSError:
                        pass
                    bat = True
            except OSError:
                continue
    except OSError:
        pass
    return bat


def metered():
    """NetworkManager says this connection is metered (a phone hotspot, mobile data)"""
    try:
        out = subprocess.run(["busctl", "--system", "get-property", "org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager",
                              "org.freedesktop.NetworkManager", "Metered"], capture_output=True, text=True, timeout=5).stdout.split()
        return out[:1] == ["u"] and out[1:2] in (["1"], ["3"])   # 1 = yes, 3 = guessed yes
    except Exception:
        return False


def saver_reason(c):
    if c["saver"] != "on":
        return ""
    return "on battery" if on_battery() else "on a metered connection" if metered() else ""


def dlog(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(DAEMON_LOG), exist_ok=True)
        with open(DAEMON_LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def desktop_notify(title, body, actions=()):
    """a desktop notification; with actions (key, label) it waits and returns the one you clicked (or None)"""
    if not shutil.which("notify-send"):
        return None
    icon = next((f for f in ICONS if os.path.isfile(f)), "")
    cmd = ["notify-send", "--app-name=GURT"] + (["-i", icon] if icon else [])
    if actions:
        try:
            has_actions = "--action" in subprocess.run(["notify-send", "--help"], capture_output=True, text=True, timeout=5).stdout
        except Exception:
            has_actions = False
        if has_actions:
            for k, label in actions:
                cmd += ["-A", f"{k}={label}"]
            try:
                r = subprocess.run(cmd + [title, body], capture_output=True, text=True, timeout=600)
                return r.stdout.strip() or None
            except Exception:
                return None
    try:
        subprocess.run(cmd + [title, body], capture_output=True, timeout=15)
    except Exception:
        pass
    return None


def gurt_quiet(args, timeout=3600, env_extra=None):
    """run gurt for the daemon (no colours, nicely, never asking anything) → (rc, output)"""
    env = dict(os.environ, NO_COLOR="1", GURT_PLAIN="1", **(env_extra or {}))
    try:
        r = subprocess.run(["nice", "-n", "10", GURT] + args, capture_output=True, text=True, timeout=timeout,
                           env=env, stdin=subprocess.DEVNULL)
        return r.returncode, ANSI.sub("", r.stdout + r.stderr)
    except Exception as e:
        return 1, str(e)


def daemon_updates():
    """refresh + see what's outdated; auto-update if that's on (only what needs no password), else tell you"""
    if any(not j.done for j in JOBS.values()):
        return dlog("you're using GURT right now, checking later")
    rc, out = gurt_quiet(["update"], env_extra={"GURT_REFRESH": "1"})   # the daemon's own refresh always runs
    apps = re.findall(r"^\s*->\s*(\S+)\s+\S+ -> (\S+)$", out, re.M)
    sysm = re.search(r"(\d+) system update\(s\) waiting", out)
    dlog(f"checked: {len(apps)} app update(s), {sysm.group(1) if sysm else 0} system update(s)")
    if not apps and not sysm:
        return
    if apps and dconf()["autoupdate"] == "on":
        nopw = os.geteuid() == 0 or subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode == 0
        if nopw:
            rc, out = gurt_quiet(["-y", "--no-system", "upgrade"])
            dlog(f"auto-update: {'done' if rc == 0 else 'had problems'}")
            dnotify("updated", "GURT updated your apps" if rc == 0 else "GURT couldn't update everything",
                    ", ".join(n for n, _ in apps[:6]) + ("…" if len(apps) > 6 else ""))
            return
        if shutil.which("flatpak"):   # flatpaks update without a password
            subprocess.run(["flatpak", "update", "--user", "-y", "--noninteractive"], capture_output=True, timeout=3600)
            dlog("auto-update: flatpaks updated; the rest need your password")
    dnotify("updates", "Updates are waiting", f"{len(apps)} app update(s)" + (f", {sysm.group(1)} system update(s)" if sysm else ""), True)


HELD = {}   # quiet hours: the newest notification of each kind waits here until they end
def dnotify(kind, title, body, open_btn=False):
    if in_quiet(dconf()):
        HELD[kind] = (title, body, open_btn)
        return dlog(f"quiet hours: holding \"{title}\" until they end")
    def go():
        if desktop_notify(title, body, [("open", "Open GURT")] if open_btn else ()) == "open":
            subprocess.Popen([GURT, "gui"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    threading.Thread(target=go, daemon=True).start()


PKG_FILE = DROP_RE
def downloads_dir():
    if os.path.isdir(CROS_DOWNLOADS):   # ChromeOS: where Chrome saves what you download
        return CROS_DOWNLOADS
    try:
        d = subprocess.run(["xdg-user-dir", "DOWNLOAD"], capture_output=True, text=True, timeout=5).stdout.strip()
        if d and os.path.isdir(d) and os.path.realpath(d) != os.path.realpath(os.path.expanduser("~")):   # it says $HOME when unset
            return d
    except Exception:
        pass
    return os.path.expanduser("~/Downloads")


def watch_downloads():
    """a package lands in ~/Downloads → 'Install with GURT?'"""
    d = downloads_dir()
    seen, sizes = set(), {}
    try:
        seen = set(os.listdir(d))   # only new files count
    except OSError:
        pass
    while True:
        time.sleep(5)
        if dconf()["watch"] != "on":
            continue
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            if n in seen or n.startswith(".") or n.endswith((".part", ".crdownload", ".download")) or not PKG_FILE.search(n):
                continue
            f = os.path.join(d, n)
            try:
                size = os.path.getsize(f)
            except OSError:
                continue
            if sizes.get(n) != size or size == 0:   # still downloading: wait until it stops growing
                sizes[n] = size
                continue
            seen.add(n)
            dlog(f"new download: {n}")
            def ask(f=f, n=n):
                if desktop_notify("Install it with GURT?", n, [("install", "Install with GURT"), ("no", "Not now")]) == "install":
                    subprocess.Popen([GURT, "gui", f], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            threading.Thread(target=ask, daemon=True).start()


def daemon_loop():
    last_refresh = last_check = 0
    waiting = ""   # why the last due check was held off (saver)
    while True:
        now, c = time.time(), dconf()
        try:
            if HELD and not in_quiet(c):   # quiet hours are over: the notifications that waited
                for k in list(HELD):
                    dnotify(k, *HELD.pop(k))
            if now - last_check >= CHECK_EVERY or (c["fresh"] == "on" and now - last_refresh >= REFRESH_EVERY):
                why = saver_reason(c)
                if why:   # saver: no downloads on battery or metered data. it runs as soon as that's over
                    if why != waiting:
                        dlog(f"saver: {why}, holding off on the update check")
                    waiting = why
                else:
                    waiting = ""
                    daemon_updates()   # gurt update refreshes the lists too
                    last_refresh = last_check = now
        except Exception as e:
            dlog(f"update check failed: {e}")
        time.sleep(60)


def daemon_tray():
    """a tray icon (needs AyatanaAppIndicator); without one GURTd just runs quietly"""
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        try:
            gi.require_version("AyatanaAppIndicator3", "0.1")
            from gi.repository import AyatanaAppIndicator3 as AI
        except (ValueError, ImportError):
            gi.require_version("AppIndicator3", "0.1")
            from gi.repository import AppIndicator3 as AI
        from gi.repository import Gtk
    except Exception:
        return False
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    icon = next((f for f in ICONS if os.path.isfile(f)), "gurt")
    ind = AI.Indicator.new("gurtd", icon, AI.IndicatorCategory.APPLICATION_STATUS)
    ind.set_status(AI.IndicatorStatus.ACTIVE)
    menu = Gtk.Menu()
    def item(label, fn):
        it = Gtk.MenuItem(label=label); it.connect("activate", lambda *_: fn()); menu.append(it)
    item("Open GURT", lambda: subprocess.Popen([GURT, "gui"], start_new_session=True))
    item("Check for updates now", lambda: threading.Thread(target=daemon_updates, daemon=True).start())
    item("Quit GURTd", Gtk.main_quit)
    menu.show_all(); ind.set_menu(menu)
    Gtk.main()
    return True


def run_daemon(server, url):
    DAEMON[0] = True
    dlog("Linus sees you. Starting GURTd btw")
    os.makedirs(RUN_DIR, exist_ok=True)
    fd = os.open(URL_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(url + "\n")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=daemon_loop, daemon=True).start()
    threading.Thread(target=watch_downloads, daemon=True).start()
    try:
        if not daemon_tray():
            while True:
                time.sleep(3600)
    finally:
        try:
            os.remove(URL_FILE)
        except OSError:
            pass
        dlog("GURTd stopped")


def attach_window():
    """gurt gui with GURTd running: just open a window onto its server"""
    try:
        url = open(URL_FILE).read().strip()
    except OSError:
        return False
    tk = find_toolkit()
    if tk:
        TK[0] = tk
        native_window(tk, url, next((f for f in ICONS if os.path.isfile(f)), None))
    else:
        open_window(url)
    return True


def main():
    global GURT, PORT, ASKPASS, ICONS
    ap = argparse.ArgumentParser()
    ap.add_argument("--gurt", default=shutil.which("gurt") or "gurt")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--no-window", action="store_true")
    ap.add_argument("--browser", action="store_true", help="use a browser window even if a native one is possible")
    ap.add_argument("--probe", action="store_true", help="exit 0 if a native app window is possible")
    ap.add_argument("--wizard", action="store_true", help="open the GURT Setup Wizard app instead of GURT (the installers use this)")
    ap.add_argument("--from-app", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--daemon", action="store_true", help="run as GURTd: fresh lists, update checks, downloads watcher, instant GURT")
    ap.add_argument("--attach", action="store_true", help="open a window onto GURTd's running server")   # GURT opened the wizard (so Finish doesn't open a 2nd GURT)
    ap.add_argument("files", nargs="*", help="a package to open (double-clicking a .gurt file)")
    a = ap.parse_args()
    WIZARD[:] = [a.wizard, a.from_app]
    if a.files:
        f = a.files[0]
        if f.startswith("file://"):
            f = unquote(urlparse(f).path)
        OPEN_FILE[0] = os.path.abspath(f) if os.path.isfile(f) else ""
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
    if a.attach:
        sys.exit(0 if attach_window() else 1)
    ASKPASS = write_askpass()
    tk = None if (a.no_window or a.browser or a.daemon) else find_toolkit()
    global MODE
    MODE = "native" if tk else "browser"
    TK[0] = tk or ""
    url = f"http://127.0.0.1:{PORT}/?t={TOKEN}"
    print(f"GURT is running at {url}" + (f" (app window: {tk})" if tk else ""), flush=True)
    icon = next((f for f in ICONS if os.path.isfile(f)), None)
    if a.daemon:
        TK[0] = find_toolkit() or ""   # the windows that attach later are native when they can be
        MODE = "native" if TK[0] else "browser"
        try:
            run_daemon(server, url)
        except KeyboardInterrupt:
            pass
        finally:
            shutil.rmtree(os.path.dirname(ASKPASS), ignore_errors=True)
        return
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
        if WIZARD[0] and conf().get("wizard") != "done":   # the setup wizard got closed with its ✕: skipped, so it won't nag
            try:
                save_conf(wizard="done")
            except Exception:
                pass


PORT, ASKPASS, ICONS, MODE = 0, "", [], "browser"
WIZARD = [False, False]   # gurt gui --wizard: this window is the GURT Setup Wizard app, not GURT
CLOSE = [None]     # closes the app window from any thread (set once the window exists)
TK = [""]


GST_DIRS = ("/usr/lib64/gstreamer-1.0", "/usr/lib/gstreamer-1.0", "/usr/lib/x86_64-linux-gnu/gstreamer-1.0",
            "/usr/lib/aarch64-linux-gnu/gstreamer-1.0", "/usr/local/lib/gstreamer-1.0", "/usr/local/lib64/gstreamer-1.0")


def audio_ok():
    """can the GTK app window actually make sound? WebKitGTK plays audio through GStreamer, and needs its
    autoaudiosink (gst-plugins-good). only say no when we're sure: python's own GStreamer bindings often
    aren't installed (openSUSE) even though WebKit's sound works fine, so that alone isn't a no"""
    if TK[0] != "gtk":
        return True
    try:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        Gst.init(None)
        if Gst.ElementFactory.find("autoaudiosink") is not None:
            return True
    except Exception:
        pass
    dirs = [d for d in GST_DIRS if os.path.isdir(d)]
    if not dirs:
        return True   # GStreamer lives somewhere we don't know: don't guess
    return any(os.path.isfile(os.path.join(d, "libgstautodetect.so")) for d in dirs)

PAGE = r"""<!doctype html>
<html lang="en" data-theme="__THEME__" data-skin="__SKIN__" data-sfx="__SFX__" data-music="__MUSIC__" data-track="__TRACK__" data-seen="__SEEN__" data-wiz="__WIZ__" data-app="__APP__" data-from="__FROM__" data-open="__OPEN__"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>GURT</title><link rel="icon" href="/icon.png">
<style>
/* GURT app styles. Rules live in CLAUDE.md: flat, 1px borders, 2px corners, no drop shadows or soft gradients,
   monospace for data + controls, dense left-aligned rows. Every skin keeps this structure and brings its own chrome. */
:root{--r:2px;--mono:ui-monospace,"JetBrains Mono","DejaVu Sans Mono",Menlo,monospace;--sans:system-ui,"Segoe UI",Roboto,sans-serif;
  --bg:#ececee;--panel:#fafafa;--ink:#111113;--muted:#5b5b63;--line:#d9d9de;--edge:#b9b9c1;--accent:#ffc629;--accent-ink:#111113;--tag:#e2e2e6;--code:#f4f4f5;--good:#17803d;--bad:#c62828;
  --hl:color-mix(in srgb,var(--accent) 18%,transparent);--c-red:#e8302a;--c-green:#1fa64a;--c-blue:#2456e0;--logo-ink:#111113}
:root{color-scheme:light dark}:root[data-theme=light]{color-scheme:light}:root[data-theme=dark]{color-scheme:dark}
@media (prefers-color-scheme: dark){:root:not([data-theme=light]){--bg:#0a0a0b;--panel:#111113;--ink:#e7e7ea;--muted:#8e8e97;--line:#222226;--edge:#2f2f35;--tag:#19191c;--code:#070708;--good:#4ade80;--bad:#f05252;--logo-ink:#e7e7ea}}
:root[data-theme=dark]{--bg:#0a0a0b;--panel:#111113;--ink:#e7e7ea;--muted:#8e8e97;--line:#222226;--edge:#2f2f35;--tag:#19191c;--code:#070708;--good:#4ade80;--bad:#f05252;--logo-ink:#e7e7ea}
*{box-sizing:border-box}[hidden]{display:none!important}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.42 var(--sans);height:100vh;display:flex;flex-direction:column}
code,.mono{font-family:var(--mono)}
header{position:relative;display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:6px 14px;padding:8px 14px;border-bottom:1px solid var(--edge);background:var(--panel)}
.brand{display:flex;flex-direction:column;align-items:flex-start;gap:2px;min-width:0}
.logosvg svg{display:block;height:40px;width:auto}
.ver{white-space:nowrap;color:var(--muted);font:11px var(--mono)}
nav{display:flex;gap:2px;margin-left:6px;min-width:0;overflow-x:auto;scrollbar-width:none;padding:2px}nav::-webkit-scrollbar{display:none}
nav button{font:600 12.5px var(--mono);background:none;border:1px solid transparent;color:var(--muted);padding:6px 10px;border-radius:var(--r);cursor:pointer;white-space:nowrap}
nav button:hover{color:var(--ink);border-color:var(--edge)}
nav button.on{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
nav .badge{background:var(--bad);color:#fff;border-radius:var(--r);font:700 10.5px var(--mono);padding:0 5px;margin-left:5px}
.hdr-actions{display:flex;gap:6px;align-items:center}
.prefs{position:relative}
#prefpop,.morepop{position:absolute;right:0;top:calc(100% + 6px);z-index:70;display:grid;gap:8px;min-width:230px;padding:10px;background:var(--panel);color:var(--ink);border:1px solid var(--edge);border-radius:var(--r)}
.chip.closed{color:var(--muted);border-style:dashed}
.closedmark{font:600 10.5px var(--mono);font-style:normal;color:var(--muted);border:1px dashed var(--edge);border-radius:var(--r);padding:0 4px;margin-left:4px;vertical-align:1px}
#prefpop label{display:grid;gap:3px;font:600 12.5px var(--mono);color:var(--muted)}#prefpop select{width:100%}
.prefrow{display:flex;flex-wrap:wrap;gap:6px}
@media (max-width:760px){header{grid-template-columns:minmax(0,1fr) auto}nav{grid-column:1/-1;grid-row:2;margin:0 -4px}.logosvg svg{height:34px}}
.srcs{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:10px}
.srcs button{font:600 12px var(--mono);background:var(--panel);border:1px solid var(--edge);color:var(--ink);border-radius:var(--r);padding:4px 9px;cursor:pointer}
.srcs button small{font:11px var(--sans);color:var(--muted);margin-left:5px}
.srcs button:hover{border-color:var(--muted)}
.srcs button.on{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
.srcs button.on small{color:var(--accent-ink);opacity:.75}
.blurb{color:var(--muted);margin:0 2px 10px}
.srcs button.dirtbtn{background:#141012;color:#f1e9ea;border-color:#3a2a2e}
.srcs button.dirtbtn small{color:#e0314b}
.srcs button.dirtbtn:hover{border-color:#e0314b}
.srcs button.dirtbtn.on{background:#e0314b;border-color:#e0314b;color:#fff}
.srcs button.dirtbtn.on small{color:#fff}
:root.dirt{--bg:#0a0708;--panel:#140d0f;--ink:#f1e9ea;--muted:#a3898d;--line:#2a1b1f;--edge:#3a2a2e;--tag:#24161a;--code:#1a1013;--accent:#e0314b;--accent-ink:#fff;--good:#ff7a8c;color-scheme:dark}
.dirtlogo{display:none;height:40px;width:auto;margin:4px 0 6px}
:root.dirt .logosvg{display:none}:root.dirt .dirtlogo{display:block}
#gate .box{background:#120b0d;color:#f1e9ea;text-align:center;border:1px solid #3a2226}
#gate .g18{display:inline-block;font:700 14px var(--mono);border:1px solid #e0314b;color:#e0314b;border-radius:var(--r);padding:2px 10px;margin-bottom:12px}
#gate p{color:#c9b3b7}
#gate .row{justify-content:center}
#gate .yeah{background:#e0314b;color:#fff;border-color:#e0314b}#gate .nah{background:#1d1417;color:#f1e9ea;border-color:#3a2a2e}
.spacer{flex:1}
#appbar,#soundbar{font-size:12.5px;padding:5px 14px;display:flex;gap:8px;align-items:center;flex-wrap:wrap;border-bottom:1px solid var(--edge)}
#appbar{background:var(--tag);color:var(--muted)}
#appbar code{color:var(--ink)}
#soundbar{background:color-mix(in srgb,var(--bad) 14%,var(--tag));color:var(--ink)}
.btn{font:600 12.5px/1.3 var(--mono);background:var(--accent);color:var(--accent-ink);border:1px solid var(--accent);border-radius:var(--r);padding:6px 11px;cursor:pointer;white-space:nowrap}
.btn:hover:not(:disabled){background:color-mix(in srgb,var(--accent) 86%,var(--ink))}.btn:disabled{opacity:.45;cursor:default}
.btn:active:not(:disabled){transform:translateY(1px)}
.btn.ghost{background:transparent;color:var(--ink);border-color:var(--edge)}
.btn.ghost:hover:not(:disabled){background:var(--tag);border-color:var(--muted)}
.btn.danger{background:var(--bad);border-color:var(--bad);color:#fff}
.btn.small{padding:3px 8px;font-size:12px}
main{flex:1;overflow:auto;padding:12px 14px 24px}
.search{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}
.more{position:relative;display:inline-flex}
.morepop[hidden]{display:none}.morepop{gap:4px;padding:6px}.morepop .btn{width:100%;text-align:left}
.search input{flex:1 1 260px;min-width:0;font:14px var(--mono);padding:8px 10px;border-radius:var(--r);border:1px solid var(--edge);background:var(--panel);color:var(--ink);outline:none}
.search input:focus{border-color:var(--accent);box-shadow:inset 0 0 0 1px var(--accent)}
.hint{color:var(--muted);font:12px var(--mono);margin:-4px 2px 10px}
/* package lists: one bordered box, one row per package — name | description + chips | actions */
.grid{display:flex;flex-direction:column;border:1px solid var(--edge);border-radius:var(--r);background:var(--panel)}
.card{background:var(--panel);border:1px solid var(--edge);border-radius:var(--r);padding:6px 10px;display:grid;grid-template-columns:minmax(150px,22%) minmax(0,1fr) auto auto;column-gap:14px;row-gap:3px;align-items:center}
.card>*{grid-column:2;min-width:0}
.card>.top{grid-column:1;grid-row:1;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.ico{width:20px;height:20px;flex:none;display:inline-grid;place-items:center;border-radius:var(--r);overflow:hidden}
.ico img{width:100%;height:100%;object-fit:contain;display:block}
.ico.letter{background:var(--tag);border:1px solid var(--edge);font:700 11px/1 var(--mono);color:var(--muted)}
.card>.row{grid-column:3;grid-row:1;justify-content:flex-end}
.card>.row:last-child{grid-column:4;grid-row:1;flex-wrap:nowrap}
.card>.desc{grid-row:1;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.grid>.card{border:0;border-bottom:1px solid var(--line);border-radius:0}.grid>.card:last-child{border-bottom:0}
.grid>.card:hover{background:var(--hl)}
@media (max-width:640px){.card{grid-template-columns:minmax(0,1fr) auto}.card>*,.card>.row,.card>.desc{grid-column:1/-1;grid-row:auto;justify-content:flex-start}.card>.top{grid-column:1;grid-row:1}.card>.row:last-child{grid-column:2;grid-row:1;justify-content:flex-end}}
.name{font:700 14px var(--mono);overflow-wrap:anywhere}.src{font:11.5px var(--mono);color:var(--muted)}
.v{font:11.5px var(--mono);color:var(--good)}
.desc{color:var(--muted);font-size:13px}
.row{display:flex;gap:5px;align-items:center;flex-wrap:wrap}
.chip{font:600 11px/1.5 var(--mono);border:1px solid var(--edge);border-radius:var(--r);padding:0 6px;background:transparent;color:var(--ink)}
.chip.ok{border-color:var(--good);color:var(--good)}
#cmptray{position:fixed;left:50%;transform:translateX(-50%);bottom:12px;z-index:40;display:flex;gap:8px;align-items:center;background:var(--panel);border:1px solid var(--accent);border-radius:var(--r);padding:6px 10px;max-width:calc(100vw - 32px)}
#cmplist{font:600 13px var(--mono);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#cmpdlg{max-width:min(920px,calc(100vw - 32px));width:100%}#cmptable{overflow-x:auto}#cmptable table{border-collapse:collapse;width:100%;font-size:13px}
#cmptable th,#cmptable td{text-align:left;padding:6px 9px;border:1px solid var(--line);vertical-align:top}#cmptable th{font:600 12.5px var(--mono);color:var(--muted);white-space:nowrap;background:var(--tag)}
.cmpbtn{margin-left:2px}.cmpbtn.on{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
.vibehead{font:700 13px var(--mono);color:var(--ink);background:var(--tag);padding:5px 10px;border-bottom:1px solid var(--line)}
.chip.trust{cursor:help}.chip.t-hi{border-color:var(--good);color:var(--good)}.chip.t-mid{border-color:#c98f00;color:#c98f00}.chip.t-lo{border-color:#e8590c;color:#e8590c}
.empty{color:var(--muted);text-align:center;padding:28px 10px;font:13px var(--mono)}
h2{font:700 14px var(--mono);color:var(--ink);margin:4px 0 8px}
#console{border-top:1px solid var(--edge);background:var(--code);height:0;transition:height .15s;display:flex;flex-direction:column}
#console.open{height:220px}
#console .bar{display:flex;align-items:center;gap:8px;padding:4px 12px;border-bottom:1px solid var(--line);font:12px var(--mono)}
#console pre{margin:0;flex:1;overflow:auto;padding:6px 12px;font-size:12px;white-space:pre-wrap;word-break:break-word}
.dot{width:8px;height:8px;border-radius:50%;background:var(--muted)}.dot.run{background:var(--accent);animation:p 1s steps(2) infinite}.dot.ok{background:var(--good)}.dot.bad{background:var(--bad)}
@keyframes p{50%{opacity:.25}}
dialog{border:1px solid var(--edge);border-radius:var(--r);padding:12px 14px 14px;max-width:420px;width:calc(100% - 32px);background:var(--panel);color:var(--ink)}
dialog::backdrop{background:rgba(0,0,0,.6)}
dialog>h3{margin:-12px -14px 12px;padding:8px 14px;font:700 14px var(--mono);border-bottom:1px solid var(--edge);background:var(--tag)}
dialog p{color:var(--muted);margin:0 0 12px}
dialog input:is([type=text],[type=password],[type=search],:not([type])){width:100%;font:14px var(--mono);padding:8px 10px;border-radius:var(--r);border:1px solid var(--edge);background:var(--bg);color:var(--ink);margin-bottom:12px;outline:none}
dialog input:is([type=text],[type=password],[type=search],:not([type])):focus{border-color:var(--accent);box-shadow:inset 0 0 0 1px var(--accent)}
dialog .row{justify-content:flex-end}
.lottobtn,#t-setup .btn.big{background:var(--panel);color:var(--ink);border-color:var(--edge);box-shadow:inset 0 -3px 0 var(--accent)}
.lottobtn:hover:not(:disabled),#t-setup .btn.big:hover:not(:disabled){background:var(--tag)}
.btn.big{font-size:14px;padding:9px 16px}
.droidbar{display:flex;align-items:center;gap:6px;flex-wrap:wrap;border:1px solid var(--edge);border-radius:var(--r);padding:7px 10px;margin:0 0 10px}
.droidbar>span{flex:1 1 260px;min-width:0}.droidbar b{display:block;font:700 13px var(--mono)}.droidbar small{display:block;color:var(--muted)}
.setuphead{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:8px}
.setuphead h2{margin:0}
.bcats{display:flex;flex-wrap:wrap;gap:4px;margin:4px 0 8px}
.bcat{font:600 12px var(--mono);background:var(--panel);border:1px solid var(--edge);color:var(--ink);border-radius:var(--r);padding:3px 9px;cursor:pointer}
.bcat.on{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
.bgroup h3{font:700 13px var(--mono);color:var(--ink);margin:14px 0 6px}
.bgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:4px}
.bapp{display:flex;gap:7px;align-items:flex-start;background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:6px 8px;cursor:pointer;font-size:13px;line-height:1.3;min-width:0}
.bapp:hover{border-color:var(--muted)}
.bapp input{margin:2px 0 0;accent-color:var(--accent);flex:none}
.bapp b{display:block;font:700 13px var(--mono);overflow-wrap:anywhere}
.bapp small{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;color:var(--muted);font-size:11.5px;line-height:1.35;margin-top:2px}
.bapp.on{border-color:var(--accent);background:var(--hl)}
.bapp.done{opacity:.55;cursor:default}
#cartcount{flex:1;min-width:0;font:13px/1.35 var(--mono)}
#cartbar{position:sticky;bottom:0;display:flex;align-items:center;gap:8px;background:var(--panel);border:1px solid var(--accent);border-radius:var(--r);padding:7px 10px;margin-top:10px}
#lottowin,#lottowin2{border:1px dashed var(--accent);border-radius:var(--r);padding:10px;margin-bottom:10px;text-align:center}
#lottowin .spin,#lottowin2 .spin{font:700 16px var(--mono);margin-bottom:6px}
#lottowin .card,#lottowin2 .card{text-align:left;max-width:640px;margin:6px auto 0}
.dropbig{display:flex;flex-direction:column;align-items:center;gap:8px;text-align:center;padding:40px 20px;margin-top:6px;border:1px dashed var(--edge);border-radius:var(--r);background:var(--panel);cursor:pointer}
.dropbig:hover,.dropbig:focus{border-color:var(--accent);border-style:solid;outline:none}
.dropbig .dropicon{font-size:40px;line-height:1}.dropbig b{font:700 16px var(--mono)}.dropbig span{color:var(--muted)}
.dropbig .fmts{display:flex;flex-wrap:wrap;gap:4px;justify-content:center;max-width:620px;margin-top:4px}
/* The Congurter™ — still a machine, just a square one */
.congurter{margin:18px auto 0;max-width:820px}
.cg-title{font:800 15px var(--mono);text-align:center;margin-bottom:8px}
.cg-title small{display:block;font:400 12px var(--sans);text-transform:none;letter-spacing:0;color:var(--muted)}
.cg-machine{position:relative;display:grid;grid-template-columns:200px 1fr;gap:0;border-radius:var(--r);padding:14px;border:1px solid var(--edge);background:var(--tag)}
.cg-hopper{position:relative;height:180px;border-radius:var(--r);cursor:pointer;display:flex;flex-direction:column;align-items:center;justify-content:flex-start;padding-top:20px;
  background:var(--bg);border:1px dashed var(--edge);clip-path:polygon(0 0,100% 0,82% 100%,18% 100%)}
.cg-hopper.hot,.cg-hopper:hover,.cg-hopper:focus{border-color:var(--accent);border-style:solid;outline:none}
.cg-hoptxt{font:700 12px var(--mono);text-align:center;padding:0 22px}.cg-hoptxt small{display:block;font:400 11px var(--sans);color:var(--muted)}
.cg-slot{position:absolute;bottom:14px;left:50%;width:60px;height:6px;margin-left:-30px;background:#000}
.cg-file{position:absolute;top:70px;left:50%;transform:translateX(-50%);max-width:150px;padding:5px 9px;border-radius:var(--r);background:var(--accent);color:#000;font:600 12px/1.2 var(--mono);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;z-index:2}
.cg-file.in{animation:cg-in .9s ease-in forwards}
@keyframes cg-in{0%{top:20px;opacity:0}25%{top:60px;opacity:1}100%{top:150px;transform:translateX(-50%) scale(.2);opacity:0}}
.cg-body{display:flex;flex-direction:column;gap:10px;padding-left:14px}
.cg-lights{display:flex;align-items:center;gap:6px}.cg-lights i{width:10px;height:10px;border-radius:50%;background:#3a3a3a}
.cg-machine.running .cg-lights i{animation:cg-blink .5s steps(2) infinite alternate}.cg-machine.running .cg-lights i:nth-child(2){animation-delay:.17s}.cg-machine.running .cg-lights i:nth-child(3){animation-delay:.34s}
@keyframes cg-blink{from{background:#3a3a3a}to{background:#ffd23f}}
.cg-machine.done .cg-lights i{background:#3ddc84}.cg-machine.jam .cg-lights i{background:#ff4d4d}
.cg-gears{margin-left:auto;font-size:22px}.cg-gears .gear{display:inline-block}.cg-gears .g2{font-size:16px;margin-left:-4px}
.cg-machine.running .gear{animation:cg-spin 1.2s linear infinite}.cg-machine.running .g2{animation-direction:reverse}
@keyframes cg-spin{to{transform:rotate(360deg)}}
.cg-screen{white-space:pre-line;font:700 14px/1.3 var(--mono);color:#3ddc84;background:#060a07;border:1px solid #1b2a1f;border-radius:var(--r);padding:10px 12px;min-height:42px;word-break:break-word}
.cg-machine.jam .cg-screen{color:#ff6b6b}
.cg-controls{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.cg-dial{display:flex;flex-direction:column;gap:3px;font:700 12.5px var(--mono);color:var(--muted);flex:1;min-width:180px}
.cg-press{display:flex;flex-direction:column;align-items:center;gap:4px;font:800 10.5px/1 var(--mono);letter-spacing:.1em;color:var(--muted)}
/* the big red button is a physical button, so it stays round and gets pushed down */
.cg-button{width:68px;height:68px;border-radius:50%;border:3px solid #7a1010;background:#e01b1b;font-size:28px;cursor:pointer;box-shadow:0 5px 0 #6b0909;transition:transform .06s,box-shadow .06s}
.cg-button:active:not(:disabled),.cg-button.pressed{transform:translateY(4px);box-shadow:0 1px 0 #6b0909}
.cg-button:disabled{filter:grayscale(.85) brightness(.8);cursor:not-allowed}
.cg-machine.loaded .cg-button:not(:disabled){animation:cg-pulse 1s steps(2) infinite}
@keyframes cg-pulse{50%{border-color:#ffd23f}}
.cg-chute{position:absolute;bottom:-24px;right:70px;width:70px;height:26px;background:#222;clip-path:polygon(10% 0,90% 0,100% 100%,0 100%)}
.cg-zone{margin-top:28px;border:1px solid var(--edge);border-radius:var(--r);padding:10px;background:repeating-linear-gradient(-45deg,var(--hl) 0 12px,transparent 12px 24px)}
.cg-zonehead{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px}.cg-zonehead small{color:var(--muted);flex:1}
.cg-tray{display:flex;flex-direction:column;gap:4px}
.cg-empty{color:var(--muted);text-align:center;padding:12px;font:12px var(--mono)}
.cg-item{display:flex;align-items:center;gap:8px;background:var(--panel);border:1px solid var(--edge);border-radius:var(--r);padding:7px 10px}
.cg-item b{font:600 12.5px var(--mono);word-break:break-all;flex:1}.cg-item small{color:var(--muted);white-space:nowrap;font:11px var(--mono)}
.cg-item.drop{animation:cg-drop .35s ease-out}
@keyframes cg-drop{from{transform:translateY(-14px);opacity:0}to{transform:none;opacity:1}}
@media (max-width:640px){.cg-machine{grid-template-columns:1fr}.cg-body{padding-left:0;padding-top:10px}.cg-hopper{height:150px}}
.dropnote{text-align:center;margin-top:12px;color:var(--muted);font-size:13px}
#musicbtn.off{opacity:.5}
/* the Install a file tab only shows when the header has room for it; otherwise the button in Discover does the job */
:root.tight nav button[data-tab=dropfile]{display:none}
#dropzone{position:fixed;inset:0;z-index:50;display:flex;align-items:center;justify-content:center;background:color-mix(in srgb,var(--bg) 90%,transparent);pointer-events:none}
#dropzone div{border:2px dashed var(--accent);border-radius:var(--r);padding:40px 56px;text-align:center;background:var(--panel);font:700 18px var(--mono)}
#dropzone small{display:block;font:400 13px var(--sans);color:var(--muted);margin-top:6px}
.cicada{text-align:center;font:600 13px var(--mono);margin:24px 0 8px}
#skinsel,#tracksel,#convfmt{font:13px var(--mono);background:var(--panel);color:var(--ink);border:1px solid var(--edge);border-radius:var(--r);padding:5px 7px;cursor:pointer}
#toast{position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:60;background:var(--panel);border:1px solid var(--accent);border-left-width:4px;border-radius:var(--r);padding:8px 14px;font:700 13px var(--mono);animation:toast-in .15s ease-out;max-width:calc(100vw - 32px)}
@keyframes toast-in{from{transform:translate(-50%,-8px);opacity:0}}
/* setup wizard: a classic installer — steps on the left, Back / Next at the bottom */
#wizard{max-width:min(860px,calc(100vw - 24px));width:100%;padding:0;overflow:hidden}
#wizard[open]{display:flex;flex-direction:column;max-height:calc(100vh - 24px)}
.wiz-top{display:flex;align-items:center;gap:10px;padding:10px 14px;background:var(--accent);color:var(--accent-ink);flex:none;border-bottom:1px solid var(--edge)}
.wiz-top b{display:block;font:800 15px var(--mono);}.wiz-top small{display:block;font:12px var(--mono);opacity:.8}
.wiz-body{display:grid;grid-template-columns:190px minmax(0,1fr);height:min(62vh,540px);min-height:0;flex:1 1 auto}
.wiz-rail{margin:0;padding:12px 10px 12px 28px;background:var(--tag);border-right:1px solid var(--edge);font:12.5px var(--mono);display:grid;align-content:start;gap:6px}
.wiz-rail li{color:var(--muted)}.wiz-rail li.on{color:var(--ink);font-weight:800}.wiz-rail li.done{color:var(--good)}.wiz-rail li.done::marker{content:"✓ "}
.wiz-page{padding:14px 16px;overflow:auto;min-height:0}
.wiz-page h3{margin:0 0 4px;font:700 17px var(--sans)}.wiz-page p{color:var(--muted);margin:0 0 12px}
.wiz-foot{display:flex;gap:6px;align-items:center;flex:none;padding:10px 14px;border-top:1px solid var(--edge);background:var(--panel)}
.wiz-checks{display:grid;gap:0;margin:0 0 12px;border:1px solid var(--edge);border-radius:var(--r)}
.wiz-check{display:flex;gap:10px;align-items:center;padding:7px 10px;border-bottom:1px solid var(--line);background:var(--panel)}.wiz-check:last-child{border-bottom:0}
.wiz-check small{color:var(--muted);display:block}.wiz-check .mark{font:700 13px var(--mono);width:12px;text-align:center;flex:none}.wiz-check .mark.ok{color:var(--good)}.wiz-check .mark.no{color:var(--bad)}.wiz-check .st{margin-left:auto;font:700 12px var(--mono);white-space:nowrap}
.wiz-opt{display:flex;gap:10px;align-items:flex-start;padding:8px 10px;border:1px solid var(--edge);border-radius:var(--r);background:var(--panel);cursor:pointer;margin-bottom:6px}
.wiz-opt input{margin-top:3px;accent-color:var(--accent);flex:none}.wiz-opt small{display:block;color:var(--muted)}
.wiz-opt:has(input:checked){border-color:var(--accent);background:var(--hl)}
.wiz-grp{margin:0 0 10px}.wiz-grp h4{margin:0 0 5px;font:700 13px var(--mono);color:var(--ink)}
.wiz-apps{display:flex;flex-wrap:wrap;gap:4px}
.wiz-app{font:600 12.5px var(--mono);padding:4px 9px;border:1px solid var(--edge);border-radius:var(--r);background:var(--panel);color:var(--ink);cursor:pointer}
.wiz-app.on{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
.wiz-looks{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:4px;margin-bottom:12px}
.wiz-look{font:600 12.5px var(--mono);padding:10px 8px;border:1px solid var(--edge);border-radius:var(--r);background:var(--panel);color:var(--ink);cursor:pointer}
.wiz-look.on{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
.wiz-tasks{display:grid;gap:0;margin:0;padding:0;list-style:none;border:1px solid var(--edge);border-radius:var(--r)}
.wiz-tasks li{display:flex;gap:10px;align-items:center;padding:7px 10px;border-bottom:1px solid var(--line);background:var(--panel)}.wiz-tasks li:last-child{border-bottom:0}
.wiz-tasks .mark{font:700 13px var(--mono);width:12px;text-align:center;flex:none}.wiz-tasks .st{margin-left:auto;font:700 12px var(--mono);white-space:nowrap}
.wiz-bar{height:14px;border:1px solid var(--edge);border-radius:var(--r);background:var(--panel);margin:10px 0;overflow:hidden}
.wiz-bar i{display:block;height:100%;width:0;background:repeating-linear-gradient(90deg,var(--accent) 0 12px,transparent 12px 14px);transition:width .3s}
@media (max-width:640px){.wiz-body{grid-template-columns:1fr;height:min(70vh,560px)}.wiz-rail{display:none}}
.wiz-log{margin:4px 0 0;padding:6px 8px;max-height:140px;overflow:auto;font:11.5px/1.45 var(--mono);white-space:pre-wrap;word-break:break-all;background:var(--bg);border:1px solid var(--line);border-radius:var(--r);color:var(--muted)}
.wiz-tasks li:has(.wiz-log){flex-wrap:wrap}.wiz-tasks li .wiz-log{flex:1 0 100%}
/* the GURT Setup Wizard app (gurt gui --wizard): its own window, with just the wizard in it */
:root[data-app=setup] body>header,:root[data-app=setup] body>main,:root[data-app=setup] #console,:root[data-app=setup] #soundbar,
:root[data-app=setup] #appbar,:root[data-app=setup] #cmptray,:root[data-app=setup] #dropzone{display:none !important}
:root[data-app=setup] #wizard{width:100vw;height:100vh;max-width:none;max-height:none;margin:0;border:0;border-radius:0}
:root[data-app=setup] #wizard[open]{max-height:none}
:root[data-app=setup] #wizard::backdrop{background:var(--bg)}
:root[data-app=setup] .wiz-body{height:auto;min-height:0;flex:1 1 auto}
:root[data-app=setup] .wiz-page{max-width:720px}
.v1hero{font:900 56px/1 var(--mono);letter-spacing:-.04em;display:inline-block;padding:2px 12px;margin-bottom:10px;background:var(--accent);color:var(--accent-ink);border:1px solid var(--edge);border-radius:var(--r)}
.v1list{margin:0 0 14px;padding-left:20px;display:grid;gap:5px}#v1dlg{max-width:520px}
#histlist .ach.last{box-shadow:inset 3px 0 var(--accent)}
#achlist,#histlist{display:grid;gap:0;max-height:60vh;overflow:auto;margin:4px 0 12px;border:1px solid var(--edge);border-radius:var(--r)}
.dset{display:grid;border:1px solid var(--edge);border-radius:var(--r);margin:0 0 10px}
.dset>div{display:flex;align-items:center;gap:10px;padding:7px 10px;border-bottom:1px solid var(--line)}.dset>div:last-child{border-bottom:0}
.dset b{display:block;font:700 13px var(--mono)}.dset small{display:block;color:var(--muted)}.dset .btn,.dset select{margin-left:auto;min-width:56px;flex:none}
.diskin{max-height:62vh;overflow:auto}
.diskin h4{font:700 13px var(--sans);margin:8px 0 6px}
.dset .sz{font:700 12.5px var(--mono);min-width:64px;flex:none}
.dset>div>span{min-width:0;overflow-wrap:anywhere}
#biglist>div{padding:5px 10px}
#biglist .chip{margin-left:auto}#biglist .chip+.btn{margin-left:0}
.dlog{margin:0 0 10px;max-height:150px;overflow:auto;padding:6px 8px;font:11.5px/1.45 var(--mono);white-space:pre-wrap;background:var(--bg);border:1px solid var(--line);border-radius:var(--r);color:var(--muted)}
#gurtddlg{max-width:520px}
.ach .mark{font:700 13px var(--mono);width:12px;text-align:center;flex:none}.ach{display:flex;gap:10px;align-items:center;padding:7px 10px;border-bottom:1px solid var(--line)}.ach:last-child{border-bottom:0}.ach.locked{opacity:.45;filter:grayscale(1)}.ach b{display:block;font:700 13px var(--mono)}.ach small{color:var(--muted)}.ach .when{margin-left:auto;font:11px var(--mono);color:var(--muted)}
.rarity{display:inline-block;font:800 11px/1 var(--mono);padding:4px 8px;border:1px solid var(--edge);border-radius:var(--r);margin:0 6px 6px;letter-spacing:.08em}
.r-common{background:var(--tag)}.r-rare{background:#2f6fde;border-color:#2f6fde;color:#fff}.r-epic{background:#8e3ae0;border-color:#8e3ae0;color:#fff}
.r-legendary{background:var(--accent);border-color:var(--accent);color:#111;animation:legend 1s steps(2) infinite}
@keyframes legend{50%{background:#111;color:var(--accent)}}
.legendary .card{border:2px solid var(--accent)}
.streak{font:12px var(--mono);color:var(--muted);padding:6px 10px;border-bottom:1px solid var(--line)}
/* cursed Congurter: shake, smoke, glitchy screen */
.cg-machine.cursed{animation:cg-shake .09s linear infinite}
@keyframes cg-shake{0%{transform:translate(0,0) rotate(0)}25%{transform:translate(-3px,1px) rotate(-.6deg)}50%{transform:translate(2px,-2px) rotate(.5deg)}75%{transform:translate(-1px,2px) rotate(-.3deg)}}
.cg-machine.cursed .cg-screen{animation:cg-glitch .18s steps(2) infinite}
@keyframes cg-glitch{0%{transform:skewX(0);filter:none}50%{transform:skewX(-8deg);filter:hue-rotate(160deg)}}
.cg-smoke{position:absolute;pointer-events:none;width:14px;height:14px;background:var(--muted);opacity:.6;animation:cg-puff 1.6s ease-out forwards;z-index:3}
@keyframes cg-puff{from{transform:translate(0,0) scale(.4);opacity:.95}to{transform:translate(var(--dx),-120px) scale(2.2);opacity:0}}
.out-line-err{color:var(--bad)}.out-line-ok{color:var(--good)}
@media (max-width:560px){.search .btn{flex:1 1 auto}}
@media (max-width:640px){nav{margin-left:0}nav button{padding:6px 8px}}

/* ── GURT: the default. near-black (or flat light grey), one yellow accent, the 4-block brand stripe under the header ── */
:root[data-skin=gurt] header{border-bottom:0;padding-bottom:12px}
:root[data-skin=gurt] header::after{content:"";position:absolute;left:0;right:0;bottom:0;height:4px;border-top:1px solid var(--edge);
  background:linear-gradient(90deg,var(--c-red) 0 25%,var(--accent) 25% 50%,var(--c-green) 50% 75%,var(--c-blue) 75%)}
:root[data-skin=gurt] nav button.on{box-shadow:inset 0 -2px 0 var(--accent-ink)}
:root[data-skin=gurt] .lottobtn,:root[data-skin=gurt] #t-setup .btn.big{box-shadow:none;border-bottom:0;
  background:var(--panel) linear-gradient(90deg,var(--c-red) 0 25%,var(--accent) 25% 50%,var(--c-green) 50% 75%,var(--c-blue) 75%) bottom/100% 3px no-repeat}

/* ── Windows 11: Segoe everywhere, 4px corners, Fluent accent underline on the active tab, quiet list rows ── */
:root[data-skin=win11]{--r:4px;--mono:"Cascadia Mono","Cascadia Code",Consolas,ui-monospace,monospace;--sans:"Segoe UI Variable","Segoe UI",system-ui,sans-serif;
  --bg:#f3f3f3;--panel:#fbfbfb;--ink:#1b1b1b;--muted:#5d5d5d;--line:#ebebeb;--edge:#dedede;--accent:#005fb8;--accent-ink:#fff;--tag:#f0f0f0;--code:#f9f9f9;--hl:#0000000a}
@media (prefers-color-scheme: dark){:root[data-skin=win11]:not([data-theme=light]){--bg:#202020;--panel:#2b2b2b;--ink:#fff;--muted:#c5c5c5;--line:#333;--edge:#3d3d3d;--accent:#60cdff;--accent-ink:#000;--tag:#323232;--code:#1c1c1c;--hl:#ffffff0d}}
:root[data-skin=win11][data-theme=dark]{--bg:#202020;--panel:#2b2b2b;--ink:#fff;--muted:#c5c5c5;--line:#333;--edge:#3d3d3d;--accent:#60cdff;--accent-ink:#000;--tag:#323232;--code:#1c1c1c;--hl:#ffffff0d}
:root[data-skin=win11] nav button,:root[data-skin=win11] .btn,:root[data-skin=win11] .srcs button,:root[data-skin=win11] .bcat,:root[data-skin=win11] .wiz-app,:root[data-skin=win11] .wiz-look{font-family:var(--sans);font-weight:600}
:root[data-skin=win11] nav button{position:relative;color:var(--ink);font-weight:400}
:root[data-skin=win11] nav button.on{background:var(--hl);color:var(--ink);border-color:transparent;font-weight:600}
:root[data-skin=win11] nav button.on::after{content:"";position:absolute;left:30%;right:30%;bottom:1px;height:3px;border-radius:2px;background:var(--accent)}
:root[data-skin=win11] .btn.ghost{background:var(--panel);border-color:var(--edge);border-bottom-color:color-mix(in srgb,var(--edge) 60%,var(--ink))}
:root[data-skin=win11] .grid>.card{margin:2px 4px;border:1px solid transparent;border-radius:var(--r)}
:root[data-skin=win11] .grid>.card:hover{border-color:var(--edge)}
:root[data-skin=win11] .grid{padding:2px 0}
:root[data-skin=win11] h2,:root[data-skin=win11] .vibehead,:root[data-skin=win11] .bgroup h3,:root[data-skin=win11] dialog>h3{font-family:var(--sans);text-transform:none;letter-spacing:0;font-size:14px;color:var(--ink)}
:root[data-skin=win11] dialog>h3{background:transparent;border-bottom:0;font-size:18px;padding-bottom:0}
:root[data-skin=win11] .search input:focus,:root[data-skin=win11] dialog input:focus{box-shadow:inset 0 -2px 0 var(--accent);border-color:var(--edge)}

/* ── Windows XP: Tahoma, flat Luna-blue title bars, the green start button as the active tab, blue listview selection ── */
:root[data-skin=xp]{--r:3px;--mono:"Lucida Console","DejaVu Sans Mono",monospace;--sans:Tahoma,"Trebuchet MS",Verdana,sans-serif;
  --bg:#ece9d8;--panel:#fff;--ink:#000;--muted:#444;--line:#e1ddca;--edge:#7f9db9;--accent:#3c8d0d;--accent-ink:#fff;--tag:#f4f3ee;--code:#fff;--good:#2c7a0b;--bad:#c4271b;--hl:#316ac5;color-scheme:light}
:root[data-skin=xp] body{font-size:13px}
:root[data-skin=xp] header{background:#245edb;border-bottom:3px solid #0a3fb0;color:#fff}
:root[data-skin=xp] header .ver{color:#c9dbff}:root[data-skin=xp] nav button{color:#fff;font-family:var(--sans);font-weight:700}
:root[data-skin=xp] nav button:hover{background:#3d77e6;border-color:#1b4fbf}
:root[data-skin=xp] nav button.on{background:#3c8d0d;border:1px solid #1d5b06;border-radius:0 10px 10px 0;font-style:italic;padding-right:16px}
:root[data-skin=xp] .btn{font-family:var(--sans);font-weight:400;border-color:#003c74;border-radius:var(--r)}
:root[data-skin=xp] .btn.ghost{background:#f4f3ee;color:#000;border-color:#003c74}:root[data-skin=xp] .btn.ghost:hover:not(:disabled){background:#fff;border-color:#e68b2c}
:root[data-skin=xp] .grid{border-color:#7f9db9;border-radius:0}
:root[data-skin=xp] .grid>.card:hover{background:#316ac5;color:#fff}
:root[data-skin=xp] .grid>.card:hover :is(.desc,.src,.v){color:#dfe9ff}
:root[data-skin=xp] .vibehead{background:#d6dff7;color:#0a246a}
:root[data-skin=xp] dialog{border:3px solid #0a3fb0;border-top-width:0;padding-top:12px}
:root[data-skin=xp] dialog>h3{background:#245edb;color:#fff;font-family:var(--sans);text-transform:none;letter-spacing:0;font-size:13px;border-bottom:0;margin-top:-12px}
:root[data-skin=xp] h2{font-family:var(--sans);text-transform:none;letter-spacing:0;color:#0a246a;font-size:13px}
:root[data-skin=xp] #console{background:#000;color:#c0c0c0}

/* ── Windows 95: teal desktop, grey bevels, flat navy title bars, a sunken white listview ── */
:root[data-skin=w95]{--r:0px;--mono:"Courier New",Courier,monospace;--sans:"MS Sans Serif","Microsoft Sans Serif",Tahoma,Arial,sans-serif;
  --bg:#008080;--panel:#c0c0c0;--ink:#000;--muted:#222;--line:#c0c0c0;--edge:#808080;--accent:#000080;--accent-ink:#fff;--tag:#c0c0c0;--code:#fff;--good:#006400;--bad:#a00000;--hl:#000080;--logo-ink:#141414;color-scheme:light}
:root[data-skin=w95] body{font-size:12px;-webkit-font-smoothing:none}
:root[data-skin=w95] header{background:#000080;color:#fff;border-bottom:2px solid #000}
:root[data-skin=w95] header .ver,:root[data-skin=w95] nav button{color:#fff}
:root[data-skin=w95] .btn,:root[data-skin=w95] nav button.on,:root[data-skin=w95] .srcs button,:root[data-skin=w95] .bcat,:root[data-skin=w95] .wiz-app,:root[data-skin=w95] .wiz-look,:root[data-skin=w95] #skinsel{background:#c0c0c0;color:#000;font-family:var(--sans);font-weight:400;border:2px solid;border-color:#fff #000 #000 #fff;box-shadow:inset -1px -1px #808080,inset 1px 1px #dfdfdf}
:root[data-skin=w95] .btn:active,:root[data-skin=w95] .srcs button.on,:root[data-skin=w95] .bcat.on,:root[data-skin=w95] .wiz-app.on,:root[data-skin=w95] .wiz-look.on,:root[data-skin=w95] nav button.on{border-color:#000 #fff #fff #000;box-shadow:inset 1px 1px #808080;font-weight:700}
:root[data-skin=w95] .grid,:root[data-skin=w95] .search input,:root[data-skin=w95] #achlist,:root[data-skin=w95] #histlist{background:#fff;border:2px solid;border-color:#808080 #fff #fff #808080}
:root[data-skin=w95] .grid>.card{background:#fff;border:0;border-bottom:1px dotted #c0c0c0;box-shadow:none}
:root[data-skin=w95] .grid>.card:hover{background:#000080;color:#fff}
:root[data-skin=w95] .grid>.card:hover :is(.desc,.src,.v){color:#dfdfdf}
:root[data-skin=w95] .card,:root[data-skin=w95] #cartbar,:root[data-skin=w95] dialog,:root[data-skin=w95] #prefpop,:root[data-skin=w95] .morepop{background:#c0c0c0;border:2px solid;border-color:#dfdfdf #000 #000 #dfdfdf;box-shadow:inset -1px -1px #808080,inset 1px 1px #fff}
:root[data-skin=w95] dialog>h3{background:#000080;color:#fff;font-family:var(--sans);text-transform:none;letter-spacing:0;font-size:12px;border:0;margin:-12px -14px 12px;padding:3px 6px}
:root[data-skin=w95] h2,:root[data-skin=w95] .hint,:root[data-skin=w95] .blurb,:root[data-skin=w95] .cicada,:root[data-skin=w95] .bgroup h3,:root[data-skin=w95] .setuphead p{color:#fff}
:root[data-skin=w95] .vibehead{background:#c0c0c0;color:#000;border-bottom:1px solid #808080}

/* ── Vaporwave: always dark, flat sunset purples, wide spaced caps, hard neon double borders + offset text ── */
:root[data-skin=vapor]{--mono:"VT323","DejaVu Sans Mono",monospace;--bg:#1a0b2e;--panel:#22103f;--ink:#fde7ff;--muted:#c79bd8;--line:#3d1d66;--edge:#b967ff;--accent:#ff71ce;--accent-ink:#1a0b2e;--tag:#2e1557;--code:#140726;--good:#05ffa1;--bad:#ff4f81;--hl:#01cdfe22;--logo-ink:#f1ede2;color-scheme:dark}
:root[data-skin=vapor] body{background:#1a0b2e linear-gradient(#ff71ce14 1px,transparent 1px) 0 0/100% 32px}
:root[data-skin=vapor] header{background:#22103f;border-bottom:3px double #01cdfe}
:root[data-skin=vapor] nav button,:root[data-skin=vapor] .btn{text-transform:uppercase;letter-spacing:.14em}
:root[data-skin=vapor] nav button.on{background:transparent;color:#ff71ce;border:3px double #ff71ce}
:root[data-skin=vapor] .btn:not(.ghost):not(.danger){background:#ff71ce;border-color:#01cdfe}
:root[data-skin=vapor] .btn.ghost{border-color:#01cdfe;color:#01cdfe}
:root[data-skin=vapor] .grid{border:3px double #b967ff}
:root[data-skin=vapor] .name{color:#ff71ce}:root[data-skin=vapor] .src{color:#01cdfe}:root[data-skin=vapor] .v{color:#fffb96}
:root[data-skin=vapor] h2,:root[data-skin=vapor] .cg-title{color:#fffb96;text-shadow:2px 2px 0 #ff71ce}
:root[data-skin=vapor] dialog{border:3px double #01cdfe}

/* ── Hacker: green-on-black, mono everything, controls are [ bracketed ] text, prompts instead of tabs ── */
:root[data-skin=hacker]{--r:0px;--sans:var(--mono);--bg:#000;--panel:#000;--ink:#33ff66;--muted:#1fa83f;--line:#0b2a10;--edge:#145a22;--accent:#33ff66;--accent-ink:#000;--tag:#031105;--code:#000;--good:#33ff66;--bad:#ff3355;--hl:#33ff6614;--logo-ink:#f1ede2;color-scheme:dark}
:root[data-skin=hacker] header{border-bottom:1px dashed #33ff66}
:root[data-skin=hacker] nav button.on{background:transparent;color:#33ff66;border-color:transparent}
:root[data-skin=hacker] nav button.on::before{content:"> "}
:root[data-skin=hacker] .btn{background:transparent;color:#33ff66;border-color:transparent;padding-left:4px;padding-right:4px}
:root[data-skin=hacker] .btn::before{content:"[ "}:root[data-skin=hacker] .btn::after{content:" ]"}
:root[data-skin=hacker] .btn:hover:not(:disabled){background:#33ff66;color:#000}
:root[data-skin=hacker] .btn.danger{color:#ff3355}
:root[data-skin=hacker] .grid{border-style:dashed}
:root[data-skin=hacker] .grid>.card{border-bottom:1px dashed var(--line)}
:root[data-skin=hacker] .grid>.card .name::before{content:"$ ";color:var(--muted)}
:root[data-skin=hacker] .chip::before{content:"<"}:root[data-skin=hacker] .chip::after{content:">"}:root[data-skin=hacker] .chip{border:0;padding:0 2px}
:root[data-skin=hacker] dialog,:root[data-skin=hacker] #prefpop,:root[data-skin=hacker] .morepop{border:1px dashed #33ff66}
:root[data-skin=hacker] .search input{border-style:dashed;caret-color:#33ff66}
</style></head><body>
<header>
  <div class="brand"><span class="logosvg"><!--logo--><svg xmlns="http://www.w3.org/2000/svg" viewBox="-6 -1223 3791 1805" role="img" aria-label="gurt"><path transform="translate(70 70) rotate(-4 529 -300) translate(0 0) scale(1 -1)" d="M257 347Q79 422 79 640Q79 796 188.0 880.5Q297 965 500 965Q543 965 610.5 957.5Q678 950 709 940L934 1051L969 1008L855 846Q917 770 917 640Q917 481 809.5 395.5Q702 310 496 310Q417 310 343 322L319 246Q321 217 356.0 191.5Q391 166 442 166H661Q1004 166 1004 -98Q1004 -207 944.5 -285.5Q885 -364 769.5 -408.0Q654 -452 482 -452Q278 -452 166.0 -393.5Q54 -335 54 -233Q54 -188 90.5 -146.0Q127 -104 232 -43Q173 -20 131.5 37.0Q90 94 90 157ZM785 -166Q785 -71 658 -71H341Q253 -135 253 -216Q253 -280 314.5 -312.0Q376 -344 483 -344Q628 -344 706.5 -297.0Q785 -250 785 -166ZM494 410Q568 410 601.0 467.5Q634 525 634 640Q634 755 601.5 809.5Q569 864 494 864Q425 864 393.5 809.5Q362 755 362 640Q362 525 393.0 467.5Q424 410 494 410Z" fill="#ffc629"/><path transform="translate(70 70) rotate(3 1552 -418) translate(994 40) scale(1 -1)" d="M705 82 637 47Q497 -25 385 -25Q125 -25 125 252V850L31 874V940H414V291Q414 207 449.5 160.0Q485 113 551 113Q627 113 703 147V850L617 874V940H992V90L1084 66V0H719Z" fill="#141414"/><path transform="translate(70 70) rotate(-5 2563 -555) translate(2103 -70) scale(1 -1)" d="M461 745Q569 865 654.5 917.5Q740 970 811 970H865V627H809L750 753Q687 753 607.0 725.5Q527 698 466 661V90L617 66V0H55V66L177 90V850L55 874V940H450Z" fill="#141414"/><path transform="translate(70 70) rotate(4 3335 -556) translate(2982 10) scale(1 -1)" d="M438 -20Q303 -20 229.5 41.0Q156 102 156 217V836H33V901L178 940L295 1153H445V940H643V836H445V235Q445 170 472.0 137.0Q499 104 543 104Q596 104 673 120V35Q643 14 570.5 -3.0Q498 -20 438 -20Z" fill="#141414"/><path class="logo-g" transform="rotate(-4 529 -300) translate(0 0) scale(1 -1)" d="M257 347Q79 422 79 640Q79 796 188.0 880.5Q297 965 500 965Q543 965 610.5 957.5Q678 950 709 940L934 1051L969 1008L855 846Q917 770 917 640Q917 481 809.5 395.5Q702 310 496 310Q417 310 343 322L319 246Q321 217 356.0 191.5Q391 166 442 166H661Q1004 166 1004 -98Q1004 -207 944.5 -285.5Q885 -364 769.5 -408.0Q654 -452 482 -452Q278 -452 166.0 -393.5Q54 -335 54 -233Q54 -188 90.5 -146.0Q127 -104 232 -43Q173 -20 131.5 37.0Q90 94 90 157ZM785 -166Q785 -71 658 -71H341Q253 -135 253 -216Q253 -280 314.5 -312.0Q376 -344 483 -344Q628 -344 706.5 -297.0Q785 -250 785 -166ZM494 410Q568 410 601.0 467.5Q634 525 634 640Q634 755 601.5 809.5Q569 864 494 864Q425 864 393.5 809.5Q362 755 362 640Q362 525 393.0 467.5Q424 410 494 410Z" fill="var(--logo-ink)" stroke="#141414" stroke-width="18"/><path transform="rotate(3 1552 -418) translate(994 40) scale(1 -1)" d="M705 82 637 47Q497 -25 385 -25Q125 -25 125 252V850L31 874V940H414V291Q414 207 449.5 160.0Q485 113 551 113Q627 113 703 147V850L617 874V940H992V90L1084 66V0H719Z" fill="#e8302a" stroke="#141414" stroke-width="18"/><path transform="rotate(-5 2563 -555) translate(2103 -70) scale(1 -1)" d="M461 745Q569 865 654.5 917.5Q740 970 811 970H865V627H809L750 753Q687 753 607.0 725.5Q527 698 466 661V90L617 66V0H55V66L177 90V850L55 874V940H450Z" fill="#1fa64a" stroke="#141414" stroke-width="18"/><path transform="rotate(4 3335 -556) translate(2982 10) scale(1 -1)" d="M438 -20Q303 -20 229.5 41.0Q156 102 156 217V836H33V901L178 940L295 1153H445V940H643V836H445V235Q445 170 472.0 137.0Q499 104 543 104Q596 104 673 120V35Q643 14 570.5 -3.0Q498 -20 438 -20Z" fill="#2456e0" stroke="#141414" stroke-width="18"/></svg><!--/logo--></span><img class="dirtlogo" src="/dirt-logo.png" alt="dirt."><div class="ver" id="ver"></div></div>
  <nav>
    <button data-tab="discover" class="on">Discover</button>
    <button data-tab="installed">Installed</button>
    <button data-tab="updates">Updates<span class="badge" id="ubadge" hidden></span></button>
    <button data-tab="setup">Setup</button>
    <button data-tab="desktops">Desktops</button>
    <button data-tab="dropfile">Install a file</button>
  </nav>
  <div class="hdr-actions">
    <button class="btn ghost small" id="syncbtn" title="gurt sync">sync</button>
    <div class="prefs"><button class="btn ghost small" id="prefbtn" aria-expanded="false" aria-controls="prefpop" title="look + sound">look</button>
      <div id="prefpop" hidden>
        <label>skin <select id="skinsel">
          <option value="gurt">GURT</option><option value="win11">Windows 11</option><option value="xp">Windows XP</option><option value="w95">Windows 95</option><option value="vapor">Vaporwave</option><option value="hacker">Hacker</option>
        </select></label>
        <label>music <select id="tracksel"><option value="auto" title="matches the skin">auto</option><option value="shop">shop</option><option value="lofi">lofi</option><option value="chip">chiptune</option><option value="synth">synthwave</option></select></label>
        <button class="btn ghost small" id="fossbtn" title="only free software: hides and blocks closed-source apps (gurt foss on)">FOSS only: off</button>
        <button class="btn ghost small" id="wizopen" title="walk through setting GURT up">setup wizard</button>
        <div class="prefrow"><button class="btn ghost small" id="musicbtn" title="background music"></button><button class="btn ghost small" id="sfxbtn" title="sound effects"></button><button class="btn ghost small" id="themebtn" title="light / dark"></button></div>
      </div>
    </div>
  </div>
</header>
<div id="soundbar" hidden>no sound: the app window needs GStreamer's audio plugins <button class="btn small" id="soundfix">fix sound</button><button class="btn ghost small" id="soundx">×</button></div>
<div id="appbar" hidden><span id="appbartxt">GURT is running in your browser want it as a real app window?</span><button class="btn small" id="appbarinst">install app window</button><button class="btn ghost small" id="appbarx">×</button></div>
<main>
  <section id="t-dropfile" hidden>
    <label class="dropbig" id="dropbig" tabindex="0">
      <span class="dropicon"></span>
      <b>drop a file here, or click to pick one</b>
      <span>gurt figures out what it is and installs it straight onto your system, any distro, no box</span>
      <span class="fmts"><code>.deb</code><code>.rpm</code><code>.pkg.tar.zst</code><code>AppImage</code><code>.flatpak</code><code>.flatpakref</code><code>.snap</code><code>.apk</code><code>.xbps</code><code>.eopkg</code><code>.chrot</code><code>.tar.gz</code><code>.zip</code><code>.7z</code><code>.exe</code><code>.msi</code><code>.dmg</code></span>
    </label>
    <div class="congurter" id="congurter">
      <div class="cg-title">The Congurter™ <small>any Linux package goes in, any other one comes out</small></div>
      <div class="cg-machine" id="cgmachine">
        <div class="cg-hopper" id="hopper" tabindex="0" title="drop a package in here (or click)">
          <span class="cg-hoptxt" id="hoptxt">drop a package in the hopper<small>or click to pick one</small></span>
          <div class="cg-file" id="cgfile" hidden></div>
          <div class="cg-slot"></div>
          <input type="file" id="convin" hidden>
        </div>
        <div class="cg-body">
          <div class="cg-lights"><i></i><i></i><i></i><span class="cg-gears"><b class="gear"></b><b class="gear g2"></b></span></div>
          <div class="cg-screen" id="cgscreen">INSERT PACKAGE</div>
          <div class="cg-controls">
            <label class="cg-dial">turn it into
              <select id="convfmt" title="convert to">
                <option value="deb">.deb (Debian, Ubuntu, Mint)</option><option value="rpm">.rpm (Fedora, openSUSE)</option>
                <option value="pacman">.pkg.tar.zst (Arch, CachyOS)</option><option value="apk">.apk (Alpine)</option>
                <option value="xbps">.xbps (Void)</option><option value="eopkg">.eopkg (Solus)</option>
                <option value="appimage">AppImage (any distro)</option><option value="gurt">.gurt</option><option value="chrot">.chrot (Tweakium)</option>
                <option value="tar.gz">.tar.gz</option><option value="zip">.zip</option>
              </select>
            </label>
            <div class="cg-press"><button class="cg-button" id="cgbtn" disabled title="CONVERT"></button><span>CONVERT</span></div>
          </div>
        </div>
        <div class="cg-chute"></div>
      </div>
      <div class="cg-zone">
        <div class="cg-zonehead"><b>Download Zone™</b><small id="zonemsg">converted files land here. grab them whenever</small><button class="btn ghost small" id="zoneopen">open Downloads</button></div>
        <div class="cg-tray" id="zone"><div class="cg-empty">empty… for now</div></div>
      </div>
    </div>
    <p class="dropnote">from a terminal it's <code>gurt outsource ./file.deb</code> (or a download link). only install files you trust</p>
  </section>
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
    <div class="search"><input id="q" placeholder="search Main GURT… (Enter searches every source)" autocomplete="off"><button class="btn" id="qall">search everywhere</button><span class="more"><button class="btn ghost" data-more aria-haspopup="true" aria-expanded="false" title="more">⋯ more</button><span class="morepop" hidden><button class="btn ghost" id="dropbtn" title="install a .deb, .rpm, AppImage, .exe… you downloaded">install a file</button><button class="btn ghost" id="convopen" title="turn a package into another format">convert a package</button><button class="btn lottobtn" id="lotto" title="win a random app">app lottery</button></span></span><input type="file" id="dropin" hidden></div>
    <p class="hint">tip: <code>aur/yay</code>, <code>apt/cowsay</code>, <code>flatpak/gimp</code>… type a full name with a source and hit install</p>
    <div id="direct" hidden class="row" style="margin-bottom:12px"><button class="btn" id="directbtn"></button></div>
    <div id="allres" hidden><h2>everywhere</h2><div class="grid" id="allgrid"></div><h2 style="margin-top:18px">Main GURT</h2></div>
    <div id="lottowin" hidden></div>
    <div class="grid" id="maingrid"></div>
    <div class="grid" id="srcgrid" hidden></div>
    <p class="cicada">Could prime Wifies solve Cicada 3301?</p>
  </section>
  <section id="t-installed" hidden>
    <div class="search"><input id="iq" placeholder="filter installed…" autocomplete="off"><button class="btn ghost" id="hogbtn" title="sort by how much disk each app takes">biggest first</button><button class="btn ghost" id="diskbtn" title="caches, trash + leftovers you can toss, and what's biggest on your disk">free up space</button><span class="more"><button class="btn ghost" data-more aria-haspopup="true" aria-expanded="false" title="more">⋯ more</button><span class="morepop" hidden><button class="btn ghost" id="lexport" title="save a list of everything you installed with gurt">export my list</button><button class="btn ghost" id="limport" title="install everything from a list you exported">import a list</button><button class="btn ghost" id="histbtn" title="what you installed + removed, and when">history</button><button class="btn ghost" id="achbtn" title="your gurt achievements">achievements</button></span></span><input type="file" id="limportin" accept=".txt,text/plain" hidden></div>
    <div class="grid" id="igrid"></div>
  </section>
  <section id="t-updates" hidden>
    <div class="row" style="margin-bottom:14px"><button class="btn ghost" id="checkbtn">check for updates</button><button class="btn" id="upbtn">update everything</button><button class="btn ghost" id="selfbtn">update gurt itself</button><span class="spacer"></span><button class="btn ghost" id="notifybtn" title="a desktop notification when updates are waiting (checks every 6 hours)">alert me</button><button class="btn ghost" id="gurtdbtn" title="GURTd, the background daemon: auto-updates, fresh lists, downloads → install, instant GURT">GURTd</button></div>
    <div class="grid" id="ugrid"><div class="empty">hit "check for updates"</div></div>
  </section>
  <section id="t-setup" hidden>
    <div class="setuphead"><div><h2>Build your setup</h2><p class="blurb">tick everything you want, hit install once. works the same on every distro.</p></div>
      <button class="btn big" id="lotto2">spin the app lottery</button></div>
    <div id="lottowin2" hidden></div>
    <div class="droidbar"><span><b>Android apps</b><small id="droidtxt">free software from F-Droid, running in Waydroid. gurt sets it up. a .apk that isn't on F-Droid gets a heads-up first</small></span>
      <button class="btn ghost small" data-cmd="android" data-arg="setup">set up Android</button><button class="btn ghost small" data-cmd="android" data-arg="fdroid">get F-Droid</button><button class="btn ghost small" id="droidopen" data-cmd="android" data-arg="open">open Android</button></div>
    <div class="bcats" id="bcats"></div>
    <div id="bgroups"></div>
    <div id="cartbar" hidden><span id="cartcount"></span><span class="spacer"></span><button class="btn ghost small" id="cartclear">clear</button><button class="btn" id="cartgo">install them</button></div>
  </section>
  <section id="t-desktops" hidden>
    <p class="blurb">Desktop environments come straight from your own distro's repos (never from another distro, that breaks stuff). After installing, log out and pick it on the login screen.</p>
    <div class="grid" id="dgrid"><div class="empty">loading desktops…</div></div>
  </section>
</main>
<div id="console"><div class="bar"><span class="dot" id="cdot"></span><b id="ctitle">activity</b><span class="spacer"></span><button class="btn ghost small" id="cstop" hidden>stop</button><button class="btn ghost small" id="chide">hide</button></div><pre id="cout"></pre></div>

<div id="dropzone" hidden><div>drop it to install<small>.deb · .rpm · .pkg.tar.zst · AppImage · .tar.gz · .zip · .flatpak · .chrot · .exe · .dmg · Android .apk — any distro, no box</small></div></div>
<div id="toast" hidden></div>
<dialog id="v1dlg"><div class="v1hero">1.0</div><h3>GURT 1.0 is here</h3>
  <p>no more 0.something. what's new since you last looked:</p>
  <ul class="v1list"><li>everything The Congurter™ makes is signed, and installs check signatures by themselves</li>
  <li>the sus check reads AUR + git build scripts for red flags before building</li>
  <li>compare apps, see what eats your disk, search "like photoshop"</li>
  <li>achievements, lottery streaks, legendary pulls</li>
  <li>a fresh look, + Vaporwave and Hacker skins and 4 music tracks (in the menu)</li></ul>
  <div class="row"><button class="btn ghost" id="v1wiz">run the setup wizard</button><span class="spacer"></span><button class="btn" id="v1ok">let's gooo</button></div></dialog>
<dialog id="wizard" aria-labelledby="wiztitle">
  <div class="wiz-top"><div><b id="wiztitle">GURT Setup Wizard</b><small id="wizstepname"></small></div></div>
  <div class="wiz-body"><ol class="wiz-rail" id="wizrail"></ol><div class="wiz-page" id="wizpage"></div></div>
  <div class="wiz-foot"><button class="btn ghost" id="wizcancel">Cancel</button><span class="spacer"></span><button class="btn ghost" id="wizback">&lt; Back</button><button class="btn" id="wiznext">Next &gt;</button></div>
</dialog>
<dialog id="devdlg"><h3>dev build</h3><p>this is a GURT dev build. type the dev password to keep it. a wrong one swaps in the normal GURT and removes the dev build.</p>
  <input type="password" id="devpw" autocomplete="off" placeholder="dev password"><p class="hint" id="devmsg"></p>
  <div class="row"><span class="spacer"></span><button class="btn" id="devgo">unlock</button></div></dialog>
<dialog id="gurtddlg"><h3>GURTd</h3>
  <p>gurt's background daemon. Linus sees you. Same settings as <code>gurt gurtd config</code> in a terminal.</p>
  <div class="dset" id="gurtdset"></div>
  <pre class="dlog" id="gurtdlog"></pre>
  <div class="row"><span class="spacer"></span><button class="btn" id="gurtdclose">done</button></div></dialog>
<dialog id="diskdlg"><h3>free up space</h3><div class="diskin"><h4>Junk you can toss</h4><div class="dset" id="junklist"></div><h4>Biggest on your computer</h4><div class="dset" id="biglist"></div></div><div class="row"><span class="spacer"></span><button class="btn" id="diskclose">done</button></div></dialog>
<dialog id="histdlg"><h3>history</h3><div id="histlist"></div><div class="row"><button class="btn ghost" id="histundo" title="take back the last thing gurt did (gurt undo)" hidden>undo last</button><span class="spacer"></span><button class="btn" id="histclose">done</button></div></dialog>
<dialog id="achdlg"><h3>achievements</h3><div id="achlist"></div><div class="row"><span class="spacer"></span><button class="btn" id="achclose">nice</button></div></dialog>
<div id="cmptray" hidden><span id="cmplist"></span><span class="spacer"></span><button class="btn ghost small" id="cmpclear">clear</button><button class="btn small" id="cmpgo">compare</button></div>
<dialog id="cmpdlg"><h3>side by side</h3><div id="cmptable"></div><div class="row"><span class="spacer"></span><button class="btn" id="cmpclose">done</button></div></dialog>
<dialog id="confirm"><h3 id="ctitle2"></h3><p id="cbody"></p><div class="row"><button class="btn ghost" id="cno">Nah</button><button class="btn" id="cyes">Yeah</button></div></dialog>
<dialog id="gate" style="padding:0;background:transparent"><div class="box" style="padding:26px 22px"><div class="g18">18+</div><h3>Are you sure?</h3>
  <p>This section of the GURT Repository is 18+ ONLY. Explore at your own risk.</p>
  <div class="row"><button class="btn nah" id="gnah">Nah</button><button class="btn yeah" id="gyeah">Yeah</button></div></div></dialog>
<dialog id="pw"><h3>password needed</h3><p id="pwprompt">gurt needs your password (sudo) to put files in system folders.</p>
  <form id="pwform"><input type="password" id="pwin" autocomplete="current-password" placeholder="your password"><div class="row"><button type="button" class="btn ghost" id="pwno">cancel</button><button class="btn" type="submit">ok</button></div></form></dialog>

<script>
const T = "__TOKEN__", MODE = "__MODE__", SETUP = document.documentElement.dataset.app === "setup";   // SETUP: this window is the setup wizard app
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const api = (p, body) => fetch(p, body ? {method:"POST", headers:{"X-Gurt-Token":T,"Content-Type":"application/json"}, body:JSON.stringify(body)} : {headers:{"X-Gurt-Token":T}}).then(r => r.json());
let S = {main:[], installed:[]}, busy = false, cur = null;

// ── state ──
// a dev build asks for the dev password once (right → never again, wrong → the normal GURT replaces it)
function devGate(){
  if (!S || S.dev !== "locked") return false;
  const d = $("#devdlg"); if (d.open) return true;
  d.addEventListener("cancel", e => e.preventDefault());   // Esc doesn't skip it
  d.showModal(); setTimeout(() => $("#devpw").focus(), 50);
  const go = async () => {
    const pw = $("#devpw").value; if (!pw) return;
    $("#devgo").disabled = true; $("#devmsg").textContent = "checking…";
    const r = await api("/api/run", {cmd:"devunlock", password: pw}).catch(() => ({}));
    $("#devpw").value = "";
    if (!r.job) { $("#devgo").disabled = false; $("#devmsg").textContent = "couldn't check it, try again"; return; }
    d.close(); cur = r.job; busy = true; setBusyUI(true);
    let from = 0, lines = [], shown = false;
    $("#ctitle").textContent = "gurt dev build"; $("#cdot").className = "dot run"; $("#console").classList.add("open"); $("#cout").textContent = "";
    for (;;) {
      const j = await api(`/api/job/${cur}?from=${from}`);
      if (j.lines.length) { lines = lines.concat(j.lines); from += j.lines.length; $("#cout").textContent += j.lines.join("\n") + "\n"; }
      if (j.ask && !shown) { shown = true; askPassword(j.ask); }
      if (!j.ask) shown = false;
      if (j.done) { busy = false; setBusyUI(false); $("#cdot").className = "dot " + (j.rc === 0 ? "ok" : "bad"); break; }
      await new Promise(res => setTimeout(res, 400));
    }
    S = await api("/api/state"); $("#ver").textContent = `v${S.version} · ${S.pm}${S.wsl ? " · Windows" : ""}`;
    if (S.dev === "locked") devGate();
    else if (SETUP || document.documentElement.dataset.wiz === "new") wizStart();   // the wizard waited for this
  };
  $("#devgo").onclick = go; $("#devpw").onkeydown = e => { if (e.key === "Enter") go(); };
  return true;
}
async function load(){ S = await api("/api/state"); ICONMAP = new Map(S.main.map(p => [p.name, p.icon])); $("#fossbtn").textContent = `FOSS only: ${S.fossonly ? "on" : "off"}`; $("#fossbtn").classList.toggle("ghost", !S.fossonly); $("#ver").textContent = `v${S.version} · ${S.pm}${S.wsl ? " · Windows" : S.cros ? " · ChromeOS" : ""}`;
  document.querySelector('nav button[data-tab="desktops"]').hidden = S.wsl || S.cros;   // no Linux desktops there: Windows / ChromeOS is the desktop
  $("#droidtxt").textContent = S.cros ? "free software from F-Droid, installed into your Chromebook's own Android. a .apk that isn't on F-Droid gets a heads-up first"
    : "free software from F-Droid, running in Waydroid. gurt sets it up. a .apk that isn't on F-Droid gets a heads-up first";
  $("#droidopen").hidden = !!S.cros;
  fitNav();
  if (S.audio === false && !soundDismissed) $("#soundbar").hidden = false;   /* no Linux desktops on Windows */ renderMain(); renderInstalled(); renderNotify(); renderCmp(); if (!$("#t-setup").hidden) renderBuilder(); if (typeof SRC !== "undefined" && SRC === "dirt") renderDirt();
  if (BYSIZE) api("/api/sizes").then(r => { SIZES = r.sizes || {}; renderInstalled(); }).catch(() => {}); else SIZES = null; }
const inst = spec => {
  const m = S.main.find(p => p.name === spec);
  return S.installed.find(i => i.spec === spec || i.key === spec || (m && i.key === m.ikey) || (i.src === "gurt" && i.name === spec))
    || (m && (S.outside || {})[m.name] ? {external: true, how: S.outside[m.name]} : null);   // got it without gurt (zypper, flatpak, an AppImage…)
};
const HOW = {zypper: "zypper", dnf: "dnf", yum: "yum", apt: "apt", pacman: "pacman", apk: "apk", xbps: "xbps", eopkg: "eopkg",
  flatpak: "flatpak", snap: "snap", AppImage: "an AppImage you downloaded", "on your PATH": "something on your PATH", "/opt": "a folder in /opt"};
const howLabel = h => HOW[h] || h;

// where an app comes from, and how much that's worth: signed/checked by someone accountable · checksum-pinned · anyone can upload
const TRUST = {
  official: ["hi", "official repo", "comes from the app maker's own signed repo"],
  apt: ["hi", "distro repo", "from Debian's signed repos, checked by gurt"], dnf: ["hi", "distro repo", "from Fedora's signed repos, checked by gurt"],
  zypper: ["hi", "distro repo", "from openSUSE's signed repos, checked by gurt"], pacman: ["hi", "distro repo", "from Arch's repos (packages checked against the repo's sha256)"],
  flathub: ["hi", "Flathub", "a Flathub app: sandboxed, and Flathub reviews what gets published"], flatpak: ["hi", "Flathub", "a Flathub app: sandboxed, and Flathub reviews what gets published"],
  snap: ["mid", "Snap Store", "from the Snap Store (Canonical's app store)"],
  prebuilt: ["mid", "official download", "the app maker's own release download, checked against a checksum pinned in Main GURT"],
  source: ["mid", "built from source", "built on your computer from the project's own code, at a pinned version"],
  gurt: ["mid", "Main GURT", "a Main GURT recipe (every change is reviewed and CI-tested)"],
  aur: ["lo", "user upload", "the AUR: anyone can upload, nobody reviews it. gurt shows you the build script and checks it for red flags first"],
  git: ["lo", "random repo", "built straight from a git repo you picked. gurt checks the build script for red flags first"],
  file: ["lo", "your file", "a file you installed yourself"], dirt: ["lo", "DIRT", "from the DIRT repo"],
};
const trustChip = k => { const t = TRUST[k]; return t ? `<span class="chip trust t-${t[0]}" title="${esc(t[2])}">${t[1]}</span>` : ""; };
// app logos: Flathub's / the recipe's icon → this computer's desktop icon for it → its first letter
let ICONMAP = new Map();
const appIcon = (name, url) => `<span class="ico" data-n="${esc(name)}"><img alt="" loading="lazy" data-step="${url ? "remote" : "local"}" src="${esc(url || `/appicon/${encodeURIComponent(name)}?t=${T}`)}"></span>`;
document.addEventListener("error", e => {
  const im = e.target; if (!(im instanceof HTMLImageElement) || !im.parentElement || !im.parentElement.classList.contains("ico")) return;
  const box = im.parentElement, n = box.dataset.n || "?";
  if (im.dataset.step === "remote") { im.dataset.step = "local"; im.src = `/appicon/${encodeURIComponent(n)}?t=${T}`; }
  else { box.classList.add("letter"); box.textContent = n[0].toUpperCase(); }
}, true);
function card({name, src="gurt", ver, desc, extra="", chips="", actions="", trust}){   // chips: more chips, in the same row as the trust chip
  const tc = trustChip(trust || src);
  return `<div class="card"><div class="top">${appIcon(name, ICONMAP.get(name))}<span class="name">${esc(name)}</span><span class="src">${esc(src)}/</span><span class="v">${esc(ver||"")}</span></div>
    <div class="desc">${esc(noEmoji(desc||""))}</div>${tc || chips ? `<div class="row">${tc}${chips}</div>` : ""}${extra}<div class="row">${actions}</div></div>`;
}
const actBtn = (label, cmd, arg, cls="") => `<button class="btn small ${cls}" data-cmd="${cmd}" data-arg="${esc(arg)}">${label}</button>`;
function installBtns(spec){
  const i = inst(spec);
  if (i && i.external) return `<span class="chip ok" title="installed with ${esc(howLabel(i.how))}, not with gurt">installed ✓ (${esc(i.how)})</span>`;
  return i ? `<span class="chip ok">installed ✓</span>${actBtn("remove","remove",spec,"ghost")}` : actBtn("install","install",spec);
}
// dev builds: edit / delete any recipe, straight on GitHub (GitHub still checks you can push to the repo)
const isDev = () => !!(S && /\+dev/.test(S.version || ""));
const devBtns = (name, tree="packages") => isDev() ? `<a class="btn ghost small" href="https://github.com/clrealy/GURT/edit/main/${tree}/${encodeURIComponent(name)}/GURTBUILD" target="_blank" rel="noopener" title="dev: edit this recipe on GitHub">edit</a>`
  + `<a class="btn ghost small" href="https://github.com/clrealy/GURT/tree/main/${tree}/${encodeURIComponent(name)}" target="_blank" rel="noopener" title="dev: delete this package on GitHub (⋯ → Delete directory)">delete</a>` : "";
let CMP = [];
const cmpBtn = n => `<button class="btn ghost small cmpbtn${CMP.includes(n) ? " on" : ""}" data-cmp="${esc(n)}" title="compare side by side">compare</button>`;
const vibeKey = q => q.replace(/^(something |apps |an app )?(like |alternatives? to |instead of )?/, "").trim();
$("#fossbtn").addEventListener("click", () => run("foss", S.fossonly ? "off" : "on", {confirm:false, quiet:true}));   // run() reloads the app list after
const closedChip = p => p.foss === "closed" ? `<span class="chip closed" title="closed source: nobody outside the company can check what's in it (license: ${esc(p.license)})">closed source</span>` : "";
function renderMain(){
  const q = $("#q").value.trim().toLowerCase();
  const vk = vibeKey(q), vapps = (S.vibes || {})[vk] || [];
  const vhits = vapps.map(n => S.main.find(p => p.name === n)).filter(Boolean).sort((a, b) => (a.foss === "closed") - (b.foss === "closed"));   // free ones first
  const hits = S.main.filter(p => !vapps.includes(p.name) && (!q || (p.name+" "+p.desc+" "+p.alias.join(" ")).toLowerCase().includes(q)));
  const mk = p => card({name:p.name, ver:p.ver, desc:p.desc, trust:p.trust, chips: closedChip(p), actions: installBtns(p.name) + cmpBtn(p.name) + devBtns(p.name)});
  $("#maingrid").innerHTML = (vhits.length ? `<div class="vibehead">apps like ${esc(vk)}</div>` + vhits.map(mk).join("") + (hits.length ? `<div class="vibehead">everything else that matched</div>` : "") : "")
    + (hits.length ? hits.map(mk).join("") : vhits.length ? "" : `<div class="empty">nothing in Main GURT matched — try "search everywhere" (or "like photoshop")</div>`);
  const direct = /^[a-z0-9-]+\/[A-Za-z0-9._+-]+$/.test($("#q").value.trim()) && !/^(https?:)/.test($("#q").value);
  $("#direct").hidden = !direct; if (direct) $("#directbtn").textContent = `install ${$("#q").value.trim()}`;
}
let SIZES = null, BYSIZE = false;
// where an installed app really came from: a Main GURT recipe that installed a Flathub app is a flatpak, one that built
// from source says so (not just "Main GURT")
function origin(i){
  if (i.via) { const s = i.via.split("/")[0]; return {src: s, trust: s === "flatpak" ? "flatpak" : s === "snap" ? "snap" : TRUST[s] ? s : "official"}; }
  const m = i.src === "gurt" && S.main.find(p => p.name === i.name);
  return {src: i.src, trust: m ? m.trust : i.src};
}
function renderInstalled(){
  const q = $("#iq").value.trim().toLowerCase();
  let list = S.installed.filter(i => !q || (i.spec+" "+i.desc).toLowerCase().includes(q));
  if (BYSIZE && SIZES) list = [...list].sort((a, b) => (SIZES[b.key] || 0) - (SIZES[a.key] || 0));
  const others = Object.entries(S.outside || {}).map(([n, how]) => [S.main.find(p => p.name === n), how])
    .filter(([m]) => m && (!q || (m.name + " " + m.desc).toLowerCase().includes(q)));
  $("#igrid").innerHTML = (list.length ? list.map(i => { const o = origin(i); return card({name:i.name, src:o.src, ver:i.ver, desc:i.desc, trust:o.trust,
      chips:`${i.via || i.src === "gurt" ? `<span class="chip" title="${esc(i.via ? "Main GURT recipe → " + i.via : "Main GURT recipe")}">Main GURT recipe</span>` : ""}${i.reason==="dep"?'<span class="chip">dependency</span>':""}${i.held?'<span class="chip">held</span>':""}${SIZES && SIZES[i.key] != null ? `<span class="chip" title="space it takes on your disk">${fmtSize(SIZES[i.key])}</span>` : ""}`,
      actions: actBtn("remove","remove",i.spec,"danger") + actBtn("rollback","rollback",i.spec,"ghost") +
        (i.held ? actBtn("unhold","unhold",i.spec,"ghost") : actBtn("hold","hold",i.spec,"ghost"))}); }).join("")
    : `<div class="empty">${S.installed.length ? "nothing matched" : "nothing installed with gurt yet"}</div>`)
    + (others.length ? `<div class="vibehead">on your computer, not from gurt (${others.length})</div>` + others.map(([m, how]) =>
        card({name:m.name, src:how === "on your PATH" || how === "/opt" ? "system" : how, ver:"", desc:m.desc, trust:"-",
          actions:`<span class="chip ok" title="installed with ${esc(howLabel(how))}, not with gurt">installed ✓ (${esc(how)})</span>`})).join("") : "");
}

// ── running gurt ──
const VERB = {dropped:"Install", de:"Install the desktop", install:"Install", "install-many":"Install", sysup:"Update your whole system", remove:"Remove", undo:"Undo the last thing gurt did", rollback:"Roll back", hold:"Hold", unhold:"Unhold", upgrade:"Update everything (your system + apps)", "self-update":"Update gurt", outsource:"Build + install"};
function ask(title, body){ return new Promise(res => { $("#ctitle2").textContent = title; $("#cbody").textContent = body; const d=$("#confirm");
  const done = v => { d.close(); $("#cyes").onclick = $("#cno").onclick = null; res(v); };
  $("#cyes").onclick = () => done(true); $("#cno").onclick = () => done(false); d.onclose = () => res(false); d.showModal(); }); }

let bgCheck = null, bgStopped = false;   // the quiet update check that runs right after the app opens
const startBgCheck = () => { if (!SETUP && !busy && !bgCheck && typeof S !== "undefined" && S && S.dev !== "locked") bgCheck = check(true, true).catch(() => {}).finally(() => { bgCheck = null; }); };
async function free(){   // can gurt start something? the quiet update check never blocks you: it stops, your thing goes first
  if (busy && bgCheck) {
    const p = bgCheck; bgStopped = true;
    if (cur) await api(`/api/job/${cur}/cancel`, {}).catch(() => {});
    await p;
  }
  if (busy) { alert("gurt's still busy with the last thing, hold up"); return false; }
  return true;
}
async function run(cmd, arg="", {all=false, quiet=false, confirm=true, fmt="", bg=false} = {}){   // bg: the background update check (buttons stay clickable)
  if (!await free()) return null;
  if (confirm && VERB[cmd]) {
    const warn = cmd === "outsource" ? " This builds + runs code from that repo — only do it if you trust it." :
                 /^aur\//.test(arg) ? " AUR packages are built from random people's recipes — make sure you trust it." : "";
    if (!await ask(`${VERB[cmd]}${arg ? " " + arg : ""}?`, `gurt will ${cmd} ${arg || ""}.${warn}`)) return null;
  }
  busy = true; if (!bg) setBusyUI(true);
  const r = await api("/api/run", {cmd, arg, all, fmt});
  if (r.error) { busy = false; setBusyUI(false); alert(r.error); return null; }
  cur = r.job; let from = 0, lines = [];
  if (!quiet) { $("#ctitle").textContent = `gurt ${cmd} ${arg}`; $("#cdot").className = "dot run"; $("#console").classList.add("open"); }   // quiet ones leave the log alone
  if (!quiet) $("#cout").textContent = "";
  let pwShown = false;
  while (true) {
    const j = await api(`/api/job/${cur}?from=${from}`);
    from = j.next; lines.push(...j.lines); achLines(j.lines);
    if (!quiet && j.lines.length) { const o = $("#cout"); o.textContent += j.lines.join("\n") + "\n"; o.scrollTop = o.scrollHeight; }
    if (j.ask && !pwShown) { pwShown = true; askPassword(j.ask); }
    if (!j.ask) pwShown = false;
    if (j.done) { if (!quiet) { $("#cdot").className = "dot " + (j.rc === 0 ? "ok" : "bad"); SFX.play(j.rc === 0 ? "ok" : "err"); } busy = false; setBusyUI(false); cur = null;
      if (j.rc === 0 && cmd === "install" && arg && arg === LOTTO_WIN) { LOTTO_WIN = ""; achieve("lottery"); }
      await load();
      if (bgStopped && !bgCheck) { bgStopped = false; setTimeout(startBgCheck, 1500); }   // the update check you interrupted runs again after
      return {rc:j.rc, lines}; }
    await new Promise(r => setTimeout(r, 300));
  }
}
// 🏆 achievements: gurt prints "🏆 achievement unlocked: …" → a toast pops up
let toastT = null;
function toast(html){ const t = $("#toast"); t.innerHTML = html; t.hidden = false; t.style.animation = "none"; void t.offsetWidth; t.style.animation = ""; clearTimeout(toastT); toastT = setTimeout(() => t.hidden = true, 4200); }
const noEmoji = t => String(t).replace(/[\p{Extended_Pictographic}\uFE0F\u200D]/gu, "").replace(/\s{2,}/g, " ").trim();   // gurt's own text has emoji; the app shows none
function achLines(lines){ lines.forEach(l => { const m = l.match(/🏆 achievement unlocked: (.+)/); if (m) { toast("achievement unlocked: " + esc(noEmoji(m[1]))); SFX.play("achieve"); } }); }
async function achieve(id){ const r = await api("/api/achieve", {id}).catch(() => ({})); if (r.line) achLines([r.line]); }
// GURTd: the background daemon's settings (the same as gurt gurtd config)
const GURTD_ROWS = [["running", "running", "in the background while you're logged in"],
  ["autoupdate", "auto-update my apps", "apps that need your password get a notification instead"],
  ["fresh", "keep package lists fresh", "every 3 hours, so searches and update checks are instant"],
  ["watch", "watch Downloads", "a new .deb / .rpm / AppImage asks to install it with GURT"],
  ["saver", "saver", "no update checks on battery or metered data, they wait till you're plugged in"]];
const QUIET = ["off", "21-7", "22-8", "23-8", "0-9"];
async function gurtdRender(){
  const d = await api("/api/gurtd").catch(() => null); if (!d) return;
  $("#gurtdset").innerHTML = GURTD_ROWS.map(([k, t, sub]) => `<div><span><b>${t}</b><small>${k === "saver" && d.holding && d.saver ? `holding off right now: ${esc(d.holding)}` : sub}</small></span>
    <button class="btn small ${d[k] ? "" : "ghost"}" data-gd="${k}">${d[k] ? "on" : "off"}</button></div>`).join("") +
    `<div><span><b>quiet hours</b><small>no popups then, they wait till it's over</small></span>
    <select data-gq title="quiet hours">${[...new Set([...QUIET, d.quiet || "off"])].map(q => `<option value="${q}"${q === (d.quiet || "off") ? " selected" : ""}>${q === "off" ? "off" : q.replace("-", ":00 – ") + ":00"}</option>`).join("")}</select></div>`;
  $("#gurtdlog").textContent = d.log || "GURTd hasn't run yet";
  $("#gurtdset").dataset.attached = d.attached ? "1" : "";
}
$("#gurtdbtn").addEventListener("click", async () => { await gurtdRender(); $("#gurtddlg").showModal(); });
$("#gurtdclose").addEventListener("click", () => $("#gurtddlg").close());
$("#gurtdset").addEventListener("change", async e => {
  const s = e.target.closest("[data-gq]"); if (!s) return;
  s.disabled = true; await run("gurtd", "quiet-" + s.value, {confirm:false, quiet:true}); setTimeout(gurtdRender, 500);
});
$("#gurtdset").addEventListener("click", async e => {
  const b = e.target.closest("[data-gd]"); if (!b) return;
  const k = b.dataset.gd, on = b.textContent.trim() === "on";
  if (k === "running" && on && $("#gurtdset").dataset.attached && !await ask("Turn GURTd off?", "this GURT window runs on GURTd, so it closes too. open GURT again after.")) return;
  b.disabled = true;
  await run("gurtd", k === "running" ? (on ? "off" : "on") : `${k}-${on ? "off" : "on"}`, {confirm:false, quiet:true});
  setTimeout(gurtdRender, 800);
});
let HIST = [];
const histLast = () => !HIST.length ? [] : HIST[0].tx ? HIST.filter(i => i.tx === HIST[0].tx) : [HIST[0]];   // what gurt undo takes back
const histWhat = i => i.what !== "install" ? "removed" : i.was && i.was !== i.ver ? `updated · ${esc(i.was)} → ${esc(i.ver)}` : `installed${i.ver ? " · " + esc(i.ver) : ""}`;
$("#histbtn").addEventListener("click", async () => {
  const r = await api("/api/history").catch(() => ({items:[]})); HIST = r.items || [];
  const last = new Set(histLast());
  $("#histlist").innerHTML = HIST.length ? HIST.map(i => `<div class="ach${last.has(i) ? " last" : ""}"><span class="mark">${i.what === "install" ? "+" : "−"}</span><span><b>${esc(i.app)}</b><small>${histWhat(i)}</small></span><span class="when">${esc(i.when)}</span></div>`).join("")
    : `<p>nothing yet, your installs and removals show up here.</p>`;
  $("#histundo").hidden = !HIST.length;
  $("#histdlg").showModal();
});
$("#histundo").addEventListener("click", async () => {
  const steps = histLast().map(i => i.what !== "install" ? `put ${i.app} back` : i.was && i.was !== i.ver ? `${i.app} back to ${i.was}` : `remove ${i.app}`);
  $("#histdlg").close();
  if (!await ask("Undo the last thing gurt did?", steps.join(", ") + ". Undo again puts it back.")) return;
  run("undo", "", {confirm:false});
});
$("#histclose").addEventListener("click", () => $("#histdlg").close());
// free up space: gurt hogs junk (toss buttons) + gurt -a hogs (the biggest things on the disk, whoever installed them)
async function diskRender(){
  $("#junklist").innerHTML = $("#biglist").innerHTML = `<div><span><small>measuring…</small></span></div>`;
  const d = await api("/api/disk").catch(() => ({junk:[], big:[]}));
  $("#junklist").innerHTML = (d.junk || []).length ? d.junk.map(j => `<div><span class="sz">${fmtSize(j.bytes)}</span><span><b>${esc(j.what)}</b><small>${esc(noEmoji(j.desc))}${j.root ? ", asks for your password" : ""}</small></span>
    <button class="btn small danger" data-toss="${esc(j.what)}">toss</button></div>`).join("") : `<div><span><small>nothing worth tossing</small></span></div>`;
  const keys = new Set((S.installed || []).map(i => i.spec));
  $("#biglist").innerHTML = (d.big || []).map(b => { const i = b.name.indexOf("/"), from = i > 0 ? b.name.slice(0, i) : "gurt";
    return `<div><span class="sz">${fmtSize(b.bytes)}</span><span><b>${esc(i > 0 ? b.name.slice(i + 1) : b.name)}</b></span><span class="chip">${esc(from)}</span>${keys.has(b.name) ? actBtn("remove", "remove", b.name, "ghost") : ""}</div>`; }).join("")
    || `<div><span><small>couldn't measure anything</small></span></div>`;
}
$("#diskbtn").addEventListener("click", () => { $("#diskdlg").showModal(); diskRender(); });
$("#diskclose").addEventListener("click", () => $("#diskdlg").close());
$("#junklist").addEventListener("click", async e => {
  const b = e.target.closest("[data-toss]"); if (!b) return;
  b.disabled = true; $("#diskdlg").close();
  const r = await run("toss", b.dataset.toss, {confirm:false});
  if (r) { $("#diskdlg").showModal(); diskRender(); }
});
// press / anywhere to jump to the search box (like GitHub + YouTube)
document.addEventListener("keydown", e => {
  if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey || document.querySelector("dialog[open]")) return;
  const t = e.target; if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
  const q = [...document.querySelectorAll("#q, #iq")].find(x => x.offsetParent); if (q) { e.preventDefault(); q.focus(); q.select(); }
});
$("#achbtn").addEventListener("click", async () => {
  const r = await api("/api/achievements").catch(() => ({items:[]})), items = r.items || [], n = items.filter(i => i.got).length;
  $("#achlist").innerHTML = `<div class="streak">${n}/${items.length} unlocked${n === items.length && n ? " — you beat gurt" : ""}</div>` + items.map(i =>
    `<div class="ach${i.got ? "" : " locked"}"><span class="mark">${i.got ? "✓" : "·"}</span><span><b>${esc(noEmoji(i.title))}</b><small>${esc(noEmoji(i.what))}</small></span>${i.got ? `<span class="when">${esc(i.got)}</span>` : ""}</div>`).join("");
  $("#achdlg").showModal();
});
$("#achclose").addEventListener("click", () => $("#achdlg").close());
// first time on 1.0: a little welcome (once), and the day-one trophy
(() => {
  const seen = document.documentElement.dataset.seen || "", ver = () => (S && S.version) || "";
  const show = () => {
    if (devGate()) return;   // the dev password comes first
    if (SETUP || document.documentElement.dataset.wiz === "new") { wizStart(); return; }   // brand new: the wizard covers what's new too
    if (!/^1\./.test(ver()) || /^1\./.test(seen)) return;
    $("#v1dlg").showModal(); SFX.play("legendary");
    $("#v1ok").onclick = () => $("#v1dlg").close();
    $("#v1wiz").onclick = () => { $("#v1dlg").close(); wizStart(); };
    $("#v1dlg").addEventListener("close", () => { api("/api/seen", {v: ver()}).catch(() => {}); achieve("v1"); }, {once: true});
  };
  const wait = setInterval(() => { if (typeof S !== "undefined" && S && S.version) { clearInterval(wait); show(); } }, 300);
})();
function setBusyUI(on){ $("#cstop").hidden = !on; document.querySelectorAll("[data-cmd], #upbtn, #checkbtn, #selfbtn, #syncbtn, #qall").forEach(b => b.disabled = on); }
function askPassword(prompt){ $("#pwprompt").textContent = "gurt needs your password (sudo) to put files in system folders. " + (prompt.includes("password") ? "" : prompt);
  $("#pwin").value = ""; $("#pw").showModal(); $("#pwin").focus(); }
$("#pwform").addEventListener("submit", async e => { e.preventDefault(); const v = $("#pwin").value; $("#pwin").value = ""; $("#pw").close(); if (cur) await api(`/api/job/${cur}/pass`, {password:v}); });
$("#pwno").addEventListener("click", async () => { $("#pw").close(); if (cur) await api(`/api/job/${cur}/cancel`, {}); });
$("#cstop").addEventListener("click", async () => { if (cur) await api(`/api/job/${cur}/cancel`, {}); });
$("#chide").addEventListener("click", () => $("#console").classList.toggle("open"));

document.addEventListener("click", e => { const b = e.target.closest("[data-cmd]"); if (b && !b.disabled) run(b.dataset.cmd, b.dataset.arg); });
// compare: pick up to 4 Main GURT apps, see them side by side
function renderCmp(){
  $("#cmptray").hidden = !CMP.length; $("#cmplist").textContent = CMP.join(" · ") + (CMP.length < 2 ? "  (pick one more)" : "");
  $("#cmpgo").disabled = CMP.length < 2;
  document.querySelectorAll("[data-cmp]").forEach(b => b.classList.toggle("on", CMP.includes(b.dataset.cmp)));
}
document.addEventListener("click", e => {
  const b = e.target.closest("[data-cmp]"); if (!b) return;
  const n = b.dataset.cmp;
  if (CMP.includes(n)) CMP = CMP.filter(x => x !== n); else if (CMP.length < 4) CMP.push(n); else { SFX.play("err"); return; }
  SFX.play(CMP.includes(n) ? "pick" : "unpick"); renderCmp();
});
$("#cmpclear").addEventListener("click", () => { CMP = []; renderCmp(); });
$("#cmpclose").addEventListener("click", () => $("#cmpdlg").close());
$("#cmpgo").addEventListener("click", async () => {
  achieve("compare");
  if (!SIZES) SIZES = (await api("/api/sizes").catch(() => ({}))).sizes || {};
  const ps = CMP.map(n => S.main.find(p => p.name === n)).filter(Boolean);
  const row = (label, f) => `<tr><th>${label}</th>${ps.map(p => `<td>${f(p)}</td>`).join("")}</tr>`;
  const sizeOf = p => { const k = Object.keys(SIZES).find(k => k === p.ikey || k === p.name); return k ? fmtSize(SIZES[k]) : "–"; };
  $("#cmptable").innerHTML = `<table>${row("app", p => `<b>${esc(p.name)}</b>`)}${row("what it is", p => esc(p.desc))}${row("comes from", p => trustChip(p.trust) || "Main GURT")}
    ${row("version", p => esc(p.ver))}${row("category", p => esc(p.category || "–"))}${row("license", p => esc(p.license || "–"))}${row("free software", p => ({foss: "yes", closed: "no, closed source", unknown: "unknown"})[p.foss] || "–")}
    ${row("installed", p => inst(p.name) ? "yes" : "no")}${row("size on disk", sizeOf)}${row("website", p => p.url ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.url.replace(/^https?:\/\//, "").slice(0, 40))}</a>` : "–")}
    ${row("", p => installBtns(p.name))}</table>`;
  $("#cmpdlg").showModal();
});
$("#hogbtn").addEventListener("click", async () => {
  BYSIZE = !BYSIZE; $("#hogbtn").classList.toggle("on", BYSIZE);
  if (BYSIZE && !SIZES) { $("#hogbtn").textContent = "measuring…"; SIZES = (await api("/api/sizes").catch(() => ({}))).sizes || {}; $("#hogbtn").textContent = "biggest first"; }
  renderInstalled();
});
function renderNotify(){ $("#notifybtn").textContent = S.notify ? "alerts on" : "alert me"; $("#notifybtn").classList.toggle("on", !!S.notify); }
$("#notifybtn").addEventListener("click", async () => { const r = await run("notify", S.notify ? "off" : "on", {confirm:false, quiet:true}); if (r && r.rc === 0) S.notify = !S.notify; renderNotify(); });

// ── search everywhere (parses `gurt search -a`) ──
// ── source tabs: search one distro's repos ──
const BLURB = {
  aur: "The Arch User Repository — PKGBUILDs gurt builds from source, on any distro.",
  apt: "Debian's packages (.deb). gurt downloads, checks and installs them on whatever you run.",
  dnf: "Fedora's packages (.rpm), installable anywhere.",
  zypper: "openSUSE Tumbleweed's packages — yes, even on Red Star OS",
  pacman: "Arch's official binary packages, installable on non-Arch distros.",
  flatpak: "Flathub apps, sandboxed. gurt sets up flatpak + Flathub for you.",
  snap: "Snap Store apps. gurt sets up snapd for you."};
BLURB.dirt = "DIRT is GURT's mature section (18+). Packages here install with gurt install dirt/<name>.";
let SRC = "gurt";
function renderDirt(){
  const q = $("#q").value.trim().toLowerCase().replace(/^dirt\//, "");
  const list = (S.dirtpkgs || []).filter(p => !q || (p.name + " " + p.desc + " " + (p.alias||[]).join(" ")).toLowerCase().includes(q));
  $("#srcgrid").innerHTML = list.length ? list.map(p => card({name:p.name, src:"dirt", ver:p.ver, desc:p.desc, actions: installBtns(`dirt/${p.name}`) + devBtns(p.name, "dirt")})).join("")
    : `<div class="empty">${(S.dirtpkgs || []).length ? "nothing in DIRT matched" : "DIRT is empty rn"}</div>`;
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
  if (!main) $("#srcgrid").innerHTML = `<div class="empty">type something and hit Enter to search ${esc(src)}</div>`;
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
  $("#srcgrid").innerHTML = `<div class="empty">searching ${esc(SRC)}…</div>`;
  const r = await run("search", `${SRC}/${t}`, {quiet:true, confirm:false}); if (!r) return;
  const res = parseSearch(r.lines);
  $("#srcgrid").innerHTML = res.length ? res.slice(0, 120).map(p => card({name:p.name, src:p.src, ver:p.ver, desc:p.desc,
      actions: installBtns(`${p.src}/${p.name}`)})).join("")
    : `<div class="empty">nothing on ${esc(SRC)} matched "${esc(t)}" ${r.lines.some(l => /unreachable|couldn.t|==> nah:|no package index/.test(l)) ? "(couldn't reach it — check your internet)" : "womp womp"}</div>`;
}
document.querySelectorAll("#srcs button").forEach(b => b.addEventListener("click", () => setSrc(b.dataset.src)));

async function searchAll(){
  if (SRC !== "gurt") return searchSrc();
  const t = $("#q").value.trim(); if (!t) return;
  if (/^(https?:\/\/|git@)/.test(t)) { run("outsource", t); return; }
  $("#allres").hidden = false; $("#allgrid").innerHTML = `<div class="empty">searching every source…</div>`;
  const r = await run("search", t, {all:true, quiet:true, confirm:false}); if (!r) return;
  const res = parseSearch(r.lines);
  $("#allgrid").innerHTML = res.length ? res.slice(0, 120).map(p => card({name:p.name, src:p.src, ver:p.ver, desc:p.desc,
      actions: installBtns(p.src === "gurt" ? p.name : `${p.src}/${p.name}`)})).join("") : `<div class="empty">nothing anywhere matched "${esc(t)}" womp womp</div>`;
}
$("#q").addEventListener("input", () => { if (SRC === "dirt") renderDirt(); if (SRC === "gurt") renderMain(); if (!$("#q").value) $("#allres").hidden = true; });
$("#q").addEventListener("keydown", e => { if (e.key === "Enter") searchAll(); });

// ── sfx: synth sounds (WebAudio, no sound files) — every skin has its own set, mutes ──
const SFX = (() => {
  let ctx = null, on = document.documentElement.dataset.sfx !== "off";
  // one note: freq, start, length, wave, volume, glide-to freq, attack
  const tone = (f, t, dur, type = "square", vol = 0.05, f2 = 0, atk = 0.004) => {
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = type; o.frequency.setValueAtTime(f, t); if (f2) o.frequency.exponentialRampToValueAtTime(f2, t + dur);
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(vol, t + atk); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(ctx.destination); o.start(t); o.stop(t + dur + 0.05);
  };
  const bell = (f, t, dur, vol = 0.05) => { tone(f, t, dur, "triangle", vol); tone(f * 2.01, t, dur * 0.6, "sine", vol * 0.35); };
  const pad = (fs, t, dur, type = "sine", vol = 0.03, atk = 0.25) => fs.forEach(f => { tone(f, t, dur, type, vol, 0, atk); tone(f * 1.004, t, dur, type, vol * 0.7, 0, atk); });
  const arp = (fs, t, step, dur, fn) => fs.forEach((f, i) => fn(f, t + i * step, dur));
  const SETS = {
    gurt: {
      click: t => tone(620, t, 0.045, "square", 0.03),
      tick: t => tone(700 + Math.random() * 600, t, 0.03, "square", 0.025),
      jackpot: t => arp([523, 659, 784, 1047, 1319], t, 0.08, 0.18, (f, s, d) => tone(f, s, d, "triangle", 0.06)),
      copy: t => { tone(988, t, 0.06, "sine", 0.06); tone(1480, t + 0.06, 0.1, "sine", 0.06); },
      pick: t => tone(660, t, 0.07, "triangle", 0.05, 990), unpick: t => tone(660, t, 0.07, "triangle", 0.05, 440),
      ok: t => arp([784, 1047, 1568], t, 0.07, 0.14, (f, s, d) => tone(f, s, d, "triangle", 0.06)),
      err: t => { tone(196, t, 0.18, "sawtooth", 0.05); tone(147, t + 0.16, 0.28, "sawtooth", 0.05); },
      theme: t => tone(300, t, 0.22, "sine", 0.05, 900), pop: t => tone(400, t, 0.09, "sine", 0.07, 1200),
      startup: t => arp([392, 523, 659, 784], t, 0.07, 0.2, (f, s, d) => tone(f, s, d, "triangle", 0.05)),
    },
    win11: {   // soft, round, quiet — modern Windows vibes
      click: t => tone(1400, t, 0.03, "sine", 0.025),
      tick: t => tone(1100 + Math.random() * 300, t, 0.035, "sine", 0.03),
      jackpot: t => { arp([659, 784, 988, 1319], t, 0.09, 0.5, (f, s, d) => tone(f, s, d, "sine", 0.05, 0, 0.01)); },
      copy: t => { tone(1319, t, 0.18, "sine", 0.05, 0, 0.008); tone(1760, t + 0.09, 0.25, "sine", 0.04, 0, 0.008); },
      pick: t => tone(880, t, 0.08, "sine", 0.04, 1175), unpick: t => tone(880, t, 0.08, "sine", 0.04, 660),
      ok: t => { tone(988, t, 0.35, "sine", 0.05, 0, 0.01); tone(1319, t + 0.12, 0.45, "sine", 0.05, 0, 0.01); },
      err: t => { tone(523, t, 0.25, "sine", 0.06, 0, 0.01); tone(392, t + 0.14, 0.4, "sine", 0.06, 0, 0.01); },
      theme: t => tone(500, t, 0.3, "sine", 0.04, 1000, 0.05), pop: t => tone(700, t, 0.12, "sine", 0.05, 1050),
      startup: t => { pad([262, 330, 392, 494], t, 1.4, "sine", 0.025, 0.35); arp([784, 988, 1175], t + 0.35, 0.12, 0.6, (f, s, d) => tone(f, s, d, "sine", 0.035, 0, 0.02)); },
    },
    xp: {      // bells + a big warm swell — very 2001
      click: t => tone(1800, t, 0.018, "square", 0.02),
      tick: t => bell(988 + Math.random() * 500, t, 0.08, 0.03),
      jackpot: t => { pad([311, 466, 622, 784], t, 2.2, "sine", 0.025, 0.5); arp([622, 932, 1245, 1568], t + 0.3, 0.22, 1.0, (f, s, d) => bell(f, s, d, 0.045)); },
      copy: t => { bell(1047, t, 0.5, 0.05); bell(1568, t + 0.11, 0.6, 0.04); },     // the "ding"
      pick: t => bell(1175, t, 0.18, 0.035), unpick: t => bell(784, t, 0.18, 0.035),
      ok: t => arp([622, 784, 932, 1245], t, 0.1, 0.5, (f, s, d) => bell(f, s, d, 0.045)),
      err: t => arp([784, 587, 392], t, 0.13, 0.45, (f, s, d) => bell(f, s, d, 0.06)),  // critical-stop energy
      theme: t => tone(400, t, 0.35, "triangle", 0.04, 800, 0.05), pop: t => bell(880, t, 0.25, 0.05),
      startup: t => { pad([156, 233, 311, 392, 466], t, 3.0, "sine", 0.022, 0.8); arp([622, 932, 1245, 1568, 1865], t + 0.6, 0.25, 1.4, (f, s, d) => bell(f, s, d, 0.04)); },
    },
    vapor: {   // slowed-down, detuned, everything glides down a little
      click: t => tone(880, t, 0.08, "sine", 0.03, 760),
      tick: t => tone(500 + Math.random() * 300, t, 0.07, "sine", 0.03, 420),
      jackpot: t => { pad([220, 277, 330, 415], t, 2.4, "sawtooth", 0.012, 0.6); arp([659, 554, 494, 440], t + 0.2, 0.3, 1.0, (f, s, d) => tone(f, s, d, "sine", 0.04, f * 0.94, 0.05)); },
      copy: t => tone(1047, t, 0.4, "sine", 0.05, 880, 0.02),
      pick: t => tone(660, t, 0.18, "sine", 0.04, 620), unpick: t => tone(440, t, 0.18, "sine", 0.04, 400),
      ok: t => pad([262, 330, 392, 494], t, 1.2, "sine", 0.025, 0.2),
      err: t => tone(330, t, 0.6, "sawtooth", 0.035, 110),
      theme: t => tone(600, t, 0.5, "sine", 0.04, 300), pop: t => tone(990, t, 0.2, "sine", 0.05, 800),
      startup: t => { pad([131, 165, 196, 247], t, 3.0, "sawtooth", 0.012, 0.9); arp([494, 440, 392, 330], t + 0.8, 0.4, 1.2, (f, s, d) => tone(f, s, d, "sine", 0.035, f * 0.97, 0.1)); },
    },
    hacker: {  // terminal blips + modem garbage
      click: t => tone(2400, t, 0.012, "square", 0.02),
      tick: t => tone(1200 + Math.random() * 2400, t, 0.015, "square", 0.02),
      jackpot: t => { for (let i = 0; i < 12; i++) tone(800 + Math.random() * 2600, t + i * 0.035, 0.03, "square", 0.025); arp([523, 784, 1047], t + 0.45, 0.06, 0.12, (f, s, d) => tone(f, s, d, "square", 0.03)); },
      copy: t => { tone(1800, t, 0.02, "square", 0.03); tone(2400, t + 0.04, 0.02, "square", 0.03); },
      pick: t => tone(1600, t, 0.03, "square", 0.025), unpick: t => tone(800, t, 0.03, "square", 0.025),
      ok: t => arp([1047, 1319, 1568, 2093], t, 0.04, 0.05, (f, s, d) => tone(f, s, d, "square", 0.03)),
      err: t => { tone(110, t, 0.3, "square", 0.04); tone(117, t, 0.3, "square", 0.04); },
      theme: t => tone(200, t, 0.15, "square", 0.03, 2000), pop: t => tone(1400, t, 0.03, "square", 0.03),
      startup: t => { for (let i = 0; i < 20; i++) tone(600 + Math.random() * 1800, t + i * 0.04, 0.035, "square", 0.02); tone(1000, t + 0.9, 0.25, "sine", 0.04); },
    },
    w95: {     // chunky square waves + a brassy ta-da
      click: t => tone(1000, t, 0.03, "square", 0.035),
      tick: t => tone(500 + Math.random() * 400, t, 0.04, "square", 0.03),
      jackpot: t => { arp([523, 659, 784], t, 0.09, 0.12, (f, s, d) => tone(f, s, d, "sawtooth", 0.04, 0, 0.01)); pad([523, 659, 784, 1047], t + 0.3, 0.9, "sawtooth", 0.018, 0.02); },
      copy: t => tone(1568, t, 0.12, "square", 0.04),
      pick: t => tone(784, t, 0.05, "square", 0.035), unpick: t => tone(392, t, 0.05, "square", 0.035),
      ok: t => { tone(523, t, 0.1, "sawtooth", 0.04, 0, 0.01); pad([523, 659, 784, 1047], t + 0.12, 0.7, "sawtooth", 0.018, 0.02); },   // ta-da
      err: t => pad([220, 277, 330], t, 0.35, "square", 0.03, 0.005),   // the "chord"
      theme: t => tone(250, t, 0.25, "square", 0.03, 750), pop: t => tone(660, t, 0.06, "square", 0.04),
      startup: t => { arp([262, 330, 392, 523, 659], t, 0.11, 0.25, (f, s, d) => tone(f, s, d, "square", 0.03)); pad([523, 659, 784], t + 0.6, 1.2, "sawtooth", 0.015, 0.1); },
    },
  };
  // shared by every skin
  SETS.gurt.cursed = t => { for (let i = 0; i < 8; i++) tone(90 + Math.random() * 900, t + i * 0.07, 0.09, "sawtooth", 0.04, 40 + Math.random() * 200); };
  SETS.gurt.legendary = t => { arp([523, 659, 784, 1047, 1319, 1568, 2093], t, 0.07, 0.35, (f, s, d) => tone(f, s, d, "triangle", 0.05)); pad([523, 659, 784, 1047], t + 0.5, 1.6, "sine", 0.03, 0.1); };
  SETS.gurt.achieve = t => { arp([784, 988, 1175, 1568], t, 0.09, 0.3, (f, s, d) => tone(f, s, d, "triangle", 0.05)); };
  const play = name => {
    if (!on) return;
    const set = SETS[document.documentElement.dataset.skin] || SETS.gurt, fn = set[name] || SETS.gurt[name];
    if (!fn) return;
    try {
      ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
      if (ctx.state === "suspended") ctx.resume();
      fn(ctx.currentTime + 0.01);
    } catch {}
  };
  return { play, get on() { return on; }, set(v) { on = v; } };
})();
const SFX_ROLES = {copy:"copy", scopy:"copy", cartcopy:"copy", lotto:"", lotto2:"", themebtn:"theme", sfxbtn:"", musicbtn:"", skinsel:"", tracksel:""};
document.addEventListener("click", e => {
  const b = e.target.closest("button, .src, .bcat, .pkg, nav button, summary");
  if (!b) return;
  const role = b.id in SFX_ROLES ? SFX_ROLES[b.id] : "click";
  if (role) SFX.play(role);
}, true);

const paintSfx = () => { $("#sfxbtn").textContent = SFX.on ? "sounds on" : "sounds off"; };
$("#sfxbtn").addEventListener("click", () => { SFX.set(!SFX.on); paintSfx(); api("/api/sfx", {on:SFX.on}).catch(() => {}); SFX.play("pop"); });
paintSfx();
// one menu for the look + sound stuff, so the header has room
const prefOpen = v => { $("#prefpop").hidden = !v; $("#prefbtn").setAttribute("aria-expanded", v); $("#prefbtn").classList.toggle("on", v); };
$("#prefbtn").addEventListener("click", e => { e.stopPropagation(); prefOpen($("#prefpop").hidden); });
document.addEventListener("click", e => { if (!$("#prefpop").hidden && !e.target.closest(".prefs")) prefOpen(false); });
document.addEventListener("keydown", e => { if (e.key === "Escape" && !$("#prefpop").hidden) { prefOpen(false); $("#prefbtn").focus(); } });
$("#bgroups").addEventListener("change", e => { if (e.target.dataset.n) SFX.play(e.target.checked ? "pick" : "unpick"); });
// ── background music: an original chill shop-style bossa loop, synthesized live (no audio files) ──
const MUSIC = (() => {
  let ctx = null, master = null, timer = null, nextT = 0, step = 0, noise = null, on = document.documentElement.dataset.music !== "off";
  const mtof = m => 440 * Math.pow(2, (m - 69) / 12);
  // tracks: 8 bars × 8 eighths each. chords (midi), bass roots, a 64-step melody (0 = rest), what plays them, and the drums
  const TRACKS = {
    shop: {bpm: 116, swing: 0.1, comp: [0, 3, 6], chord: ["sine", 2, 0.018, 0.55], bass: "triangle", lead: ["sine", 4, 0.045, 0.45], drums: "shaker",
      chords: [[53,57,60,64],[50,53,57,60],[55,58,62,65],[48,52,55,58],[57,60,64,67],[50,54,57,60],[55,58,62,65],[48,52,55,58]], roots: [41,38,43,36,45,38,43,36],
      mel: [72,0,76,0,79,77,76,0, 74,0,0,72,69,0,72,0, 70,0,74,0,77,0,76,74, 72,0,0,0,67,0,70,72, 76,0,79,0,81,79,76,0, 78,0,76,74,72,0,0,74, 70,0,72,74,77,76,74,0, 72,0,0,0,0,0,0,0]},
    lofi: {bpm: 78, swing: 0.16, comp: [0, 4], chord: ["triangle", 2, 0.02, 1.3], bass: "sine", lead: ["sine", 3, 0.035, 0.7], drums: "lofi",
      chords: [[60,64,67,71],[57,60,64,67],[62,65,69,72],[55,59,62,65],[60,64,67,71],[52,55,59,62],[53,57,60,64],[55,59,62,65]], roots: [36,33,38,31,36,40,41,43],
      mel: [76,0,0,74,72,0,0,0, 72,0,69,0,67,0,0,0, 74,0,0,72,69,0,72,0, 71,0,0,0,0,0,67,0, 76,0,79,0,76,74,72,0, 72,0,0,74,76,0,0,0, 77,0,76,0,74,0,72,0, 72,0,0,0,0,0,0,0]},
    chip: {bpm: 140, swing: 0, arp: true, chord: ["square", 0, 0.014, 0.11], bass: "square", lead: ["square", 0, 0.028, 0.18], drums: "chip",
      chords: [[64,67,71],[60,64,67],[67,71,74],[62,66,69],[64,67,71],[60,64,67],[62,66,69],[59,63,66]], roots: [40,36,43,38,40,36,38,35],
      mel: [76,0,79,0,83,0,81,79, 76,0,0,0,72,0,74,76, 79,0,0,79,81,0,83,0, 81,0,79,0,78,0,74,0, 76,0,79,0,83,0,86,0, 84,0,83,0,79,0,76,0, 78,0,79,0,81,0,83,0, 83,0,0,0,0,0,0,0]},
    synth: {bpm: 100, swing: 0, comp: [0], chord: ["sawtooth", 0, 0.008, 1.9], bass: "sawtooth", octbass: true, lead: ["sawtooth", 2, 0.02, 0.5], drums: "synth",
      chords: [[57,60,64],[53,57,60],[55,60,64],[55,59,62],[57,60,64],[53,57,60],[55,60,64],[56,59,64]], roots: [45,41,48,43,45,41,48,40],
      mel: [69,0,0,72,0,0,76,0, 74,0,72,0,69,0,0,0, 72,0,0,76,0,0,79,0, 79,0,76,0,74,0,72,0, 69,0,0,72,0,0,76,0, 77,0,76,0,72,0,0,0, 76,0,74,0,72,0,71,0, 68,0,0,0,71,0,0,0]},
  };
  const SKIN_TRACK = {vapor: "synth", hacker: "chip"};
  let pick = document.documentElement.dataset.track || "auto";
  const track = () => TRACKS[pick !== "auto" && TRACKS[pick] ? pick : SKIN_TRACK[document.documentElement.dataset.skin] || "shop"];
  const voice = (t, f, dur, vol, type, harm) => {
    const g = ctx.createGain(); g.connect(master);
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(vol, t + 0.008); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    [[1, 1], [harm, 0.25]].forEach(([mul, lv]) => {
      if (!mul) return;
      const o = ctx.createOscillator(), og = ctx.createGain(); o.type = type; o.frequency.value = f * mul; og.gain.value = lv;
      o.connect(og).connect(g); o.start(t); o.stop(t + dur + 0.05);
    });
  };
  const shaker = (t, vol) => {
    const s = ctx.createBufferSource(), g = ctx.createGain(), hp = ctx.createBiquadFilter();
    s.buffer = noise; hp.type = "highpass"; hp.frequency.value = 7000;
    g.gain.setValueAtTime(vol, t); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.05);
    s.connect(hp).connect(g).connect(master); s.start(t); s.stop(t + 0.06);
  };
  const hit = (t, vol, freq, type, dur) => {   // noise drums: hats (highpass), snares (bandpass)
    const s = ctx.createBufferSource(), g = ctx.createGain(), f = ctx.createBiquadFilter();
    s.buffer = noise; f.type = type; f.frequency.value = freq;
    g.gain.setValueAtTime(vol, t); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    s.connect(f).connect(g).connect(master); s.start(t); s.stop(t + dur + 0.01);
  };
  const kick = (t, vol) => {
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.frequency.setValueAtTime(130, t); o.frequency.exponentialRampToValueAtTime(42, t + 0.12);
    g.gain.setValueAtTime(vol, t); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.25);
    o.connect(g).connect(master); o.start(t); o.stop(t + 0.3);
  };
  const DRUMS = {
    shaker: (t, e) => shaker(t, e % 2 ? 0.02 : 0.012),
    lofi: (t, e) => { if (e === 0 || e === 5) kick(t, 0.09); if (e === 2 || e === 6) hit(t, 0.03, 1500, "bandpass", 0.14); hit(t, e % 2 ? 0.006 : 0.01, 8000, "highpass", 0.04); },
    chip: (t, e) => { if (e === 0 || e === 4) kick(t, 0.07); if (e === 2 || e === 6) hit(t, 0.04, 3000, "bandpass", 0.07); if (e % 2) hit(t, 0.012, 9000, "highpass", 0.02); },
    synth: (t, e) => { if (e % 2 === 0) kick(t, 0.09); if (e === 2 || e === 6) hit(t, 0.05, 1800, "bandpass", 0.2); if (e % 2) hit(t, 0.012, 9000, "highpass", 0.05); },
  };
  const schedule = () => {
    if (nextT < ctx.currentTime - 0.3) nextT = ctx.currentTime + 0.05;   // timers got throttled: pick the beat back up instead of blasting every missed note
    while (nextT < ctx.currentTime + 0.2) {
      const T = track(), E = 60 / T.bpm / 2;
      const bar = Math.floor(step / 8) % 8, e = step % 8, t = nextT, [ct, ch, cv, cd] = T.chord;
      if (T.arp) voice(t, mtof(T.chords[bar][step % T.chords[bar].length] + 12), cd, cv, ct, ch);        // chiptune arpeggio
      else if (T.comp.includes(e)) T.chords[bar].forEach(m => voice(t, mtof(m), cd, cv, ct, ch));      // chords
      if (T.octbass) voice(t, mtof(T.roots[bar] + (e % 2 ? 12 : 0)), E * 0.9, 0.05, T.bass, 0);          // synthwave octave bass
      else {
        if (e === 0) voice(t, mtof(T.roots[bar]), 0.5, 0.07, T.bass, 0);                                  // bass: root…
        if (e === 3) voice(t, mtof(T.roots[bar] + 7), 0.35, 0.05, T.bass, 0);                             // …fifth…
        if (e === 6) voice(t, mtof(T.roots[bar] + 12), 0.3, 0.045, T.bass, 0);                           // …octave
      }
      const m = T.mel[step % 64]; if (m) voice(t, mtof(m), T.lead[3], T.lead[2], T.lead[0], T.lead[1]); // melody
      DRUMS[T.drums](t, e);
      nextT += E * (e % 2 ? 1 - T.swing : 1 + T.swing);
      step++;
    }
  };
  const start = () => {
    if (timer || !on) return;
    try {
      ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
      if (!master) {
        master = ctx.createGain(); master.gain.value = 0.55; master.connect(ctx.destination);
        noise = ctx.createBuffer(1, ctx.sampleRate * 0.1, ctx.sampleRate); const d = noise.getChannelData(0);
        for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
      }
      if (ctx.state === "suspended") ctx.resume();
      nextT = ctx.currentTime + 0.1; timer = setInterval(schedule, 40); schedule();
    } catch {}
  };
  const stop = () => { clearInterval(timer); timer = null; };
  // browsers only allow sound after you touch the page, so the first click starts it
  ["pointerdown", "mousedown", "click", "touchend", "keydown"].forEach(ev => addEventListener(ev, () => { if (on && !timer) start(); else if (on && ctx && ctx.state !== "running") ctx.resume(); }, true));
  // keep it looping: if the audio got paused behind our back (window hidden, system interrupted it), wake it back up
  setInterval(() => { if (on && timer && ctx && ctx.state !== "running") ctx.resume().catch(() => {}); }, 1000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden && on && ctx) ctx.resume().catch(() => {}); });
  if (on) start();
  return { get on() { return on; }, set(v) { on = v; v ? start() : stop(); }, get track() { return pick; }, setTrack(v) { pick = v; step = 0; } };
})();
$("#tracksel").value = MUSIC.track;
$("#tracksel").addEventListener("change", e => { MUSIC.setTrack(e.target.value); api("/api/track", {track:e.target.value}).catch(() => {}); if (!MUSIC.on) { MUSIC.set(true); paintMusic(); api("/api/music", {on:true}).catch(() => {}); } });
const paintMusic = () => { $("#musicbtn").textContent = MUSIC.on ? "music on" : "music off"; $("#musicbtn").classList.toggle("off", !MUSIC.on); $("#musicbtn").title = MUSIC.on ? "pause the music" : "play background music"; };
$("#musicbtn").addEventListener("click", () => { MUSIC.set(!MUSIC.on); paintMusic(); api("/api/music", {on:MUSIC.on}).catch(() => {}); });
paintMusic();
$("#qall").addEventListener("click", searchAll);
let soundDismissed = false;
$("#soundx").addEventListener("click", () => { soundDismissed = true; $("#soundbar").hidden = true; });
$("#soundfix").addEventListener("click", async () => { const r = await run("gui-setup", "", {confirm:false}); if (r && r.rc === 0) { $("#soundbar").hidden = true; alert("sound's installed close GURT and open it again to hear it"); } });
// ── drop in foreign files (or pick one): gurt figures out what it is and installs it ──
const DROPPABLE = /\.(deb|rpm|pkg\.tar(\.[a-z0-9]+)?|apk|xbps|eopkg|appimage|dmg|exe|msi|snap|flatpak|flatpakref|tar(\.[a-z0-9]+)?|tgz|tbz2?|txz|tzst|zip|7z|gz|xz|bz2|zst)$/i;
const fmtSize = b => b >= 1073741824 ? (b / 1073741824).toFixed(1) + " GB" : b > 1048576 ? (b / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(b / 1024)) + " KB";
// what got dropped? a real File (browsers), or a path the app window caught (WebKitGTK only tells the page "a link")
async function droppedThing(e){
  const f = e.dataTransfer?.files?.[0];
  if (f) return f;
  const r = await api("/api/lastdrop").catch(() => ({paths:[]}));
  return r.paths && r.paths.length ? {path:r.paths[0], name:r.paths[0].split("/").pop()} : null;
}
// a file that's already on this computer (dropped on the app window, or double-clicked): link it in, no upload
const linkPath = path => api("/api/droppath", {path}).catch(() => ({error:"couldn't open that file"}));
async function installFile(f){
  if (!f) return;
  if (f.path) {
    const r = await linkPath(f.path);
    if (r.error) { alert(r.error); return; }
    if (!await free()) return;
    if (!await ask(`Install ${r.orig}?`, `gurt ${/\.gurt$/i.test(r.orig) ? "installs this GURT package" : "figures out what it is and installs it straight onto your system (no box)"}. ${fmtSize(r.size)}. Only install files you trust.`)) return;
    await run("dropped", r.name, {confirm:false});
    return;
  }
  if (!DROPPABLE.test(f.name) && !/\.gurt$/i.test(f.name)) { alert(`gurt can't install "${f.name}" — try a .deb, .rpm, AppImage, .tar.gz, .exe, .dmg…`); return; }
  if (!await free()) return;
  if (!await ask(`Install ${f.name}?`, `gurt figures out what it is and installs it straight onto your system (no box). ${fmtSize(f.size)}. Only install files you trust.`)) return;
  $("#ctitle").textContent = `uploading ${f.name}…`; $("#cdot").className = "dot run"; $("#console").classList.add("open");
  const r = await fetch("/api/drop", {method:"POST", headers:{"X-Gurt-Token":T, "X-Filename":encodeURIComponent(f.name)}, body:f}).then(x => x.json()).catch(() => ({error:"upload failed"}));
  if (r.error) { $("#cdot").className = "dot bad"; alert(r.error); return; }
  await run("dropped", r.name, {confirm:false});
}
$("#dropbtn").addEventListener("click", () => $("#dropin").click());
// ── The Congurter™: file in the hopper → press the button → it drops into the Download Zone™ ──
let cgLoaded = null;
const cgM = () => $("#cgmachine"), cgScreen = t => { $("#cgscreen").textContent = t; };
// feed it something cursed: it shakes, smokes, and the screen glitches out
const CURSED_LINES = ["WHY ARE YOU LIKE THIS", "THE MACHINE HAS SEEN THINGS", "ERROR: TOO CURSED", "THE CONGURTER REFUSES", "THAT'S NOT FOOD"];
function cgCurse(msg){
  const m = cgM(); m.classList.add("jam", "cursed"); SFX.play("cursed");
  cgScreen(CURSED_LINES[Math.floor(Math.random() * CURSED_LINES.length)] + "\n" + msg);
  for (let i = 0; i < 6; i++) setTimeout(() => {
    const p = document.createElement("span"); p.className = "cg-smoke";
    p.style.left = (40 + Math.random() * 55) + "%"; p.style.top = (20 + Math.random() * 40) + "%"; p.style.setProperty("--dx", (Math.random() * 80 - 40) + "px");
    m.appendChild(p); setTimeout(() => p.remove(), 1700);
  }, i * 140);
  setTimeout(() => m.classList.remove("cursed"), 1500);
}
const cgExt = n => (n.match(/\.(pkg\.tar\.[a-z0-9]+|tar\.[a-z0-9]+|[a-z0-9]+)$/i) || ["", ""])[1].toLowerCase();
const CG_SAME = {deb: "deb", rpm: "rpm", "pkg.tar.zst": "pacman", apk: "apk", xbps: "xbps", eopkg: "eopkg", appimage: "appimage", gurt: "gurt", "tar.gz": "tar.gz", zip: "zip"};
async function cgLoad(f){
  if (!f) return;
  cgM().classList.remove("done", "jam");
  if (f.path) {   // already on this computer: no upload, just link it in
    if (!await free()) return;
    const chip = $("#cgfile"); chip.textContent = "" + f.name; chip.hidden = false; chip.classList.remove("in"); void chip.offsetWidth; chip.classList.add("in");
    $("#hoptxt").style.visibility = "hidden"; SFX.play("pop");
    const r = await linkPath(f.path);
    setTimeout(() => { chip.hidden = true; $("#hoptxt").style.visibility = ""; }, 900);
    if (r.error || /\.(dmg|snap|flatpak|flatpakref|7z)$/i.test(r.name || "")) { cgCurse(r.error ? r.error : "a ." + cgExt(r.name) + " doesn't convert. try a .deb .rpm .pkg.tar.zst AppImage .exe…"); return; }
    cgLoaded = {name:r.name, orig:r.orig};
    cgM().classList.add("loaded"); $("#cgbtn").disabled = false;
    cgScreen(`LOADED: ${r.orig}\npick a format, smash the`);
    return;
  }
  if (!DROPPABLE.test(f.name) && !/\.gurt$/i.test(f.name)) { cgCurse(`gurt can't even open ${f.name}`); return; }
  if (/\.(dmg|snap|flatpak|flatpakref|7z)$/i.test(f.name)) { cgCurse("a ." + cgExt(f.name) + " doesn't convert. try a .deb .rpm .pkg.tar.zst AppImage .exe…"); return; }
  if (!await free()) return;
  const chip = $("#cgfile"); chip.textContent = "" + f.name; chip.hidden = false; chip.classList.remove("in"); void chip.offsetWidth; chip.classList.add("in");
  $("#hoptxt").style.visibility = "hidden"; cgScreen(`LOADING ${f.name}…`); SFX.play("pop");
  const r = await fetch("/api/drop", {method:"POST", headers:{"X-Gurt-Token":T, "X-Filename":encodeURIComponent(f.name)}, body:f}).then(x => x.json()).catch(() => ({error:"upload failed"}));
  setTimeout(() => { chip.hidden = true; $("#hoptxt").style.visibility = ""; }, 900);
  if (r.error) { cgM().classList.add("jam"); cgScreen("JAMMED " + r.error); return; }
  cgLoaded = {name:r.name, orig:f.name};
  cgM().classList.add("loaded"); $("#cgbtn").disabled = false;
  cgScreen(`LOADED: ${f.name}\npick a format, smash the`);
}
$("#hopper").addEventListener("click", () => $("#convin").click());
// list exporter: everything you installed with gurt → a text file (gurt import puts it all back, on any distro)
$("#lexport").addEventListener("click", async () => {
  const r = await run("export", "", {confirm:false});
  const saved = r && r.lines.map(l => (l.match(/saved your package list to (\S+)/) || [])[1]).find(Boolean);
  if (saved) alert(`saved your list to ${saved}\n\non another computer (any distro): open GURT → Installed → import a list`);
});
$("#limport").addEventListener("click", () => $("#limportin").click());
$("#limportin").addEventListener("change", async e => {
  const f = e.target.files[0]; e.target.value = ""; if (!f) return;
  const txt = await f.text(), n = txt.split("\n").filter(l => l.replace(/#.*/, "").trim()).length;
  if (!n) { alert("that list is empty"); return; }
  if (!await ask(`Install ${n} package(s) from ${f.name}?`, "gurt installs everything on the list. Already-installed ones get skipped.")) return;
  const r = await fetch("/api/listup", {method:"POST", headers:{"X-Gurt-Token":T}, body:txt}).then(x => x.json()).catch(() => ({error:"upload failed"}));
  if (r.error) { alert(r.error); return; }
  await run("import", r.name, {confirm:false});
});
$("#hopper").addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("#convin").click(); } });
$("#convin").addEventListener("change", e => { cgLoad(e.target.files[0]); e.target.value = ""; });
// dropping onto the hopper feeds the machine instead of installing
$("#hopper").addEventListener("dragover", e => { e.preventDefault(); e.stopPropagation(); $("#hopper").classList.add("hot"); $("#dropzone").hidden = true; });
$("#hopper").addEventListener("dragleave", () => $("#hopper").classList.remove("hot"));
$("#hopper").addEventListener("drop", async e => { e.preventDefault(); e.stopPropagation(); dragDepth = 0; $("#dropzone").hidden = true; $("#hopper").classList.remove("hot"); cgLoad(await droppedThing(e)); });
$("#cgbtn").addEventListener("click", async () => {
  if (!cgLoaded || !await free()) return;
  const b = $("#cgbtn"); b.classList.add("pressed"); setTimeout(() => b.classList.remove("pressed"), 150);
  const fmt = $("#convfmt"), what = fmt.options[fmt.selectedIndex].text.split(" ")[0];
  if (CG_SAME[cgExt(cgLoaded.orig)] === fmt.value) { cgCurse(`it's ALREADY a ${what}. you can't congurt it into itself`); return; }
  const cursedIn = /\.(exe|msi)$/i.test(cgLoaded.orig);
  cgM().classList.remove("loaded", "done", "jam"); cgM().classList.add("running"); b.disabled = true;
  cgScreen(`CONGURTING ${cgLoaded.orig} → ${what}…`);
  const r = await run("convert", cgLoaded.name, {confirm:false, fmt:fmt.value, quiet:true});
  cgM().classList.remove("running");
  if (r && r.rc === 0) {
    cgM().classList.add("done"); cgScreen(cursedIn ? "CURSED… BUT IT WORKED it's in the Download Zone™" : "DONE it's in the Download Zone™"); cgLoaded = null;
    await loadZone(true);
  } else {
    cgM().classList.add("jam"); b.disabled = false; cgM().classList.add("loaded");
    const why = (r ? r.lines : []).filter(l => /nah:|can't|couldn't/.test(l)).pop();
    cgScreen("JAMMED " + (why ? why.replace(/^==> nah:\s*/, "") : "check the log"));
    if (r) { $("#ctitle").textContent = `gurt convert ${cgLoaded.orig}`; $("#cdot").className = "dot bad"; $("#cout").textContent = r.lines.join("\n"); $("#console").classList.add("open"); }
  }
});
async function loadZone(fresh){
  const z = await api("/api/zone").catch(() => ({items:[]}));
  const items = z.items || [];
  $("#zone").innerHTML = items.length ? items.map((it, i) => `<div class="cg-item${fresh && i === 0 ? " drop" : ""}"><b>${esc(it.name)}</b><small>${fmtSize(it.size)}${it.signed ? ` · <span title="${it.signed === "inside" ? "signed with your gurt key (the signature is inside the file)" : `signed with your gurt key (${esc(it.signed)} file comes along)`}">signed</span>` : ""}</small>
      <button class="btn small" data-get="${esc(it.name)}">retrieve</button><button class="btn ghost small" data-del="${esc(it.name)}" title="toss it">toss</button></div>`).join("")
    : `<div class="cg-empty">empty… for now</div>`;
}
$("#zone").addEventListener("click", async e => {
  const g = e.target.closest("[data-get]"), d = e.target.closest("[data-del]");
  if (g) { const r = await api("/api/zone/retrieve", {name:g.dataset.get}); $("#zonemsg").textContent = r.error ? r.error : `retrieved saved to ${r.path}`; SFX.play(r.error ? "err" : "ok"); }
  if (d) { await api("/api/zone/delete", {name:d.dataset.del}); SFX.play("unpick"); loadZone(false); }
});
$("#zoneopen").addEventListener("click", () => api("/api/opendir", {}));
$("#dropbig").addEventListener("click", e => { e.preventDefault(); $("#dropin").click(); });
$("#dropbig").addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("#dropin").click(); } });
// no room in the header for the Install a file tab? hide it (and bounce back to Discover if you were on it)
function fitNav(){
  const root = document.documentElement, n = document.querySelector("nav");
  root.classList.remove("tight");
  if (innerWidth <= 900 || n.scrollWidth > n.clientWidth + 1) root.classList.add("tight");
  const tight = root.classList.contains("tight");
  if (tight && !wasTight && !$("#t-dropfile").hidden) document.querySelector('nav button[data-tab="discover"]').click();
  wasTight = tight;
}
let wasTight = false;
// narrow window: the button in Discover opens the Install a file page (it has the converter) without its tab
$("#convopen").addEventListener("click", () => {
  document.querySelectorAll("nav button").forEach(x => x.classList.remove("on"));
  for (const t of ["discover","installed","updates","setup","desktops","dropfile"]) $("#t-"+t).hidden = t !== "dropfile";
  document.querySelector('nav button[data-tab="dropfile"]').classList.add("on");
  loadZone(false);
});
addEventListener("resize", fitNav); fitNav();
$("#dropin").addEventListener("change", e => { installFile(e.target.files[0]); e.target.value = ""; });
let dragDepth = 0;
const hasFiles = e => { const t = [...(e.dataTransfer?.types || [])]; return t.includes("Files") || t.includes("text/uri-list"); };
addEventListener("dragenter", e => { if (!hasFiles(e)) return; e.preventDefault(); if (!dragDepth++) SFX.play("pop"); $("#dropzone").hidden = false; });
addEventListener("dragover", e => { if (hasFiles(e)) e.preventDefault(); });
addEventListener("dragleave", e => { if (hasFiles(e) && --dragDepth <= 0) { dragDepth = 0; $("#dropzone").hidden = true; } });
addEventListener("drop", async e => { if (!hasFiles(e)) return; e.preventDefault(); dragDepth = 0; $("#dropzone").hidden = true; installFile(await droppedThing(e)); });
// opened with a file (double-clicking a .gurt in your file manager)
if (document.documentElement.dataset.open) { const p = document.documentElement.dataset.open; setTimeout(() => installFile({path:p, name:p.split("/").pop()}), 600); }
// lottery: spin through Main GURT, land on one, install it if you dare
let spinning = false, LOTTO_WIN = "";
const RARITY = {common: "COMMON", rare: "RARE", epic: "EPIC", legendary: "LEGENDARY"};
async function spinLottery(box, show, after){
  if (spinning || !S.main.length) return;
  spinning = true;
  const L = await api("/api/lotto", {}).catch(() => ({streak: 1, best: 1, rarity: "common", legendary: []}));
  const pool = S.main, leg = pool.filter(p => (L.legendary || []).includes(p.name));
  let rarity = L.rarity, win;
  if (rarity === "legendary" && leg.length) win = leg[Math.floor(Math.random() * leg.length)];
  else { win = pool[Math.floor(Math.random() * pool.length)]; if (rarity === "legendary") rarity = "epic"; }
  LOTTO_WIN = win.name;
  box.hidden = false; box.classList.toggle("legendary", rarity === "legendary"); let i = 0;
  const steps = rarity === "legendary" ? 30 : 18;
  const tick = () => {
    if (i++ < steps) { SFX.play("tick"); box.innerHTML = `<div class="spin">${esc(pool[Math.floor(Math.random() * pool.length)].name)}</div>`; return setTimeout(tick, 40 + i * 6); }
    spinning = false; SFX.play(rarity === "legendary" ? "legendary" : "jackpot");
    box.innerHTML = `<span class="rarity r-${rarity}">${RARITY[rarity]}</span>` + show(win)
      + `<div class="streak">${L.streak} day streak (best ${L.best}) · spin once a day, longer streaks = better odds of a legendary</div>`;
    after && after(win);
    if (rarity === "legendary") achieve("legendary");
    if (L.streak >= 7) achieve("streak7");
  };
  tick();
}
$("#lotto").addEventListener("click", () => spinLottery($("#lottowin"),
  win => `<div class="spin">jackpot!</div>` + card({name:win.name, ver:win.ver, desc:win.desc, actions: installBtns(win.name)})));
// ── setup builder: pick a bunch, install them in one go ──
const CATS = {browsers:"Browsers", chat:"Chat & email", media:"Media", creative:"Creative", office:"Office & notes",
  dev:"Dev", cli:"Terminal tools", gaming:"Gaming", internet:"Files & remote", system:"System", security:"Security", fun:"Fun", other:"Other"};
const PICKED = new Set(); let BCAT = "all";
const catOf = p => CATS[p.category] ? p.category : "other";
function renderBuilder(){
  const have = [...new Set(S.main.map(catOf))].sort((a, b) => Object.keys(CATS).indexOf(a) - Object.keys(CATS).indexOf(b));
  $("#bcats").innerHTML = [`<button class="bcat${BCAT === "all" ? " on" : ""}" data-c="all">all (${S.main.length})</button>`]
    .concat(have.map(c => `<button class="bcat${BCAT === c ? " on" : ""}" data-c="${c}">${CATS[c]}</button>`)).join("");
  $("#bgroups").innerHTML = have.filter(c => BCAT === "all" || BCAT === c).map(c => `<div class="bgroup"><h3>${CATS[c]}</h3><div class="bgrid">${
    S.main.filter(p => catOf(p) === c).map(p => {
      const done = inst(p.name), on = PICKED.has(p.name), d = (p.desc || "").replace(/\s*\((Flathub|official repo[^)]*)\)\s*$/, "").replace(/^[^—]*—\s*/, "");
      return `<label class="bapp${on ? " on" : ""}${done ? " done" : ""}" title="${esc(p.desc)}"><input type="checkbox" data-n="${esc(p.name)}"${on || done ? " checked" : ""}${done ? " disabled" : ""}><span><b>${esc(p.name)}${p.foss === "closed" ? ` <i class="closedmark" title="closed source">closed</i>` : ""}</b><small>${done ? "installed ✓" : esc(d)}</small></span></label>`;
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
  return `<div class="spin">jackpot!</div>` + card({name:win.name, ver:win.ver, desc:win.desc,
    actions: installBtns(win.name) + (inst(win.name) ? "" : ` <button class="btn ghost small" id="lwpick">add to my setup</button>`)});
}, win => { const b = $("#lwpick"); if (b) b.onclick = () => { PICKED.add(win.name); BCAT = catOf(win); renderBuilder(); b.textContent = "added ✓"; }; }));

$("#directbtn").addEventListener("click", () => run("install", $("#q").value.trim()));
$("#iq").addEventListener("input", renderInstalled);

// ⋯ more menus: the stuff you don't need every day
function moreClose(except){ document.querySelectorAll(".more").forEach(m => { if (m === except) return; m.querySelector(".morepop").hidden = true; m.querySelector("[data-more]").setAttribute("aria-expanded", "false"); }); }
document.addEventListener("click", e => {
  const b = e.target.closest("[data-more]");
  if (b) { const m = b.closest(".more"), pop = m.querySelector(".morepop"); moreClose(m); pop.hidden = !pop.hidden; b.setAttribute("aria-expanded", String(!pop.hidden)); return; }
  moreClose();   // clicked anywhere else, or an item in a menu
});
document.addEventListener("keydown", e => { if (e.key === "Escape") moreClose(); });

// ── updates ──
async function check(quiet = false, bg = false){
  $("#ugrid").innerHTML = `<div class="empty">checking…</div>`;
  const r = await run("update", "", {confirm:false, quiet, bg}); if (!r) return;
  if (quiet && bgStopped) { $("#ugrid").innerHTML = `<div class="empty">hit "check for updates"</div>`; return; }   // stopped for something you clicked
  const ups = r.lines.map(l => l.match(/^\s*->\s*(\S+)\s+(\S+) -> (\S+)$/)).filter(Boolean);
  // gurt itself counts as an update too (and goes first — the new gurt might be needed for the rest)
  const selfUp = r.lines.find(l => /is out \(you have|gurt self-update/.test(l));
  const sysM = r.lines.map(l => l.match(/(\d+) system update\(s\) waiting from (\S+)/)).find(Boolean);
  const n = ups.length + (selfUp ? 1 : 0) + (sysM ? 1 : 0);
  $("#ubadge").hidden = !n; $("#ubadge").textContent = n;
  const sv = selfUp && selfUp.match(/gurt (\S+) is out \(you have (\S+)\)/);
  $("#ugrid").innerHTML = !n ? `<div class="empty">everything's up to date, you're chillin</div>`
    : (selfUp ? card({name:"gurt", ver: sv ? `${sv[2]} → ${sv[1]}` : "new version", desc:"gurt itself has an update", actions: actBtn("update gurt","self-update","")}) : "")
      + (sysM ? card({name:"your system", src:sysM[2], ver:`${sysM[1]} update${sysM[1] === "1" ? "" : "s"}`, desc:`${sysM[1]} package${sysM[1] === "1" ? "" : "s"} from your distro (${sysM[2]}) — "update everything" installs them too`, actions: actBtn("update system","sysup","")}) : "")
      + ups.map(m => card({name:m[1].split("/").pop(), src:m[1].includes("/") ? m[1].split("/")[0] : "gurt", ver:`${m[2]} → ${m[3]}`, desc:"update available", actions: actBtn("update","install",m[1])})).join("");
}
$("#checkbtn").addEventListener("click", () => check());
// check for updates quietly right after opening, so the Updates tab shows its count without a click
setTimeout(startBgCheck, 2500);
$("#upbtn").addEventListener("click", async () => { if (await run("upgrade")) check(); });
$("#selfbtn").addEventListener("click", () => run("self-update"));
$("#syncbtn").addEventListener("click", () => run("sync", "", {confirm:false}));
// ── light / dark ── (starts on your system's theme, remembers what you pick)
const darkMQ = matchMedia("(prefers-color-scheme: dark)");
const isDark = () => { const t = document.documentElement.dataset.theme; return t === "dark" || (t !== "light" && darkMQ.matches); };
const themeIcon = () => { $("#themebtn").textContent = isDark() ? "light" : "dark"; };
$("#themebtn").addEventListener("click", () => {
  const t = isDark() ? "light" : "dark";
  document.documentElement.dataset.theme = t; themeIcon(); api("/api/theme", {theme:t}).catch(() => {});
});
darkMQ.addEventListener("change", themeIcon); themeIcon();
// ── skins ── (XP + 95 are always light, like the real thing)
const applySkin = s => { document.documentElement.dataset.skin = s; $("#skinsel").value = s; $("#themebtn").hidden = ["xp", "w95", "vapor", "hacker"].includes(s); if (typeof fitNav === "function") fitNav(); };
$("#skinsel").addEventListener("change", e => { applySkin(e.target.value); api("/api/skin", {skin:e.target.value}).catch(() => {}); if (typeof SFX !== "undefined") SFX.play("startup"); });
applySkin(document.documentElement.dataset.skin || "gurt");

// ── tabs ──
document.querySelectorAll("nav button").forEach(b => b.addEventListener("click", () => {
  document.querySelectorAll("nav button").forEach(x => x.classList.toggle("on", x === b));
  for (const t of ["discover","installed","updates","setup","desktops","dropfile"]) $("#t-"+t).hidden = b.dataset.tab !== t;
  b.scrollIntoView({block: "nearest", inline: "nearest"});   // phones: the tab row scrolls, keep the picked tab in view
  if (b.dataset.tab === "setup") renderBuilder();
  if (b.dataset.tab === "dropfile") loadZone(false);
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
    : `<div class="empty">couldn't list desktops</div>`;
}

setInterval(() => api("/api/ping").catch(() => {}), 5000); api("/api/ping");
if (MODE === "browser") {
  $("#appbar").hidden = false; $("#appbarx").onclick = () => $("#appbar").hidden = true;
  $("#appbarinst").onclick = async () => {
    const r = await run("gui-setup", "", {confirm:false}); if (!r) return;
    if (r.rc === 0) {
      $("#appbartxt").textContent = "app window installed reopening GURT as a real app…"; $("#appbarinst").hidden = true;
      await api("/api/relaunch", {});
      setTimeout(() => { document.body.innerHTML = `<div class="empty" style="padding:80px 20px">GURT reopened in its own window you can close this tab</div>`; }, 1500);
    } else { $("#appbartxt").textContent = "couldn't install the app window check the activity log below"; }
  };
}

// ── GURT Setup Wizard: its own app (gurt gui --wizard, "GURT Setup Wizard" in the app menu), a classic installer.
//    the installers start it at your first login; GURT's menu opens it in its own window ──
function wizStart(){
  if (SETUP) return wizOpen();
  api("/api/setup-app", {}).then(() => toast("the GURT Setup Wizard opened in its own window")).catch(() => toast("couldn't open the setup wizard (try: gurt setup)"));
}
let wizQuitting = false;
async function wizQuit(open){   // the setup wizard app is done: close its window (and open GURT if you ticked that)
  wizQuitting = true;
  if (MODE === "browser") document.body.innerHTML = `<div class="empty" style="padding:80px 20px">${open ? "GURT is opening " : ""}you can close this tab</div>`;
  await api("/api/close", {open: !!open}).catch(() => {});
}
const WIZ_STEPS = ["Welcome", "System check", "App sources", "Your look", "Starter apps", "Extras", "Install"];
const STARTER = {"Browsers": ["firefox", "brave", "librewolf", "zen-browser", "chromium"], "Chat": ["vesktop", "telegram", "signal", "element"],   // mostly free software (Steam's the one exception)
  "Media": ["vlc", "mpv", "spotube", "obs-studio", "kdenlive"], "Creative": ["gimp", "krita", "inkscape", "blender"],
  "Office": ["libreoffice", "onlyoffice", "joplin", "thunderbird"], "Dev": ["vscodium", "zed", "neovim", "btop"],
  "Gaming": ["steam", "heroic", "lutris", "prismlauncher", "bottles"]};
const WIZ_SRCS = [["flatpak", "Flathub", "sandboxed apps, and where most Main GURT apps come from"], ["aur", "the AUR", "Arch's user repo, built from source on your PC (gurt checks the build scripts for red flags first)"],
  ["apt", "Debian / Ubuntu repos", "apt/ packages on any distro"], ["dnf", "Fedora repos", "dnf/ packages on any distro"],
  ["zypper", "openSUSE repos", "zypper/ packages on any distro"], ["pacman", "Arch repos", "pacman/ packages on any distro"]];
const WIZ_SKINS = [["gurt", "GURT"], ["win11", "Windows 11"], ["xp", "Windows XP"], ["w95", "Windows 95"], ["vapor", "Vaporwave"], ["hacker", "Hacker"]];
const WIZ_TRACKS = [["auto", "auto"], ["shop", "shop"], ["lofi", "lofi"], ["chip", "chiptune"], ["synth", "synthwave"]];
let W = null, wizStep = 0, wizDoc = null, wizState = "edit";   // edit → running → done
function wizOpen(){
  W = {utils: true, srcs: new Set(["flatpak"]), apps: new Set(), notify: true, appwin: MODE === "browser", launch: document.documentElement.dataset.from !== "app", tasks: []};
  wizStep = 0; wizState = "edit"; wizDoc = null; prefOpen(false);
  if (!$("#wizard").open) $("#wizard").showModal();
  wizRender();
  api("/api/doctor").then(d => { wizDoc = d; if (wizStep === 1 || wizStep === 6) wizRender(); }).catch(() => { wizDoc = {utils: [], failed: true}; wizRender(); });
}
const wizMissing = () => ((wizDoc && wizDoc.utils) || []).filter(u => !u.ok).map(u => u.name);
function wizTasks(){
  const t = [], miss = wizMissing();
  if (miss.length && (W.utils || (W.srcs.has("flatpak") && miss.includes("flatpak")))) t.push({label: `install the utilities apps need (${miss.join(", ")})`, cmd: "utils"});
  for (const s of W.srcs) if (s !== "flatpak") t.push({label: `get the ${WIZ_SRCS.find(x => x[0] === s)[1]} package list`, cmd: "sync-src", arg: s});
  if (W.apps.size) t.push({label: `install ${W.apps.size} app${W.apps.size === 1 ? "" : "s"}: ${[...W.apps].join(", ")}`, cmd: "install-many", arg: [...W.apps].join(" ")});
  if (W.notify && !(wizDoc && wizDoc.notify)) t.push({label: "turn on update alerts", cmd: "notify", arg: "on"});
  if (W.appwin && MODE === "browser") t.push({label: SETUP ? "install the app window (GURT opens as a real app)" : "install the app window (GURT reopens as a real app at the end)", cmd: "gui-setup", relaunch: true});
  return t;
}
const opt = (id, on, title, sub, dis = false) => `<label class="wiz-opt"><input type="checkbox" data-w="${id}"${on ? " checked" : ""}${dis ? " disabled" : ""}><span><b>${title}</b>${sub ? `<small>${sub}</small>` : ""}</span></label>`;
function wizRender(){
  $("#wizrail").innerHTML = WIZ_STEPS.map((n, i) => `<li class="${i === wizStep ? "on" : i < wizStep ? "done" : ""}">${n}</li>`).join("");
  $("#wizstepname").textContent = `step ${wizStep + 1} of ${WIZ_STEPS.length}: ${WIZ_STEPS[wizStep]}`;
  const d = wizDoc, pg = $("#wizpage");
  if (wizStep === 0) pg.innerHTML = `<h3>Welcome to the GURT Setup Wizard</h3>${S && S.version ? `<p><b>GURT ${esc(S.version)} is installed</b></p>` : ""}
    <p>This wizard finishes installing GURT on your computer: it checks your system, sets up the places apps come from, picks your look, and installs a few starter apps if you want some.</p>
    <p>It takes about a minute, and you can change all of it later. Click <b>Next</b> to continue.</p>`;
  if (wizStep === 1) {
    if (!d) pg.innerHTML = `<h3>System check</h3><p>checking your system…</p>`;
    else {
      const miss = wizMissing(), chk = (ok, title, sub, st) => `<div class="wiz-check"><span class="mark ${ok ? "ok" : "no"}">${ok ? "✓" : "!"}</span><span><b>${title}</b>${sub ? `<small>${sub}</small>` : ""}</span><span class="st">${st || ""}</span></div>`;
      pg.innerHTML = `<h3>System check</h3><p>here's what GURT found.</p><div class="wiz-checks">
        ${chk(true, esc(d.distro || "your distro"), `package manager: ${esc(d.pm || "?")}${d.wsl ? " · running in WSL on Windows" : d.cros ? " · Linux on ChromeOS" : ""}`)}
        ${chk(d.sudo, d.sudo ? "sudo works" : "no sudo or doas", d.sudo ? "GURT asks for your password when it installs things system-wide" : "install sudo, or run GURT as root")}
        ${chk(!miss.length, miss.length ? `${miss.length} utilit${miss.length === 1 ? "y" : "ies"} missing` : "every utility apps need is here", miss.length ? esc(miss.join(", ")) : "flatpak, git, unzip tools, a compiler…")}
        ${d.audio === false ? chk(false, "no sound in the app window", "the app window needs GStreamer's audio plugins (the app offers a fix)") : ""}
      </div>${miss.length ? opt("utils", W.utils, "install the missing utilities", "recommended: most apps need some of these to install") : ""}`;
    }
  }
  if (wizStep === 2) pg.innerHTML = `<h3>App sources</h3><p>where should GURT get apps? your own distro's repos${d ? ` (${esc(d.pm)})` : ""} and Main GURT always work. these are extra, and you can use any of them later too.</p>`
    + WIZ_SRCS.map(([id, name, sub]) => opt("src:" + id, W.srcs.has(id), name, sub)).join("");
  if (wizStep === 3) {
    const cur = document.documentElement.dataset.skin || "gurt", tr = MUSIC.track, th = document.documentElement.dataset.theme || "dark";
    pg.innerHTML = `<h3>Your look</h3><p>pick a skin (every skin has its own sound effects), a music track, and light or dark. try them, it changes right away.</p>
      <div class="wiz-looks">${WIZ_SKINS.map(([id, n]) => `<button class="wiz-look${cur === id ? " on" : ""}" data-skin="${id}">${n}</button>`).join("")}</div>
      <div class="wiz-grp"><h4>music</h4><div class="wiz-apps">${WIZ_TRACKS.map(([id, n]) => `<button class="wiz-app${tr === id ? " on" : ""}" data-track="${id}">${n}</button>`).join("")}<button class="wiz-app${MUSIC.on ? "" : " on"}" data-mute="1">no music</button></div></div>
      <div class="wiz-grp"><h4>light or dark</h4><div class="wiz-apps">${[["dark", "dark (default)"], ["light", "light"], ["auto", "match my system"]].map(([id, n]) => `<button class="wiz-app${th === id ? " on" : ""}" data-theme="${id}">${n}</button>`).join("")}</div></div>`;
  }
  if (wizStep === 4) {
    const groups = Object.entries(STARTER).map(([g, names]) => [g, names.filter(n => S.main.some(p => p.name === n))]).filter(([, n]) => n.length);
    pg.innerHTML = `<h3>Starter apps</h3><p>tick a few to install now, or skip this. there are ${S.main.length.toLocaleString()} more in Discover.</p>`
      + groups.map(([g, names]) => `<div class="wiz-grp"><h4>${g}</h4><div class="wiz-apps">${names.map(n => inst(n)
          ? `<button class="wiz-app" disabled title="already installed">${esc(n)} ✓</button>` : `<button class="wiz-app${W.apps.has(n) ? " on" : ""}" data-app="${esc(n)}">${esc(n)}</button>`).join("")}</div></div>`).join("")
      + `<div class="row"><button class="btn ghost small" id="wizlotto">surprise me</button><button class="btn ghost small" id="wizimport" title="a list you exported (export my list) or a profile from your old PC">import a list from your old PC</button><span class="hint">${W.apps.size} picked</span></div>`
      + (W.imported ? `<p class="hint" style="margin-top:8px">${esc(W.imported)}</p>` : "")
      + `<input type="file" id="wizimportin" accept=".txt,.profile,text/plain" hidden>`;
  }
  if (wizStep === 5) pg.innerHTML = `<h3>Extras</h3><p>a couple more things.</p>`
    + opt("notify", W.notify || (d && d.notify), "tell me when updates are waiting", d && d.notify ? "already on" : "a desktop notification, checked every 6 hours", !!(d && d.notify))
    + (MODE === "browser" ? opt("appwin", W.appwin, "install the real app window", "right now GURT is running in your browser. this gives it its own window + a menu entry") : "");
  if (wizStep === 6) {
    if (wizState === "edit") {
      W.tasks = wizTasks();
      pg.innerHTML = W.tasks.length ? `<h3>Ready to install</h3><p>GURT is about to:</p><ul class="wiz-tasks">${W.tasks.map(t => `<li><span class="mark">·</span><span>${esc(t.label)}</span></li>`).join("")}</ul>
        <p style="margin-top:12px">click <b>Install</b> to start. it might ask for your password.</p>`
        : `<h3>Nothing to install</h3><p>you're all set click <b>Finish</b> and go explore.</p>`;
    } else {
      const done = W.tasks.filter(t => t.st && t.st !== "run").length;
      pg.innerHTML = `<h3>${wizState === "done" ? "All done" : "Installing…"}</h3><div class="wiz-bar"><i style="width:${W.tasks.length ? Math.round(done / W.tasks.length * 100) : 100}%"></i></div>
        <ul class="wiz-tasks">${W.tasks.map(t => `<li><span class="mark">${t.st === "ok" ? "✓" : t.st === "bad" ? "✗" : t.st === "run" ? "…" : "·"}</span><span>${esc(t.label)}</span><span class="st">${t.st === "bad" ? "didn't work" : ""}</span>${t.st === "bad" && t.log ? `<pre class="wiz-log">${esc(t.log)}</pre>` : ""}</li>`).join("")}</ul>
        ${wizState === "done" ? `<p style="margin-top:12px">${W.tasks.some(t => t.st === "bad") ? "some of it didn't work, but everything else is ready. " : ""}GURT is set up click <b>Finish</b>.</p>` : ""}`;
    }
    if (SETUP && wizState !== "running") pg.innerHTML += opt("launch", W.launch, "open GURT when I click Finish", "");
  }
  $("#wizback").disabled = wizStep === 0 || wizState !== "edit";
  $("#wizcancel").hidden = wizState !== "edit";
  $("#wiznext").disabled = wizState === "running";
  $("#wiznext").textContent = wizStep < 6 ? "Next >" : wizState === "edit" ? (W.tasks.length ? "Install" : "Finish") : "Finish";
}
async function wizRun(){
  wizState = "running"; wizRender();
  let relaunch = false;
  for (const t of W.tasks) {
    t.st = "run"; wizRender();
    const r = await run(t.cmd, t.arg || "", {confirm: false, quiet: true});
    t.st = r && r.rc === 0 ? "ok" : "bad";
    if (r && r.rc !== 0) { $("#cout").textContent = r.lines.join("\n"); t.log = r.lines.slice(-12).join("\n"); }
    if (t.relaunch && t.st === "ok") { if (SETUP) W.launch = true; else relaunch = true; }   // the setup app opens the real GURT on Finish
    wizRender();
  }
  wizState = "done"; wizRender(); SFX.play("ok");
  await wizDone();
  if (relaunch) { await api("/api/relaunch", {}).catch(() => {}); setTimeout(() => { document.body.innerHTML = `<div class="empty" style="padding:80px 20px">GURT reopened in its own window you can close this tab</div>`; }, 1500); }
}
async function wizDone(){ document.documentElement.dataset.wiz = "done"; await api("/api/wizard", {v: (S && S.version) || ""}).catch(() => {}); achieve("wizard"); }
$("#wiznext").addEventListener("click", async () => {
  if (wizStep < 6) { wizStep++; return wizRender(); }
  if (wizState === "edit" && W.tasks.length) return wizRun();
  if (wizState === "edit") await wizDone();
  if (SETUP) return wizQuit(W.launch);
  $("#wizard").close();
});
$("#wizback").addEventListener("click", () => { if (wizStep > 0) { wizStep--; wizRender(); } });
$("#wizcancel").addEventListener("click", async () => {
  if (!SETUP) return $("#wizard").close();
  await api("/api/wizard", {v: (S && S.version) || ""}).catch(() => {});   // skipped: the first-login autostart won't nag
  wizQuit(false);
});
$("#wizard").addEventListener("cancel", e => { if (SETUP || wizState === "running") e.preventDefault(); });   // no Esc mid-install (or out of the wizard app)
$("#wizard").addEventListener("close", () => {
  if (SETUP) { if (!wizQuitting) $("#wizard").showModal(); return; }   // the wizard app is the wizard: Esc can't leave an empty window
  if (document.documentElement.dataset.wiz === "new") api("/api/wizard", {v: (S && S.version) || ""}).catch(() => {});   // skipped: don't nag
});
$("#wizopen").addEventListener("click", wizStart);
$("#wizpage").addEventListener("change", async e => {
  if (e.target.id === "wizimportin") {   // an exported list or a profile → its apps join the install
    const f = e.target.files[0]; if (!f) return;
    let text = await f.text(), skipped = 0, added = 0;
    if (/^\[apps\]$/m.test(text)) text = (text.split(/^\[apps\]$/m)[1] || "").split(/^\[/m)[0];   // a profile: just its [apps] part
    for (let line of text.split("\n")) {
      line = line.replace(/#.*/, "").trim(); if (!line) continue;
      if (/^outsource /.test(line) || !/^[a-z0-9-]+\/[A-Za-z0-9._+-]+$|^[A-Za-z0-9._+-]+$/.test(line)) { skipped++; continue; }
      if (!inst(line) && !W.apps.has(line)) { W.apps.add(line); added++; }
    }
    W.imported = `${f.name}: added ${added} app${added === 1 ? "" : "s"}${skipped ? `, skipped ${skipped} (git repos: gurt import ${f.name} does those)` : ""}`;
    SFX.play(added ? "ok" : "pop"); return wizRender();
  }
  const k = e.target.dataset.w; if (!k) return;
  if (k.startsWith("src:")) e.target.checked ? W.srcs.add(k.slice(4)) : W.srcs.delete(k.slice(4)); else W[k] = e.target.checked;
});
$("#wizpage").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  if (b.dataset.skin) { applySkin(b.dataset.skin); api("/api/skin", {skin: b.dataset.skin}).catch(() => {}); SFX.play("startup"); wizRender(); }
  else if (b.dataset.track) { MUSIC.setTrack(b.dataset.track); $("#tracksel").value = b.dataset.track; api("/api/track", {track: b.dataset.track}).catch(() => {});
    if (!MUSIC.on) { MUSIC.set(true); api("/api/music", {on: true}).catch(() => {}); } paintMusic(); wizRender(); }
  else if (b.dataset.mute) { MUSIC.set(false); paintMusic(); api("/api/music", {on: false}).catch(() => {}); wizRender(); }
  else if (b.dataset.theme) { const t = b.dataset.theme; if (t === "auto") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
    themeIcon(); api("/api/theme", {theme: t}).catch(() => {}); wizRender(); }
  else if (b.dataset.app) { const n = b.dataset.app; W.apps.has(n) ? W.apps.delete(n) : W.apps.add(n); SFX.play(W.apps.has(n) ? "pick" : "unpick"); wizRender(); }
  else if (b.id === "wizimport") $("#wizimportin").click();
  else if (b.id === "wizlotto") { const pool = S.main.filter(p => !inst(p.name) && !W.apps.has(p.name)); if (pool.length) { W.apps.add(pool[Math.floor(Math.random() * pool.length)].name); SFX.play("jackpot"); wizRender(); } }
});
load();
</script></body></html>"""

if __name__ == "__main__":
    main()

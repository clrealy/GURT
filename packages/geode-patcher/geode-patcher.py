#!/usr/bin/env python3
"""
Geode Patcher for Linux — a tiny GUI to install/uninstall the Geode mod loader
into Geometry Dash (Steam + Proton/Wine). No extra deps, just Python 3 + tkinter.

Run:  python3 geode-patcher.py
(If tkinter is missing: sudo apt install python3-tk / sudo pacman -S tk / sudo dnf install python3-tkinter)
"""
import io
import json
import os
import re
import shutil
import threading
import urllib.request
import zipfile
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import tkinter.font as tkfont

GD_APPID = "322170"
GD_EXE = "GeometryDash.exe"
API_LATEST = "https://api.github.com/repos/geode-sdk/geode/releases/latest"
API_LIST = "https://api.github.com/repos/geode-sdk/geode/releases?per_page=15"
LAUNCH_OPT = 'WINEDLLOVERRIDES="xinput1_4=n,b" %command%'
GEODE_FILES = ["Geode.dll", "Geode.pdb", "xinput1_4.dll", "XInput1_4.dll",
               "GeodeUpdater.exe", "GeodeUninstaller.exe"]
UA = {"User-Agent": "geode-linux-patcher", "Accept": "application/vnd.github+json"}

STEAM_ROOTS = [
    "~/.steam/steam",
    "~/.steam/root",
    "~/.local/share/Steam",
    "~/.var/app/com.valvesoftware.Steam/.local/share/Steam",  # Flatpak
    "~/snap/steam/common/.local/share/Steam",                  # Snap
]


# ---------------------------------------------------------------- detection
def steam_libraries():
    libs = []
    for root in STEAM_ROOTS:
        root = Path(os.path.expanduser(root))
        if not root.exists():
            continue
        libs.append(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            for p in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(errors="ignore")):
                libs.append(Path(p.replace("\\\\", "\\")))
    seen, out = set(), []
    for l in libs:
        try:
            r = l.resolve()
        except OSError:
            continue
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def find_gd():
    for lib in steam_libraries():
        manifest = lib / "steamapps" / f"appmanifest_{GD_APPID}.acf"
        common = lib / "steamapps" / "common"
        if manifest.exists():
            m = re.search(r'"installdir"\s+"([^"]+)"', manifest.read_text(errors="ignore"))
            if m and (common / m.group(1) / GD_EXE).exists():
                return common / m.group(1)
        cand = common / "Geometry Dash"
        if (cand / GD_EXE).exists():
            return cand
    return None


def is_installed(gd: Path):
    return (gd / "Geode.dll").exists()


# ---------------------------------------------------------------- github
def get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        return json.load(r)


def pick_win_asset(release):
    for a in release.get("assets", []):
        n = a["name"].lower()
        if n.endswith(".zip") and "win" in n and "installer" not in n:
            return a
    return None


# ---------------------------------------------------------------- GUI
# chunky game-menu look: blue backdrop, black outlines, 3D buttons that press down
BG, GRID, PANEL, FIELD, OUT = "#0f1d52", "#16296a", "#1b3388", "#0a1440", "#05081a"
YELLOW, LIME, CYAN, RED, ORANGE = "#ffd84a", "#5ee83a", "#2fc8ff", "#ff4560", "#ff9f1c"
TEXT, SOFT, OFF = "#ffffff", "#a9bcff", "#56618c"
W, H = 660, 640


def pick_font(root, wanted, fallback):
    have = set(tkfont.families(root))
    return next((f for f in wanted if f in have), fallback)


def find_icon():
    here = Path(__file__).resolve().parent
    for p in (here.parent / "share" / "pixmaps" / "geode-patcher.png", here / "geode-patcher.png"):
        if p.exists():
            return p
    return None


def mix(hex_color, other="#ffffff", t=0.3):
    a = [int(hex_color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def rrect(c, x1, y1, x2, y2, r, **kw):
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


def stroke_text(c, x, y, text, font, fill, anchor="center", w=2, **kw):
    for dx in (-w, 0, w):
        for dy in (-w, 0, w):
            if dx or dy:
                c.create_text(x + dx, y + dy, text=text, font=font, fill=OUT, anchor=anchor, **kw)
    return c.create_text(x, y, text=text, font=font, fill=fill, anchor=anchor, **kw)


class Chunky(tk.Canvas):
    """a fat outlined button that sinks when you press it"""

    def __init__(self, master, text, color, command, font, bg, w=None, h=40):
        self.font, self.color, self.command, self.h = font, color, command, h
        self.w = w or tkfont.Font(master, font=font).measure(text) + 40
        super().__init__(master, width=self.w, height=h + 6, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.text, self.enabled, self.hover, self.down = text, True, False, False
        self.bind("<Enter>", lambda e: self._set(hover=True))
        self.bind("<Leave>", lambda e: self._set(hover=False, down=False))
        self.bind("<ButtonPress-1>", lambda e: self._set(down=True))
        self.bind("<ButtonRelease-1>", self._release)
        self.draw()

    def _set(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        self.draw()

    def _release(self, e):
        fire = self.down and self.enabled and 0 <= e.x <= self.w and 0 <= e.y <= self.h + 6
        self._set(down=False)
        if fire:
            self.command()

    def set_text(self, text):
        self.text = text
        self.draw()

    def set_enabled(self, on):
        self.enabled = on
        self.configure(cursor="hand2" if on else "arrow")
        self.draw()

    def draw(self):
        self.delete("all")
        col = self.color if self.enabled else OFF
        if self.hover and self.enabled:
            col = mix(col, "#ffffff", 0.15)
        dy = 4 if (self.down and self.enabled) else 0
        rrect(self, 2, 8, self.w - 2, self.h + 4, 12, fill=OUT, outline=OUT, width=3)  # base
        rrect(self, 2, 2 + dy, self.w - 2, self.h - 2 + dy, 12, fill=col, outline=OUT, width=3)
        shine = 0.07 if self.color == FIELD else 0.28  # dark dropdowns get a faint shine, not a grey bar
        rrect(self, 8, 6 + dy, self.w - 8, self.h * 0.42 + dy, 7, fill=mix(col, "#ffffff", shine), outline="")
        stroke_text(self, self.w / 2, self.h / 2 + dy, self.text, self.font, TEXT)


class Toggle(tk.Canvas):
    def __init__(self, master, var, bg):
        super().__init__(master, width=30, height=30, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.var = var
        self.bind("<Button-1>", lambda e: (var.set(not var.get()), self.draw()))
        self.draw()

    def draw(self):
        self.delete("all")
        on = self.var.get()
        rrect(self, 3, 3, 27, 27, 7, fill=RED if on else FIELD, outline=OUT, width=3)
        if on:
            self.create_line(9, 15, 13, 20, 21, 9, fill=TEXT, width=4, capstyle="round", joinstyle="round")


class LevelBar(tk.Canvas):
    """progress bar styled like a level progress bar, percent in the middle"""

    def __init__(self, master, w, font, bg):
        self.w, self.font = w, font
        super().__init__(master, width=w, height=30, bg=bg, highlightthickness=0, bd=0)
        self.set(0)

    def set(self, pct):
        self.delete("all")
        pct = max(0.0, min(100.0, pct))
        rrect(self, 2, 2, self.w - 2, 28, 12, fill=FIELD, outline=OUT, width=3)
        if pct > 0:
            x2 = max(26, 4 + (self.w - 8) * pct / 100)
            rrect(self, 4, 4, x2, 26, 10, fill=LIME, outline="")
            rrect(self, 8, 6, max(12, x2 - 4), 13, 4, fill=mix(LIME, "#ffffff", 0.35), outline="")
        stroke_text(self, self.w / 2, 15, f"{int(pct)}%", self.font, TEXT)


class App(tk.Tk):
    def __init__(self):
        super().__init__(className="geode-patcher")  # WM_CLASS must match the .desktop
        self.title("Geode Patcher")
        self.configure(bg=BG)
        self.geometry(f"{W}x{H}")
        self.resizable(False, False)
        self.releases, self.sel = [], -1

        bold = pick_font(self, ["Fredoka", "Baloo 2", "Nunito", "Rubik", "Ubuntu", "Cantarell",
                                "Noto Sans", "DejaVu Sans", "Liberation Sans"], "Sans")
        mono = pick_font(self, ["JetBrains Mono", "Fira Code", "Hack", "DejaVu Sans Mono",
                                "Liberation Mono", "Noto Sans Mono"], "Monospace")
        self.f_title = (bold, 24, "bold")
        self.f_btn = (bold, 11, "bold")
        self.f_big = (bold, 14, "bold")
        self.f_label = (bold, 10, "bold")
        self.f_text = (bold, 10)
        self.f_mono = (mono, 10, "bold")

        self._icon = None
        icon = find_icon()
        if icon:
            try:
                self._icon = tk.PhotoImage(file=str(icon))
                self.iconphoto(True, self._icon)
            except tk.TclError:
                self._icon = None  # very old Tk without PNG support
        self._build()
        self.detect()
        self.load_releases()

    # ---- drawing
    def _panel(self, y1, y2, title):
        c = self.c
        rrect(c, 20, y1 + 6, W - 20, y2 + 6, 16, fill=OUT, outline=OUT, width=3)
        rrect(c, 20, y1, W - 20, y2, 16, fill=PANEL, outline=OUT, width=3)
        stroke_text(c, 38, y1 + 18, title, self.f_label, YELLOW, anchor="w")

    def _build(self):
        c = self.c = tk.Canvas(self, width=W, height=H, bg=BG, highlightthickness=0, bd=0)
        c.pack()
        for x in range(0, W, 48):
            c.create_line(x, 0, x, H, fill=GRID)
        for y in range(0, H, 48):
            c.create_line(0, y, W, y, fill=GRID)

        # header
        tx = 24
        if self._icon is not None:
            try:
                self._head_icon = self._icon.subsample(max(1, self._icon.width() // 64))
                c.create_rectangle(22, 14, 92, 84, fill=OUT, outline=OUT)
                c.create_image(25, 17, image=self._head_icon, anchor="nw")
                tx = 108
            except tk.TclError:
                pass
        stroke_text(c, tx, 38, "GEODE PATCHER", self.f_title, TEXT, anchor="w", w=3)
        stroke_text(c, tx, 70, "mod loader installer for Geometry Dash on Linux", self.f_text, SOFT, anchor="w", w=1)
        self.badge = None

        # GD folder
        self._panel(104, 190, "GEOMETRY DASH FOLDER")
        browse = Chunky(c, "BROWSE", CYAN, self.browse, self.f_btn, PANEL)
        detect = Chunky(c, "DETECT", CYAN, self.detect, self.f_btn, PANEL)
        c.create_window(W - 36, 134, window=browse, anchor="ne")
        c.create_window(W - 36 - browse.w - 10, 134, window=detect, anchor="ne")
        self.path = tk.StringVar()
        self.path.trace_add("write", lambda *_: self.refresh_state())
        entry = tk.Entry(c, textvariable=self.path, bg=FIELD, fg=TEXT, insertbackground=LIME, relief="flat",
                         font=self.f_text, highlightthickness=3, highlightbackground=OUT, highlightcolor=LIME)
        c.create_window(36, 134, window=entry, anchor="nw",
                        width=W - 72 - browse.w - detect.w - 20, height=40)

        # version
        self._panel(208, 294, "GEODE VERSION")
        self.ver = Chunky(c, "loading...  ▼", FIELD, self.pick_version, self.f_mono, PANEL, w=240)
        c.create_window(36, 238, window=self.ver, anchor="nw")
        refresh = Chunky(c, "REFRESH", CYAN, self.load_releases, self.f_btn, PANEL)
        c.create_window(36 + 240 + 10, 238, window=refresh, anchor="nw")
        self.wipe = tk.BooleanVar(value=False)
        tw = tkfont.Font(self, font=self.f_text).measure("delete mods too")
        c.create_window(W - 36 - tw - 10, 258, window=Toggle(c, self.wipe, PANEL), anchor="e")
        stroke_text(c, W - 36, 258, "delete mods too", self.f_text, TEXT, anchor="e", w=1)

        # actions + progress
        self._panel(312, 466, "PATCH")
        self.btn_install = Chunky(c, "INSTALL / UPDATE", LIME, self.install, self.f_big, PANEL, h=48)
        c.create_window(36, 340, window=self.btn_install, anchor="nw")
        uninstall = Chunky(c, "UNINSTALL", RED, self.uninstall, self.f_btn, PANEL, h=48)
        c.create_window(36 + self.btn_install.w + 12, 340, window=uninstall, anchor="nw")
        self.bar = LevelBar(c, W - 72, self.f_label, PANEL)
        c.create_window(36, 404, window=self.bar, anchor="nw")
        self.status_id = c.create_text(36, 444, text="ready", font=self.f_text, fill=SOFT,
                                       anchor="w", width=W - 72)

        # launch option
        self._panel(484, 570, "STEAM LAUNCH OPTION")
        copy = Chunky(c, "COPY", YELLOW, self.copy_opt, self.f_btn, PANEL)
        c.create_window(W - 36, 514, window=copy, anchor="ne")
        opt = tk.Label(c, text=LAUNCH_OPT, bg=FIELD, fg=CYAN, font=self.f_mono, anchor="w", padx=10,
                       highlightthickness=3, highlightbackground=OUT)
        c.create_window(36, 514, window=opt, anchor="nw", width=W - 72 - copy.w - 10, height=40)

        # ground with spikes
        gy = 604
        c.create_rectangle(0, gy, W, H, fill="#081033", outline="")
        c.create_line(0, gy, W, gy, fill=CYAN, width=3)
        for x0, n in ((40, 1), (150, 3), (330, 2), (470, 1), (560, 2)):
            for i in range(n):
                x = x0 + i * 22
                c.create_polygon(x, gy, x + 11, gy - 16, x + 22, gy, fill=OUT, outline=CYAN, width=2)

    def set_badge(self, text, color):
        c = self.c
        if self.badge:
            for i in self.badge:
                c.delete(i)
        bw = tkfont.Font(self, font=self.f_label).measure(text) + 28
        before = set(c.find_all())
        rrect(c, W - 24 - bw, 22, W - 24, 54, 12, fill=color, outline=OUT, width=3)
        stroke_text(c, W - 24 - bw / 2, 38, text, self.f_label, TEXT)
        self.badge = set(c.find_all()) - before

    # ---- helpers
    def say(self, msg):
        self.after(0, lambda: self.c.itemconfigure(self.status_id, text=msg))

    def gd(self):
        p = Path(self.path.get()).expanduser()
        if not (p / GD_EXE).exists():
            messagebox.showerror("Geode Patcher", f"Couldn't find {GD_EXE} in that folder.")
            return None
        return p

    def browse(self):
        d = filedialog.askdirectory(title="Pick your Geometry Dash folder")
        if d:
            self.path.set(d)

    def detect(self):
        p = find_gd()
        if p:
            self.path.set(str(p))
            self.say("found Geometry Dash")
        else:
            self.say("couldn't auto-find GD. hit BROWSE and pick the folder with GeometryDash.exe")
            self.refresh_state()

    def refresh_state(self):
        p = Path(self.path.get()).expanduser()
        if not (p / GD_EXE).exists():
            self.set_badge("NO GD FOUND", OFF)
        elif is_installed(p):
            self.set_badge("GEODE INSTALLED", LIME)
        else:
            self.set_badge("NOT INSTALLED", ORANGE)

    def copy_opt(self):
        self.clipboard_clear()
        self.clipboard_append(LAUNCH_OPT)
        self.say("launch option copied. paste it into Steam > GD > Properties > Launch Options")

    # ---- releases
    def pick_version(self):
        if not self.releases:
            self.say("no versions loaded yet, hit REFRESH")
            return
        m = tk.Menu(self, tearoff=0, bg=FIELD, fg=TEXT, activebackground=LIME, activeforeground=OUT,
                    font=self.f_mono, bd=0, relief="flat")
        for i, r in enumerate(self.releases):
            m.add_command(label=self._ver_name(i), command=lambda i=i: self._choose(i))
        m.tk_popup(self.ver.winfo_rootx(), self.ver.winfo_rooty() + self.ver.h + 4)

    def _ver_name(self, i):
        r = self.releases[i]
        return r["tag_name"] + ("  latest" if i == 0 else "  pre" if r.get("prerelease") else "")

    def _choose(self, i):
        self.sel = i
        self.ver.set_text(self._ver_name(i) + "  ▼")

    def load_releases(self):
        self.say("fetching Geode releases...")
        threading.Thread(target=self._load_releases, daemon=True).start()

    def _load_releases(self):
        try:
            latest = get_json(API_LATEST)
            rels = [latest] + [r for r in get_json(API_LIST)
                               if r["tag_name"] != latest["tag_name"]]
            rels = [r for r in rels if pick_win_asset(r)]

            def apply():
                self.releases = rels
                if rels:
                    self._choose(0)
                else:
                    self.ver.set_text("none found  ▼")
                self.say(f"{len(rels)} releases loaded" if rels else "no Geode releases found")
            self.after(0, apply)
        except Exception as e:
            self.after(0, lambda: self.ver.set_text("offline  ▼"))
            self.say(f"couldn't reach GitHub: {e}")

    # ---- install
    def install(self):
        gd = self.gd()
        if not gd:
            return
        if not self.releases or self.sel < 0:
            messagebox.showerror("Geode Patcher", "No Geode release loaded yet. Hit REFRESH.")
            return
        rel = self.releases[self.sel]
        self.btn_install.set_enabled(False)
        threading.Thread(target=self._install, args=(gd, rel), daemon=True).start()

    def _install(self, gd, rel):
        ok = False
        try:
            asset = pick_win_asset(rel)
            self.say(f"downloading {asset['name']}...")
            req = urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": UA["User-Agent"]})
            buf = io.BytesIO()
            with urllib.request.urlopen(req, timeout=60) as r:
                total = int(r.headers.get("Content-Length") or asset.get("size") or 0)
                got = 0
                while chunk := r.read(65536):
                    buf.write(chunk)
                    got += len(chunk)
                    if total:
                        pct = got * 100 / total
                        self.after(0, lambda p=pct: self.bar.set(p))
            self.say("extracting into the GD folder...")
            root = gd.resolve()
            with zipfile.ZipFile(buf) as z:
                for m in z.infolist():
                    target = (gd / m.filename).resolve()
                    if target != root and root not in target.parents:
                        raise RuntimeError(f"sketchy path in zip: {m.filename}")
                z.extractall(gd)
            ok = True
            self.say(f"Geode {rel['tag_name']} installed! set the launch option below, then launch GD")
            self.after(0, self.copy_opt)
            self.after(0, lambda: messagebox.showinfo(
                "Geode Patcher",
                f"Geode {rel['tag_name']} installed!\n\nLast step: set GD's Steam launch option to\n\n"
                f"{LAUNCH_OPT}\n\n(it's on your clipboard)"))
        except Exception as e:
            self.say(f"install failed: {e}")
        finally:
            self.after(0, lambda: self.btn_install.set_enabled(True))
            self.after(0, lambda: self.bar.set(100 if ok else 0))
            self.after(0, self.refresh_state)

    # ---- uninstall
    def uninstall(self):
        gd = self.gd()
        if not gd:
            return
        if not messagebox.askyesno("Geode Patcher", "Remove Geode from this GD folder?"):
            return
        removed = []
        for name in GEODE_FILES:
            p = gd / name
            if p.exists():
                p.unlink()
                removed.append(name)
        if self.wipe.get() and (gd / "geode").is_dir():
            shutil.rmtree(gd / "geode")
            removed.append("geode/")
        self.bar.set(0)
        self.say(("removed " + ", ".join(removed) + ". you can clear the Steam launch option now")
                 if removed else "nothing to remove, Geode wasn't installed there")
        self.refresh_state()


if __name__ == "__main__":
    App().mainloop()

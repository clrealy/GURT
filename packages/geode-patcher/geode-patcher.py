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
C = {  # flat dark palette, one accent
    "bg": "#15161a", "panel": "#1c1e23", "field": "#101115", "edge": "#2f323a",
    "text": "#e9e9ec", "muted": "#8b8f99", "accent": "#ffc629", "accent_hi": "#ffd35c",
    "on_accent": "#15161a", "btn": "#272a31", "good": "#3ddc84", "bad": "#ff5c5c", "warn": "#ffb020",
}


def pick_font(root, wanted, fallback):
    have = set(tkfont.families(root))
    return next((f for f in wanted if f in have), fallback)


def find_icon():
    here = Path(__file__).resolve().parent
    for p in (here.parent / "share" / "pixmaps" / "geode-patcher.png", here / "geode-patcher.png"):
        if p.exists():
            return p
    return None


class App(tk.Tk):
    def __init__(self):
        super().__init__(className="geode-patcher")  # WM_CLASS must match the .desktop
        self.title("Geode Patcher")
        self.configure(bg=C["bg"])
        self.geometry("640x520")
        self.minsize(560, 500)
        self.releases = []

        self.mono = pick_font(self, ["JetBrains Mono", "Fira Code", "Cascadia Mono", "Hack",
                                     "DejaVu Sans Mono", "Liberation Mono", "Noto Sans Mono"], "Monospace")
        self.sans = pick_font(self, ["Inter", "Cantarell", "Noto Sans", "Ubuntu",
                                     "DejaVu Sans", "Liberation Sans"], "Sans")
        self._icon = None
        icon = find_icon()
        if icon:
            try:
                self._icon = tk.PhotoImage(file=str(icon))
                self.iconphoto(True, self._icon)
            except tk.TclError:
                self._icon = None  # very old Tk without PNG support
        self._style()
        self._build()
        self.detect()
        self.load_releases()

    # ---- look
    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        mono = (self.mono, 10)
        s.configure(".", background=C["bg"], foreground=C["text"], bordercolor=C["edge"],
                    lightcolor=C["edge"], darkcolor=C["edge"], troughcolor=C["field"],
                    focuscolor=C["accent"], font=(self.sans, 10))
        for name, bg, fg, hover in (("TButton", C["btn"], C["text"], C["edge"]),
                                    ("Accent.TButton", C["accent"], C["on_accent"], C["accent_hi"]),
                                    ("Danger.TButton", C["btn"], C["bad"], C["edge"])):
            s.configure(name, background=bg, foreground=fg, font=(self.mono, 10, "bold"),
                        padding=(12, 6), relief="flat", borderwidth=1, anchor="center", width=0)
            s.map(name, background=[("disabled", C["panel"]), ("pressed", C["edge"]), ("active", hover)],
                  foreground=[("disabled", C["muted"])],
                  bordercolor=[("focus", C["accent"])])
        s.configure("Accent.TButton", bordercolor=C["accent"], padding=(18, 9), font=(self.mono, 11, "bold"))
        s.configure("TEntry", fieldbackground=C["field"], foreground=C["text"], insertcolor=C["accent"],
                    padding=(8, 6), font=mono)
        s.map("TEntry", bordercolor=[("focus", C["accent"])])
        s.configure("TCombobox", fieldbackground=C["field"], background=C["panel"], foreground=C["text"],
                    arrowcolor=C["accent"], padding=(8, 5))
        s.map("TCombobox", fieldbackground=[("readonly", C["field"])], foreground=[("readonly", C["text"])],
              selectbackground=[("readonly", C["field"])], selectforeground=[("readonly", C["text"])],
              bordercolor=[("focus", C["accent"])])
        self.option_add("*TCombobox*Listbox.background", C["field"])
        self.option_add("*TCombobox*Listbox.foreground", C["text"])
        self.option_add("*TCombobox*Listbox.selectBackground", C["accent"])
        self.option_add("*TCombobox*Listbox.selectForeground", C["on_accent"])
        self.option_add("*TCombobox*Listbox.font", mono)
        s.configure("TCheckbutton", background=C["panel"], foreground=C["muted"], indicatorbackground=C["field"],
                    indicatorforeground=C["accent"], font=(self.sans, 10))
        s.map("TCheckbutton", background=[("active", C["panel"])], foreground=[("active", C["text"])],
              indicatorbackground=[("selected", C["field"])])
        s.configure("Horizontal.TProgressbar", background=C["accent"], troughcolor=C["field"],
                    bordercolor=C["edge"], lightcolor=C["accent"], darkcolor=C["accent"], thickness=6)

    def _label(self, parent, text, **kw):
        bg = kw.pop("bg", C["bg"])
        return tk.Label(parent, text=text, bg=bg, fg=C["muted"], font=(self.mono, 8, "bold"), **kw)

    def _section(self, title):
        box = tk.Frame(self.body, bg=C["panel"], highlightthickness=1, highlightbackground=C["edge"])
        box.pack(fill="x", pady=(0, 10))
        self._label(box, title.upper(), bg=C["panel"]).pack(anchor="w", padx=12, pady=(9, 4))
        inner = tk.Frame(box, bg=C["panel"])
        inner.pack(fill="x", padx=12, pady=(0, 12))
        return inner

    def _build(self):
        # brand stripe, hard stops
        stripe = tk.Frame(self, height=4, bg=C["bg"])
        stripe.pack(fill="x")
        for col in ("#ff5c5c", "#ffc629", "#3ddc84", "#4aa3ff"):
            tk.Frame(stripe, height=4, bg=col).pack(side="left", fill="x", expand=True)

        head = tk.Frame(self, bg=C["bg"])
        head.pack(fill="x", padx=18, pady=(16, 12))
        if self._icon is not None:
            try:
                self._head_icon = self._icon.subsample(max(1, self._icon.width() // 56))
                tk.Label(head, image=self._head_icon, bg=C["bg"]).pack(side="left", padx=(0, 12))
            except tk.TclError:
                pass
        titles = tk.Frame(head, bg=C["bg"])
        titles.pack(side="left", fill="y")
        tk.Label(titles, text="GEODE PATCHER", bg=C["bg"], fg=C["text"],
                 font=(self.mono, 18, "bold")).pack(anchor="w")
        tk.Label(titles, text="mod loader installer for Geometry Dash on Linux", bg=C["bg"],
                 fg=C["muted"], font=(self.sans, 10)).pack(anchor="w")
        self.chip = tk.Label(head, text="", bg=C["field"], fg=C["muted"], font=(self.mono, 9, "bold"),
                             padx=10, pady=4, highlightthickness=1, highlightbackground=C["edge"])
        self.chip.pack(side="right", anchor="n", pady=(4, 0))

        self.body = tk.Frame(self, bg=C["bg"])
        self.body.pack(fill="both", expand=True, padx=18)

        # game folder
        g = self._section("Geometry Dash folder")
        self.path = tk.StringVar()
        self.path.trace_add("write", lambda *_: self.refresh_state())
        ttk.Entry(g, textvariable=self.path).pack(side="left", fill="x", expand=True)
        ttk.Button(g, text="DETECT", command=self.detect).pack(side="left", padx=(6, 0))
        ttk.Button(g, text="BROWSE", command=self.browse).pack(side="left", padx=(6, 0))

        # version + options
        v = self._section("Geode version")
        self.ver = ttk.Combobox(v, state="readonly", width=26, font=(self.mono, 10))
        self.ver.pack(side="left")
        ttk.Button(v, text="REFRESH", command=self.load_releases).pack(side="left", padx=(6, 0))
        self.wipe = tk.BooleanVar(value=False)
        ttk.Checkbutton(v, text="uninstall also deletes mods", variable=self.wipe).pack(side="right")

        # actions
        a = tk.Frame(self.body, bg=C["bg"])
        a.pack(fill="x", pady=(2, 8))
        self.btn_install = ttk.Button(a, text="INSTALL / UPDATE", style="Accent.TButton", command=self.install)
        self.btn_install.pack(side="left")
        ttk.Button(a, text="UNINSTALL", style="Danger.TButton", command=self.uninstall).pack(side="left", padx=(8, 0))

        self.bar = ttk.Progressbar(self.body, mode="determinate", style="Horizontal.TProgressbar")
        self.bar.pack(fill="x", pady=(4, 6))
        self.status = tk.StringVar(value="ready")
        tk.Label(self.body, textvariable=self.status, bg=C["bg"], fg=C["text"], font=(self.mono, 9),
                 anchor="w", justify="left", wraplength=580).pack(fill="x")

        # launch option footer
        foot = tk.Frame(self, bg=C["panel"], highlightthickness=1, highlightbackground=C["edge"])
        foot.pack(fill="x", side="bottom", padx=18, pady=(0, 18))
        self._label(foot, "STEAM LAUNCH OPTION  ·  GD > Properties > Launch Options",
                    bg=C["panel"]).pack(anchor="w", padx=12, pady=(9, 4))
        row = tk.Frame(foot, bg=C["panel"])
        row.pack(fill="x", padx=12, pady=(0, 12))
        tk.Label(row, text=LAUNCH_OPT, bg=C["field"], fg=C["accent"], font=(self.mono, 10), anchor="w",
                 padx=8, pady=6, highlightthickness=1, highlightbackground=C["edge"]
                 ).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="COPY", command=self.copy_opt).pack(side="left", padx=(6, 0))

    def set_chip(self, text, color):
        self.chip.configure(text="● " + text, fg=color, highlightbackground=color)

    # ---- helpers
    def say(self, msg):
        self.after(0, self.status.set, msg)

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
            self.set_chip("NO GD FOUND", C["muted"])
        elif is_installed(p):
            self.set_chip("GEODE INSTALLED", C["good"])
        else:
            self.set_chip("NOT INSTALLED", C["warn"])

    def copy_opt(self):
        self.clipboard_clear()
        self.clipboard_append(LAUNCH_OPT)
        self.say("launch option copied. paste it into Steam > GD > Properties > Launch Options")

    # ---- releases
    def load_releases(self):
        self.say("fetching Geode releases...")
        threading.Thread(target=self._load_releases, daemon=True).start()

    def _load_releases(self):
        try:
            latest = get_json(API_LATEST)
            rels = [latest] + [r for r in get_json(API_LIST)
                               if r["tag_name"] != latest["tag_name"]]
            rels = [r for r in rels if pick_win_asset(r)]
            names = [r["tag_name"] + ("  latest" if i == 0 else "  pre" if r.get("prerelease") else "")
                     for i, r in enumerate(rels)]

            def apply():
                self.releases = rels
                self.ver["values"] = names
                if names:
                    self.ver.current(0)
                self.status.set(f"{len(names)} releases loaded" if names else "no Geode releases found")
            self.after(0, apply)
        except Exception as e:
            self.say(f"couldn't reach GitHub: {e}")

    # ---- install
    def install(self):
        gd = self.gd()
        if not gd:
            return
        if not self.releases or self.ver.current() < 0:
            messagebox.showerror("Geode Patcher", "No Geode release loaded yet. Hit REFRESH.")
            return
        rel = self.releases[self.ver.current()]
        self.btn_install.state(["disabled"])
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
                        self.after(0, self.bar.configure, {"value": got * 100 / total})
            self.say("extracting into the GD folder...")
            root = gd.resolve()
            with zipfile.ZipFile(buf) as z:
                for m in z.infolist():
                    target = (gd / m.filename).resolve()
                    if target != root and root not in target.parents:
                        raise RuntimeError(f"sketchy path in zip: {m.filename}")
                z.extractall(gd)
            ok = True
            self.say(f"Geode {rel['tag_name']} installed. set the launch option below, then launch GD")
            self.after(0, self.copy_opt)
            self.after(0, lambda: messagebox.showinfo(
                "Geode Patcher",
                f"Geode {rel['tag_name']} installed!\n\nLast step: set GD's Steam launch option to\n\n"
                f"{LAUNCH_OPT}\n\n(it's on your clipboard)"))
        except Exception as e:
            self.say(f"install failed: {e}")
        finally:
            self.after(0, lambda: self.btn_install.state(["!disabled"]))
            self.after(0, self.bar.configure, {"value": 100 if ok else 0})
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
        self.bar.configure(value=0)
        self.say(("removed " + ", ".join(removed) + ". you can clear the Steam launch option now")
                 if removed else "nothing to remove, Geode wasn't installed there")
        self.refresh_state()


if __name__ == "__main__":
    App().mainloop()

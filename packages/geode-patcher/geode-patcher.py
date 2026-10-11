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
class App(tk.Tk):
    def __init__(self):
        super().__init__(className="geode-patcher")  # WM_CLASS must match the .desktop
        self.title("Geode Patcher (Linux)")
        icon = Path(__file__).resolve().parent.parent / "share" / "pixmaps" / "geode-patcher.png"
        try:
            if icon.exists():
                self._icon = tk.PhotoImage(file=str(icon))
                self.iconphoto(True, self._icon)
        except tk.TclError:
            pass  # very old Tk without PNG support
        self.geometry("560x400")
        self.minsize(480, 360)
        self.releases = []

        pad = {"padx": 12, "pady": 6}
        ttk.Label(self, text="Geode Patcher 🐧", font=("Sans", 16, "bold")).pack(anchor="w", **pad)

        # folder row
        f = ttk.Frame(self); f.pack(fill="x", **pad)
        ttk.Label(f, text="GD folder:").pack(side="left")
        self.path = tk.StringVar()
        ttk.Entry(f, textvariable=self.path).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(f, text="Browse", command=self.browse).pack(side="left")
        ttk.Button(f, text="Auto-detect", command=self.detect).pack(side="left", padx=(6, 0))

        # version row
        v = ttk.Frame(self); v.pack(fill="x", **pad)
        ttk.Label(v, text="Geode version:").pack(side="left")
        self.ver = ttk.Combobox(v, state="readonly", width=24)
        self.ver.pack(side="left", padx=6)
        ttk.Button(v, text="Refresh", command=self.load_releases).pack(side="left")

        self.wipe = tk.BooleanVar(value=False)
        ttk.Checkbutton(self, text="On uninstall, also delete the geode/ folder (mods + mod data)",
                        variable=self.wipe).pack(anchor="w", **pad)

        # action row
        b = ttk.Frame(self); b.pack(fill="x", **pad)
        self.btn_install = ttk.Button(b, text="Install / Update", command=self.install)
        self.btn_install.pack(side="left")
        ttk.Button(b, text="Uninstall", command=self.uninstall).pack(side="left", padx=6)
        ttk.Button(b, text="Copy launch option", command=self.copy_opt).pack(side="right")

        self.bar = ttk.Progressbar(self, mode="determinate")
        self.bar.pack(fill="x", **pad)
        self.status = tk.StringVar(value="ready")
        ttk.Label(self, textvariable=self.status, wraplength=520, justify="left").pack(anchor="w", **pad)

        ttk.Label(self, foreground="gray", wraplength=520, justify="left",
                  text=f"After installing, set this as GD's Steam launch option:\n{LAUNCH_OPT}"
                  ).pack(anchor="w", side="bottom", **pad)

        self.detect()
        self.load_releases()

    # ---- helpers
    def say(self, msg):
        self.after(0, self.status.set, msg)

    def gd(self):
        p = Path(self.path.get()).expanduser()
        if not (p / GD_EXE).exists():
            messagebox.showerror("Nope", f"Couldn't find {GD_EXE} in that folder.")
            return None
        return p

    def browse(self):
        d = filedialog.askdirectory(title="Pick your Geometry Dash folder")
        if d:
            self.path.set(d)
            self.refresh_state()

    def detect(self):
        p = find_gd()
        if p:
            self.path.set(str(p))
            self.refresh_state()
        else:
            self.say("couldn't auto-find GD 😭 hit Browse and pick the folder with GeometryDash.exe")

    def refresh_state(self):
        p = Path(self.path.get())
        if (p / GD_EXE).exists():
            self.say("Geode is installed ✅" if is_installed(p) else "GD found, Geode not installed yet")

    def copy_opt(self):
        self.clipboard_clear()
        self.clipboard_append(LAUNCH_OPT)
        self.say("launch option copied 📋 Steam → GD → Properties → Launch Options → paste")

    # ---- releases
    def load_releases(self):
        self.say("fetching Geode releases…")
        threading.Thread(target=self._load_releases, daemon=True).start()

    def _load_releases(self):
        try:
            latest = get_json(API_LATEST)
            rels = [latest] + [r for r in get_json(API_LIST)
                               if r["tag_name"] != latest["tag_name"]]
            rels = [r for r in rels if pick_win_asset(r)]
            self.releases = rels
            names = [r["tag_name"] + ("  (latest)" if i == 0 else "  (pre)" if r.get("prerelease") else "")
                     for i, r in enumerate(rels)]
            def apply():
                self.ver["values"] = names
                if names:
                    self.ver.current(0)
                self.refresh_state() if self.path.get() else self.say("ready")
            self.after(0, apply)
        except Exception as e:
            self.say(f"couldn't reach GitHub: {e}")

    # ---- install
    def install(self):
        gd = self.gd()
        if not gd:
            return
        if not self.releases or self.ver.current() < 0:
            messagebox.showerror("Hold up", "No Geode release loaded yet — hit Refresh.")
            return
        rel = self.releases[self.ver.current()]
        self.btn_install["state"] = "disabled"
        threading.Thread(target=self._install, args=(gd, rel), daemon=True).start()

    def _install(self, gd, rel):
        try:
            asset = pick_win_asset(rel)
            self.say(f"downloading {asset['name']}…")
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
            self.say("extracting into GD folder…")
            with zipfile.ZipFile(buf) as z:
                for m in z.infolist():
                    target = (gd / m.filename).resolve()
                    if not str(target).startswith(str(gd.resolve())):
                        raise RuntimeError(f"sketchy path in zip: {m.filename}")
                z.extractall(gd)
            self.say(f"Geode {rel['tag_name']} installed ✅ now set the launch option (button above) and launch GD 🔥")
            self.after(0, lambda: messagebox.showinfo(
                "Done 🎉",
                f"Geode {rel['tag_name']} installed!\n\nLast step: set GD's Steam launch option to\n\n{LAUNCH_OPT}\n\n(it's been copied to your clipboard)"))
            self.after(0, self.copy_opt)
        except Exception as e:
            self.say(f"install failed 💀 {e}")
        finally:
            self.after(0, lambda: self.btn_install.configure(state="normal"))
            self.after(0, self.bar.configure, {"value": 0})

    # ---- uninstall
    def uninstall(self):
        gd = self.gd()
        if not gd:
            return
        if not messagebox.askyesno("Uninstall Geode?", "Remove Geode from this GD folder?"):
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
        self.say(("removed: " + ", ".join(removed) + " — you can clear the Steam launch option now")
                 if removed else "nothing to remove, Geode wasn't there 🤷")


if __name__ == "__main__":
    App().mainloop()

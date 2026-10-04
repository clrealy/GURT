#!/usr/bin/env python3
"""PhotoGIMP Patcher - a tiny GUI to apply/restore PhotoGIMP on Linux.

Works with native GIMP 3.x and the Flatpak build. Fully standalone: just run it.
If Tkinter is missing it installs it for you, then relaunches.
"""
import base64
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

# ---------------------------------------------------------------- dependencies
# package manager command -> Tkinter package(s)
PKG_MANAGERS = [
    ("pacman",       ["pacman", "-S", "--needed", "--noconfirm"], ["tk"]),
    ("apt-get",      ["apt-get", "install", "-y"],                 ["python3-tk"]),
    ("dnf",          ["dnf", "install", "-y"],                     ["python3-tkinter"]),
    ("zypper",       ["zypper", "--non-interactive", "install"],  ["python3-tk"]),
    ("xbps-install", ["xbps-install", "-Sy"],                      ["python3-tkinter"]),
    ("apk",          ["apk", "add"],                               ["py3-tkinter"]),
    ("eopkg",        ["eopkg", "install", "-y"],                   ["python3-tkinter"]),
]


def _has_tk(python):
    return subprocess.call([python, "-c", "import tkinter"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def _relaunch_with_tk_python():
    """Some setups have python3 pointing at a non-distro Python. Find one that has tk."""
    for py in sorted(glob.glob("/usr/bin/python3*"), reverse=True):
        if os.access(py, os.X_OK) and not py.endswith("-config") and \
                os.path.realpath(py) != os.path.realpath(sys.executable) and _has_tk(py):
            os.execv(py, [py, os.path.abspath(__file__), *sys.argv[1:]])


def _install_tk():
    for name, cmd, pkgs in PKG_MANAGERS:
        if not shutil.which(name):
            continue
        if os.geteuid() == 0:
            elev = []
        elif shutil.which("pkexec") and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            elev = ["pkexec"]          # graphical password prompt
        elif sys.stdin.isatty() and shutil.which("sudo"):
            elev = ["sudo"]
        else:
            return False
        print(f"Tkinter missing, installing {' '.join(pkgs)} with {name}...")
        if name == "apt-get":
            subprocess.call(elev + ["apt-get", "update"])
        return subprocess.call(elev + cmd + pkgs) == 0
    return False


try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
except ImportError:
    _relaunch_with_tk_python()
    if _install_tk():
        if _has_tk(sys.executable):
            os.execv(sys.executable, [sys.executable, os.path.abspath(__file__), *sys.argv[1:]])
        _relaunch_with_tk_python()
    msg = ("PhotoGIMP Patcher needs Tkinter and couldn't install it automatically.\n"
           "Install it with your package manager: Arch 'tk', Debian/Ubuntu 'python3-tk', "
           "Fedora 'python3-tkinter', openSUSE 'python3-tk'")
    if shutil.which("notify-send"):
        subprocess.call(["notify-send", "PhotoGIMP Patcher", msg])
    raise SystemExit(msg)

RELEASE_URL = "https://github.com/Diolinux/PhotoGIMP/releases/latest/download/PhotoGIMP-linux.zip"
HOME = Path.home()
NATIVE, FLATPAK = "Native (distro package)", "Flatpak (org.gimp.GIMP)"
# GIMP's config *base*; the real folder is <base>/<major.minor>, e.g. 3.0 or 3.2
TARGETS = {
    NATIVE: Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "GIMP",
    FLATPAK: HOME / ".var/app/org.gimp.GIMP/config/GIMP",
}
BACKUP_ROOT = HOME / ".local/share/photogimp-patcher/backups"


def native_gimp():
    """Newest GIMP 3 binary on PATH (gimp-3.2 beats gimp-3.0 beats plain gimp)."""
    best = None
    for d in os.environ.get("PATH", "").split(":"):
        for p in glob.glob(os.path.join(d, "gimp-3*")):
            if os.access(p, os.X_OK) and (best is None or Path(p).name > Path(best).name):
                best = p
    return best or shutil.which("gimp")


def flatpak_gimp_installed():
    return shutil.which("flatpak") and subprocess.call(
        ["flatpak", "info", "org.gimp.GIMP"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def detect_targets():
    """Return the install types that look present on this machine."""
    found = []
    # a binary on the system, or a GIMP 3 config folder that exists = it's there
    if native_gimp():
        found.append(NATIVE)
    if flatpak_gimp_installed() or _newest_existing(TARGETS[FLATPAK]):
        found.append(FLATPAK)
    return found


def _gimp_cmd(kind):
    return ["flatpak", "run", "org.gimp.GIMP"] if kind == FLATPAK else [native_gimp() or "gimp"]


def _newest_existing(base):
    dirs = [p for p in base.glob("3.*") if p.is_dir()]
    return max(dirs, key=lambda p: [int(x) if x.isdigit() else 0 for x in p.name.split(".")]) if dirs else None


def flatpak_shares_host_config():
    """GIMP's Flatpak is usually allowed xdg-config/GIMP, i.e. it uses ~/.config/GIMP like native."""
    try:
        perms = subprocess.run(["flatpak", "info", "--show-permissions", "org.gimp.GIMP"],
                               capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    for line in perms.splitlines():
        if line.startswith("filesystems="):
            for fs in line.split("=", 1)[1].split(";"):
                fs = fs.split(":")[0]   # drop :create / :ro
                if fs in ("xdg-config", "home", "host") or fs.startswith("xdg-config/GIMP"):
                    return True
    return False


def resolve_config_dir(kind, log=print, ask_gimp=True):
    """Find the exact folder GIMP reads its config from (same trick as PhotoGIMP's install.sh)."""
    base = TARGETS[kind]
    if kind == FLATPAK and flatpak_shares_host_config():
        base = TARGETS[NATIVE]
    cmd = _gimp_cmd(kind)
    if ask_gimp and (kind == FLATPAK or cmd[0]):
        log("Asking GIMP where its config lives (takes a few secs)...")
        script = '(begin (display "GIMP_CONFIG_DIR=") (display gimp-directory) (newline))'
        try:
            out = subprocess.run(cmd + ["--no-interface", "--console-messages",
                                        "--batch-interpreter=plug-in-script-fu-eval",
                                        "--batch", script, "--quit"],
                                 capture_output=True, text=True, timeout=90).stdout
            for line in out.splitlines():
                if line.startswith("GIMP_CONFIG_DIR="):
                    return Path(line.split("=", 1)[1].strip())
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:  # fall back to the version number
            out = subprocess.run(cmd + ["--version"], capture_output=True, text=True, timeout=30).stdout
            import re
            m = re.search(r"\b(3\.\d+)", out)
            if m:
                return base / m.group(1)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return _newest_existing(base) or base / "3.0"


def gimp_running():
    return subprocess.call(["pgrep", "-x", r"gimp(-3(\.[0-9]+)?)?"],  # process name only
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def fetch_zip(log):
    tmp = Path(tempfile.mkdtemp(prefix="photogimp-")) / "PhotoGIMP-linux.zip"
    log("Downloading latest PhotoGIMP release...")
    urllib.request.urlretrieve(RELEASE_URL, tmp)
    log(f"Downloaded {tmp.stat().st_size // 1024} KB")
    return tmp


def extract(zip_path, log):
    out = Path(tempfile.mkdtemp(prefix="photogimp-x-"))
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(out)
    roots = [p for p in out.iterdir() if p.is_dir()]
    root = roots[0] if len(roots) == 1 else out
    src = root / ".config/GIMP/3.0"
    if not src.is_dir():
        raise RuntimeError("Zip doesn't look like a PhotoGIMP Linux release (no .config/GIMP/3.0)")
    log("Extracted patch files")
    return root


def backup(target, log):
    if not target.exists() or not any(target.iterdir()):
        log("No existing config to back up")
        return None
    kind = "flatpak" if ".var/app" in str(target) else "native"
    dest = BACKUP_ROOT / f"{kind}-{target.name}-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copytree(target, dest)
    log(f"Backed up current config -> {dest}")
    return dest


def apply_patch(root, target, extras, log):
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(root / ".config/GIMP/3.0", target, dirs_exist_ok=True)
    log(f"Patched config in {target}")
    # PhotoGIMP's launcher runs `flatpak run org.gimp.GIMP`, so it'd break a native GIMP's shortcut
    if extras and ".var/app" not in str(target):
        log("Skipping PhotoGIMP launcher/icon (it's Flatpak-only)")
    elif extras:
        share = root / ".local/share"
        if share.is_dir():
            shutil.copytree(share, HOME / ".local/share", dirs_exist_ok=True)
            log("Installed PhotoGIMP icon + launcher")
            os.system("update-desktop-database ~/.local/share/applications >/dev/null 2>&1")
            os.system("gtk-update-icon-cache -f ~/.local/share/icons/hicolor >/dev/null 2>&1")


APP_DIR = HOME / ".local/share/photogimp-patcher"
DESKTOP_FILE = HOME / ".local/share/applications/photogimp-patcher.desktop"
ICON_FILE = HOME / ".local/share/icons/hicolor/256x256/apps/photogimp-patcher.png"


def icon_bytes():
    return base64.b64decode(ICON_PNG_B64)


def menu_entry_installed():
    return DESKTOP_FILE.exists()


def add_to_menu():
    """Copy this script somewhere stable and register an app menu entry + icon."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    script = APP_DIR / "photogimp-patcher.py"
    if Path(__file__).resolve() != script.resolve():
        shutil.copy2(__file__, script)
    script.chmod(0o755)
    ICON_FILE.parent.mkdir(parents=True, exist_ok=True)
    ICON_FILE.write_bytes(icon_bytes())
    DESKTOP_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Absolute paths: launchers don't see your shell PATH
    DESKTOP_FILE.write_text(
        "[Desktop Entry]\nType=Application\nName=PhotoGIMP Patcher\n"
        "Comment=Apply or restore the PhotoGIMP patch for GIMP 3\n"
        f'Exec="{sys.executable}" "{script}"\nIcon={ICON_FILE}\n'
        "Terminal=false\nCategories=Graphics;Utility;\nStartupWMClass=Photogimp-patcher\n")
    for cmd in (["update-desktop-database", str(DESKTOP_FILE.parent)],
                ["gtk-update-icon-cache", "-f", str(HOME / ".local/share/icons/hicolor")],
                ["kbuildsycoca6"], ["kbuildsycoca5"]):
        if shutil.which(cmd[0]):
            subprocess.call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def remove_from_menu():
    for f in (DESKTOP_FILE, ICON_FILE, APP_DIR / "photogimp-patcher.py"):
        f.unlink(missing_ok=True)


def list_backups():
    if not BACKUP_ROOT.exists():
        return []
    return sorted((p for p in BACKUP_ROOT.iterdir() if p.is_dir()), reverse=True)


class App(tk.Tk):
    def __init__(self):
        super().__init__(className="photogimp-patcher")  # WM_CLASS must match the .desktop
        self.title("PhotoGIMP Patcher")
        try:
            big = tk.PhotoImage(data=ICON_PNG_B64)
            self._icons = [big, big.subsample(4), big.subsample(8)]  # 256, 64, 32
            self.iconphoto(True, *self._icons)
        except tk.TclError:
            pass  # very old Tk without PNG support
        self.geometry("560x470")
        self.minsize(480, 420)
        self.local_zip = None

        pad = {"padx": 12, "pady": 6}
        ttk.Label(self, text="PhotoGIMP Patcher", font=("Sans", 16, "bold")).pack(anchor="w", **pad)
        ttk.Label(self, text="Makes GIMP 3 look + feel like Photoshop. Close GIMP before patching.",
                  foreground="gray").pack(anchor="w", padx=12)

        box = ttk.LabelFrame(self, text="Patch these GIMP installs")
        box.pack(fill="x", **pad)
        detected = detect_targets()
        self.targets = {}
        for name in TARGETS:
            self.targets[name] = tk.BooleanVar(value=name in detected or not detected and name == NATIVE)
            label = name + ("  ✓ detected" if name in detected else "")
            ttk.Checkbutton(box, text=label, variable=self.targets[name]).pack(anchor="w", padx=8, pady=2)

        opts = ttk.LabelFrame(self, text="Options")
        opts.pack(fill="x", **pad)
        self.do_backup = tk.BooleanVar(value=True)
        self.do_extras = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Back up my current GIMP config first", variable=self.do_backup).pack(anchor="w", padx=8)
        ttk.Checkbutton(opts, text="Install PhotoGIMP icon + launcher", variable=self.do_extras).pack(anchor="w", padx=8)
        row = ttk.Frame(opts)
        row.pack(fill="x", padx=8, pady=4)
        self.src_label = ttk.Label(row, text="Source: latest release from GitHub")
        self.src_label.pack(side="left")
        ttk.Button(row, text="Use local zip…", command=self.pick_zip).pack(side="right")

        btns = ttk.Frame(self)
        btns.pack(fill="x", **pad)
        self.patch_btn = ttk.Button(btns, text="Apply PhotoGIMP", command=self.run_patch)
        self.patch_btn.pack(side="left")
        ttk.Button(btns, text="Restore backup…", command=self.restore).pack(side="left", padx=8)
        self.menu_btn = ttk.Button(btns, command=self.toggle_menu)
        if not Path(__file__).resolve().as_posix().startswith(("/usr/", "/opt/")):
            # system package install already ships a menu entry
            self.menu_btn.pack(side="right")
            self._refresh_menu_btn()

        self.bar = ttk.Progressbar(self, mode="indeterminate")
        self.bar.pack(fill="x", padx=12)
        self.logbox = tk.Text(self, height=8, state="disabled", wrap="word")
        self.logbox.pack(fill="both", expand=True, **pad)

    def log(self, msg):
        def _w():
            self.logbox.configure(state="normal")
            self.logbox.insert("end", msg + "\n")
            self.logbox.see("end")
            self.logbox.configure(state="disabled")
        self.after(0, _w)

    def _refresh_menu_btn(self):
        self.menu_btn.config(text="Remove from app menu" if menu_entry_installed() else "Add to app menu")

    def toggle_menu(self):
        try:
            if menu_entry_installed():
                remove_from_menu()
                self.log("Removed from app menu")
            else:
                add_to_menu()
                self.log("Added 'PhotoGIMP Patcher' to your app menu ✓")
        except Exception as e:
            messagebox.showerror("App menu", str(e))
        self._refresh_menu_btn()

    def pick_zip(self):
        f = filedialog.askopenfilename(filetypes=[("Zip", "*.zip")])
        if f:
            self.local_zip = Path(f)
            self.src_label.config(text=f"Source: {self.local_zip.name}")

    def run_patch(self):
        self.patch_btn.config(state="disabled")
        self.bar.start(10)
        threading.Thread(target=self._patch, daemon=True).start()

    def _patch(self):
        try:
            if gimp_running():
                raise RuntimeError("GIMP is running! Close it first, it overwrites its config when it quits.")
            kinds = [k for k, v in self.targets.items() if v.get()]
            if not kinds:
                raise RuntimeError("Tick at least one GIMP install to patch.")
            z = self.local_zip or fetch_zip(self.log)
            root = extract(z, self.log)
            done = set()
            for kind in kinds:
                self.log(f"── {kind} ──")
                target = resolve_config_dir(kind, self.log)
                if target in done:
                    self.log(f"Shares {target} with the other install, already patched ✓")
                    continue
                done.add(target)
                self.log(f"GIMP config folder: {target}")
                if self.do_backup.get():
                    backup(target, self.log)
                apply_patch(root, target, self.do_extras.get(), self.log)
            self.log("Done! Launch GIMP and enjoy 🎉")
            self.after(0, lambda: messagebox.showinfo("PhotoGIMP", "Patch applied! Restart GIMP."))
        except Exception as e:
            self.log(f"Error: {e}")
            self.after(0, lambda: messagebox.showerror("PhotoGIMP", str(e)))
        finally:
            self.after(0, lambda: (self.bar.stop(), self.patch_btn.config(state="normal")))

    def restore(self):
        backups = list_backups()
        if not backups:
            messagebox.showinfo("Restore", "No backups found yet.")
            return
        win = tk.Toplevel(self)
        win.title("Restore backup")
        lb = tk.Listbox(win, width=60, height=10)
        for b in backups:
            lb.insert("end", b.name)
        lb.pack(padx=10, pady=10)

        def go():
            sel = lb.curselection()
            if not sel:
                return
            src = backups[sel[0]]
            kind = FLATPAK if src.name.startswith("flatpak") else NATIVE
            ver = src.name.split("-")[1] if src.name.count("-") >= 3 else None
            target = TARGETS[kind] / ver if ver else resolve_config_dir(kind, ask_gimp=False)
            if not messagebox.askyesno("Restore", f"Replace {target} with backup {src.name}?"):
                return
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(src, target)
            self.log(f"Restored {src.name} -> {target}")
            win.destroy()
        ttk.Button(win, text="Restore selected", command=go).pack(pady=(0, 10))


# Embedded app icon (256x256 PNG)
ICON_PNG_B64 = (
    "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"
    "AAAAAElFTkSuQmCC"
)


if __name__ == "__main__":
    App().mainloop()

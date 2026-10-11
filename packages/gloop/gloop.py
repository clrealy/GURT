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
  gloop add <file|url>  add a mashup (.json recipe or .gloop bundle)
  gloop export <id> [--bundle] [-o file]   save one to share

Mashups live in ~/.local/share/gloop/mashups/*.json. Two kinds:

  Minecraft (Fabric):
    {"id": "speed-craft", "name": "Speed Craft", "type": "minecraft",
     "minecraft_version": "latest",          # or e.g. "1.21.1"
     "mods": ["fabric-api", "sodium"]}       # Modrinth slugs

  Thunderstore (Lethal Company, R.E.P.O., Valheim, Risk of Rain 2...):
    {"id": "my-mix", "name": "My Mix", "type": "thunderstore", "steam_appid": 1966720,
     "packages": ["Owner-ModName"]}            # BepInEx + deps get added for you

  Any Steam game, direct files or zips (Nexus-style; works with Proton games):
    {"id": "my-mod", "name": "My Mod", "type": "steam", "steam_appid": 400,
     "files": [{"url": "https://...", "dest": "portal/custom/thing.vpk", "sha256": "optional"},
               {"path": "~/Downloads/mod.zip", "dest": "Data", "extract": true}]}

  "games": [{"name": "Minecraft"}, {"name": "Portal", "steam_appid": 400}] says
  which games a mashup mixes, so the Mix screen can find it.

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
import tempfile
import zipfile
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

APP = "gloop"
VERSION = "0.4.0"
UA = f"gloop/{VERSION} (linux mashup launcher)"
DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / APP
MASHUP_DIR = DATA / "mashups"
INST_DIR = DATA / "instances"
BACKUP_DIR = DATA / "backups"
STATE_FILE = DATA / "state.json"

FABRIC_META = "https://meta.fabricmc.net/v2"
MODRINTH = "https://api.modrinth.com/v2"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
TS_RE = re.compile(r"^[A-Za-z0-9_]+-[A-Za-z0-9_]+$")
THUNDERSTORE = "https://thunderstore.io/api/experimental/package"

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
    "portal-craft.json": {
        "id": "portal-craft",
        "name": "Portal Craft",
        "type": "minecraft",
        "description": "A working portal gun in Minecraft. Blue portal, orange portal, go.",
        "games": [{"name": "Minecraft"}, {"name": "Portal", "steam_appid": 400}],
        "minecraft_version": "1.20.4",
        "mods": ["fabric-api", "portal-gun"],
    },
    "terra-craft.json": {
        "id": "terra-craft",
        "name": "Terra Craft",
        "type": "minecraft",
        "description": "Terraria in Minecraft: bosses, gear, coins, minecarts, cabins, crates, quick stack.",
        "games": [{"name": "Minecraft"}, {"name": "Terraria", "steam_appid": 105600}],
        "minecraft_version": "1.20.1",
        "mods": ["fabric-api", "terramine", "terrablender", "numismatic-overhaul", "spelunker", "terrastorage",
                 "subterrestrial", "terracart-reloaded", "fishing-loot-crates"],
    },
    "stronghold-run.json": {
        "id": "stronghold-run",
        "name": "Stronghold Run",
        "type": "thunderstore",
        "description": "Loot a Minecraft stronghold in R.E.P.O., with Minecraft valuables to haul out.",
        "games": [{"name": "R.E.P.O.", "steam_appid": 3241660}, {"name": "Minecraft"}],
        "steam_appid": 3241660,
        "community": "repo",
        "packages": ["AriIcedT-MinecraftStrongholdLevel", "Kizzycocoa-MinecraftItemsPlus"],
    },
    "aperture-repo.json": {
        "id": "aperture-repo",
        "name": "Aperture Repo",
        "type": "thunderstore",
        "description": "A real portal gun in R.E.P.O. Shoot blue and orange, yeet loot through walls.",
        "games": [{"name": "R.E.P.O.", "steam_appid": 3241660}, {"name": "Portal", "steam_appid": 400}],
        "steam_appid": 3241660,
        "community": "repo",
        "packages": ["TheMorningStar-PortalGun"],
    },
    "lethal-craft.json": {
        "id": "lethal-craft",
        "name": "Lethal Craft",
        "type": "thunderstore",
        "description": "A blocky Minecraft moon to land on, plus Minecraft scrap to sell to the Company.",
        "games": [{"name": "Lethal Company", "steam_appid": 1966720}, {"name": "Minecraft"}],
        "steam_appid": 1966720,
        "community": "lethal-company",
        "packages": ["DalekMC-MinecraftMoon", "4902-Minecraft_Scraps"],
    },
    "lethal-64.json": {
        "id": "lethal-64",
        "name": "Lethal 64",
        "type": "thunderstore",
        "description": "Clock in as Super Mario 64 Mario. Wahoo, the Company needs scrap.",
        "games": [{"name": "Lethal Company", "steam_appid": 1966720}, {"name": "Super Mario 64"}],
        "steam_appid": 1966720,
        "community": "lethal-company",
        "packages": ["3UPPER-SM64Mario"],
    },
    "_example-steam.json": {
        "id": "example-steam",
        "name": "Example Steam Mashup (template)",
        "type": "steam",
        "description": "Template - files starting with _ are ignored. Copy + edit me.",
        "steam_appid": 400,
        "files": [{"url": "https://example.com/mod.vpk", "dest": "portal/custom/mod.vpk"},
                  {"path": "~/Downloads/some-nexus-mod.zip", "dest": "Data", "extract": True}],
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
        bm = m.get("bundled_mods")
        if bm is not None and (not isinstance(bm, list) or not all(isinstance(x, str) for x in bm)):
            raise ValueError("'bundled_mods' must be a list of file names")
        if not bm and (not isinstance(m.get("mods"), list) or not m["mods"]):
            raise ValueError("minecraft mashup needs a 'mods' list of Modrinth slugs")
    elif m.get("type") in ("steam", "thunderstore"):
        if not isinstance(m.get("steam_appid"), int):
            raise ValueError("this mashup needs a numeric 'steam_appid'")
        if m["type"] == "steam":
            if not isinstance(m.get("files"), list) or not m["files"]:
                raise ValueError("steam mashup needs a 'files' list")
            for f in m["files"]:
                if not isinstance(f, dict) or not (f.get("url") or f.get("path") or f.get("bundled")) or "dest" not in f:
                    raise ValueError("each file needs a 'url' or 'path', plus a 'dest'")
        else:
            pk = m.get("packages")
            if not isinstance(pk, list) or not pk or not all(isinstance(x, str) and TS_RE.match(x) for x in pk):
                raise ValueError("thunderstore mashup needs 'packages' like [\"Owner-ModName\"]")
    else:
        raise ValueError("'type' must be 'minecraft', 'thunderstore' or 'steam'")
    games = m.get("games", [])
    if not isinstance(games, list) or not all(isinstance(g, dict) and isinstance(g.get("name"), str) for g in games):
        raise ValueError("'games' must look like [{\"name\": \"Minecraft\"}]")
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


def mc_game_version(m):
    game = m.get("minecraft_version", "latest")
    if game in (None, "", "latest"):
        game = latest_stable(f"{FABRIC_META}/versions/game")
    return game


def mc_resolve(slugs, game):
    """Modrinth slugs -> the files to grab for this Minecraft version, required deps included"""
    out, queue, done, got = [], [(sl, False) for sl in slugs], set(), set()
    q = urllib.parse.urlencode({"loaders": json.dumps(["fabric"]), "game_versions": json.dumps([game])})
    while queue:
        slug, is_dep = queue.pop(0)
        if slug in done:
            continue
        done.add(slug)
        try:
            vers = http_json(f"{MODRINTH}/project/{urllib.parse.quote(slug)}/version?{q}")
        except urllib.error.HTTPError as e:
            log(f"  ! {slug}: not found on Modrinth ({e.code}), skipping")
            continue
        if not vers:
            log(f"  ! {slug}: no Fabric build for {game} yet, skipping")
            continue
        v = vers[0]
        if v.get("project_id") in got:     # same mod asked for by slug and by id
            continue
        got.add(v.get("project_id"))
        f = next((x for x in v["files"] if x.get("primary")), v["files"][0])
        out.append({"slug": slug, "dep": is_dep, "url": f["url"], "filename": f["filename"],
                    "sha512": f.get("hashes", {}).get("sha512")})
        for d in v.get("dependencies", []):
            if d.get("dependency_type") == "required" and d.get("project_id"):
                queue.append((d["project_id"], True))
    return out


def install_minecraft(m):
    game = mc_game_version(m)
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
        bdir = bundle_dir(m)
        if m.get("bundled_mods"):
            for rel in m["bundled_mods"]:
                src = safe_join(bdir, rel)
                if not src.is_file():
                    raise RuntimeError(f"this bundle is missing {rel}")
                shutil.copy2(src, mods / src.name)
                rec["mods"].append(src.name)
                log(f"  + {src.name} (from the bundle)")
        else:
            for f in mc_resolve(m.get("mods", []), game):
                download(f["url"], mods / f["filename"], sha512=f["sha512"])
                rec["mods"].append(f["filename"])
                log(f"  + {f['slug']}{' (needed by another mod)' if f['dep'] else ''}: {f['filename']} verified")

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
    if rec.get("prism_instance") and Path(rec["prism_instance"]).name.startswith("gloop-"):
        shutil.rmtree(rec["prism_instance"], ignore_errors=True)
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


PRISM_FLATPAK = "org.prismlauncher.PrismLauncher"


def prism():
    """-> (launch command, data dir) for Prism Launcher (native or Flatpak), or None"""
    home = Path.home()
    if shutil.which("prismlauncher"):
        cmd, data = [shutil.which("prismlauncher")], home / ".local/share/PrismLauncher"
    elif shutil.which("flatpak") and subprocess.run(["flatpak", "info", PRISM_FLATPAK],
                                                     capture_output=True).returncode == 0:
        cmd, data = ["flatpak", "run", PRISM_FLATPAK], home / f".var/app/{PRISM_FLATPAK}/data/PrismLauncher"
    else:
        return None
    if os.environ.get("GLOOP_PRISM_DIR"):
        data = Path(os.environ["GLOOP_PRISM_DIR"])
    return cmd, data


def prism_instances(data):
    inst = "instances"
    cfg = data / "prismlauncher.cfg"
    if cfg.exists():
        mm = re.search(r"^InstanceDir=(.+)$", cfg.read_text(errors="ignore"), re.M)
        if mm:
            inst = mm.group(1).strip()
    p = Path(os.path.expanduser(inst))
    return p if p.is_absolute() else data / p


def ensure_prism(m, rec, data):
    """make (or refresh) a Prism instance for this mashup, with its own copy of the mods"""
    pid = f"gloop-{m['id']}"
    idir = prism_instances(data) / pid
    mods = idir / ".minecraft" / "mods"
    vid = rec["version_id"]                      # fabric-loader-<loader>-<game>
    loader, game = vid[len("fabric-loader-"):].split("-", 1)
    mods.mkdir(parents=True, exist_ok=True)
    (idir / "instance.cfg").write_text(
        f"[General]\nConfigVersion=1.2\nInstanceType=OneSix\nname={m['name']} [gloop]\niconKey=grass\n")
    (idir / "mmc-pack.json").write_text(json.dumps({"formatVersion": 1, "components": [
        {"uid": "net.minecraft", "version": game, "important": True},
        {"uid": "net.fabricmc.intermediary", "version": game, "dependencyOnly": True},
        {"uid": "net.fabricmc.fabric-loader", "version": loader},
    ]}, indent=2))
    for f in mods.glob("*.jar"):
        f.unlink()
    for jar in (Path(rec["instance"]) / "mods").glob("*.jar"):
        shutil.copy2(jar, mods / jar.name)
    rec["prism_instance"] = str(idir)
    return pid


def launch_minecraft(m, rec):
    pr = prism()
    if pr:
        cmd, data = pr
        pid = ensure_prism(m, rec, data)
        subprocess.Popen(cmd + ["--launch", pid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        log(f"launching '{m['name']}' in Prism Launcher")
        return {"msg": "Opening in Prism Launcher. First launch downloads Minecraft, so give it a sec.",
                "save": True}
    for cmd in ("minecraft-launcher", "minecraft"):
        if shutil.which(cmd):
            subprocess.Popen([cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            log(f"opened the launcher - pick the '{m['name']} [gloop]' profile and hit Play")
            return {"msg": f"Pick the '{m['name']} [gloop]' profile in the launcher and hit Play."}
    raise RuntimeError("no Minecraft launcher found. install Prism Launcher "
                       "(gurt install prismlauncher, or flatpak install flathub org.prismlauncher.PrismLauncher)")


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


class GameFiles:
    """puts files into a game folder, backing up anything it replaces so uninstall can undo it all."""

    def __init__(self, game, backup):
        self.game, self.backup, self.files, self.seen = game, backup, [], set()

    def put(self, rel, src):
        dest = (self.game / rel).resolve()
        if self.game not in dest.parents:
            raise RuntimeError(f"blocked sketchy path outside the game folder: {rel}")
        r = str(dest.relative_to(self.game))
        if r not in self.seen:
            self.seen.add(r)
            entry = {"rel": r, "backed_up": False}
            if dest.exists():
                (self.backup / r).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, self.backup / r)
                entry["backed_up"] = True
            self.files.append(entry)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)

    def put_zip(self, zpath, mapper):
        with zipfile.ZipFile(zpath) as z, tempfile.TemporaryDirectory(dir=DATA) as tmp:
            for info in z.infolist():
                name = info.filename.replace("\\", "/")
                if info.is_dir() or name.startswith("/") or ".." in name.split("/"):
                    continue
                rel = mapper(name)
                if not rel:
                    continue
                out = Path(tmp) / "f"
                with z.open(info) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                self.put(rel, out)


def game_folder(m):
    game = find_game(m["steam_appid"])
    if not game or not game.exists():
        url = f"https://store.steampowered.com/app/{m['steam_appid']}"
        raise RuntimeError(f"you need the game first (Steam app {m['steam_appid']}). grab it: {url}")
    return game.resolve()


def files_rec(m, gf):
    return {"type": m["type"], "appid": m["steam_appid"], "game": str(gf.game),
            "backup": str(gf.backup), "files": gf.files}


def install_steam(m):
    gf = GameFiles(game_folder(m), BACKUP_DIR / m["id"])
    DATA.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=DATA) as tmp:
            for i, f in enumerate(m["files"]):
                if f.get("bundled"):
                    src = safe_join(bundle_dir(m), f["bundled"])
                    if not src.is_file():
                        raise RuntimeError(f"this bundle is missing {f['bundled']}")
                elif f.get("path"):
                    src = Path(os.path.expanduser(f["path"]))
                    if not src.is_file():
                        raise RuntimeError(f"can't find {src} - download the mod there first")
                    if f.get("sha256") and hashlib.sha256(src.read_bytes()).hexdigest() != f["sha256"].lower():
                        raise RuntimeError(f"hash mismatch for {src.name} - refusing to install")
                else:
                    src = Path(tmp) / f"dl{i}"
                    download(f["url"], src, sha256=f.get("sha256"))
                if f.get("extract"):
                    if not zipfile.is_zipfile(src):
                        raise RuntimeError(f"{f.get('path') or f['url']} isn't a .zip (7z/rar: unzip it yourself first)")
                    base, strip = f["dest"].strip("/"), int(f.get("strip", 0))

                    def mapper(name, base=base, strip=strip):
                        parts = name.split("/")[strip:]
                        return "/".join([base] + parts) if parts else None
                    gf.put_zip(src, mapper)
                    log(f"  + unpacked into {f['dest'] or 'the game folder'}")
                else:
                    gf.put(f["dest"], src)
                    log(f"  + {f['dest']}")
    except Exception:
        uninstall_steam(files_rec(m, gf), {})
        raise
    return files_rec(m, gf)


def ts_resolve(names):
    """Owner-Name list -> install order (deps first), always starting with a BepInEx pack."""
    order, seen = [], set()

    def visit(full):
        key = full.lower()
        if key in seen:
            return
        seen.add(key)
        ns, name = full.split("-", 1)
        try:
            d = http_json(f"{THUNDERSTORE}/{urllib.parse.quote(ns)}/{urllib.parse.quote(name)}/")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{full} isn't on Thunderstore ({e.code})")
        latest = d["latest"]
        for dep in latest.get("dependencies", []):
            visit(dep.rsplit("-", 1)[0])           # drop the version: always take the newest
        order.append({"full": d["full_name"], "url": latest["download_url"], "ver": latest["version_number"]})
    for n in names:
        visit(n)
    if not any(p["full"].lower().startswith("bepinex-bepinexpack") or "bepinexpack" in p["full"].lower() for p in order):
        visit("BepInEx-BepInExPack")
        order.insert(0, order.pop())
    else:   # the loader goes in first
        order.sort(key=lambda p: "bepinexpack" not in p["full"].lower())
    return order


SKIP_TOP = {"manifest.json", "icon.png", "readme.md", "changelog.md", "license", "license.md", "license.txt"}


def ts_mapper(full, names):
    if "bepinexpack" in full.lower():
        # the pack zip wraps the loader in a folder (BepInExPack/, BepInExPack_Valheim/...): unwrap it
        tops = {n.split("/")[0] for n in names if "/" in n and n.split("/")[0].lower().startswith("bepinexpack")}

        def m(name):
            first, _, rest = name.partition("/")
            if first in tops:
                return rest or None
            return None if name.lower() in SKIP_TOP else name
        return m

    def m(name):
        parts = name.split("/")
        if len(parts) == 1 and parts[0].lower() in SKIP_TOP:
            return None
        head = parts[0].lower()
        if head == "bepinex":
            return "/".join(["BepInEx"] + parts[1:])
        if head in ("plugins", "patchers", "core", "monomod") and len(parts) > 1:
            return "/".join(["BepInEx", head, full] + parts[1:])
        if head == "config" and len(parts) > 1:
            return "/".join(["BepInEx", "config"] + parts[1:])
        return "/".join(["BepInEx", "plugins", full] + parts)
    return m


def install_thunderstore(m):
    gf = GameFiles(game_folder(m), BACKUP_DIR / m["id"])
    DATA.mkdir(parents=True, exist_ok=True)
    try:
        if m.get("bundled_packages"):
            pkgs = [{"full": Path(r).stem, "bundled": r, "ver": "(bundled)"} for r in m["bundled_packages"]]
        else:
            pkgs = ts_resolve(m["packages"])
        with tempfile.TemporaryDirectory(dir=DATA) as tmp:
            for p in pkgs:
                if p.get("bundled"):
                    z = safe_join(bundle_dir(m), p["bundled"])
                else:
                    z = Path(tmp) / f"{p['full']}.zip"
                    download(p["url"], z)
                with zipfile.ZipFile(z) as zz:
                    names = [i.filename.replace("\\", "/") for i in zz.infolist() if not i.is_dir()]
                gf.put_zip(z, ts_mapper(p["full"], names))
                log(f"  + {p['full']} {p['ver']}")
    except Exception:
        uninstall_steam(files_rec(m, gf), {})
        raise
    return files_rec(m, gf)


def uninstall_steam(rec, _others):
    game, backup = Path(rec["game"]), Path(rec["backup"])
    for e in reversed(rec["files"]):
        dest = game / e["rel"]
        if e["backed_up"] and (backup / e["rel"]).exists():
            shutil.copy2(backup / e["rel"], dest)
        else:
            dest.unlink(missing_ok=True)
            d = dest.parent   # tidy folders we made, stop at the first one that still has stuff
            while d != game and d.is_dir() and not any(d.iterdir()):
                d.rmdir()
                d = d.parent
    shutil.rmtree(backup, ignore_errors=True)


def launch_steam(m, _rec):
    url = f"steam://rungameid/{m['steam_appid']}"
    opener = shutil.which("xdg-open") or shutil.which("steam")
    if not opener:
        raise RuntimeError(f"couldn't find xdg-open or steam - open Steam and launch app {m['steam_appid']}")
    subprocess.Popen([opener, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    log("launching through Steam")


BEPINEX_OPT = 'WINEDLLOVERRIDES="winhttp=n,b" %command%'


def launch_thunderstore(m, rec):
    launch_steam(m, rec)
    note = ("One-time setup: in Steam, right-click the game > Properties > Launch Options and paste "
            "this, or the mods won't load under Proton.")
    log(f"{note}  {BEPINEX_OPT}")
    return {"msg": note, "copy": BEPINEX_OPT}


# ------------------------------------------------------- export / import
# a mashup is a .json recipe. a .gloop bundle is a zip: mashup.json + files/ with the mods packed in,
# so it installs the exact same files on someone else's PC (and works offline for the mods).

def bundle_dir(m):
    return MASHUP_DIR / f"{m['id']}.files"


def safe_join(base, rel):
    p = (base / rel).resolve()
    if base.resolve() not in p.parents:
        raise RuntimeError(f"blocked sketchy path in bundle: {rel}")
    return p


def downloads_dir():
    try:
        d = subprocess.run(["xdg-user-dir", "DOWNLOAD"], capture_output=True, text=True).stdout.strip()
        if d and d != str(Path.home()):
            return Path(d)
    except OSError:
        pass
    return Path.home() / "Downloads"


def clean_manifest(m):
    return {k: v for k, v in m.items() if not k.startswith("_")}


def do_export(mid, bundle=False, out=None):
    m = clean_manifest(get(mid))
    out = Path(out) if out else downloads_dir() / f"{mid}.{'gloop' if bundle else 'json'}"
    out.parent.mkdir(parents=True, exist_ok=True)
    if not bundle:
        out.write_text(json.dumps(m, indent=2))
        log(f"exported the recipe to {out}")
        return out
    log(f"packing {m['name']} into a bundle...")
    DATA.mkdir(parents=True, exist_ok=True)
    tmp_out = out.with_name(out.name + ".part")
    with tempfile.TemporaryDirectory(dir=DATA) as tmp, zipfile.ZipFile(tmp_out, "w", zipfile.ZIP_DEFLATED) as z:
        files = []   # (path on disk, name in bundle)
        if m["type"] == "minecraft":
            if m.get("bundled_mods"):
                files += [(safe_join(bundle_dir(m), r), r) for r in m["bundled_mods"]]
            else:
                game = mc_game_version(m)
                m["minecraft_version"] = game   # pin it, so the packed mods match the game
                for f in mc_resolve(m.get("mods", []), game):
                    dst = Path(tmp) / f["filename"]
                    download(f["url"], dst, sha512=f["sha512"])
                    files.append((dst, f"files/{f['filename']}"))
                    log(f"  + {f['filename']}")
                m["bundled_mods"] = [n for _, n in files]
        elif m["type"] == "steam":
            for i, f in enumerate(m["files"]):
                if f.get("bundled"):
                    files.append((safe_join(bundle_dir(m), f["bundled"]), f["bundled"]))
                    continue
                src = Path(os.path.expanduser(f["path"])) if f.get("path") else Path(tmp) / f"dl{i}"
                if f.get("path") and not src.is_file():
                    raise RuntimeError(f"can't pack {src}, it isn't there")
                if not f.get("path"):
                    download(f["url"], src, sha256=f.get("sha256"))
                name = f"files/{i}-{Path(f.get('path') or urllib.parse.urlparse(f['url']).path).name or 'file'}"
                files.append((src, name))
                for k in ("url", "path"):
                    f.pop(k, None)
                f["bundled"] = name
        else:   # thunderstore: pack the exact package zips
            pk = []
            for p in ts_resolve(m["packages"]):
                dst = Path(tmp) / f"{p['full']}.zip"
                download(p["url"], dst)
                files.append((dst, f"files/{p['full']}.zip"))
                pk.append(p["full"])
                log(f"  + {p['full']} {p['ver']}")
            m["bundled_packages"] = [n for _, n in files]
        for src, name in files:
            z.write(src, name)
        z.writestr("mashup.json", json.dumps(m, indent=2))
    tmp_out.replace(out)
    log(f"exported the bundle to {out} ({out.stat().st_size // 1024} KB)")
    return out


def do_import_bundle(path):
    with zipfile.ZipFile(path) as z:
        try:
            m = validate(json.loads(z.read("mashup.json")))
        except KeyError:
            raise ValueError("that .gloop file has no mashup.json inside")
        bdir = bundle_dir(m)
        shutil.rmtree(bdir, ignore_errors=True)
        bdir.mkdir(parents=True)
        for info in z.infolist():
            if info.is_dir() or not info.filename.startswith("files/"):
                continue
            dst = safe_join(bdir, info.filename)
            dst.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(dst, "wb") as out:
                shutil.copyfileobj(src, out)
    (MASHUP_DIR / f"{m['id']}.json").write_text(json.dumps(m, indent=2))
    log(f"imported bundle '{m['id']}' - run `gloop play {m['id']}`")
    return m


# ------------------------------------------------------------- actions

INSTALLERS = {"minecraft": install_minecraft, "steam": install_steam, "thunderstore": install_thunderstore}
UNINSTALLERS = {"minecraft": uninstall_minecraft, "steam": uninstall_steam, "thunderstore": uninstall_steam}
LAUNCHERS = {"minecraft": launch_minecraft, "steam": launch_steam, "thunderstore": launch_thunderstore}


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
    if m["type"] != "minecraft":
        for oid, o in state["installed"].items():
            if o.get("appid") == m["steam_appid"]:
                raise RuntimeError(f"'{oid}' is already modding that game. uninstall it first so they don't clash")
    log(f"installing {m['name']}...")
    rec = INSTALLERS[m["type"]](m)
    state["installed"][mid] = rec
    save_state(state)
    log(f"{m['name']} installed")
    return m, rec


def do_launch(mid):
    m, rec = do_install(mid)
    note = LAUNCHERS[m["type"]](m, rec) or {}
    if note.get("save"):            # the launcher changed the install record (e.g. made a Prism instance)
        state = load_state()
        state["installed"][mid] = rec
        save_state(state)
    return note


def do_play(mid):
    do_launch(mid)


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
    if not re.match(r"^https?://", src) and zipfile.is_zipfile(src):
        return do_import_bundle(src)
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

Thunderstore mashup (Lethal Company, R.E.P.O., Valheim, Risk of Rain 2, and more):
{"id": "lowercase-with-dashes", "name": "Cool Name", "type": "thunderstore",
 "description": "one sentence",
 "games": [{"name": "Lethal Company", "steam_appid": 1966720}, {"name": "Minecraft"}],
 "steam_appid": 1966720,
 "packages": ["Owner-ModName"]}

Any other Steam game (direct files, or a zip the user downloads from Nexus etc):
{"id": "lowercase-with-dashes", "name": "Cool Name", "type": "steam",
 "description": "one sentence",
 "games": [{"name": "Game", "steam_appid": 123}, {"name": "Other Game"}],
 "steam_appid": 123,
 "files": [{"url": "https://direct-download-link", "dest": "path/inside/game/folder",
            "sha256": "hash of the file"},
           {"path": "~/Downloads/the-mod.zip", "dest": "folder/in/game", "extract": true}]}

Rules:
- A mashup MIXES two games: "games" lists the game you play AND the game it brings in.
- Only use Modrinth slugs for real Fabric mods (check modrinth.com). Always include fabric-api.
  Pick a minecraft_version the mods actually support. Dependencies get installed for you.
- Only use Thunderstore packages that really exist (thunderstore.io). BepInEx + deps get added for you.
- Nexus mods need a login, so use "path" + "extract" and tell me which file to download.
- Steam "dest" paths are relative to the game's install folder and can't leave it.
- Only link files from places the mod author publishes them, and include sha256.
- Keep "id" short, lowercase, letters/numbers/dashes.

What I want:
"""


GAMES = [
    {"name": "Minecraft"}, {"name": "Lethal Company", "steam_appid": 1966720},
    {"name": "R.E.P.O.", "steam_appid": 3241660}, {"name": "Portal", "steam_appid": 400},
    {"name": "Portal 2", "steam_appid": 620}, {"name": "Half-Life 2", "steam_appid": 220},
    {"name": "Super Mario 64"}, {"name": "Skyrim", "steam_appid": 489830},
    {"name": "Elden Ring", "steam_appid": 1245620}, {"name": "Valheim", "steam_appid": 892970},
    {"name": "Risk of Rain 2", "steam_appid": 632360}, {"name": "Terraria", "steam_appid": 105600},
    {"name": "Content Warning", "steam_appid": 2881650},
]


def steam_cover(appid):
    return f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg"


def game_list():
    out, seen = [], set()
    extra = [g for m in load_mashups().values() for g in m.get("games", [])]
    for g in GAMES + extra:
        key = g["name"].lower()
        if key in seen:
            continue
        seen.add(key)
        a = g.get("steam_appid")
        out.append({"name": g["name"], "cover": steam_cover(a) if isinstance(a, int) else None})
    return out


def web_log(line):
    LOGS.append(line)


def cover_for(m):
    if m.get("cover"):
        return m["cover"]
    appids = [g.get("steam_appid") for g in m.get("games", []) if isinstance(g, dict)]
    appids.append(m.get("steam_appid"))
    for a in appids:
        if isinstance(a, int):
            return steam_cover(a)
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
                note = do_launch(mid)
                JOBS[mid] = {"state": "launched", "msg": note.get("msg", ""), "copy": note.get("copy", "")}
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
        if u.path == "/api/games":
            return self.send(200, {"games": game_list()})
        if u.path == "/api/agent":
            return self.send(200, AGENT_INSTRUCTIONS, "text/plain")
        self.send(404, {"error": "not found"})

    def do_POST(self):
        # every action needs the per-session token, so random websites can't poke gloop
        if not self.host_ok() or self.headers.get("X-Gloop-Token") != TOKEN:
            return self.send(403, {"error": "forbidden"})
        n = int(self.headers.get("Content-Length") or 0)
        parts = urllib.parse.urlparse(self.path).path.strip("/").split("/")
        if parts == ["api", "import"]:   # a .json or .gloop file, sent as raw bytes
            if n > 1024 * 1024 * 1024:
                return self.send(413, {"error": "that file is over 1 GB"})
            DATA.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=DATA, suffix=".import", delete=False) as tf:
                left = n
                while left > 0:
                    chunk = self.rfile.read(min(left, 1 << 20))
                    if not chunk:
                        break
                    tf.write(chunk)
                    left -= len(chunk)
            try:
                if zipfile.is_zipfile(tf.name):
                    m = do_import_bundle(tf.name)
                else:
                    m = validate(json.loads(Path(tf.name).read_text()))
                    MASHUP_DIR.mkdir(parents=True, exist_ok=True)
                    (MASHUP_DIR / f"{m['id']}.json").write_text(json.dumps(m, indent=2))
                    log(f"imported '{m['id']}'")
                return self.send(200, {"ok": True, "id": m["id"]})
            except (ValueError, RuntimeError, json.JSONDecodeError, zipfile.BadZipFile, UnicodeDecodeError) as e:
                return self.send(400, {"error": f"couldn't import that: {e}"})
            finally:
                os.unlink(tf.name)
        if n > 1_000_000:
            return self.send(413, {"error": "too big"})
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self.send(400, {"error": "bad json"})
        try:
            if len(parts) == 3 and parts[:2] == ["api", "export"]:
                mid = urllib.parse.unquote(parts[2])
                out = do_export(mid, bool(body.get("bundle")))
                return self.send(200, {"ok": True, "path": str(out)})
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
.expmenu{display:flex;flex-direction:column;gap:6px;margin-top:6px}
.expmenu .ghost{text-align:left;font-size:13px;padding:8px 10px}
.expmenu small{color:var(--dim);display:block;font-size:12px}
.note{background:#b6ff3b14;border:1px solid #b6ff3b40;border-radius:10px;padding:8px 10px;font-size:13px;color:var(--ink)}
.note code{display:block;margin:6px 0;font-size:12px;word-break:break-all;color:var(--goo)}
.mix{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin:22px 0 8px}
.slot{flex:1 1 140px;max-width:240px;min-width:0;aspect-ratio:460/215;border-radius:14px;border:2px dashed #ffffff33;display:flex;align-items:flex-end;padding:10px;font-weight:800;background:#17141f center/cover no-repeat;cursor:pointer;position:relative;overflow:hidden}
.slot.full{border:2px solid var(--goo)}
.slot span{position:relative;z-index:1;text-shadow:0 1px 4px #000}
.slot.full::before{content:"";position:absolute;inset:0;background:linear-gradient(transparent 40%,#000a)}
.plus{font-size:34px;font-weight:900;color:var(--goo)}
.mixbtn{padding:14px 26px;font-size:17px;flex:0 0 auto}
@media(max-width:560px){.mix .plus{flex:0 0 auto}.mixbtn{flex:1 1 100%}.gtiles{grid-template-columns:repeat(2,1fr)}header nav button{padding:8px 9px}.logbtn{display:none}}
.gtiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:10px;margin-top:14px}
.gtile{aspect-ratio:460/215;border-radius:10px;background:#221d30 center/cover no-repeat;border:2px solid transparent;cursor:pointer;display:flex;align-items:flex-end;padding:6px 8px;font-size:12px;font-weight:700;position:relative;overflow:hidden;color:#fff}
.gtile::before{content:"";position:absolute;inset:0;background:linear-gradient(transparent 35%,#000c)}
.gtile span{position:relative}
.gtile:hover{border-color:#b6ff3b88}.gtile.on{border-color:var(--goo)}
.gtile.mc,.slot.mc{background:linear-gradient(#5fae3b 0 30%,#4a8a2e 30% 34%,#8b5a2b 34%)}
.gtile.none,.slot.none{background:radial-gradient(circle at 30% 30%,#4a3d6b,#17141f)}
.sect{margin:30px 0 12px;font-size:20px;font-weight:800}
#mixres{margin-top:18px}
.empty{color:var(--dim);text-align:center;padding:40px 0;grid-column:1/-1}
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
  <h1>Mix any game <span>with any game.</span></h1>
  <p>Pick two games and hit Mix. Gloop grabs what it needs, sets it up and launches it. Uninstall puts every file back.</p>
  <div class="mix">
    <div class="slot none" id="slot0"><span>Pick a game</span></div>
    <div class="plus">+</div>
    <div class="slot none" id="slot1"><span>Pick a game</span></div>
    <button class="play mixbtn" id="mixbtn">Mix it</button>
  </div>
  <div class="gtiles" id="gtiles"></div>
  <div id="mixres"></div>
</section>
<main>
  <div class="sect" id="gridtitle">All mashups</div>
  <div class="grid" id="grid"></div>
  <div id="create" hidden>
    <div class="two">
      <div class="panel">
        <h2>Make one yourself</h2><p>Fill this in and it shows up in Discover.</p>
        <label>Name</label><input id="c-name" placeholder="Speedy Skyblock">
        <label>Description</label><input id="c-desc" placeholder="What it plays like">
        <label>Type</label>
        <select id="c-type"><option value="minecraft">Minecraft (Fabric mods)</option><option value="thunderstore">Thunderstore (Lethal Company, R.E.P.O., Valheim…)</option><option value="steam">Any Steam game (files or a zip)</option></select>
        <label>Game it mixes in (optional)</label><input id="c-with" placeholder="Portal">
        <div id="c-mc">
          <label>Minecraft version</label><input id="c-ver" value="latest">
          <label>Modrinth mod slugs (comma or new line)</label><textarea id="c-mods">fabric-api</textarea>
        </div>
        <div id="c-steam" hidden>
          <label>Game name</label><input id="c-game" placeholder="Lethal Company">
          <label>Steam app ID (from the store page URL)</label><input id="c-appid" placeholder="1966720">
          <div id="c-tsbox"><label>Thunderstore packages, Owner-ModName (comma or new line)</label><textarea id="c-pkgs" placeholder="DalekMC-MinecraftMoon"></textarea></div>
          <div id="c-filebox"><label>One per line: link or ~/path | folder/in/game | sha256 (optional). Zips get unpacked.</label><textarea id="c-files" placeholder="~/Downloads/cool-nexus-mod.zip | Data"></textarea></div>
        </div>
        <div class="row"><button class="play" id="c-save">Create mashup</button></div>
      </div>
      <div class="panel">
        <h2>Import a mashup</h2><p>Got a .json or .gloop file from someone? Drop it in.</p>
        <div class="row"><label class="ghost" style="margin:0;cursor:pointer">Choose file…<input type="file" id="c-file" accept=".json,.gloop,application/json,application/zip" hidden></label></div>
        <h2 style="margin-top:22px">Build it with your AI</h2><p>Copy the instructions, paste them into Claude (or any AI) with your idea, then paste back the JSON it gives you.</p>
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
let tab="discover",data=[],logNext=0,games=[],pick=[null,null];const openExport=new Set();
const $=s=>document.querySelector(s);
const LABEL={idle:"▶ Play",installing:"Installing…",starting:"Starting…",launched:"✓ Launched — play again",removing:"Removing…",error:"Retry"};
function toast(t){const e=$("#toast");e.textContent=t;e.classList.add("show");clearTimeout(e._t);e._t=setTimeout(()=>e.classList.remove("show"),2600)}
function mk(tag,cls,txt){const e=document.createElement(tag);if(cls)e.className=cls;if(txt!=null)e.textContent=txt;return e}
async function post(url,body){const r=await fetch(url,{method:"POST",headers:{"X-Gloop-Token":TOKEN,"Content-Type":"application/json"},body:JSON.stringify(body||{})});let j={};try{j=await r.json()}catch(e){}if(!r.ok)throw new Error(j.error||("HTTP "+r.status));return j}
async function load(){try{data=(await (await fetch("/api/mashups")).json()).mashups;render()}catch(e){}}
const TYPE={minecraft:"Minecraft",thunderstore:"Thunderstore",steam:"Steam"};
function setCover(el,cover,name){el.classList.remove("mc","none");el.style.backgroundImage="";if(cover)el.style.backgroundImage=`url("${encodeURI(cover)}")`;else el.classList.add(name&&name.toLowerCase()==="minecraft"?"mc":"none")}
function card(m){
  const c=mk("div","card"),cv=mk("div","cover");
  if(m.cover){cv.style.backgroundImage=`url("${encodeURI(m.cover)}")`}else cv.classList.add(m.type==="minecraft"?"mc":"none");
  const b=mk("span","badge"+(m.installed?" inst":""),m.installed?"Installed":TYPE[m.type]);cv.append(b);
  const body=mk("div","body");
  body.append(mk("div","title",m.name));
  if(m.games.length)body.append(mk("div","games",m.games.join(" + ")));
  body.append(mk("div","desc",m.description||""));
  const st=m.job.state,row=mk("div","row"),p=mk("button","play"+(st==="error"?" err":""),LABEL[st]||"▶ Play");
  if(["installing","starting","removing"].includes(st))p.disabled=true;
  p.onclick=()=>act(m.id,"play");row.append(p);
  if(m.installed){const u=mk("button","ghost","Uninstall");u.onclick=()=>{if(confirm(`Uninstall ${m.name}? Every file goes back how it was.`))act(m.id,"uninstall")};row.append(u)}
  const ex=mk("button","ghost","⤓");ex.title="Export";ex.setAttribute("aria-label","Export");row.append(ex);
  const menu=mk("div","expmenu");menu.hidden=!openExport.has(m.id);
  ex.onclick=()=>{menu.hidden=!menu.hidden;menu.hidden?openExport.delete(m.id):openExport.add(m.id)};
  [["Export recipe (.json)","Small. Mods download fresh on their PC.",false],["Export bundle (.gloop)","Mods packed inside. Bigger, but exact.",true]].forEach(([t,d,b])=>{
    const o=mk("button","ghost",t);o.append(mk("small",null,d));o.onclick=()=>exportMashup(m.id,b,o);menu.append(o)});
  body.append(row,menu);
  if(st==="error"&&m.job.msg)body.append(mk("div","err-msg",m.job.msg));
  if(st==="launched"&&m.job.msg){const n=mk("div","note",m.job.msg);
    if(m.job.copy){n.append(mk("code",null,m.job.copy));const cb=mk("button","ghost","Copy");cb.onclick=()=>copy(m.job.copy);n.append(cb)}
    body.append(n)}
  c.append(cv,body);return c}
async function exportMashup(id,bundle,btn){btn.disabled=true;toast(bundle?"Packing the bundle… 📦":"Saving…");
  try{const j=await post(`/api/export/${encodeURIComponent(id)}`,{bundle});toast(`Saved to ${j.path} ✅`)}catch(e){toast(e.message)}btn.disabled=false}
async function importFile(file){if(!file)return;toast(`Importing ${file.name}…`);
  try{const r=await fetch("/api/import",{method:"POST",headers:{"X-Gloop-Token":TOKEN},body:file});const j=await r.json();if(!r.ok)throw new Error(j.error);
    toast(`Added ${j.id} ✨`);await load();loadGames();document.querySelector('nav button[data-tab="discover"]').click()}catch(e){toast(e.message)}}
async function copy(t){try{await navigator.clipboard.writeText(t);toast("Copied 📋")}catch(e){prompt("Copy this:",t)}}
function matches(m){const g=m.games.map(x=>x.toLowerCase());return pick.every(p=>!p||g.includes(p.name.toLowerCase()))}
function renderMix(){
  pick.forEach((p,i)=>{const s=$("#slot"+i);setCover(s,p&&p.cover,p&&p.name);s.classList.toggle("full",!!p);s.firstChild.textContent=p?p.name:"Pick a game"});
  const gt=$("#gtiles");gt.replaceChildren();
  games.forEach(g=>{const t=mk("div","gtile");setCover(t,g.cover,g.name);t.append(mk("span",null,g.name));
    if(pick.some(p=>p&&p.name===g.name))t.classList.add("on");
    t.onclick=()=>{const i=pick.findIndex(p=>p&&p.name===g.name);if(i>=0)pick[i]=null;else{const e=pick.indexOf(null);pick[e<0?1:e]=g}renderMix();render()};gt.append(t)})}
function render(){
  const g=$("#grid");$("#create").hidden=tab!=="create";g.hidden=tab==="create";$("#hero").hidden=tab!=="discover";$("#gridtitle").hidden=tab==="create";
  if(tab==="create")return;
  const filt=tab==="discover"&&(pick[0]||pick[1]);
  $("#gridtitle").textContent=tab==="mine"?"My mashups":filt?`Mashups with ${pick.filter(Boolean).map(p=>p.name).join(" + ")}`:"All mashups";
  if(filt){const list=data.filter(matches);g.replaceChildren();
    if(!list.length){const e=mk("div","empty",`No mashup mixes ${pick.filter(Boolean).map(p=>p.name).join(" + ")} yet. `);
      if(pick[0]&&pick[1]){const b=mk("button","play","✨ Build this mix with your AI");b.style.marginTop="12px";b.onclick=mixAI;e.append(mk("br"),b)}
      g.append(e)}
    else list.forEach(m=>g.append(card(m)));return}
  const list=tab==="mine"?data.filter(m=>m.installed):data;g.replaceChildren();
  if(!list.length){g.append(mk("div","empty",tab==="mine"?"Nothing installed yet. Hit Play on something in Discover.":"No mashups yet. Make one in Create."));return}
  list.forEach(m=>g.append(card(m)))}
async function act(id,a){try{await post(`/api/${a}/${encodeURIComponent(id)}`);load()}catch(e){toast(e.message)}}
async function logs(){try{const j=await (await fetch("/api/logs?since="+logNext)).json();if(j.lines.length){const pre=$("#logtext");pre.textContent+=j.lines.join("\n")+"\n";pre.scrollTop=pre.scrollHeight}logNext=j.next}catch(e){}}
document.querySelectorAll("nav button").forEach(b=>b.onclick=()=>{document.querySelectorAll("nav button").forEach(x=>x.classList.toggle("on",x===b));tab=b.dataset.tab;render()});
$("#logbtn").onclick=()=>$("#logs").classList.toggle("open");
$("#c-type").onchange=e=>{const v=e.target.value;$("#c-mc").hidden=v!=="minecraft";$("#c-steam").hidden=v==="minecraft";$("#c-tsbox").hidden=v!=="thunderstore";$("#c-filebox").hidden=v!=="steam"};
async function agentText(){return (await fetch("/api/agent")).text()}
async function mixAI(){const [a,b]=pick;const t=(await agentText())+`Mix ${a.name} and ${b.name}. Put both in "games".`;
  document.querySelector('nav button[data-tab="create"]').click();
  try{await navigator.clipboard.writeText(t);toast(`Copied! Paste it into your AI, then paste the JSON here 📋`)}catch(e){$("#c-json").value=t;toast("Couldn't copy, it's in the box")}}
$("#slot0").onclick=()=>{pick[0]=null;renderMix();render()};$("#slot1").onclick=()=>{pick[1]=null;renderMix();render()};
$("#mixbtn").onclick=()=>{if(!pick[0]||!pick[1])return toast("pick two games first 🎮");render();$("#gridtitle").scrollIntoView({behavior:"smooth"})};
async function loadGames(){try{games=(await (await fetch("/api/games")).json()).games;renderMix()}catch(e){}}
const slug=s=>s.toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-+|-+$/g,"").slice(0,60);
async function create(m){try{const j=await post("/api/create",m);toast(`Added ${j.id} ✨`);await load();loadGames();document.querySelector('nav button[data-tab="discover"]').click()}catch(e){toast(e.message)}}
$("#c-save").onclick=()=>{
  const name=$("#c-name").value.trim();if(!name)return toast("give it a name first");
  const m={id:slug(name),name,description:$("#c-desc").value.trim(),type:$("#c-type").value};
  const w=$("#c-with").value.trim();
  if(m.type==="minecraft"){m.games=[{name:"Minecraft"}];m.minecraft_version=$("#c-ver").value.trim()||"latest";m.mods=$("#c-mods").value.split(/[\s,]+/).filter(Boolean)}
  else{m.steam_appid=parseInt($("#c-appid").value,10);m.games=[{name:$("#c-game").value.trim()||name,steam_appid:m.steam_appid}];
    if(m.type==="thunderstore")m.packages=$("#c-pkgs").value.split(/[\s,]+/).filter(Boolean);
    else m.files=$("#c-files").value.split("\n").map(l=>l.split("|").map(s=>s.trim())).filter(p=>p[0]).map(([src,dest,sha256])=>{
      const f=/^https?:/.test(src)?{url:src}:{path:src};f.dest=dest||"";if(sha256)f.sha256=sha256;if(/\.zip$/i.test(src))f.extract=true;return f})}
  if(w)m.games.push({name:w});
  create(m)};
$("#c-copy").onclick=async()=>{const t=await agentText();try{await navigator.clipboard.writeText(t);toast("Copied — paste it into your AI 📋")}catch(e){$("#c-json").value=t;toast("Couldn't copy, it's in the box")}};
$("#c-import").onclick=()=>{let m;try{m=JSON.parse($("#c-json").value.replace(/^```(json)?|```$/gm,""))}catch(e){return toast("that JSON is busted")}create(m)};
$("#c-type").onchange({target:$("#c-type")});
$("#c-file").onchange=e=>{importFile(e.target.files[0]);e.target.value=""};
document.addEventListener("dragover",e=>e.preventDefault());
document.addEventListener("drop",e=>{e.preventDefault();const f=e.dataTransfer.files[0];if(f&&/\.(json|gloop)$/i.test(f.name))importFile(f)});
load();loadGames();logs();setInterval(load,1500);setInterval(logs,1500);
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
    ex = sub.add_parser("export", help="save a mashup as a .json recipe, or --bundle for a .gloop with the mods inside")
    ex.add_argument("id")
    ex.add_argument("--bundle", action="store_true")
    ex.add_argument("-o", "--output")
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
            do_add(a.source)
            return None
        if a.cmd == "export":
            return do_export(a.id, a.bundle, a.output) and None
        {"play": do_play, "install": do_install, "uninstall": do_uninstall}[a.cmd](a.id)
    except (RuntimeError, ValueError, OSError, urllib.error.URLError) as e:
        log(f"error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main() or 0)

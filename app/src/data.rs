//! what GURT knows: read straight from gurt's own files (the same as `gurt-gui.py`'s state() used to)
use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::OnceLock;

pub static GURT: OnceLock<String> = OnceLock::new();
pub fn gurt() -> &'static str {
    GURT.get().map(|s| s.as_str()).unwrap_or("gurt")
}

pub fn home() -> PathBuf {
    std::env::var_os("HOME").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("/"))
}
pub fn config_dir() -> PathBuf {
    std::env::var_os("XDG_CONFIG_HOME").map(PathBuf::from).filter(|p| p.is_absolute()).unwrap_or_else(|| home().join(".config"))
}
pub fn state_dir() -> PathBuf {
    std::env::var_os("XDG_STATE_HOME").map(PathBuf::from).filter(|p| p.is_absolute()).unwrap_or_else(|| home().join(".local/state"))
}

/// run gurt quietly (no colours) and hand back what it printed
pub fn gurt_out(args: &[&str]) -> String {
    Command::new(gurt())
        .args(args)
        .env("NO_COLOR", "1")
        .env("GURT_PLAIN", "1")
        .stdin(Stdio::null())
        .stderr(Stdio::null())
        .output()
        .map(|o| String::from_utf8_lossy(&o.stdout).into_owned())
        .unwrap_or_default()
}
pub fn gurt_out_all(args: &[&str]) -> String {
    Command::new(gurt())
        .args(args)
        .env("NO_COLOR", "1")
        .env("GURT_PLAIN", "1")
        .stdin(Stdio::null())
        .output()
        .map(|o| strip_ansi(&(String::from_utf8_lossy(&o.stdout).into_owned() + &String::from_utf8_lossy(&o.stderr))))
        .unwrap_or_default()
}

pub fn strip_ansi(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut it = s.chars().peekable();
    while let Some(c) = it.next() {
        if c == '\x1b' && it.peek() == Some(&'[') {
            it.next();
            for d in it.by_ref() {
                if d.is_ascii_alphabetic() {
                    break;
                }
            }
        } else if c != '\r' {
            out.push(c);
        }
    }
    out
}

/// gurt __paths: version, repo, db, cache, pm, wsl…
pub fn paths() -> HashMap<String, String> {
    gurt_out(&["__paths"])
        .lines()
        .filter_map(|l| l.split_once('=').map(|(a, b)| (a.to_string(), b.to_string())))
        .collect()
}

/// a `key = value` info file (.gurtinfo, a db entry's info). alias / depends / arch / source can repeat
pub fn kv(path: &Path) -> HashMap<String, Vec<String>> {
    let mut out: HashMap<String, Vec<String>> = HashMap::new();
    if let Ok(s) = fs::read_to_string(path) {
        for line in s.lines() {
            if let Some((k, v)) = line.split_once(" = ") {
                out.entry(k.to_string()).or_default().push(v.to_string());
            }
        }
    }
    out
}
fn one(m: &HashMap<String, Vec<String>>, k: &str) -> String {
    m.get(k).and_then(|v| v.last()).cloned().unwrap_or_default()
}

// ── the app's own settings: ~/.config/gurt/gui.json ──
pub fn conf_path() -> PathBuf {
    config_dir().join("gurt/gui.json")
}
pub fn conf() -> serde_json::Map<String, serde_json::Value> {
    fs::read_to_string(conf_path())
        .ok()
        .and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok())
        .and_then(|v| v.as_object().cloned())
        .unwrap_or_default()
}
pub fn conf_str(k: &str) -> Option<String> {
    conf().get(k).and_then(|v| v.as_str()).map(str::to_string)
}
pub fn conf_bool(k: &str, def: bool) -> bool {
    conf().get(k).and_then(|v| v.as_bool()).unwrap_or(def)
}
pub fn save_conf(k: &str, v: serde_json::Value) {
    let mut c = conf();
    c.insert(k.to_string(), v);
    let p = conf_path();
    let _ = fs::create_dir_all(p.parent().unwrap());
    let _ = fs::write(&p, serde_json::Value::Object(c).to_string());
}

// ── free software or not: the same rule as gurt's foss_class and the site's fossOf ──
pub fn foss_class(lic: &str) -> &'static str {
    let l = lic.trim().to_lowercase();
    if l.is_empty() || l.starts_with("see ") || l == "unknown" || l == "other" {
        return "unknown";
    }
    let words: Vec<&str> = l.split(|c: char| c == '-' || c == ' ').collect();
    let closed = l.contains("proprietary")
        || l == "custom"
        || (l.contains("licenseref-") && !l.contains("licenseref-kde-accepted"))
        || l.contains("sspl")
        || words.iter().any(|w| *w == "nc" || *w == "nd")
        || l.contains("sul-1")
        || l.contains("freeware")
        || l.contains("shareware");
    if closed { "closed" } else { "foss" }
}

pub fn foss_strict() -> bool {
    match std::env::var("GURT_FOSS") {
        Ok(v) => v == "on",
        Err(_) => fs::read_to_string(config_dir().join("gurt/foss")).map(|s| s.trim() == "on").unwrap_or(false),
    }
}

#[derive(Clone, Debug, Default)]
pub struct Pkg {
    pub name: String,
    pub ver: String,
    pub desc: String,
    pub alias: Vec<String>,
    pub ikey: String,     // where it lands once installed (flatpak:<id>, <repo>:<pkg>, or its own name)
    pub flatpak: String,  // its Flathub id, when it comes from Flathub
    pub vpkg: String,
    pub vtype: String,    // flatpak | snap | repo | ""
    pub icon: String,     // a logo URL (Flathub's, or the recipe's icon=)
    pub category: String,
    pub trust: String,
    pub license: String,
    pub foss: &'static str,
    pub url: String,
    #[allow(dead_code)] // DIRT + Main GURT recipes carry it; the app doesn't show it yet
    pub maintainer: String,
    pub search: String,   // name + desc + aliases, lowercase, for filtering
}

#[derive(Clone, Debug, Default)]
pub struct Installed {
    pub key: String,
    pub via: String,
    pub spec: String,
    pub name: String,
    pub src: String,
    pub ver: String,
    pub desc: String,
    pub reason: String,
    pub held: bool,
}

#[derive(Clone, Debug, Default)]
pub struct GhApp {
    pub cat: String,
    pub repo: String,
    pub name: String,
    pub desc: String,
}

#[derive(Clone, Debug, Default)]
pub struct State {
    pub version: String,
    pub pm: String,
    pub dirt: bool,
    pub wsl: bool,
    pub cros: bool,
    pub nix: bool,
    pub hook: bool,
    pub dev: String,
    pub fossonly: bool,
    pub notify: bool,
    pub main: Vec<Pkg>,
    pub dirtpkgs: Vec<Pkg>,
    pub installed: Vec<Installed>,
    pub outside: HashMap<String, String>, // Main GURT apps on this computer, not from gurt → how
    pub vibes: HashMap<String, Vec<String>>,
    pub packs: Vec<Pack>,
    pub ghonly: Vec<GhApp>,
    pub cache: String,
    #[allow(dead_code)]
    pub repo: String,
    pub unlocks: HashSet<String>, // what GURT keys unlocked: app:… skin:… track:… ach:…
    pub all_unlocked: bool,       // 🧪 dev builds
}

pub const FLATHUB_ICON: &str = "https://dl.flathub.org/repo/appstream/x86_64/icons/128x128/";

fn recipe_trust(info: &HashMap<String, Vec<String>>) -> String {
    match one(info, "via_type").as_str() {
        "flatpak" => return "flathub".into(),
        "snap" => return "snap".into(),
        _ => {}
    }
    if !one(info, "via_repo").is_empty() {
        return "official".into();
    }
    let src = info.get("source").map(|v| v.join(" ")).unwrap_or_default();
    if src.contains("git+") {
        "source".into()
    } else if src.contains("://") {
        "prebuilt".into()
    } else {
        "gurt".into()
    }
}

fn read_tree(dir: &Path, full: bool, unlocked: &dyn Fn(&str) -> bool) -> Vec<Pkg> {
    let mut names: Vec<String> = fs::read_dir(dir)
        .map(|rd| rd.filter_map(|e| e.ok()).map(|e| e.file_name().to_string_lossy().into_owned()).collect())
        .unwrap_or_default();
    names.sort();
    let mut out = Vec::new();
    for name in names {
        let info = kv(&dir.join(&name).join(".gurtinfo"));
        // hidden + secret recipes stay out of sight, unless a GURT key unlocked them
        if info.is_empty() || ((one(&info, "hidden") == "true" || one(&info, "secret") == "true") && !unlocked(&format!("app:{name}"))) {
            continue;
        }
        let (vt, vp, vr) = (one(&info, "via_type"), one(&info, "via_pkg"), one(&info, "via_repo"));
        let pname = { let n = one(&info, "pkgname"); if n.is_empty() { name.clone() } else { n } };
        let ikey = if vt == "flatpak" || vt == "snap" {
            format!("{vt}:{vp}")
        } else if !vr.is_empty() {
            format!("{vr}:{}", if vp.is_empty() { &name } else { &vp })
        } else {
            name.clone()
        };
        let mut icon = one(&info, "icon");
        if icon.is_empty() && vt == "flatpak" && !vp.is_empty() {
            icon = format!("{FLATHUB_ICON}{vp}.png");
        }
        let alias = info.get("alias").cloned().unwrap_or_default();
        let desc = one(&info, "pkgdesc");
        let ver = if full && !vr.is_empty() { "latest".to_string() } else { format!("{}-{}", one(&info, "pkgver"), one(&info, "pkgrel")) };
        let license = one(&info, "license");
        let search = format!("{} {} {}", pname, desc, alias.join(" ")).to_lowercase();
        out.push(Pkg {
            foss: foss_class(&license),
            trust: if full { recipe_trust(&info) } else { "dirt".into() },
            vtype: if !vt.is_empty() { vt.clone() } else if !vr.is_empty() { "repo".into() } else { String::new() },
            flatpak: if vt == "flatpak" { vp.clone() } else { String::new() },
            name: pname, ver, desc, alias, ikey, vpkg: vp, icon, license, search,
            category: one(&info, "category"), url: one(&info, "url"), maintainer: one(&info, "maintainer"),
        });
    }
    out
}

pub fn ghonly(repo: &str) -> Vec<GhApp> {
    let mut cands = vec![PathBuf::from(repo).join("gh-only.map")];
    cands.extend(share_dirs().into_iter().map(|d| d.join("gh-only.map")));
    for f in cands {
        if let Ok(s) = fs::read_to_string(&f) {
            return s
                .lines()
                .filter(|l| !l.starts_with('#'))
                .filter_map(|l| {
                    let p: Vec<&str> = l.splitn(4, '|').collect();
                    (p.len() == 4).then(|| GhApp { cat: p[0].into(), repo: p[1].into(), name: p[2].into(), desc: p[3].into() })
                })
                .collect();
        }
    }
    Vec::new()
}

/// a package pack (packs.map): a bunch of Main GURT apps for one thing, installed together
#[derive(Clone, Debug)]
pub struct Pack {
    pub id: String,
    pub name: String,
    pub desc: String,
    pub apps: Vec<String>,
}
pub fn packs(repo: &str) -> Vec<Pack> {
    let mut cands = vec![PathBuf::from(repo).join("packs.map")];
    cands.extend(share_dirs().into_iter().map(|d| d.join("packs.map")));
    for f in cands {
        if let Ok(s) = fs::read_to_string(&f) {
            return s
                .lines()
                .filter(|l| !l.starts_with('#'))
                .filter_map(|l| {
                    let mut it = l.splitn(4, '|');
                    let (id, name, desc, apps) = (it.next()?, it.next()?, it.next()?, it.next()?);
                    Some(Pack { id: id.into(), name: name.into(), desc: desc.into(), apps: apps.split_whitespace().map(str::to_string).collect() })
                })
                .collect();
        }
    }
    Vec::new()
}

pub fn vibes(repo: &str) -> HashMap<String, Vec<String>> {
    let mut out = HashMap::new();
    let mut cands = vec![PathBuf::from(repo).join("vibes.map")];
    cands.extend(share_dirs().into_iter().map(|d| d.join("vibes.map")));
    for f in cands {
        if let Ok(s) = fs::read_to_string(&f) {
            for line in s.lines() {
                if line.starts_with('#') {
                    continue;
                }
                if let Some((keys, apps)) = line.split_once(':') {
                    let apps: Vec<String> = apps.split_whitespace().map(str::to_string).collect();
                    for k in keys.split('|') {
                        out.insert(k.trim().to_lowercase(), apps.clone());
                    }
                }
            }
            break;
        }
    }
    out
}

/// where gurt keeps its shared files (vibes.map, gh-only.map…), next to the gurt that's running us first
pub fn share_dirs() -> Vec<PathBuf> {
    let mut v = Vec::new();
    if let Ok(g) = which(gurt()).map(|p| fs::canonicalize(&p).unwrap_or(p)) {
        if let Some(d) = g.parent() {
            v.push(d.to_path_buf());
            v.push(d.join("../share/gurt"));
        }
    }
    v.push("/usr/local/share/gurt".into());
    v.push("/usr/share/gurt".into());
    v
}

pub fn which(cmd: &str) -> Result<PathBuf, ()> {
    if cmd.contains('/') {
        return if Path::new(cmd).exists() { Ok(cmd.into()) } else { Err(()) };
    }
    for d in std::env::var("PATH").unwrap_or_default().split(':') {
        let p = Path::new(d).join(cmd);
        if p.is_file() {
            return Ok(p);
        }
    }
    Err(())
}
pub fn has(cmd: &str) -> bool {
    which(cmd).is_ok()
}

pub fn notify_on() -> bool {
    if config_dir().join("systemd/user/gurt-notify.timer").exists() || config_dir().join("autostart/gurt-notify.desktop").exists() {
        return true;
    }
    Command::new("crontab").arg("-l").stderr(Stdio::null()).output().map(|o| String::from_utf8_lossy(&o.stdout).contains("gurt notify now")).unwrap_or(false)
}

// ── apps you got without gurt (your distro's package manager, flatpak, snap, an AppImage, /opt) still count ──
fn native_pkgs(pm: &str) -> HashSet<String> {
    let cmd: &[&str] = match pm {
        "zypper" | "dnf" | "yum" => &["rpm", "-qa", "--qf", "%{NAME}\n"],
        "apt" => &["dpkg-query", "-W", "-f=${Package}\n"],
        "pacman" => &["pacman", "-Qq"],
        "apk" => &["apk", "info"],
        "xbps" => &["xbps-query", "-l"],
        "eopkg" => &["eopkg", "li"],
        // Gentoo: /var/db/pkg/<category>/<name>-<version>
        "emerge" => {
            let mut out = HashSet::new();
            for cat in fs::read_dir("/var/db/pkg").into_iter().flatten().flatten() {
                for p in fs::read_dir(cat.path()).into_iter().flatten().flatten() {
                    let b = p.file_name().to_string_lossy().to_string();
                    // name-1.2.3-r1 → name (the version starts at the first "-<digit>" that isn't part of the name)
                    let mut name = b.as_str();
                    for (i, _) in b.match_indices('-') {
                        if b[i + 1..].starts_with(|c: char| c.is_ascii_digit()) {
                            name = &b[..i];
                            break;
                        }
                    }
                    out.insert(name.to_lowercase());
                }
            }
            return out;
        }
        _ => return HashSet::new(),
    };
    let out = Command::new(cmd[0]).args(&cmd[1..]).stderr(Stdio::null()).output().map(|o| String::from_utf8_lossy(&o.stdout).into_owned()).unwrap_or_default();
    out.lines()
        .filter_map(|l| {
            let w: Vec<&str> = l.split_whitespace().collect();
            let n = if pm == "xbps" { w.get(1)? } else { w.first()? };
            let n = if pm == "xbps" { n.rsplit_once('-').map(|(a, _)| a).unwrap_or(n) } else { n };
            Some(n.to_lowercase())
        })
        .collect()
}

fn squash(s: &str) -> String {
    s.chars().filter(|c| c.is_ascii_alphanumeric()).collect::<String>().to_lowercase()
}

/// Obsidian-1.6.7.AppImage → obsidian
fn appimage_name(f: &str) -> String {
    let low = f.to_lowercase();
    let stem = &low[..low.len().saturating_sub(9)];
    let mut cut = stem.len();
    let b = stem.as_bytes();
    for i in 1..stem.len() {
        if matches!(b[i - 1], b'-' | b'_' | b' ' | b'.') {
            let rest = &stem[i..];
            if rest.starts_with(|c: char| c.is_ascii_digit())
                || (rest.starts_with('v') && rest[1..].starts_with(|c: char| c.is_ascii_digit()))
                || ["x86", "amd64", "aarch64", "arm64", "linux"].iter().any(|w| rest.starts_with(w))
            {
                cut = i - 1;
                break;
            }
        }
    }
    squash(&stem[..cut])
}

fn outside_apps(main: &[Pkg], pm: &str, flatpaks: &HashSet<String>) -> HashMap<String, String> {
    let native = native_pkgs(pm);
    let snaps: HashSet<String> = Command::new("snap")
        .arg("list")
        .stderr(Stdio::null())
        .output()
        .map(|o| String::from_utf8_lossy(&o.stdout).lines().skip(1).filter_map(|l| l.split_whitespace().next().map(str::to_lowercase)).collect())
        .unwrap_or_default();
    let mut onpath = HashSet::new();
    for d in std::env::var("PATH").unwrap_or_default().split(':') {
        if let Ok(rd) = fs::read_dir(d) {
            onpath.extend(rd.filter_map(|e| e.ok()).map(|e| e.file_name().to_string_lossy().to_lowercase()));
        }
    }
    let mut images = HashSet::new();
    for d in ["Applications", "Apps", ".local/bin", "bin", "Downloads", "Desktop", "AppImages"] {
        if let Ok(rd) = fs::read_dir(home().join(d)) {
            for e in rd.filter_map(|e| e.ok()) {
                let n = e.file_name().to_string_lossy().into_owned();
                if n.to_lowercase().ends_with(".appimage") {
                    images.insert(appimage_name(&n));
                }
            }
        }
    }
    let opt: HashSet<String> = fs::read_dir("/opt").map(|rd| rd.filter_map(|e| e.ok()).map(|e| e.file_name().to_string_lossy().to_lowercase()).collect()).unwrap_or_default();
    let mut out = HashMap::new();
    for a in main {
        let names: Vec<String> = std::iter::once(a.name.to_lowercase()).chain(a.alias.iter().filter(|x| !x.is_empty()).map(|x| x.to_lowercase())).collect();
        let vp = a.vpkg.to_lowercase();
        let how = if !a.flatpak.is_empty() && flatpaks.contains(&a.flatpak) {
            Some("flatpak".to_string())
        } else if a.vtype == "snap" && snaps.contains(&vp) {
            Some("snap".into())
        } else if (!vp.is_empty() && a.vtype == "repo" && native.contains(&vp)) || names.iter().any(|n| native.contains(n)) {
            Some(pm.to_string())
        } else if names.iter().any(|n| snaps.contains(n)) {
            Some("snap".into())
        } else if names.iter().any(|n| onpath.contains(n)) {
            Some("on your PATH".into())
        } else if names.iter().any(|n| opt.contains(n)) {
            Some("/opt".into())
        } else if names.iter().any(|n| images.contains(&squash(n))) {
            Some("AppImage".into())
        } else {
            None
        };
        if let Some(h) = how {
            out.insert(a.name.clone(), h);
        }
    }
    out
}

pub fn load_state() -> State {
    let p = paths();
    let g = |k: &str| p.get(k).cloned().unwrap_or_default();
    let repo = g("repo");
    let db = PathBuf::from(g("db"));
    let strict = foss_strict();
    let dev = { let d = g("dev"); if d.is_empty() { "no".to_string() } else { d } };
    let unlocks = key_unlocks();
    let all = dev != "no"; // 🧪 dev builds have everything keys unlock
    let unlocked = |u: &str| all || unlocks.contains(u);
    let mut main = read_tree(&Path::new(&repo).join("packages"), true, &unlocked);
    main.retain(|m| !(strict && m.foss != "foss"));
    main.sort_by_key(|m| m.foss == "closed"); // stable: free ones first, A–Z inside each
    let dirtpkgs = read_tree(&Path::new(&repo).join("dirt"), false, &unlocked);
    let by_ikey: HashMap<&str, &str> = main.iter().filter(|m| m.ikey != m.name).map(|m| (m.ikey.as_str(), m.name.as_str())).collect();
    let mut installed = Vec::new();
    let mut keys: Vec<String> = fs::read_dir(&db).map(|rd| rd.filter_map(|e| e.ok()).map(|e| e.file_name().to_string_lossy().into_owned()).collect()).unwrap_or_default();
    keys.sort();
    for key in keys {
        let info = kv(&db.join(&key).join("info"));
        let reason = fs::read_to_string(db.join(&key).join("reason")).map(|s| s.trim().to_string()).unwrap_or_default();
        let (mut src, mut name) = match key.split_once(':') {
            Some((a, b)) => (a.to_string(), b.to_string()),
            None => ("gurt".to_string(), key.clone()),
        };
        let rel = one(&info, "pkgrel");
        let mut via = String::new();
        let recipe = { let r = one(&info, "recipe"); if r.is_empty() { by_ikey.get(key.as_str()).map(|s| s.to_string()).unwrap_or_default() } else { r } };
        if !recipe.is_empty() && src != "gurt" {
            via = format!("{src}/{name}");
            src = "gurt".into();
            name = recipe;
        }
        let spec = if src == "gurt" && via.is_empty() { key.clone() } else if !via.is_empty() { name.clone() } else { format!("{src}/{name}") };
        let ver = { let v = one(&info, "pkgver"); let v = if v.is_empty() { "?".to_string() } else { v }; if rel.is_empty() { v } else { format!("{v}-{rel}") } };
        installed.push(Installed { held: db.join(&key).join("held").exists(), desc: one(&info, "pkgdesc"), key, via, spec, name, src, ver, reason });
    }
    let flatpaks: HashSet<String> = if has("flatpak") {
        Command::new("flatpak").args(["list", "--app", "--columns=application"]).stderr(Stdio::null()).output()
            .map(|o| String::from_utf8_lossy(&o.stdout).split_whitespace().map(str::to_string).collect()).unwrap_or_default()
    } else {
        HashSet::new()
    };
    let gurt_keys: HashSet<String> = installed.iter().map(|i| i.key.clone()).chain(installed.iter().filter(|i| i.src == "gurt").map(|i| i.name.clone())).collect();
    let outside = outside_apps(&main, &g("pm"), &flatpaks)
        .into_iter()
        .filter(|(n, _)| !gurt_keys.contains(n) && !main.iter().any(|a| &a.name == n && gurt_keys.contains(&a.ikey)))
        .collect();
    State {
        version: g("version"), pm: g("pm"), dirt: g("dirt") == "on", wsl: g("wsl") == "yes", cros: g("cros") == "yes",
        nix: g("nix") == "yes", hook: g("hook") == "on", dev, unlocks, all_unlocked: all,
        fossonly: strict, notify: notify_on(), vibes: vibes(&repo), packs: packs(&repo), ghonly: ghonly(&repo),
        main, dirtpkgs, installed, outside, cache: g("cache"), repo,
    }
}

/// ~/.config/gurt/keys: "skin:gold 2026-11-08" lines, written by gurt redeem
pub fn key_unlocks() -> HashSet<String> {
    fs::read_to_string(config_dir().join("gurt/keys")).unwrap_or_default().lines().filter_map(|l| l.split_whitespace().next().map(str::to_string)).collect()
}

impl State {
    /// did a GURT key unlock this? (skin:gold, track:shanty…) dev builds: yes, always
    pub fn has(&self, u: &str) -> bool {
        self.all_unlocked || self.unlocks.contains(u)
    }
    /// is it installed? (by gurt, or another way for Main GURT apps) → Some(how) where "gurt" = by gurt
    pub fn inst(&self, spec: &str) -> Option<InstHit> {
        let m = self.main.iter().find(|p| p.name == spec);
        if let Some(i) = self.installed.iter().find(|i| i.spec == spec || i.key == spec || m.is_some_and(|m| i.key == m.ikey) || (i.src == "gurt" && i.name == spec)) {
            return Some(InstHit::Gurt(i.spec.clone()));
        }
        m.and_then(|m| self.outside.get(&m.name)).map(|h| InstHit::External(h.clone()))
    }
    pub fn pkg(&self, name: &str) -> Option<&Pkg> {
        self.main.iter().find(|p| p.name == name)
    }
}

pub enum InstHit {
    Gurt(String),     // installed by gurt: its spec, for remove
    External(String), // got it another way (zypper, flatpak, an AppImage…)
}

pub fn how_label(h: &str) -> String {
    match h {
        "AppImage" => "an AppImage you downloaded".into(),
        "on your PATH" => "something on your PATH".into(),
        "/opt" => "a folder in /opt".into(),
        _ => h.into(),
    }
}

/// gurt's own text has emoji; the app shows none
pub fn no_emoji(s: &str) -> String {
    let t: String = s
        .chars()
        .filter(|&c| {
            let u = c as u32;
            !(u == 0xFE0F || u == 0x200D || (0x1F000..=0x1FAFF).contains(&u) || (0x2600..=0x27BF).contains(&u) && !matches!(c, '✓' | '✗' | '×') || (0x1F900..=0x1F9FF).contains(&u) || (0x2B00..=0x2BFF).contains(&u))
        })
        .collect();
    let mut out = String::with_capacity(t.len());
    let mut sp = false;
    for c in t.chars() {
        if c == ' ' {
            if !sp {
                out.push(c);
            }
            sp = true;
        } else {
            out.push(c);
            sp = false;
        }
    }
    out.trim().to_string()
}

// ── 🖼 app logos from this computer: the app's .desktop file → its Icon= → a file in an icon theme ──
pub struct DesktopIcons {
    by_stem: HashMap<String, String>, // desktop file stem (lowercase) → its Icon= value
}
impl DesktopIcons {
    pub fn scan() -> Self {
        let h = home();
        let dirs = [
            h.join(".local/share/applications"), "/usr/local/share/applications".into(), "/usr/share/applications".into(),
            h.join(".local/share/flatpak/exports/share/applications"), "/var/lib/flatpak/exports/share/applications".into(),
            "/var/lib/snapd/desktop/applications".into(),
        ];
        let mut by_stem = HashMap::new();
        for d in dirs {
            let Ok(rd) = fs::read_dir(&d) else { continue };
            for e in rd.filter_map(|e| e.ok()) {
                let n = e.file_name().to_string_lossy().into_owned();
                let Some(stem) = n.strip_suffix(".desktop") else { continue };
                if let Ok(s) = fs::read_to_string(e.path()) {
                    if let Some(icon) = s.lines().find_map(|l| l.strip_prefix("Icon=")) {
                        by_stem.entry(stem.to_lowercase()).or_insert_with(|| icon.trim().to_string());
                    }
                }
            }
        }
        DesktopIcons { by_stem }
    }
    /// the icon file for an app (name, its Flathub id, its aliases)
    pub fn find(&self, wants: &[String]) -> Option<PathBuf> {
        let wants: Vec<String> = wants.iter().filter(|w| !w.is_empty()).map(|w| w.to_lowercase()).collect();
        for (stem, icon) in &self.by_stem {
            if wants.iter().any(|w| stem == w || stem.ends_with(&format!(".{w}")) || stem.ends_with(&format!("_{w}"))) {
                if let Some(f) = theme_icon(icon) {
                    return Some(f);
                }
            }
        }
        wants.iter().find_map(|w| theme_icon(w))
    }
}

pub fn theme_icon(name: &str) -> Option<PathBuf> {
    let p = Path::new(name);
    if p.is_absolute() {
        let low = name.to_lowercase();
        return (p.is_file() && (low.ends_with(".png") || low.ends_with(".svg"))).then(|| p.to_path_buf());
    }
    let h = home();
    let bases = [h.join(".local/share/icons"), h.join(".icons"), "/usr/local/share/icons".into(), "/usr/share/icons".into(),
        h.join(".local/share/flatpak/exports/share/icons"), "/var/lib/flatpak/exports/share/icons".into()];
    for base in bases {
        let Ok(rd) = fs::read_dir(&base) else { continue };
        let mut themes: Vec<String> = rd.filter_map(|e| e.ok()).map(|e| e.file_name().to_string_lossy().into_owned()).filter(|t| t != "hicolor").collect();
        themes.sort();
        themes.insert(0, "hicolor".into());
        for t in themes {
            for size in ["scalable", "256x256", "128x128", "96x96", "64x64", "48x48", "512x512", "32x32"] {
                let exts: [&str; 2] = if size == "scalable" { ["svg", "png"] } else { ["png", "svg"] };
                for ext in exts {
                    let f = base.join(&t).join(size).join("apps").join(format!("{name}.{ext}"));
                    if f.is_file() {
                        return Some(f);
                    }
                }
            }
        }
    }
    ["png", "svg"].iter().map(|e| PathBuf::from(format!("/usr/share/pixmaps/{name}.{e}"))).find(|f| f.is_file())
}

// ── little things the dialogs read ──
pub struct HistItem {
    pub when: String,
    pub what: String,
    pub app: String,
    pub ver: String,
    pub tx: String,
}
pub fn history() -> Vec<HistItem> {
    let s = fs::read_to_string(state_dir().join("gurt/history")).unwrap_or_default();
    let lines: Vec<&str> = s.lines().collect();
    let start = lines.len().saturating_sub(300);
    lines[start..]
        .iter()
        .rev()
        .filter_map(|l| {
            let p: Vec<&str> = l.split('\t').collect();
            (p.len() >= 4).then(|| HistItem { when: p[0].into(), what: p[1].into(), app: p[2].into(), ver: p[3].into(), tx: p.get(4).unwrap_or(&"").to_string() })
        })
        .collect()
}

pub struct Ach {
    pub title: String,
    pub what: String,
    pub got: bool,
}
pub fn achievements() -> Vec<Ach> {
    gurt_out(&["achievements", "--tsv"])
        .lines()
        .filter_map(|l| {
            let p: Vec<&str> = l.split('\t').collect();
            (p.len() == 4).then(|| Ach { title: p[1].into(), what: p[2].into(), got: !p[3].is_empty() && p[3] != "0" && p[3] != "no" })
        })
        .collect()
}

pub struct Junk {
    pub what: String,
    pub bytes: u64,
    pub desc: String,
    pub root: bool,
}
pub fn disk() -> (Vec<Junk>, Vec<(u64, String)>) {
    let junk = gurt_out(&["hogs", "junk", "--tsv"])
        .lines()
        .filter_map(|l| {
            let p: Vec<&str> = l.split('\t').collect();
            (p.len() == 4).then(|| Junk { what: p[0].into(), bytes: p[1].parse().unwrap_or(0), desc: p[2].into(), root: p[3] == "1" })
        })
        .collect();
    let big = gurt_out(&["-a", "hogs", "--tsv"])
        .lines()
        .filter_map(|l| l.split_once('\t').map(|(b, n)| (b.parse().unwrap_or(0), n.to_string())))
        .take(25)
        .collect();
    (junk, big)
}
pub fn sizes() -> HashMap<String, u64> {
    gurt_out(&["hogs", "--tsv"]).lines().filter_map(|l| l.split_once('\t').and_then(|(b, k)| b.parse().ok().map(|b| (k.to_string(), b)))).collect()
}

pub fn fmt_size(b: u64) -> String {
    if b >= 1 << 30 {
        format!("{:.1} GB", b as f64 / (1u64 << 30) as f64)
    } else if b > 1 << 20 {
        format!("{:.1} MB", b as f64 / (1u64 << 20) as f64)
    } else {
        format!("{} KB", (b / 1024).max(1))
    }
}

pub struct Doctor {
    pub distro: String,
    pub pm: String,
    pub wsl: bool,
    pub cros: bool,
    pub sudo: bool,
    pub missing: Vec<String>,
    pub notify: bool,
}
pub fn doctor() -> Doctor {
    let out = gurt_out_all(&["utils", "list"]);
    let missing = out
        .lines()
        .filter_map(|l| {
            let t = l.trim_start();
            t.strip_prefix('✗').map(|r| r.split_whitespace().next().unwrap_or("").to_string())
        })
        .filter(|s| !s.is_empty())
        .collect();
    let osr = fs::read_to_string("/etc/os-release").unwrap_or_default();
    let get = |k: &str| osr.lines().find_map(|l| l.strip_prefix(&format!("{k}="))).map(|v| v.trim_matches('"').to_string());
    let p = paths();
    let euid = unsafe { libc::geteuid() };
    Doctor {
        distro: get("PRETTY_NAME").or_else(|| get("ID")).unwrap_or_default(),
        pm: p.get("pm").cloned().unwrap_or_else(|| "?".into()),
        wsl: p.get("wsl").is_some_and(|v| v == "yes"),
        cros: p.get("cros").is_some_and(|v| v == "yes"),
        sudo: euid == 0 || has("sudo") || has("doas"),
        missing,
        notify: notify_on(),
    }
}

/// the lottery's streak lives in the same file `gurt lottery` uses, so the CLI and the app share one
pub struct Lotto {
    pub streak: u32,
    pub best: u32,
    pub rarity: &'static str,
}
pub const LEGENDARY: [&str; 6] = ["hpa2", "tsudore", "opsec", "oneko", "zsnes", "frozen-bubble"];
pub fn lotto_spin() -> Lotto {
    let f = config_dir().join("gurt/lottery");
    let st: BTreeMap<String, String> = fs::read_to_string(&f)
        .unwrap_or_default()
        .lines()
        .filter_map(|l| l.trim().split_once('=').map(|(a, b)| (a.to_string(), b.to_string())))
        .collect();
    let today = today();
    let mut streak: u32 = st.get("streak").and_then(|s| s.parse().ok()).unwrap_or(0);
    let mut best: u32 = st.get("best").and_then(|s| s.parse().ok()).unwrap_or(0);
    let last = st.get("last").cloned().unwrap_or_default();
    if last != today.0 {
        streak = if last == today.1 { streak + 1 } else { 1 };
    }
    best = best.max(streak);
    let _ = fs::create_dir_all(f.parent().unwrap());
    let _ = fs::write(&f, format!("last={}\nstreak={streak}\nbest={best}\n", today.0));
    let r = rand_below(1000);
    let leg = (10 + 5 * (streak.saturating_sub(1))).min(50);
    let rarity = if r < leg { "legendary" } else if r < leg + 70 { "epic" } else if r < leg + 290 { "rare" } else { "common" };
    Lotto { streak, best, rarity }
}
/// (today, yesterday) as YYYY-MM-DD, local time
fn today() -> (String, String) {
    let fmt = |t: libc::time_t| unsafe {
        let mut tm: libc::tm = std::mem::zeroed();
        libc::localtime_r(&t, &mut tm);
        format!("{:04}-{:02}-{:02}", tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday)
    };
    let now = unsafe { libc::time(std::ptr::null_mut()) };
    (fmt(now), fmt(now - 86400))
}
pub fn rand_below(n: u32) -> u32 {
    use std::hash::{BuildHasher, Hasher};
    let mut h = std::collections::hash_map::RandomState::new().build_hasher();
    h.write_u128(std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0));
    (h.finish() % n.max(1) as u64) as u32
}
pub fn local_hour() -> i32 {
    unsafe {
        let t = libc::time(std::ptr::null_mut());
        let mut tm: libc::tm = std::mem::zeroed();
        libc::localtime_r(&t, &mut tm);
        tm.tm_hour
    }
}

pub fn downloads_dir() -> PathBuf {
    let cros = Path::new("/mnt/chromeos/MyFiles/Downloads");
    if cros.is_dir() {
        return cros.into();
    }
    if let Ok(o) = Command::new("xdg-user-dir").arg("DOWNLOAD").stderr(Stdio::null()).output() {
        let d = PathBuf::from(String::from_utf8_lossy(&o.stdout).trim());
        if d.is_dir() && fs::canonicalize(&d).ok() != fs::canonicalize(home()).ok() {
            return d;
        }
    }
    let d = home().join("Downloads");
    if d.is_dir() { d } else { home() }
}

/// a free name in a folder: thing.deb, thing-2.deb, thing-3.deb…
pub fn unique_path(dir: &Path, name: &str) -> PathBuf {
    let (stem, ext) = split_pkg_ext(name);
    let mut p = dir.join(name);
    let mut i = 2;
    while p.exists() {
        p = dir.join(format!("{stem}-{i}{ext}"));
        i += 1;
    }
    p
}
pub fn split_pkg_ext(name: &str) -> (&str, &str) {
    let low = name.to_lowercase();
    for e in [".pkg.tar.zst", ".pkg.tar.xz", ".pkg.tar.gz", ".pkg.tar", ".tar.gz", ".tar.xz", ".tar.zst", ".tar.bz2"] {
        if low.ends_with(e) {
            return name.split_at(name.len() - e.len());
        }
    }
    for e in [".deb", ".rpm", ".apk", ".xbps", ".eopkg", ".appimage", ".gurt", ".zip", ".exe", ".msi", ".7z", ".tgz"] {
        if low.ends_with(e) {
            return name.split_at(name.len() - e.len());
        }
    }
    (name, "")
}

/// files gurt can install / convert (the same list gurt outsource understands)
pub fn droppable(name: &str) -> bool {
    let l = name.to_lowercase();
    let exts = [".deb", ".rpm", ".apk", ".xbps", ".eopkg", ".gurt", ".appimage", ".dmg", ".exe", ".msi", ".snap", ".flatpak", ".flatpakref",
        ".tgz", ".tbz", ".tbz2", ".txz", ".tzst", ".zip", ".7z", ".gz", ".xz", ".bz2", ".zst", ".tar"];
    exts.iter().any(|e| l.ends_with(e)) || l.contains(".pkg.tar") || l.contains(".tar.")
}

/// a package name / spec that's safe to hand to gurt
pub fn spec_ok(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 200
        && !s.starts_with('-')
        && s.chars().next().is_some_and(|c| c.is_ascii_alphanumeric())
        && s.chars().all(|c| c.is_ascii_alphanumeric() || "._+°:@/-".contains(c))
}
pub fn url_ok(s: &str) -> bool {
    let is_url = (s.starts_with("https://") || s.starts_with("http://") || s.starts_with("git@")) && s.len() < 300 && !s.chars().any(|c| c.is_whitespace());
    let is_repo = s.split('/').count() == 2 && s.chars().all(|c| c.is_ascii_alphanumeric() || "_.-/".contains(c)) && !s.starts_with('-');
    is_url || is_repo
}

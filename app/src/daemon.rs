//! GURTd: gurt's background daemon (gurt gurtd on). keeps the package lists fresh, checks for updates (and installs them
//! if you turned auto-update on), offers to install packages that land in your Downloads, holds popups in quiet hours,
//! and skips downloads on battery / metered data
use crate::data::{self, config_dir, gurt, has, home, local_hour};
use std::collections::{HashMap, HashSet};
use std::io::Write;
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime};

const REFRESH_EVERY: u64 = 3 * 3600;
const CHECK_EVERY: u64 = 6 * 3600;

pub fn run_dir() -> PathBuf {
    std::env::var_os("XDG_RUNTIME_DIR").map(PathBuf::from).filter(|p| p.is_dir()).unwrap_or_else(|| home().join(".cache/gurt"))
}
/// GURTd's pid lives here while it runs (gurt gurtd status reads it)
pub fn url_file() -> PathBuf {
    run_dir().join("gurtd.pid")
}
fn log_file() -> PathBuf {
    home().join(".cache/gurt/gurtd.log")
}

pub fn dlog(msg: &str) {
    let ts = Command::new("date").arg("+%Y-%m-%d %H:%M:%S").output().map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string()).unwrap_or_default();
    let line = format!("{ts} {msg}");
    println!("{line}");
    let f = log_file();
    let _ = std::fs::create_dir_all(f.parent().unwrap());
    if let Ok(mut fh) = std::fs::OpenOptions::new().create(true).append(true).open(&f) {
        let _ = writeln!(fh, "{line}");
    }
}

pub fn dconf() -> HashMap<String, String> {
    let mut c: HashMap<String, String> = [("autoupdate", "off"), ("watch", "on"), ("fresh", "on"), ("saver", "on"), ("quiet", "off")].into_iter().map(|(a, b)| (a.into(), b.into())).collect();
    for l in std::fs::read_to_string(config_dir().join("gurt/daemon.conf")).unwrap_or_default().lines() {
        if let Some((k, v)) = l.trim().split_once('=') {
            let ok = if k == "quiet" { v == "off" || quiet_range(v).is_some() } else { v == "on" || v == "off" };
            if c.contains_key(k) && ok {
                c.insert(k.into(), v.into());
            }
        }
    }
    c
}
fn quiet_range(v: &str) -> Option<(i32, i32)> {
    let (a, b) = v.split_once('-')?;
    let (a, b): (i32, i32) = (a.parse().ok()?, b.parse().ok()?);
    ((0..24).contains(&a) && (0..24).contains(&b)).then_some((a, b))
}
/// quiet hours (quiet=22-8): GURTd still checks, but holds its notifications until they end
fn in_quiet(c: &HashMap<String, String>) -> bool {
    let Some((a, b)) = c.get("quiet").and_then(|q| quiet_range(q)) else { return false };
    let h = local_hour();
    if a < b { a <= h && h < b } else if a != b { h >= a || h < b } else { false }
}

/// unplugged and running on battery (any charger plugged in = no)
fn on_battery() -> bool {
    let base = std::path::Path::new("/sys/class/power_supply");
    let Ok(rd) = std::fs::read_dir(base) else { return false };
    let mut bat = false;
    for e in rd.filter_map(|e| e.ok()) {
        let r = |f: &str| std::fs::read_to_string(e.path().join(f)).map(|s| s.trim().to_string()).unwrap_or_default();
        let kind = r("type");
        if ["Mains", "USB", "USB_C"].contains(&kind.as_str()) && r("online") == "1" {
            return false;
        }
        if kind == "Battery" && r("status") == "Discharging" && r("scope") != "Device" {
            bat = true;
        }
    }
    bat
}
/// NetworkManager says this connection is metered (a phone hotspot, mobile data)
fn metered() -> bool {
    let out = Command::new("busctl")
        .args(["--system", "get-property", "org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager", "org.freedesktop.NetworkManager", "Metered"])
        .stderr(Stdio::null())
        .output()
        .map(|o| String::from_utf8_lossy(&o.stdout).into_owned())
        .unwrap_or_default();
    let w: Vec<&str> = out.split_whitespace().collect();
    w.first() == Some(&"u") && matches!(w.get(1), Some(&"1") | Some(&"3"))
}
pub fn saver_reason() -> String {
    if on_battery() {
        "on battery".into()
    } else if metered() {
        "on a metered connection".into()
    } else {
        String::new()
    }
}

fn icon() -> String {
    ["/usr/share/gurt/gurt.png", "/usr/local/share/gurt/gurt.png"]
        .iter()
        .map(PathBuf::from)
        .chain(std::iter::once(home().join(".local/share/icons/hicolor/256x256/apps/gurt.png")))
        .find(|p| p.is_file())
        .map(|p| p.display().to_string())
        .unwrap_or_default()
}

/// a desktop notification; with actions (key, label) it waits and returns the one you clicked
fn notify(title: &str, body: &str, actions: &[(&str, &str)]) -> Option<String> {
    if !has("notify-send") {
        return None;
    }
    let mut cmd = Command::new("notify-send");
    cmd.arg("--app-name=GURT");
    let ic = icon();
    if !ic.is_empty() {
        cmd.args(["-i", &ic]);
    }
    let with_actions = !actions.is_empty()
        && Command::new("notify-send").arg("--help").output().map(|o| String::from_utf8_lossy(&o.stdout).contains("--action")).unwrap_or(false);
    if with_actions {
        for (k, l) in actions {
            cmd.args(["-A", &format!("{k}={l}")]);
        }
    }
    let out = cmd.args([title, body]).stderr(Stdio::null()).output().ok()?;
    let s = String::from_utf8_lossy(&out.stdout).trim().to_string();
    (with_actions && !s.is_empty()).then_some(s)
}

fn open_gurt(args: &[&str]) {
    let me = std::env::current_exe().unwrap_or_else(|_| "gurt-app".into());
    let _ = Command::new(me).arg("--gurt").arg(gurt()).args(args).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null()).spawn();
}

type Held = Arc<Mutex<HashMap<&'static str, (String, String, bool)>>>;

fn dnotify(held: &Held, kind: &'static str, title: String, body: String, open_btn: bool) {
    if in_quiet(&dconf()) {
        dlog(&format!("quiet hours: holding \"{title}\" until they end"));
        held.lock().unwrap().insert(kind, (title, body, open_btn));
        return;
    }
    std::thread::spawn(move || {
        let acts: &[(&str, &str)] = if open_btn { &[("open", "Open GURT")] } else { &[] };
        if notify(&title, &body, acts).as_deref() == Some("open") {
            open_gurt(&[]);
        }
    });
}

/// run gurt for the daemon (no colours, nicely, never asking anything) → (rc, output)
fn gurt_quiet(args: &[&str], extra: &[(&str, &str)]) -> (i32, String) {
    let mut c = Command::new("nice");
    c.args(["-n", "10", gurt()]).args(args).env("NO_COLOR", "1").env("GURT_PLAIN", "1").stdin(Stdio::null());
    for (k, v) in extra {
        c.env(k, v);
    }
    match c.output() {
        Ok(o) => (o.status.code().unwrap_or(1), data::strip_ansi(&(String::from_utf8_lossy(&o.stdout).into_owned() + &String::from_utf8_lossy(&o.stderr)))),
        Err(e) => (1, e.to_string()),
    }
}

/// refresh + see what's outdated; auto-update if that's on (only what needs no password), else tell you
fn updates(held: &Held) {
    let (_, out) = gurt_quiet(&["update"], &[("GURT_REFRESH", "1")]);
    let apps: Vec<String> = out
        .lines()
        .filter_map(|l| {
            let w: Vec<&str> = l.trim_start().strip_prefix("-> ")?.split_whitespace().collect();
            (w.len() == 4 && w[2] == "->").then(|| w[0].to_string())
        })
        .collect();
    let sys = out.lines().find_map(|l| l.split_once(" system update(s) waiting").and_then(|(a, _)| a.split_whitespace().last().map(str::to_string)));
    dlog(&format!("checked: {} app update(s), {} system update(s)", apps.len(), sys.clone().unwrap_or_else(|| "0".into())));
    if apps.is_empty() && sys.is_none() {
        return;
    }
    if !apps.is_empty() && dconf().get("autoupdate").map(|s| s == "on").unwrap_or(false) {
        let nopw = unsafe { libc::geteuid() } == 0 || Command::new("sudo").args(["-n", "true"]).stdout(Stdio::null()).stderr(Stdio::null()).status().map(|s| s.success()).unwrap_or(false);
        if nopw {
            let (rc, _) = gurt_quiet(&["-y", "--no-system", "upgrade"], &[]);
            dlog(&format!("auto-update: {}", if rc == 0 { "done" } else { "had problems" }));
            let list = apps.iter().take(6).cloned().collect::<Vec<_>>().join(", ") + if apps.len() > 6 { "…" } else { "" };
            dnotify(held, "updated", if rc == 0 { "GURT updated your apps".into() } else { "GURT couldn't update everything".into() }, list, false);
            return;
        }
        if has("flatpak") {
            let _ = Command::new("flatpak").args(["update", "--user", "-y", "--noninteractive"]).stdout(Stdio::null()).stderr(Stdio::null()).status();
            dlog("auto-update: flatpaks updated; the rest need your password");
        }
    }
    let body = format!("{} app update(s){}", apps.len(), sys.map(|n| format!(", {n} system update(s)")).unwrap_or_default());
    dnotify(held, "updates", "Updates are waiting".into(), body, true);
}

/// a package lands in your Downloads → "Install it with GURT?"
fn watch_downloads() {
    let d = data::downloads_dir();
    let mut seen: HashSet<String> = std::fs::read_dir(&d).map(|rd| rd.filter_map(|e| e.ok()).map(|e| e.file_name().to_string_lossy().into_owned()).collect()).unwrap_or_default();
    let mut sizes: HashMap<String, u64> = HashMap::new();
    loop {
        std::thread::sleep(Duration::from_secs(5));
        if dconf().get("watch").map(|s| s != "on").unwrap_or(false) {
            continue;
        }
        let Ok(rd) = std::fs::read_dir(&d) else { continue };
        for e in rd.filter_map(|e| e.ok()) {
            let n = e.file_name().to_string_lossy().into_owned();
            if seen.contains(&n) || n.starts_with('.') || n.ends_with(".part") || n.ends_with(".crdownload") || n.ends_with(".download") || !data::droppable(&n) {
                continue;
            }
            let Ok(md) = e.metadata() else { continue };
            let size = md.len();
            if sizes.get(&n) != Some(&size) || size == 0 {
                sizes.insert(n.clone(), size); // still downloading: wait until it stops growing
                continue;
            }
            seen.insert(n.clone());
            dlog(&format!("new download: {n}"));
            let f = e.path().display().to_string();
            std::thread::spawn(move || {
                if notify("Install it with GURT?", &n, &[("install", "Install with GURT"), ("no", "Not now")]).as_deref() == Some("install") {
                    open_gurt(&[&f]);
                }
            });
        }
    }
}

/// which gurt + app code is on disk now: an update changes it, and GURTd restarts as the new version
fn code_stamp() -> String {
    let me = std::env::current_exe().ok();
    let g = data::which(gurt()).ok().map(|p| std::fs::canonicalize(&p).unwrap_or(p));
    [me, g]
        .iter()
        .map(|f| {
            f.as_ref()
                .and_then(|f| std::fs::metadata(f).ok())
                .map(|m| format!("{:?}:{}", m.modified().unwrap_or(SystemTime::UNIX_EPOCH), m.len()))
                .unwrap_or_else(|| "-".into())
        })
        .collect::<Vec<_>>()
        .join(" ")
}

pub fn main() -> i32 {
    let pidf = url_file();
    if let Ok(old) = std::fs::read_to_string(&pidf) {
        if let Ok(pid) = old.trim().parse::<i32>() {
            if pid != std::process::id() as i32 && unsafe { libc::kill(pid, 0) } == 0 {
                eprintln!("GURTd is already running (pid {pid})");
                return 0;
            }
        }
    }
    let _ = std::fs::create_dir_all(run_dir());
    let _ = std::fs::write(&pidf, format!("{}\n", std::process::id()));
    dlog("Linus sees you. Starting GURTd btw");
    std::thread::spawn(watch_downloads);
    let held: Held = Default::default();
    let stamp = code_stamp();
    let mut seen_stamp = String::new();
    let mut last_check: Option<Instant> = None;
    let mut last_refresh: Option<Instant> = None;
    let mut waiting = String::new();
    loop {
        let c = dconf();
        let now_stamp = code_stamp();
        if now_stamp != stamp {
            if now_stamp == seen_stamp {
                // GURT got updated (and the files settled): start over as the new version
                dlog("GURT was updated, restarting GURTd on the new version");
                let _ = std::fs::remove_file(&pidf);
                let me = std::env::current_exe().unwrap_or_else(|_| "gurt-app".into());
                let args: Vec<String> = std::env::args().skip(1).collect();
                let err = std::os::unix::process::CommandExt::exec(Command::new(me).args(args));
                dlog(&format!("couldn't restart: {err}"));
            }
            seen_stamp = now_stamp;
        }
        if !in_quiet(&c) {
            let waiting_now: Vec<_> = held.lock().unwrap().drain().collect();
            for (k, (t, b, o)) in waiting_now {
                dnotify(&held, k, t, b, o);
            }
        }
        let due_check = last_check.map(|t| t.elapsed().as_secs() >= CHECK_EVERY).unwrap_or(true);
        let due_fresh = c.get("fresh").map(|s| s == "on").unwrap_or(true) && last_refresh.map(|t| t.elapsed().as_secs() >= REFRESH_EVERY).unwrap_or(true);
        if due_check || due_fresh {
            let why = if c.get("saver").map(|s| s == "on").unwrap_or(true) { saver_reason() } else { String::new() };
            if !why.is_empty() {
                if why != waiting {
                    dlog(&format!("saver: {why}, holding off on the update check"));
                }
                waiting = why;
            } else {
                waiting.clear();
                updates(&held); // gurt update refreshes the lists too
                last_check = Some(Instant::now());
                last_refresh = last_check;
            }
        }
        std::thread::sleep(Duration::from_secs(60));
    }
}

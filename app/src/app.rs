//! GURT, the app: everything it does runs the real `gurt` CLI
use crate::data::{self, State};
use crate::jobs::{self, Job};
use crate::skin::{self, hex, mono, monob, sansb, Pal, Skin};
use crate::widgets::{self as w, Kind};
use egui::{pos2, vec2, Align2, Color32, CornerRadius, Rect, Sense, Stroke, StrokeKind, Ui};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::mpsc::{channel, Receiver};
use std::sync::Arc;
use std::time::{Duration, Instant};

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Tab {
    Discover,
    Installed,
    Updates,
    Setup,
    Desktops,
    Files,
}

/// what to do once a job finishes
#[derive(Clone, Debug)]
pub enum After {
    Nothing,
    SearchSrc(String),
    SearchAll(String),
    Check,
    Desktops,
    Convert(String),
    Wizard(usize),
    DevUnlock,
    Redeem,
    KeyGen,
    KeyCheck,
    Upgrade,
}

#[derive(Clone)]
pub struct Act {
    pub args: Vec<String>,
    pub stdin: Option<String>,
    pub quiet: bool,
    pub bg: bool,
    pub confirm: Option<(String, String)>,
    pub after: After,
}
impl Act {
    pub fn new(args: &[&str]) -> Act {
        Act { args: args.iter().map(|s| s.to_string()).collect(), stdin: None, quiet: false, bg: false, confirm: None, after: After::Nothing }
    }
    pub fn quiet(mut self) -> Act {
        self.quiet = true;
        self
    }
    pub fn then(mut self, a: After) -> Act {
        self.after = a;
        self
    }
    pub fn ask(mut self, title: impl Into<String>, body: impl Into<String>) -> Act {
        self.confirm = Some((title.into(), body.into()));
        self
    }
}

pub struct Running {
    pub job: Arc<Job>,
    pub act: Act,
    pub seen: usize,
}

#[derive(Clone, Debug)]
pub struct Hit {
    pub src: String,
    pub name: String,
    pub ver: String,
    pub desc: String,
}

pub enum Dialog {
    History(Vec<data::HistItem>),
    Achievements(Option<Vec<data::Ach>>),
    Disk(Option<(Vec<data::Junk>, Vec<(u64, String)>)>),
    Gurtd(Option<GurtdView>),
    Compare,
    DirtGate,
    DevLock(String, String),
    /// 🔑 redeem a GURT key: what you typed, what gurt said, did it work
    Redeem(String, Vec<String>, bool),
    /// 🧪 dev builds: make a key (which unlocks are ticked, a note, the new key's lines) + check one
    KeyGen(KeyGenView),
}
#[derive(Default)]
pub struct KeyGenView {
    pub picks: Vec<bool>,
    pub note: String,
    pub made: Vec<(String, String)>, // key= line= unlock= what= from gurt __keygen
    pub check: String,
    pub checked: Vec<(String, String)>,
    pub err: String,
}
/// everything a GURT key can unlock (the same list as gurt's KEY_UNLOCKS)
pub const KEY_UNLOCKS: [(&str, &str); 7] = [
    ("app:hpa2", "the secret app hpa2"), ("skin:gold", "the Golden Duck skin + coin sounds"), ("track:shanty", "the shanty music track"),
    ("ach:golden", "achievement: golden duck"), ("ach:quack", "achievement: duck whisperer"), ("ach:shanty", "achievement: sea legs"), ("ach:konami", "achievement: up up down down"),
];
fn kv_lines(lines: &[String]) -> Vec<(String, String)> {
    lines.iter().filter_map(|l| l.split_once('=').filter(|(k, _)| ["key", "line", "unlock", "what", "note"].contains(k)).map(|(k, v)| (k.to_string(), data::no_emoji(v)))).collect()
}

pub struct GurtdView {
    pub running: bool,
    pub c: HashMap<String, String>,
    pub log: String,
    pub holding: String,
}

pub struct Up {
    pub name: String,
    pub src: String,
    pub ver: String,
    pub desc: String,
    pub btn: &'static str,
    pub act: Act,
}

pub struct ZoneItem {
    pub name: String,
    pub size: u64,
    pub signed: Option<String>,
}

pub struct Lotto {
    pub win: String,
    pub rarity: &'static str,
    pub streak: u32,
    pub best: u32,
    pub spin_left: u32,
    pub next: Instant,
    pub showing: String,
    pub in_setup: bool,
}

pub struct App {
    pub st: Arc<State>,
    pub loaded: bool,
    loader: Option<Receiver<State>>,
    pub skin: Skin,
    pub theme: String,
    pub pal: Pal,
    applied: Option<(Skin, bool)>,
    pub tab: Tab,
    pub src: String,
    pub q: String,
    pub iq: String,
    pub all: Option<Result<Vec<Hit>, String>>,
    pub src_res: Option<Result<Vec<Hit>, String>>,
    pub run: Option<Running>,
    queued: Option<Act>,
    pub console: Vec<String>,
    pub console_open: bool,
    pub console_title: String,
    pub console_dot: Color32,
    pw: String,
    pub confirm: Option<Act>,
    pub dialog: Option<Dialog>,
    toast: Option<(String, Instant)>,
    pub ups: Option<Result<Vec<Up>, String>>,
    pub badge: usize,
    pub desktops: Option<Result<(Vec<(String, String, String, bool)>, String), String>>,
    pub picked: std::collections::BTreeSet<String>,
    pub bcat: String,
    pub lotto: Option<Lotto>,
    pub cmp: Vec<String>,
    pub sizes: Option<HashMap<String, u64>>,
    pub bysize: bool,
    pub zone: Vec<ZoneItem>,
    pub zone_msg: String,
    pub cg_file: Option<PathBuf>,
    pub cg_fmt: usize,
    pub cg_screen: String,
    pub cg_state: &'static str, // idle loaded running done jam cursed
    pub cg_until: Option<Instant>,
    pub wiz: Option<crate::wizard::Wiz>,
    pub setup_app: bool,   // this window is the GURT Setup Wizard app
    pub from_app: bool,
    pub gated: bool,       // GURT, before the setup wizard is finished
    icons: crate::icons::Icons,
    bg_started: Option<Instant>,
    bg_check_stopped: bool,
    pub open_file: Option<PathBuf>,
    pub more_open: Option<&'static str>,
    pub prefs_open: bool,
    pub sound: crate::sound::Sound,
    seen_ver_checked: bool,
    pub width: f32,
    pub quit: bool,
    size_rx: Option<Receiver<HashMap<String, u64>>>,
    dlg_rx: Option<Receiver<Dialog>>,
    pub all_open: bool,
    pub cg_hover: bool,
    pub gurtd_reopen: bool,
}

impl App {
    pub fn new(cc: &eframe::CreationContext<'_>, wizard: bool, from_app: bool, open: Option<PathBuf>) -> App {
        egui_extras::install_image_loaders(&cc.egui_ctx);
        let ctx = cc.egui_ctx.clone();
        let _ = jobs::REPAINT.set(Box::new(move || ctx.request_repaint()));
        let skin = Skin::from_id(&data::conf_str("skin").unwrap_or_default());
        let theme = data::conf_str("theme").filter(|t| ["light", "dark", "auto"].contains(&t.as_str())).unwrap_or_else(|| "dark".into());
        let wiz_done = data::conf_str("wizard").as_deref() == Some("done");
        let mut app = App {
            st: Arc::new(State::default()),
            loaded: false,
            loader: None,
            skin,
            theme,
            pal: skin::pal(skin, true),
            applied: None,
            tab: Tab::Discover,
            src: "gurt".into(),
            q: String::new(),
            iq: String::new(),
            all: None,
            src_res: None,
            run: None,
            queued: None,
            console: Vec::new(),
            console_open: false,
            console_title: "activity".into(),
            console_dot: hex(0x8e8e97),
            pw: String::new(),
            confirm: None,
            dialog: None,
            toast: None,
            ups: None,
            badge: 0,
            desktops: None,
            picked: Default::default(),
            bcat: "all".into(),
            lotto: None,
            cmp: Vec::new(),
            sizes: None,
            bysize: false,
            zone: Vec::new(),
            zone_msg: "converted files land here. grab them whenever".into(),
            cg_file: None,
            cg_fmt: 0,
            cg_screen: "INSERT PACKAGE".into(),
            cg_state: "idle",
            cg_until: None,
            wiz: None,
            setup_app: wizard,
            from_app,
            gated: !wizard && !wiz_done,
            icons: crate::icons::Icons::new(),
            bg_started: None,
            bg_check_stopped: false,
            open_file: open,
            more_open: None,
            prefs_open: false,
            sound: crate::sound::Sound::new(skin),
            seen_ver_checked: false,
            width: 1100.0,
            quit: false,
            size_rx: None,
            dlg_rx: None,
            all_open: false,
            cg_hover: false,
            gurtd_reopen: false,
        };
        // for screenshots / tests: open on a tab or a source
        match std::env::var("GURT_APP_TAB").unwrap_or_default().as_str() {
            "installed" => app.tab = Tab::Installed,
            "updates" => app.tab = Tab::Updates,
            "setup" => app.tab = Tab::Setup,
            "desktops" => app.tab = Tab::Desktops,
            "files" => app.tab = Tab::Files,
            _ => {}
        }
        if let Ok(s) = std::env::var("GURT_APP_SRC") {
            app.src = s;
        }
        app.reload();
        app.sound.play("startup");
        app
    }

    // ── state ──
    pub fn reload(&mut self) {
        let (tx, rx) = channel();
        self.loader = Some(rx);
        std::thread::spawn(move || {
            let _ = tx.send(data::load_state());
            if let Some(r) = jobs::REPAINT.get() {
                r();
            }
        });
    }
    fn poll_state(&mut self) {
        if let Some(rx) = &self.loader {
            if let Ok(s) = rx.try_recv() {
                let first = !self.loaded;
                self.st = Arc::new(s);
                self.loaded = true;
                self.loader = None;
                if self.bysize {
                    self.load_sizes();
                }
                if first {
                    self.on_first_load();
                }
            }
        }
    }
    fn on_first_load(&mut self) {
        // 🔑 a locked skin or track (gui.json edited by hand, or a dev build swapped for a normal one) falls back
        if self.skin == Skin::Gold && !self.st.has("skin:gold") {
            self.skin = Skin::Gurt;
            self.sound.set_skin(Skin::Gurt);
        }
        if crate::sound::track_locked(&self.sound.track) && !self.st.has(&format!("track:{}", self.sound.track)) {
            self.sound.track = "auto".into();
            data::save_conf("track", "auto".into());
            self.sound.sync_music();
        }
        if self.st.dev == "locked" {
            self.dialog = Some(Dialog::DevLock(String::new(), String::new()));
            return;
        }
        if self.setup_app {
            self.wiz = Some(crate::wizard::Wiz::new(self));
            return;
        }
        if let Some(f) = self.open_file.take() {
            self.install_file(f);
        }
        self.bg_started = Some(Instant::now());
    }
    pub fn load_sizes(&mut self) {
        let (tx, rx) = channel();
        std::thread::spawn(move || {
            let _ = tx.send(data::sizes());
            if let Some(r) = jobs::REPAINT.get() {
                r();
            }
        });
        self.size_rx = Some(rx);
    }

    pub fn toast(&mut self, t: impl Into<String>) {
        self.toast = Some((t.into(), Instant::now()));
    }

    pub fn pw_mut(&mut self) -> &mut String {
        &mut self.pw
    }

    /// is gurt doing something your click has to wait for? the quiet update check doesn't count:
    /// it stops for your click (start) and picks back up after
    pub fn busy(&self) -> bool {
        self.run.as_ref().is_some_and(|r| !r.act.bg)
    }

    /// run gurt (asks first when it changes your system)
    pub fn go(&mut self, act: Act) {
        if act.confirm.is_some() {
            self.confirm = Some(act);
            return;
        }
        self.start(act);
    }
    fn start(&mut self, act: Act) {
        if let Some(r) = &self.run {
            if r.act.bg {
                // the quiet update check never blocks you: it stops, your thing goes first
                r.job.cancel();
                self.bg_check_stopped = true;
                self.queued = Some(act);
                return;
            }
            self.toast("gurt's still busy with the last thing, hold up");
            return;
        }
        let job = jobs::start(act.args.clone(), act.stdin.clone());
        if !act.quiet {
            self.console = vec![];
            self.console_title = job.title.clone();
            self.console_dot = self.pal.accent;
            self.console_open = true;
        }
        self.run = Some(Running { job, act, seen: 0 });
    }

    fn poll_job(&mut self) {
        let Some(r) = &mut self.run else { return };
        let (new, done, rc, _ask) = r.job.snapshot_from(r.seen);
        r.seen += new.len();
        if !r.act.quiet {
            self.console.extend(new.iter().cloned());
        }
        for l in &new {
            if let Some(a) = l.split("achievement unlocked: ").nth(1) {
                self.toast = Some((format!("achievement unlocked: {}", data::no_emoji(a)), Instant::now()));
                self.sound.play("achieve");
            }
        }
        if !done {
            return;
        }
        let r = self.run.take().unwrap();
        let lines = r.job.lines();
        if !r.act.quiet {
            self.console_dot = if rc == 0 { self.pal.good } else { self.pal.bad };
            self.sound.play(if rc == 0 { "ok" } else { "err" });
        }
        self.finish(r.act, rc, lines);
        self.reload();
        if self.gurtd_reopen {
            self.gurtd_reopen = false;
            self.open_dialog(Dialog::Gurtd(None), || Dialog::Gurtd(Some(crate::dialogs::gurtd_view())));
        }
        if let Some(q) = self.queued.take() {
            self.start(q);
        } else if self.bg_check_stopped {
            self.bg_check_stopped = false;
            self.bg_started = Some(Instant::now());
        }
    }

    fn finish(&mut self, act: Act, rc: i32, lines: Vec<String>) {
        match act.after {
            After::Nothing => {}
            After::Upgrade => self.check(false, false),
            After::SearchSrc(t) => {
                let res = parse_search(&lines);
                self.src_res = Some(if res.is_empty() {
                    let net = lines.iter().any(|l| l.contains("unreachable") || l.contains("couldn't") || l.contains("==> nah:") || l.contains("no package index"));
                    Err(format!("nothing on {} matched \"{t}\" {}", self.src, if net { "(couldn't reach it — check your internet)" } else { "womp womp" }))
                } else {
                    Ok(res)
                });
            }
            After::SearchAll(t) => {
                let res = parse_search(&lines);
                self.all = Some(if res.is_empty() { Err(format!("nothing anywhere matched \"{t}\" womp womp")) } else { Ok(res) });
            }
            After::Check => {
                if act.bg && self.bg_check_stopped {
                    self.ups = None;
                    return;
                }
                self.parse_updates(&lines);
            }
            After::Desktops => {
                let mut des = Vec::new();
                for l in &lines {
                    if let Some(rest) = l.strip_prefix("  ") {
                        if rest.starts_with(' ') {
                            continue;
                        }
                        let Some((name, more)) = rest.split_once(char::is_whitespace) else { continue };
                        let more = more.trim();
                        let (more, ok) = match more.strip_suffix("(not in your distro's repos)") {
                            Some(m) => (m.trim(), false),
                            None => (more, true),
                        };
                        let (title, desc) = more.split_once(" — ").unwrap_or((more, ""));
                        des.push((name.to_string(), data::no_emoji(title), data::no_emoji(desc), ok));
                    }
                }
                let dm = lines.iter().find_map(|l| l.split("your login screen: ").nth(1)).map(|s| s.trim_end_matches(')').to_string()).unwrap_or_default();
                self.desktops = Some(if des.is_empty() { Err("couldn't list desktops".into()) } else { Ok((des, dm)) });
            }
            After::Convert(orig) => {
                if rc == 0 {
                    let cursed = orig.to_lowercase().ends_with(".exe") || orig.to_lowercase().ends_with(".msi");
                    self.cg_state = "done";
                    self.cg_screen = if cursed { "CURSED… BUT IT WORKED it's in the Download Zone™".into() } else { "DONE it's in the Download Zone™".into() };
                    self.cg_file = None;
                    self.load_zone();
                } else {
                    self.cg_state = "jam";
                    let why = lines.iter().rev().find(|l| l.contains("nah:") || l.contains("can't") || l.contains("couldn't")).map(|l| l.replace("==> nah:", "").trim().to_string());
                    self.cg_screen = format!("JAMMED {}", why.unwrap_or_else(|| "check the log".into()));
                    self.console = lines;
                    self.console_title = format!("gurt convert {orig}");
                    self.console_dot = self.pal.bad;
                    self.console_open = true;
                }
            }
            After::Wizard(i) => crate::wizard::task_done(self, i, rc, &lines),
            After::Redeem => {
                let ok = rc == 0;
                let said: Vec<String> = lines.iter().skip(1).map(|l| data::no_emoji(l.trim().trim_start_matches("==> nah:").trim_start_matches("==>").trim_start_matches("->").trim())).filter(|l| !l.is_empty()).collect();
                if let Some(Dialog::Redeem(input, out, good)) = &mut self.dialog {
                    *out = said;
                    *good = ok;
                    if ok {
                        input.clear();
                    }
                }
                self.sound.play(if ok { "jackpot" } else { "err" });
                if ok {
                    self.reload(); // 🔑 new skins, tracks and apps show up now
                }
            }
            After::KeyGen | After::KeyCheck => {
                let kv = kv_lines(&lines);
                let err = if rc == 0 { String::new() } else { lines.iter().rev().find(|l| l.contains("nah:")).map(|l| data::no_emoji(l.split("nah:").nth(1).unwrap_or(l).trim())).unwrap_or_else(|| "that didn't work".into()) };
                if let Some(Dialog::KeyGen(v)) = &mut self.dialog {
                    v.err = err;
                    if matches!(act.after, After::KeyGen) { v.made = kv; } else { v.checked = kv; }
                }
                if rc == 0 {
                    self.sound.play("ok");
                }
            }
            After::DevUnlock => {
                // reload, and look again: still locked = a wrong password (gurt swapped in the normal GURT)
                self.dialog = None;
                self.loaded = false;
            }
        }
    }

    // ── things the tabs call ──
    pub fn check(&mut self, quiet: bool, bg: bool) {
        self.ups = None;
        let mut a = Act::new(&["update"]).then(After::Check);
        a.quiet = quiet;
        a.bg = bg;
        self.go(a);
    }
    fn parse_updates(&mut self, lines: &[String]) {
        let mut ups = Vec::new();
        // gurt itself first (the new gurt might be needed for the rest)
        if let Some(l) = lines.iter().find(|l| l.contains("is out (you have") || l.contains("gurt self-update")) {
            let ver = l
                .split("gurt ")
                .nth(1)
                .and_then(|r| r.split_once(" is out (you have "))
                .map(|(new, rest)| format!("{} → {new}", rest.split(')').next().unwrap_or("")))
                .unwrap_or_else(|| "new version".into());
            ups.push(Up { name: "gurt".into(), src: "gurt".into(), ver, desc: "gurt itself has an update".into(), btn: "update gurt", act: verb(&["-y", "self-update"], "Update gurt", "") });
        }
        if let Some((n, pm)) = lines.iter().find_map(|l| {
            let (a, b) = l.split_once(" system update(s) waiting from ")?;
            let n = a.split_whitespace().last()?.to_string();
            Some((n, b.split_whitespace().next().unwrap_or("").to_string()))
        }) {
            let s = if n == "1" { "" } else { "s" };
            ups.push(Up { name: "your system".into(), src: pm.clone(), ver: format!("{n} update{s}"), desc: format!("{n} package{s} from your distro ({pm}) — \"update everything\" installs them too"), btn: "update system", act: verb(&["-y", "sysup"], "Update your whole system", "") });
        }
        for l in lines {
            let t = l.trim_start();
            if let Some(rest) = t.strip_prefix("-> ") {
                let parts: Vec<&str> = rest.split_whitespace().collect();
                if parts.len() == 4 && parts[2] == "->" {
                    let spec = parts[0];
                    let (src, name) = spec.split_once('/').unwrap_or(("gurt", spec));
                    ups.push(Up { name: name.into(), src: src.into(), ver: format!("{} → {}", parts[1], parts[3]), desc: "update available".into(), btn: "update", act: verb(&["-y", "install", spec], "Install", spec) });
                }
            }
        }
        self.badge = ups.len();
        self.ups = Some(Ok(ups));
    }

    pub fn search_src(&mut self) {
        if self.src == "dirt" || self.src == "gurt" {
            return;
        }
        let t = self.q.trim().trim_start_matches(&format!("{}/", self.src)).to_string();
        if t.is_empty() || !data::spec_ok(&t.replace(' ', "-")) {
            return;
        }
        self.src_res = None;
        let spec = format!("{}/{t}", self.src);
        self.go(Act::new(&["-y", "search", &spec]).quiet().then(After::SearchSrc(t)));
    }
    pub fn search_all(&mut self) {
        let t = self.q.trim().to_string();
        if t.is_empty() {
            return;
        }
        if t.starts_with("http://") || t.starts_with("https://") || t.starts_with("git@") {
            if data::url_ok(&t) {
                self.go(verb(&["-y", "outsource", &t], "Build + install", &t));
            }
            return;
        }
        if !t.chars().all(|c| c.is_alphanumeric() || " ._+-/".contains(c)) {
            return;
        }
        self.all = None;
        self.all_open = true;
        self.go(Act::new(&["-y", "-a", "search", &t]).quiet().then(After::SearchAll(t.clone())));
    }

    pub fn install_file(&mut self, f: PathBuf) {
        let name = f.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
        if !f.is_file() || !data::droppable(&name) {
            self.toast(format!("gurt can't install {name} (.deb .rpm .AppImage .tar.gz .exe .dmg …)"));
            return;
        }
        let p = f.display().to_string();
        let sub = if name.to_lowercase().ends_with(".gurt") { "add" } else { "outsource" };
        self.go(Act::new(&["-y", sub, &p]).ask(format!("Install {name}?"), format!("gurt will install {name}. only install files you trust.")));
    }

    pub fn load_zone(&mut self) {
        let d = zone_dir(&self.st);
        let mut items: Vec<(std::time::SystemTime, ZoneItem)> = std::fs::read_dir(&d)
            .map(|rd| {
                rd.filter_map(|e| e.ok())
                    .filter_map(|e| {
                        let name = e.file_name().to_string_lossy().into_owned();
                        let md = e.metadata().ok()?;
                        if !md.is_file() || name.ends_with(".part") || [".sig", ".sig2", ".asc"].iter().any(|x| name.ends_with(x)) {
                            return None;
                        }
                        let signed = [".sig", ".sig2", ".asc"].iter().find(|x| d.join(format!("{name}{x}")).exists()).map(|x| x.to_string());
                        Some((md.modified().unwrap_or(std::time::UNIX_EPOCH), ZoneItem { name, size: md.len(), signed }))
                    })
                    .collect()
            })
            .unwrap_or_default();
        items.sort_by(|a, b| b.0.cmp(&a.0));
        self.zone = items.into_iter().map(|x| x.1).collect();
    }

    // ── the frame ──
    fn apply_look(&mut self, ctx: &egui::Context) {
        let dark = match self.skin.fixed_theme() {
            Some(d) => d,
            None => match self.theme.as_str() {
                "light" => false,
                "auto" => ctx.system_theme().map(|t| t == egui::Theme::Dark).unwrap_or(true),
                _ => true,
            },
        };
        if self.applied == Some((self.skin, dark)) {
            return;
        }
        let fonts_changed = self.applied.map(|a| a.0) != Some(self.skin);
        self.applied = Some((self.skin, dark));
        self.pal = skin::pal(self.skin, dark);
        if fonts_changed {
            ctx.set_fonts(skin::fonts(self.skin));
        }
        let theme = if dark { egui::Theme::Dark } else { egui::Theme::Light };
        ctx.set_theme(theme);
        let st = skin::style(&self.pal, &ctx.global_style());
        ctx.set_style_of(theme, st);
        self.sound.set_skin(self.skin);
    }

    pub fn set_skin(&mut self, s: Skin) {
        self.skin = s;
        data::save_conf("skin", s.id().into());
        self.sound.set_skin(s);
        self.sound.play("startup");
    }
    pub fn set_theme(&mut self, t: &str) {
        self.theme = t.into();
        data::save_conf("theme", t.into());
        self.sound.play("theme");
    }
}

pub fn verb(args: &[&str], what: &str, arg: &str) -> Act {
    let warn = if args.contains(&"outsource") {
        " This builds + runs code from that repo — only do it if you trust it."
    } else if arg.starts_with("aur/") {
        " AUR packages are built from random people's recipes — make sure you trust it."
    } else {
        ""
    };
    let cmd = args.iter().find(|a| !a.starts_with('-')).copied().unwrap_or("");
    Act::new(args).ask(format!("{what}{}?", if arg.is_empty() { String::new() } else { format!(" {arg}") }), format!("gurt will {cmd} {arg}.{warn}"))
}

pub fn parse_search(lines: &[String]) -> Vec<Hit> {
    let mut res: Vec<Hit> = Vec::new();
    let mut last: Option<usize> = None;
    for l in lines {
        let t = l.trim_end();
        let head = t.strip_suffix(" [installed]").unwrap_or(t);
        let parts: Vec<&str> = head.split(' ').collect();
        if parts.len() == 2 && !l.starts_with(' ') {
            if let Some((src, name)) = parts[0].split_once('/') {
                if !src.is_empty() && src.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-') && !name.is_empty() {
                    res.push(Hit { src: src.into(), name: name.into(), ver: parts[1].into(), desc: String::new() });
                    last = Some(res.len() - 1);
                    continue;
                }
            }
        }
        if let Some(i) = last {
            if l.starts_with("    ") {
                res[i].desc = data::no_emoji(l.trim());
                last = None;
            }
        }
    }
    res
}

pub fn zone_dir(st: &State) -> PathBuf {
    let base = if st.cache.is_empty() { data::home().join(".cache/gurt") } else { PathBuf::from(&st.cache) };
    let d = base.join("zone");
    let _ = std::fs::create_dir_all(&d);
    d
}

impl eframe::App for App {
    fn ui(&mut self, ui: &mut Ui, _frame: &mut eframe::Frame) {
        let ctx = ui.ctx().clone();
        self.apply_look(&ctx);
        self.poll_state();
        self.poll_job();
        self.poll_sizes();
        self.poll_dialogs();
        self.width = ctx.content_rect().width();
        // the quiet update check, right after opening
        if let Some(t) = self.bg_started {
            if t.elapsed() > Duration::from_millis(2500) && self.run.is_none() && self.loaded && !self.gated && self.dialog.is_none() {
                self.bg_started = None;
                self.check(true, true);
            } else if t.elapsed() <= Duration::from_millis(2500) {
                ctx.request_repaint_after(Duration::from_millis(300));
            }
        }
        // files dropped on the window
        let dropped: Vec<PathBuf> = ctx.input(|i| i.raw.dropped_files.iter().map(|f| f.path().to_path_buf()).collect());
        if let Some(f) = dropped.into_iter().next() {
            if self.tab == Tab::Files && self.cg_hover {
                self.cg_load(f);
            } else {
                self.install_file(f);
            }
        }
        let hovering = ctx.input(|i| !i.raw.hovered_files.is_empty());
        let p = self.pal;
        let bg = egui::Frame::new().fill(p.bg);
        egui::CentralPanel::default().frame(bg).show(ui, |ui| {
            if self.setup_app {
                crate::wizard::show_app(self, ui);
            } else if self.gated {
                self.gate_ui(ui);
            } else {
                self.header(ui);
                self.console_panel(ui);
                egui::CentralPanel::default().frame(egui::Frame::new().fill(p.bg).inner_margin(egui::Margin::symmetric(14, 10))).show(ui, |ui| {
                    if !self.loaded {
                        w::hint(ui, &p, "loading GURT…");
                        return;
                    }
                    match self.tab {
                        Tab::Discover => crate::tabs::discover(self, ui),
                        Tab::Installed => crate::tabs::installed(self, ui),
                        Tab::Updates => crate::tabs::updates(self, ui),
                        Tab::Setup => crate::tabs::setup(self, ui),
                        Tab::Desktops => crate::tabs::desktops(self, ui),
                        Tab::Files => crate::tabs::files(self, ui),
                    }
                });
            }
        });
        if hovering && !self.setup_app {
            let r = ctx.content_rect().shrink(18.0);
            let pt = ctx.layer_painter(egui::LayerId::new(egui::Order::Foreground, egui::Id::unique("dropzone")));
            pt.rect_filled(r, CornerRadius::same(p.r), p.panel.gamma_multiply(0.92));
            pt.rect_stroke(r, CornerRadius::same(p.r), Stroke::new(2.0, p.accent), StrokeKind::Inside);
            pt.text(r.center() - vec2(0.0, 12.0), Align2::CENTER_CENTER, "drop it to install", sansb(20.0), p.ink);
            pt.text(r.center() + vec2(0.0, 16.0), Align2::CENTER_CENTER, ".deb · .rpm · .pkg.tar.zst · AppImage · .tar.gz · .zip · .flatpak · .exe · .dmg — any distro, no box", mono(12.0), p.muted);
        }
        self.dialogs(&ctx);
        self.toast_ui(&ctx);
        if self.run.is_some() || self.loader.is_some() || self.lotto.as_ref().is_some_and(|l| l.spin_left > 0) {
            ctx.request_repaint_after(Duration::from_millis(100));
        }
        if self.quit {
            ctx.send_viewport_cmd(egui::ViewportCommand::Close);
        }
    }

    fn on_exit(&mut self, _gl: Option<&eframe::glow::Context>) {
        // let what gurt is doing finish before the app goes away
        if let Some(r) = &self.run {
            if !r.act.bg {
                while !r.job.done() {
                    std::thread::sleep(Duration::from_millis(300));
                }
            }
        }
    }
}

impl App {
    // ── header: logo, tabs, sync + look ──
    fn header(&mut self, ui: &mut Ui) {
        let p = self.pal;
        let narrow = self.width < 760.0;
        let frame = egui::Frame::new().fill(p.header).inner_margin(egui::Margin::symmetric(14, 8));
        egui::Panel::top("header").frame(frame).show_separator_line(false).show(ui, |ui| {
            let tabs: Vec<(Tab, &str)> = [
                (Tab::Discover, "Discover"),
                (Tab::Installed, "Installed"),
                (Tab::Updates, "Updates"),
                (Tab::Setup, "Setup"),
                (Tab::Desktops, "Desktops"),
                (Tab::Files, "Install a file"),
            ]
            .into_iter()
            .filter(|(t, _)| *t != Tab::Desktops || !(self.st.wsl || self.st.cros))
            .filter(|(t, _)| *t != Tab::Files || self.width > 900.0)
            .collect();
            let logo_row = |this: &mut App, ui: &mut Ui| {
                ui.vertical(|ui| {
                    ui.spacing_mut().item_spacing.y = 2.0;
                    crate::icons::logo(ui, &p, if this.src == "dirt" { 28.0 } else { 34.0 }, this.src == "dirt");
                    let mut v = format!("v{} · {}", this.st.version, this.st.pm);
                    if this.st.wsl {
                        v += " · Windows";
                    } else if this.st.cros {
                        v += " · ChromeOS";
                    }
                    ui.label(egui::RichText::new(v).font(mono(11.0)).color(if matches!(p.skin, Skin::Xp) { hex(0xc9dbff) } else if p.skin == Skin::W95 { hex(0xffffff) } else { p.muted }));
                });
            };
            let actions = |this: &mut App, ui: &mut Ui| {
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    let r = w::btn_on(ui, &p, "look", this.prefs_open, true);
                    if r.clicked() {
                        this.prefs_open = !this.prefs_open;
                        this.sound.play("click");
                    }
                    if this.prefs_open {
                        this.prefs_popup(ui, r.rect);
                    }
                    if w::btn(ui, &p, "sync", Kind::Ghost, true).on_hover_text("gurt sync").clicked() {
                        this.go(Act::new(&["sync"]));
                    }
                });
            };
            if narrow {
                ui.horizontal(|ui| {
                    logo_row(self, ui);
                    actions(self, ui);
                });
                egui::ScrollArea::horizontal().id_salt("navscroll").scroll_bar_visibility(egui::scroll_area::ScrollBarVisibility::AlwaysHidden).show(ui, |ui| {
                    ui.horizontal(|ui| self.nav(ui, &tabs));
                });
            } else {
                ui.horizontal(|ui| {
                    logo_row(self, ui);
                    ui.add_space(10.0);
                    self.nav(ui, &tabs);
                    actions(self, ui);
                });
            }
        });
        // GURT's 4-block brand stripe (hard stops) under the header; the other skins draw their own edge
        let r = ui.max_rect();
        let y = ui.min_rect().top();
        let _ = (r, y);
        egui::Panel::top("stripe").exact_size(if p.skin == Skin::Gurt { 4.0 } else if matches!(p.skin, Skin::Xp | Skin::Vapor | Skin::Gold) { 3.0 } else { 1.0 }).frame(egui::Frame::new()).show_separator_line(false).show(ui, |ui| {
            let r = ui.max_rect();
            let pt = ui.painter();
            match p.skin {
                Skin::Gurt => {
                    let cols = [hex(0xe8302a), hex(0xffc629), hex(0x1fa64a), hex(0x2456e0)];
                    for (i, c) in cols.iter().enumerate() {
                        let x0 = r.left() + r.width() * i as f32 / 4.0;
                        pt.rect_filled(Rect::from_min_max(pos2(x0, r.top()), pos2(x0 + r.width() / 4.0 + 1.0, r.bottom())), CornerRadius::ZERO, *c);
                    }
                }
                Skin::Xp => {
                    pt.rect_filled(r, CornerRadius::ZERO, hex(0x0a3fb0));
                }
                Skin::Vapor => {
                    pt.line_segment([r.left_top() + vec2(0.0, 0.5), r.right_top() + vec2(0.0, 0.5)], Stroke::new(1.0, skin::VAPOR_CYAN));
                    pt.line_segment([r.left_bottom() - vec2(0.0, 0.5), r.right_bottom() - vec2(0.0, 0.5)], Stroke::new(1.0, skin::VAPOR_CYAN));
                }
                Skin::Hacker => {
                    pt.extend(egui::Shape::dashed_line(&[r.left_center(), r.right_center()], Stroke::new(1.0, p.accent), 4.0, 3.0));
                }
                Skin::W95 => {
                    pt.rect_filled(r, CornerRadius::ZERO, hex(0x000000));
                }
                Skin::Win11 => {
                    pt.rect_filled(r, CornerRadius::ZERO, p.edge);
                }
                Skin::Gold => {
                    pt.line_segment([r.left_top() + vec2(0.0, 0.5), r.right_top() + vec2(0.0, 0.5)], Stroke::new(1.0, p.accent));
                    pt.line_segment([r.left_bottom() - vec2(0.0, 0.5), r.right_bottom() - vec2(0.0, 0.5)], Stroke::new(1.0, p.accent));
                }
            }
        });
    }

    fn nav(&mut self, ui: &mut Ui, tabs: &[(Tab, &str)]) {
        let p = self.pal;
        ui.spacing_mut().item_spacing.x = 2.0;
        for (t, label) in tabs {
            let badge = if *t == Tab::Updates && self.badge > 0 { Some(self.badge) } else { None };
            if w::tab(ui, &p, label, self.tab == *t, badge).clicked() && self.tab != *t {
                self.tab = *t;
                self.sound.play("click");
                if *t == Tab::Files {
                    self.load_zone();
                }
                if *t == Tab::Desktops && self.desktops.is_none() && !self.busy() {
                    self.go(Act::new(&["de", "list"]).quiet().then(After::Desktops));
                }
            }
        }
    }

    fn prefs_popup(&mut self, ui: &mut Ui, anchor: Rect) {
        let p = self.pal;
        let ctx = ui.ctx().clone();
        let area = egui::Area::new(egui::Id::unique("prefpop")).order(egui::Order::Foreground).fixed_pos(pos2((anchor.right() - 250.0).max(8.0), anchor.bottom() + 6.0));
        let resp = area.show(&ctx, |ui| {
            w::panel(ui, &p, |ui| {
                ui.set_width(230.0);
                ui.spacing_mut().item_spacing.y = 7.0;
                ui.label(egui::RichText::new("skin").font(mono(12.0)).color(p.muted));
                let cur = self.skin;
                egui::ComboBox::from_id_salt("skinsel").selected_text(skin::SKINS.iter().find(|s| s.0 == cur).unwrap().2).width(220.0).show_ui(ui, |ui| {
                    for (s, id, name) in skin::SKINS {
                        if s == Skin::Gold && !self.st.has(&format!("skin:{id}")) {
                            continue; // 🔑
                        }
                        if ui.selectable_label(cur == s, name).clicked() && cur != s {
                            self.set_skin(s);
                        }
                    }
                });
                ui.label(egui::RichText::new("music").font(mono(12.0)).color(p.muted));
                let tr = self.sound.track.clone();
                egui::ComboBox::from_id_salt("tracksel").selected_text(crate::sound::track_name(&tr)).width(220.0).show_ui(ui, |ui| {
                    for (id, name) in crate::sound::TRACKS {
                        if crate::sound::track_locked(id) && !self.st.has(&format!("track:{id}")) {
                            continue; // 🔑
                        }
                        if ui.selectable_label(tr == id, name).clicked() {
                            self.sound.set_track(id);
                        }
                    }
                });
                ui.horizontal_wrapped(|ui| {
                    let fo = self.st.fossonly;
                    if w::btn_on(ui, &p, &format!("FOSS only: {}", if fo { "on" } else { "off" }), fo, true)
                        .on_hover_text("only free software: hides and blocks closed-source apps (gurt foss on)")
                        .clicked()
                    {
                        self.go(Act::new(&["foss", if fo { "off" } else { "on" }]).quiet());
                    }
                    if w::btn(ui, &p, "setup wizard", Kind::Ghost, true).on_hover_text("walk through setting GURT up").clicked() {
                        self.prefs_open = false;
                        open_wizard_app(&mut *self);
                    }
                    if w::btn(ui, &p, "redeem a key", Kind::Ghost, true).on_hover_text("a GURT key unlocks secret apps, skins, music and achievements").clicked() {
                        self.prefs_open = false;
                        self.dialog = Some(Dialog::Redeem(String::new(), vec![], false));
                    }
                    if self.st.dev == "ok" && w::btn(ui, &p, "make a key", Kind::Primary, true).on_hover_text("dev builds: make a GURT key").clicked() {
                        self.prefs_open = false;
                        self.dialog = Some(Dialog::KeyGen(KeyGenView { picks: vec![false; KEY_UNLOCKS.len()], ..Default::default() }));
                    }
                });
                ui.horizontal_wrapped(|ui| {
                    let m = self.sound.music_on;
                    if w::btn(ui, &p, if m { "music on" } else { "music off" }, Kind::Ghost, true).clicked() {
                        self.sound.set_music(!m);
                    }
                    let s = self.sound.sfx_on;
                    if w::btn(ui, &p, if s { "sounds on" } else { "sounds off" }, Kind::Ghost, true).clicked() {
                        self.sound.set_sfx(!s);
                        self.sound.play("pop");
                    }
                    if self.skin.fixed_theme().is_none() {
                        let dark = self.pal.dark;
                        if w::btn(ui, &p, if dark { "light" } else { "dark" }, Kind::Ghost, true).clicked() {
                            self.set_theme(if dark { "light" } else { "dark" });
                        }
                    }
                });
            });
        });
        if ctx.input(|i| i.pointer.any_click()) && !resp.response.contains_pointer() && !ui.rect_contains_pointer(anchor) && !egui::Popup::is_any_open(&ctx) {
            self.prefs_open = false;
        }
        if ctx.input(|i| i.key_pressed(egui::Key::Escape)) {
            self.prefs_open = false;
        }
    }

    // ── the activity log at the bottom ──
    fn console_panel(&mut self, ui: &mut Ui) {
        let p = self.pal;
        let (bg, ink) = if p.skin == Skin::Xp { (hex(0x000000), hex(0xc0c0c0)) } else { (p.code, p.ink) };
        let h = if self.console_open { 220.0 } else { 30.0 };
        egui::Panel::bottom("console").exact_size(h).frame(egui::Frame::new().fill(bg)).show_separator_line(false).show(ui, |ui| {
            let r = ui.max_rect();
            ui.painter().line_segment([r.left_top(), r.right_top()], Stroke::new(1.0, p.edge));
            ui.horizontal(|ui| {
                ui.add_space(12.0);
                ui.set_height(28.0);
                let col = if self.run.as_ref().is_some_and(|r| !r.act.quiet) { p.accent } else { self.console_dot };
                w::dot(ui, col);
                ui.label(egui::RichText::new(&self.console_title).font(monob(12.0)).color(ink));
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    ui.add_space(10.0);
                    if w::btn(ui, &p, if self.console_open { "hide" } else { "show" }, Kind::Ghost, true).clicked() {
                        self.console_open = !self.console_open;
                    }
                    if self.run.as_ref().is_some_and(|r| !r.act.quiet) && w::btn(ui, &p, "stop", Kind::Ghost, true).clicked() {
                        if let Some(r) = &self.run {
                            r.job.cancel();
                        }
                    }
                });
            });
            if self.console_open {
                let r = ui.cursor();
                ui.painter().line_segment([pos2(r.left(), r.top()), pos2(ui.max_rect().right(), r.top())], Stroke::new(1.0, p.line));
                egui::ScrollArea::vertical().id_salt("cout").stick_to_bottom(true).auto_shrink([false, false]).show(ui, |ui| {
                    ui.add_space(4.0);
                    ui.spacing_mut().item_spacing.y = 1.0;
                    for l in &self.console {
                        let l = &data::no_emoji(l);
                        ui.horizontal(|ui| {
                            ui.add_space(12.0);
                            ui.add(egui::Label::new(egui::RichText::new(l).font(mono(12.0)).color(ink)).wrap());
                        });
                    }
                });
            }
        });
    }

    fn toast_ui(&mut self, ctx: &egui::Context) {
        let Some((t, at)) = &self.toast else { return };
        if at.elapsed() > Duration::from_millis(4200) {
            self.toast = None;
            return;
        }
        ctx.request_repaint_after(Duration::from_millis(250));
        let p = self.pal;
        let t = t.clone();
        egui::Area::new(egui::Id::unique("toast")).order(egui::Order::Tooltip).anchor(Align2::CENTER_BOTTOM, vec2(0.0, -48.0)).show(ctx, |ui| {
            w::panel(ui, &p, |ui| {
                ui.set_max_width(420.0);
                ui.label(egui::RichText::new(t).font(monob(12.5)).color(p.ink));
            });
        });
    }

    fn gate_ui(&mut self, ui: &mut Ui) {
        // GURT waits behind this until the setup wizard is finished
        let p = self.pal;
        if data::conf_str("wizard").as_deref() == Some("done") {
            self.gated = false;
            self.bg_started = Some(Instant::now());
            return;
        }
        ui.ctx().request_repaint_after(Duration::from_secs(2));
        ui.add_space(ui.available_height() * 0.12);
        ui.horizontal(|ui| {
            ui.add_space(24.0);
            ui.vertical(|ui| {
                ui.set_max_width(520.0);
                dialog_box(ui, &p, "Set up GURT first", |ui| {
                    ui.add(egui::Label::new(egui::RichText::new("GURT opens once you've finished the GURT Setup Wizard: a minute of questions about your sources, your look and your first apps.").color(p.muted)).wrap());
                    ui.add_space(6.0);
                    ui.horizontal(|ui| {
                        if w::btn(ui, &p, "open the setup wizard", Kind::Primary, false).clicked() {
                            open_wizard_app(self);
                        }
                        ui.label(egui::RichText::new("waiting for the wizard…").font(mono(12.0)).color(p.muted));
                    });
                });
            });
        });
    }
}

/// a row of buttons on the right (one row high: a bare right-to-left layout would take all the height there is)
pub fn right<R>(ui: &mut Ui, add: impl FnOnce(&mut Ui) -> R) -> R {
    ui.horizontal(|ui| ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), add).inner).inner
}

/// the setup wizard is its own app window
pub fn open_wizard_app(app: &mut App) {
    let me = std::env::current_exe().unwrap_or_else(|_| PathBuf::from("gurt-app"));
    let ok = std::process::Command::new(me)
        .args(["--gurt", data::gurt(), "--wizard", "--from-app"])
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .is_ok();
    app.toast(if ok { "the GURT Setup Wizard opened in its own window" } else { "couldn't open the setup wizard (try: gurt setup)" });
}

/// a dialog's look: a title row with a bottom border, then content
pub fn dialog_box<R>(ui: &mut Ui, p: &Pal, title: &str, add: impl FnOnce(&mut Ui) -> R) -> R {
    let (bar, bar_ink) = match p.skin {
        Skin::Xp => (hex(0x245edb), hex(0xffffff)),
        Skin::W95 => (hex(0x000080), hex(0xffffff)),
        _ => (p.panel, p.ink),
    };
    let frame = egui::Frame::new().fill(p.panel).corner_radius(CornerRadius::same(p.r));
    let inner = frame.show(ui, |ui| {
        let w = ui.available_width();
        let (r, _) = ui.allocate_exact_size(vec2(w, 32.0), Sense::hover());
        let rr = if p.skin == Skin::W95 { r.shrink(3.0) } else { r };
        ui.painter().rect_filled(rr, CornerRadius::ZERO, bar);
        if !matches!(p.skin, Skin::Xp | Skin::W95) {
            ui.painter().line_segment([r.left_bottom(), r.right_bottom()], Stroke::new(1.0, p.edge));
        }
        let f = if p.skin == Skin::Hacker { monob(14.0) } else if p.skin == Skin::Win11 { sansb(17.0) } else { sansb(14.0) };
        ui.painter().text(pos2(rr.left() + 10.0, rr.center().y), Align2::LEFT_CENTER, title, f, if p.skin == Skin::Vapor { skin::VAPOR_YELLOW } else { bar_ink });
        egui::Frame::new().inner_margin(egui::Margin { left: 12, right: 12, top: 8, bottom: 12 }).show(ui, add).inner
    });
    match p.skin {
        Skin::W95 => w::bevel(ui, inner.response.rect, false),
        Skin::Xp => {
            ui.painter().rect_stroke(inner.response.rect, CornerRadius::same(p.r), Stroke::new(3.0, hex(0x0a3fb0)), StrokeKind::Inside);
        }
        Skin::Vapor => w::double_rect(ui, inner.response.rect, skin::VAPOR_CYAN),
        Skin::Gold => w::double_rect(ui, inner.response.rect, p.accent),
        _ => w::box_border(ui, p, inner.response.rect),
    }
    inner.inner
}

/// a modal window in GURT's style; returns (content's value, closed by Esc / clicking outside)
pub fn modal<R>(ctx: &egui::Context, p: &Pal, id: &str, title: &str, width: f32, add: impl FnOnce(&mut Ui) -> R) -> (R, bool) {
    let m = egui::Modal::new(egui::Id::unique(id)).frame(egui::Frame::new()).backdrop_color(Color32::from_black_alpha(110)).show(ctx, |ui| {
        let maxw = (ctx.content_rect().width() - 24.0).min(width);
        ui.set_width(maxw);
        dialog_box(ui, p, title, |ui| {
            ui.set_max_height(ctx.content_rect().height() - 120.0);
            add(ui)
        })
    });
    let close = m.should_close();
    (m.inner, close)
}

impl App {
    pub fn icon(&mut self, ui: &Ui, r: Rect, name: &str) {
        let p = self.pal;
        let st = self.st.clone();
        let pkg = st.pkg(name);
        let remote = pkg.map(|p| p.icon.clone()).unwrap_or_default();
        let wants: Vec<String> = match pkg {
            Some(p) => std::iter::once(p.name.clone()).chain(std::iter::once(p.flatpak.clone())).chain(p.alias.iter().cloned()).collect(),
            None => vec![name.to_string()],
        };
        if !self.icons.paint(ui, r, name, &remote, &wants) {
            w::letter_tile(ui, &p, r, name);
        }
    }
}

// size + dialog data that loads in the background
impl App {
    fn poll_sizes(&mut self) {
        if let Some(rx) = &self.size_rx {
            if let Ok(s) = rx.try_recv() {
                self.sizes = Some(s);
                self.size_rx = None;
            }
        }
    }
    fn poll_dialogs(&mut self) {
        if let Some(rx) = &self.dlg_rx {
            if let Ok(d) = rx.try_recv() {
                self.dialog = Some(d);
                self.dlg_rx = None;
            }
        }
        if !self.seen_ver_checked && self.loaded && !self.setup_app && !self.gated {
            self.seen_ver_checked = true;
        }
    }
    /// open a dialog whose content loads in the background
    pub fn open_dialog(&mut self, placeholder: Dialog, load: impl FnOnce() -> Dialog + Send + 'static) {
        self.dialog = Some(placeholder);
        let (tx, rx) = channel();
        std::thread::spawn(move || {
            let _ = tx.send(load());
            if let Some(r) = jobs::REPAINT.get() {
                r();
            }
        });
        self.dlg_rx = Some(rx);
    }
}


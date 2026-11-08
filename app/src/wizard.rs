//! the GURT Setup Wizard: its own app window (gurt gui --wizard), a classic installer. 7 steps, then it runs what you picked
use crate::app::{Act, After, App};
use crate::data;
use crate::skin::{self, hex, mono, monob, sans, sansb, Skin};
use crate::widgets::{self as w, Kind};
use egui::{vec2, CornerRadius, Rect, Sense, Stroke, Ui};
use std::collections::BTreeSet;
use std::sync::mpsc::{channel, Receiver};

const STEPS: [&str; 7] = ["Welcome", "System check", "App sources", "Your look", "Starter apps", "Extras", "Install"];
const STARTER: [(&str, &[&str]); 7] = [
    ("Browsers", &["firefox", "brave", "librewolf", "zen-browser", "chromium"]),
    ("Chat", &["vesktop", "telegram", "signal", "element"]),
    ("Media", &["vlc", "mpv", "spotube", "obs-studio", "kdenlive"]),
    ("Creative", &["gimp", "krita", "inkscape", "blender"]),
    ("Office", &["libreoffice", "onlyoffice", "joplin", "thunderbird"]),
    ("Dev", &["vscodium", "zed", "neovim", "btop"]),
    ("Gaming", &["steam", "heroic", "lutris", "prismlauncher", "bottles"]),
];
const SRCS: [(&str, &str, &str); 10] = [
    ("flatpak", "Flathub", "sandboxed apps, and where most Main GURT apps come from"),
    ("aur", "the AUR", "Arch's user repo, built from source on your PC (gurt checks the build scripts for red flags first)"),
    ("apt", "Debian / Ubuntu repos", "apt/ packages on any distro"),
    ("dnf", "Fedora repos", "dnf/ packages on any distro"),
    ("zypper", "openSUSE repos", "zypper/ packages on any distro"),
    ("pacman", "Arch repos", "pacman/ packages on any distro"),
    ("apk", "Alpine repos", "apk/ packages (musl systems, or scripts and data anywhere)"),
    ("xbps", "Void repos", "xbps/ packages on any distro"),
    ("eopkg", "Solus repos", "eopkg/ packages on any distro"),
    ("gentoo", "Gentoo's binary packages", "gentoo/ packages on any distro"),
];

pub struct Task {
    label: String,
    args: Vec<String>,
    st: &'static str, // "" | run | ok | bad
    log: String,
}

pub struct Wiz {
    step: usize,
    state: &'static str, // edit | running | done
    utils: bool,
    srcs: BTreeSet<String>,
    apps: BTreeSet<String>,
    notify: bool,
    hook: bool,
    launch: bool,
    tasks: Vec<Task>,
    doc: Option<data::Doctor>,
    doc_rx: Option<Receiver<data::Doctor>>,
    imported: String,
    quit_ask: bool,
}

impl Wiz {
    pub fn new(app: &App) -> Wiz {
        let (tx, rx) = channel();
        std::thread::spawn(move || {
            let _ = tx.send(data::doctor());
            if let Some(r) = crate::jobs::REPAINT.get() {
                r();
            }
        });
        Wiz {
            step: 0, state: "edit", utils: true, srcs: ["flatpak".to_string()].into(), apps: BTreeSet::new(), notify: true, hook: true,
            launch: !app.from_app, tasks: vec![], doc: None, doc_rx: Some(rx), imported: String::new(), quit_ask: false,
        }
    }
    fn tasks(&self, app: &App) -> Vec<Task> {
        let mut t = Vec::new();
        let miss = self.doc.as_ref().map(|d| d.missing.clone()).unwrap_or_default();
        let s = |v: &[&str]| v.iter().map(|x| x.to_string()).collect::<Vec<_>>();
        if !miss.is_empty() && (self.utils || (self.srcs.contains("flatpak") && miss.iter().any(|m| m == "flatpak"))) {
            t.push(Task { label: format!("install the utilities apps need ({})", miss.join(", ")), args: s(&["-y", "utils"]), st: "", log: String::new() });
        }
        for src in &self.srcs {
            if src == "flatpak" {
                continue;
            }
            let name = SRCS.iter().find(|x| x.0 == src).map(|x| x.1).unwrap_or(src);
            t.push(Task { label: format!("get the {name} package list"), args: s(&["sync", src]), st: "", log: String::new() });
        }
        if !self.apps.is_empty() {
            let n = self.apps.len();
            let mut a = s(&["-y", "install"]);
            a.extend(self.apps.iter().cloned());
            t.push(Task { label: format!("install {n} app{}: {}", if n == 1 { "" } else { "s" }, self.apps.iter().cloned().collect::<Vec<_>>().join(", ")), args: a, st: "", log: String::new() });
        }
        if self.hook && !app.st.hook {
            t.push(Task { label: "turn on Hotwyr (GURT backs up your package manager)".into(), args: s(&["hotwyr", "on"]), st: "", log: String::new() });
        }
        if self.notify && !self.doc.as_ref().is_some_and(|d| d.notify) {
            t.push(Task { label: "turn on update alerts".into(), args: s(&["notify", "on"]), st: "", log: String::new() });
        }
        t
    }
}

/// a task finished: mark it, start the next one (or wrap up)
pub fn task_done(app: &mut App, i: usize, rc: i32, lines: &[String]) {
    let Some(wz) = &mut app.wiz else { return };
    if let Some(t) = wz.tasks.get_mut(i) {
        t.st = if rc == 0 { "ok" } else { "bad" };
        if rc != 0 {
            t.log = lines[lines.len().saturating_sub(12)..].join("\n");
        }
    }
    run_next(app, i + 1);
}
fn run_next(app: &mut App, i: usize) {
    let Some(wz) = &mut app.wiz else { return };
    if let Some(t) = wz.tasks.get_mut(i) {
        t.st = "run";
        let args: Vec<&str> = t.args.iter().map(|s| s.as_str()).collect();
        let a = Act::new(&args).quiet().then(After::Wizard(i));
        app.go(a);
        return;
    }
    wz.state = "done";
    app.sound.play("ok");
    finished(app);
}
fn finished(app: &App) {
    data::save_conf("wizard", "done".into());
    data::save_conf("seen", app.st.version.clone().into());
    let _ = std::process::Command::new(data::gurt()).args(["__achieve", "wizard"]).stdout(std::process::Stdio::null()).stderr(std::process::Stdio::null()).spawn();
}
fn quit(app: &mut App, open: bool) {
    if open {
        let me = std::env::current_exe().unwrap_or_else(|_| "gurt-app".into());
        let _ = std::process::Command::new(me).args(["--gurt", data::gurt()]).stdin(std::process::Stdio::null()).stdout(std::process::Stdio::null()).stderr(std::process::Stdio::null()).spawn();
    }
    app.quit = true;
}

fn opt(ui: &mut Ui, app: &App, on: &mut bool, title: &str, sub: &str, enabled: bool) -> bool {
    let p = app.pal;
    let c = w::check_row(ui, &p, on, title, sub, enabled);
    ui.add_space(4.0);
    c
}

/// a pickable chip: a skin, a track, a starter app
fn choice(ui: &mut Ui, app: &App, text: &str, on: bool, enabled: bool) -> egui::Response {
    w::btn_ex(ui, &app.pal, text, if on { Kind::Primary } else { Kind::Ghost }, true, on && app.pal.skin == Skin::W95, enabled)
}

pub fn show_app(app: &mut App, ui: &mut Ui) {
    let p = app.pal;
    if let Some(wz) = &mut app.wiz {
        if let Some(rx) = &wz.doc_rx {
            if let Ok(d) = rx.try_recv() {
                wz.doc = Some(d);
                wz.doc_rx = None;
            }
        }
    }
    if app.wiz.is_none() {
        // still loading (or the dev lock is up)
        ui.centered_and_justified(|ui| {
            ui.label(egui::RichText::new("loading…").color(p.muted));
        });
        return;
    }
    let step = app.wiz.as_ref().unwrap().step;
    let state = app.wiz.as_ref().unwrap().state;
    // the title bar: the skin's accent (GURT yellow, XP blue, 95 navy)
    let (bar, bar_ink) = match p.skin {
        Skin::Xp => (hex(0x245edb), hex(0xffffff)),
        Skin::W95 => (hex(0x000080), hex(0xffffff)),
        Skin::Hacker => (hex(0x000000), p.accent),
        _ => (p.accent, p.accent_ink),
    };
    egui::Panel::top("wiztop").exact_size(56.0).frame(egui::Frame::new().fill(bar).inner_margin(egui::Margin::symmetric(14, 8))).show_separator_line(false).show(ui, |ui| {
        ui.vertical(|ui| {
            ui.spacing_mut().item_spacing.y = 2.0;
            ui.label(egui::RichText::new("GURT Setup Wizard").font(monob(15.0)).color(bar_ink));
            ui.label(egui::RichText::new(format!("step {} of {}: {}", step + 1, STEPS.len(), STEPS[step])).font(mono(12.0)).color(bar_ink));
        });
        if p.skin == Skin::Hacker {
            let r = ui.max_rect();
            ui.painter().extend(egui::Shape::dashed_line(&[r.left_bottom() + vec2(-14.0, 8.0), r.right_bottom() + vec2(14.0, 8.0)], Stroke::new(1.0, p.accent), 4.0, 3.0));
        }
    });
    // the footer: Cancel · < Back · Next >
    let mut nav: Option<&'static str> = None;
    egui::Panel::bottom("wizfoot").exact_size(50.0).frame(egui::Frame::new().fill(p.panel).inner_margin(egui::Margin::symmetric(14, 10))).show_separator_line(false).show(ui, |ui| {
        let r = ui.max_rect();
        ui.painter().line_segment([r.left_top() - vec2(14.0, 10.0), r.right_top() + vec2(14.0, -10.0)], Stroke::new(1.0, p.edge));
        ui.horizontal(|ui| {
            if state == "edit" && w::btn(ui, &p, "Cancel", Kind::Ghost, false).clicked() {
                nav = Some("cancel");
            }
            crate::app::right(ui, |ui| {
                let wz = app.wiz.as_ref().unwrap();
                let next = if step < 6 { "Next >" } else if state == "edit" { if wz.tasks(app).is_empty() { "Finish" } else { "Install" } } else { "Finish" };
                if w::btn_ex(ui, &p, next, Kind::Primary, false, false, state != "running").clicked() {
                    nav = Some("next");
                }
                if w::btn_ex(ui, &p, "< Back", Kind::Ghost, false, false, step > 0 && state == "edit").clicked() {
                    nav = Some("back");
                }
            });
        });
    });
    let narrow = app.width < 640.0;
    if !narrow {
        egui::Panel::left("wizrail").exact_size(190.0).frame(egui::Frame::new().fill(p.panel).inner_margin(egui::Margin::symmetric(6, 12))).show_separator_line(false).show(ui, |ui| {
            let r = ui.max_rect();
            ui.painter().line_segment([r.right_top() + vec2(6.0, -12.0), r.right_bottom() + vec2(6.0, 12.0)], Stroke::new(1.0, p.edge));
            for (i, n) in STEPS.iter().enumerate() {
                let (col, f) = if i == step { (p.ink, monob(12.5)) } else if i < step { (p.muted, mono(12.5)) } else { (p.muted.gamma_multiply(0.8), mono(12.5)) };
                let mark = if i < step { "✓" } else { "" };
                ui.label(egui::RichText::new(format!("{}. {n} {mark}", i + 1)).font(f).color(col));
            }
        });
    }
    egui::CentralPanel::default().frame(egui::Frame::new().fill(p.bg).inner_margin(egui::Margin::symmetric(16, 14))).show(ui, |ui| {
        egui::ScrollArea::vertical().auto_shrink([false, false]).show(ui, |ui| {
            ui.set_max_width(ui.available_width().min(720.0));
            page(app, ui, step);
        });
    });
    // Cancel before it's done = GURT stays locked; the wizard comes back next time
    if app.wiz.as_ref().unwrap().quit_ask {
        let mut ans = None;
        let ctx = ui.ctx().clone();
        let (_, closed) = crate::app::modal(&ctx, &p, "wizquit", "Quit the setup wizard?", 420.0, |ui| {
            ui.add(egui::Label::new(egui::RichText::new("GURT opens once the setup wizard is finished. It'll be here next time.").color(p.muted)).wrap());
            ui.add_space(8.0);
            crate::app::right(ui, |ui| {
                if w::btn(ui, &p, "Yeah", Kind::Primary, false).clicked() {
                    ans = Some(true);
                }
                if w::btn(ui, &p, "Nah", Kind::Ghost, false).clicked() {
                    ans = Some(false);
                }
            });
        });
        if closed {
            ans = Some(false);
        }
        if let Some(a) = ans {
            app.wiz.as_mut().unwrap().quit_ask = false;
            if a {
                quit(app, false);
            }
        }
    }
    match nav {
        Some("back") => {
            app.wiz.as_mut().unwrap().step -= 1;
            app.sound.play("click");
        }
        Some("cancel") => {
            if data::conf_str("wizard").as_deref() == Some("done") {
                quit(app, false);
            } else {
                app.wiz.as_mut().unwrap().quit_ask = true;
            }
        }
        Some("next") => {
            app.sound.play("click");
            if step < 6 {
                app.wiz.as_mut().unwrap().step += 1;
            } else if state == "edit" {
                let t = app.wiz.as_ref().unwrap().tasks(app);
                if t.is_empty() {
                    finished(app);
                    let l = app.wiz.as_ref().unwrap().launch;
                    quit(app, l);
                } else {
                    let wz = app.wiz.as_mut().unwrap();
                    wz.tasks = t;
                    wz.state = "running";
                    run_next(app, 0);
                }
            } else {
                let l = app.wiz.as_ref().unwrap().launch;
                quit(app, l);
            }
        }
        _ => {}
    }
}

fn page(app: &mut App, ui: &mut Ui, step: usize) {
    let p = app.pal;
    let h = |ui: &mut Ui, t: &str| {
        w::heading(ui, &p, t, 18.0);
        ui.add_space(4.0);
    };
    let para = |ui: &mut Ui, t: &str| {
        ui.add(egui::Label::new(egui::RichText::new(t).font(sans(14.0)).color(if p.skin == Skin::W95 { hex(0xffffff) } else { p.muted })).wrap());
        ui.add_space(6.0);
    };
    match step {
        0 => {
            h(ui, "Welcome to the GURT Setup Wizard");
            if !app.st.version.is_empty() {
                ui.label(egui::RichText::new(format!("GURT {} is installed", app.st.version)).font(sansb(14.0)).color(p.ink));
                ui.add_space(6.0);
            }
            para(ui, "This wizard finishes installing GURT on your computer: it checks your system, sets up the places apps come from, picks your look, and installs a few starter apps if you want some.");
            para(ui, "It takes about a minute, and you can change all of it later. Click Next to continue.");
        }
        1 => {
            h(ui, "System check");
            let wz = app.wiz.as_mut().unwrap();
            match &wz.doc {
                None => para(ui, "checking your system…"),
                Some(d) => {
                    para(ui, "here's what GURT found.");
                    let chk = |ui: &mut Ui, ok: bool, title: &str, sub: &str| {
                        ui.horizontal(|ui| {
                            ui.label(egui::RichText::new(if ok { "✓" } else { "!" }).font(monob(15.0)).color(if ok { p.good } else { p.bad }));
                            ui.vertical(|ui| {
                                ui.spacing_mut().item_spacing.y = 0.0;
                                ui.label(egui::RichText::new(title).font(sansb(14.0)).color(p.ink));
                                ui.add(egui::Label::new(egui::RichText::new(sub).font(sans(12.5)).color(p.muted)).wrap());
                            });
                        });
                        ui.add_space(4.0);
                    };
                    w::panel(ui, &p, |ui| {
                        ui.set_width(ui.available_width());
                        let extra = if d.wsl { " · running in WSL on Windows" } else if d.cros { " · Linux on ChromeOS" } else { "" };
                        chk(ui, true, if d.distro.is_empty() { "your distro" } else { &d.distro }, &format!("package manager: {}{extra}", d.pm));
                        chk(ui, d.sudo, if d.sudo { "sudo works" } else { "no sudo or doas" }, if d.sudo { "GURT asks for your password when it installs things system-wide" } else { "install sudo, or run GURT as root" });
                        let n = d.missing.len();
                        chk(ui, n == 0, &if n > 0 { format!("{n} utilit{} missing", if n == 1 { "y" } else { "ies" }) } else { "every utility apps need is here".into() }, &if n > 0 { d.missing.join(", ") } else { "flatpak, git, unzip tools, a compiler…".into() });
                    });
                    ui.add_space(8.0);
                    if !d.missing.is_empty() {
                        let mut u = wz.utils;
                        w::check_row(ui, &p, &mut u, "install the missing utilities", "recommended: most apps need some of these to install", true);
                        app.wiz.as_mut().unwrap().utils = u;
                    }
                }
            }
        }
        2 => {
            h(ui, "App sources");
            let pm = app.wiz.as_ref().unwrap().doc.as_ref().map(|d| format!(" ({})", d.pm)).unwrap_or_default();
            para(ui, &format!("where should GURT get apps? your own distro's repos{pm} and Main GURT always work. these are extra, and you can use any of them later too."));
            for (id, name, sub) in SRCS {
                let mut on = app.wiz.as_ref().unwrap().srcs.contains(id);
                if opt(ui, app, &mut on, name, sub, true) {
                    let wz = app.wiz.as_mut().unwrap();
                    if on { wz.srcs.insert(id.into()); } else { wz.srcs.remove(id); }
                }
            }
        }
        3 => {
            h(ui, "Your look");
            para(ui, "pick a skin (every skin has its own sound effects), a music track, and light or dark. try them, it changes right away.");
            ui.horizontal_wrapped(|ui| {
                for (s, id, name) in skin::SKINS {
                    if s == Skin::Gold && !app.st.has(&format!("skin:{id}")) {
                        continue; // 🔑
                    }
                    if choice(ui, app, name, app.skin == s, true).clicked() && app.skin != s {
                        app.set_skin(s);
                    }
                }
            });
            ui.add_space(10.0);
            ui.label(egui::RichText::new("music").font(monob(13.0)).color(p.ink));
            ui.horizontal_wrapped(|ui| {
                let on = app.sound.music_on;
                for (id, name) in crate::sound::TRACKS {
                    if crate::sound::track_locked(id) && !app.st.has(&format!("track:{id}")) {
                        continue; // 🔑
                    }
                    if choice(ui, app, name, on && app.sound.track == id, true).clicked() {
                        app.sound.set_track(id);
                    }
                }
                if choice(ui, app, "no music", !on, true).clicked() {
                    app.sound.set_music(false);
                }
            });
            ui.add_space(10.0);
            ui.label(egui::RichText::new("light or dark").font(monob(13.0)).color(p.ink));
            ui.horizontal_wrapped(|ui| {
                let fixed = app.skin.fixed_theme().is_some();
                for (id, name) in [("dark", "dark (default)"), ("light", "light"), ("auto", "match my system")] {
                    if choice(ui, app, name, app.theme == id, !fixed).clicked() {
                        app.set_theme(id);
                    }
                }
            });
            if app.skin.fixed_theme().is_some() {
                ui.add_space(4.0);
                w::hint(ui, &p, "this skin only comes one way, like the real thing");
            }
        }
        4 => {
            h(ui, "Starter apps");
            para(ui, &format!("tick a few to install now, or skip this. there are {} more in Discover.", app.st.main.len()));
            let st = app.st.clone();
            for (g, names) in STARTER {
                let names: Vec<&str> = names.iter().copied().filter(|n| st.pkg(n).is_some()).collect();
                if names.is_empty() {
                    continue;
                }
                ui.label(egui::RichText::new(g).font(monob(13.0)).color(p.ink));
                ui.horizontal_wrapped(|ui| {
                    for n in names {
                        let done = st.inst(n).is_some();
                        let on = app.wiz.as_ref().unwrap().apps.contains(n);
                        let label = if done { format!("{n} ✓") } else { n.to_string() };
                        if choice(ui, app, &label, on, !done).clicked() {
                            let wz = app.wiz.as_mut().unwrap();
                            if on { wz.apps.remove(n); } else { wz.apps.insert(n.into()); }
                            app.sound.play(if on { "unpick" } else { "pick" });
                        }
                    }
                });
                ui.add_space(6.0);
            }
            ui.horizontal(|ui| {
                if w::btn(ui, &p, "surprise me", Kind::Ghost, true).clicked() {
                    let pool: Vec<String> = st.main.iter().filter(|m| st.inst(&m.name).is_none() && !app.wiz.as_ref().unwrap().apps.contains(&m.name)).map(|m| m.name.clone()).collect();
                    if !pool.is_empty() {
                        let n = pool[data::rand_below(pool.len() as u32) as usize].clone();
                        app.wiz.as_mut().unwrap().apps.insert(n);
                        app.sound.play("jackpot");
                    }
                }
                if w::btn(ui, &p, "import a list from your old PC", Kind::Ghost, true).on_hover_text("a list you exported (export my list) or a profile from your old PC").clicked() {
                    if let Some(f) = crate::tabs::pick_file("pick a list or a profile") {
                        import_list(app, &f);
                    }
                }
                ui.label(egui::RichText::new(format!("{} picked", app.wiz.as_ref().unwrap().apps.len())).font(mono(12.0)).color(p.muted));
            });
            let im = app.wiz.as_ref().unwrap().imported.clone();
            if !im.is_empty() {
                w::hint(ui, &p, &im);
            }
        }
        5 => {
            h(ui, "Extras");
            para(ui, "a couple more things.");
            let pm = app.wiz.as_ref().unwrap().doc.as_ref().map(|d| d.pm.clone()).unwrap_or_else(|| "your package manager".into());
            let already = app.wiz.as_ref().unwrap().doc.as_ref().is_some_and(|d| d.notify);
            let mut hk = app.wiz.as_ref().unwrap().hook;
            opt(ui, app, &mut hk, &format!("Hotwyr: GURT backs up {pm}"), &format!("when {pm} can't find something (sudo {pm} install yay), GURT offers it from another source. its upgrades, searches and \"command not found\" include GURT too"), true);
            let mut nt = app.wiz.as_ref().unwrap().notify || already;
            opt(ui, app, &mut nt, "tell me when updates are waiting", if already { "already on" } else { "a desktop notification, checked every 6 hours" }, !already);
            let wz = app.wiz.as_mut().unwrap();
            wz.hook = hk;
            wz.notify = nt;
        }
        _ => {
            let state = app.wiz.as_ref().unwrap().state;
            if state == "edit" {
                let t = app.wiz.as_ref().unwrap().tasks(app);
                if t.is_empty() {
                    h(ui, "Nothing to install");
                    para(ui, "you're all set click Finish and go explore.");
                } else {
                    h(ui, "Ready to install");
                    para(ui, "GURT is about to:");
                    for x in &t {
                        ui.horizontal(|ui| {
                            ui.label(egui::RichText::new("·").font(monob(14.0)).color(p.muted));
                            ui.add(egui::Label::new(egui::RichText::new(&x.label).color(p.ink)).wrap());
                        });
                    }
                    ui.add_space(8.0);
                    para(ui, "click Install to start. it might ask for your password.");
                }
            } else {
                h(ui, if state == "done" { "All done" } else { "Installing…" });
                let wz = app.wiz.as_ref().unwrap();
                let done = wz.tasks.iter().filter(|t| t.st == "ok" || t.st == "bad").count();
                let frac = if wz.tasks.is_empty() { 1.0 } else { done as f32 / wz.tasks.len() as f32 };
                let (r, _) = ui.allocate_exact_size(vec2(ui.available_width(), 14.0), Sense::hover());
                ui.painter().rect_filled(r, CornerRadius::same(p.r), p.tag);
                ui.painter().rect_stroke(r, CornerRadius::same(p.r), Stroke::new(1.0, p.edge), egui::StrokeKind::Inside);
                ui.painter().rect_filled(Rect::from_min_size(r.min, vec2(r.width() * frac, r.height())), CornerRadius::same(p.r), p.accent);
                ui.add_space(8.0);
                for t in &wz.tasks {
                    ui.horizontal(|ui| {
                        let (m, c) = match t.st { "ok" => ("✓", p.good), "bad" => ("✗", p.bad), "run" => ("…", p.accent), _ => ("·", p.muted) };
                        ui.label(egui::RichText::new(m).font(monob(14.0)).color(c));
                        ui.add(egui::Label::new(egui::RichText::new(&t.label).color(p.ink)).wrap());
                        if t.st == "bad" {
                            ui.label(egui::RichText::new("didn't work").font(mono(12.0)).color(p.bad));
                        }
                    });
                    if t.st == "bad" && !t.log.is_empty() {
                        egui::Frame::new().fill(p.code).inner_margin(6).show(ui, |ui| {
                            ui.add(egui::Label::new(egui::RichText::new(&t.log).font(mono(11.0)).color(p.ink)).wrap());
                        });
                    }
                }
                if state == "done" {
                    ui.add_space(8.0);
                    let bad = wz.tasks.iter().any(|t| t.st == "bad");
                    para(ui, &format!("{}GURT is set up click Finish.", if bad { "some of it didn't work, but everything else is ready. " } else { "" }));
                }
            }
            if state != "running" {
                ui.add_space(8.0);
                let mut l = app.wiz.as_ref().unwrap().launch;
                opt(ui, app, &mut l, "open GURT when I click Finish", "", true);
                app.wiz.as_mut().unwrap().launch = l;
            }
        }
    }
}

/// an exported list or a profile → its apps join the install
fn import_list(app: &mut App, f: &std::path::Path) {
    let mut text = std::fs::read_to_string(f).unwrap_or_default();
    if let Some(i) = text.find("\n[apps]\n").or_else(|| text.starts_with("[apps]\n").then_some(0)) {
        let rest = &text[i..].trim_start_matches('\n')["[apps]\n".len()..];
        text = rest.split("\n[").next().unwrap_or("").to_string();
    }
    let (mut added, mut skipped) = (0, 0);
    for line in text.lines() {
        let l = line.split('#').next().unwrap_or("").trim();
        if l.is_empty() {
            continue;
        }
        if l.starts_with("outsource ") || !data::spec_ok(l) || l.contains(':') {
            skipped += 1;
            continue;
        }
        if app.st.inst(l).is_none() && app.wiz.as_mut().unwrap().apps.insert(l.to_string()) {
            added += 1;
        }
    }
    let name = f.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
    app.wiz.as_mut().unwrap().imported = format!("{name}: added {added} app{}{}", if added == 1 { "" } else { "s" }, if skipped > 0 { format!(", skipped {skipped} (git repos: gurt import {name} does those)") } else { String::new() });
    app.sound.play(if added > 0 { "ok" } else { "pop" });
}

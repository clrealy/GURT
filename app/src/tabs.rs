//! the six tabs
use crate::app::{verb, Act, After, App, Dialog, Hit, Lotto};
use crate::data::{self, fmt_size, InstHit};
use crate::skin::{hex, mono, monob, sans, sansb, Pal, Skin};
use crate::widgets::{self as w, ChipKind, Kind};
use egui::{pos2, vec2, Align2, Color32, CornerRadius, Rect, Sense, Stroke, Ui, UiBuilder};
use std::time::{Duration, Instant};

pub const SOURCES: [(&str, &str); 20] = [
    ("gurt", "Main GURT"), ("aur", "Arch User Repo"), ("apt", "Debian · Ubuntu"), ("dnf", "Fedora"), ("zypper", "openSUSE"), ("pacman", "Arch"),
    ("xbps", "Void"), ("eopkg", "Solus"), ("apk", "Alpine"), ("gentoo", "Gentoo"), ("gh", "GitHub releases"), ("appimage", "AppImageHub"),
    ("pip", "PyPI"), ("npm", "npm"), ("cargo", "crates.io"), ("brew", "Homebrew"), ("flatpak", "Flathub"), ("snap", "Snap Store"), ("nix", "nixpkgs"), ("dirt", "18+"),
];
fn blurb(src: &str) -> &'static str {
    match src {
        "aur" => "The Arch User Repository — PKGBUILDs gurt builds from source, on any distro.",
        "apt" => "Debian's packages (.deb). gurt downloads, checks and installs them on whatever you run.",
        "dnf" => "Fedora's packages (.rpm), installable anywhere.",
        "zypper" => "openSUSE Tumbleweed's packages — yes, even on Red Star OS",
        "pacman" => "Arch's official binary packages, installable on non-Arch distros.",
        "xbps" => "Void Linux's binary packages, installable on non-Void distros.",
        "eopkg" => "Solus's binary packages, installable on non-Solus distros.",
        "apk" => "Alpine's packages. They're built for musl, so on glibc only scripts and data install.",
        "gentoo" => "Gentoo's official binary packages, installable on non-Gentoo distros.",
        "gh" => "Apps straight from GitHub releases. gurt picks the file for your system, checks it and keeps it updated.",
        "appimage" => "AppImageHub's catalog. Apps with a GitHub release install and update through gh/.",
        "pip" => "Python apps, each in its own venv, with their commands on your PATH.",
        "npm" => "Node.js command-line apps, each in its own folder.",
        "cargo" => "Rust apps, built on your PC with cargo.",
        "brew" => "Homebrew on Linux: installs as you, so it works on locked-down systems too.",
        "flatpak" => "Flathub apps, sandboxed. gurt sets up flatpak + Flathub for you.",
        "snap" => "Snap Store apps. gurt sets up snapd for you.",
        "nix" => "nixpkgs, into your own nix profile. no sudo.",
        "dirt" => "DIRT is GURT's mature section (18+). Packages here install with gurt install dirt/<name>.",
        _ => "",
    }
}

pub fn trust(k: &str) -> Option<(ChipKind, &'static str, &'static str)> {
    Some(match k {
        "official" => (ChipKind::Hi, "official repo", "comes from the app maker's own signed repo"),
        "apt" => (ChipKind::Hi, "distro repo", "from Debian's signed repos, checked by gurt"),
        "dnf" => (ChipKind::Hi, "distro repo", "from Fedora's signed repos, checked by gurt"),
        "zypper" => (ChipKind::Hi, "distro repo", "from openSUSE's signed repos, checked by gurt"),
        "pacman" => (ChipKind::Hi, "distro repo", "from Arch's repos (packages checked against the repo's sha256)"),
        "flathub" | "flatpak" => (ChipKind::Hi, "Flathub", "a Flathub app: sandboxed, and Flathub reviews what gets published"),
        "snap" => (ChipKind::Mid, "Snap Store", "from the Snap Store (Canonical's app store)"),
        "prebuilt" => (ChipKind::Mid, "official download", "the app maker's own release download, checked against a checksum pinned in Main GURT"),
        "source" => (ChipKind::Mid, "built from source", "built on your computer from the project's own code, at a pinned version"),
        "gurt" => (ChipKind::Mid, "Main GURT", "a Main GURT recipe (every change is reviewed and CI-tested)"),
        "aur" => (ChipKind::Lo, "user upload", "the AUR: anyone can upload, nobody reviews it. gurt shows you the build script and checks it for red flags first"),
        "git" => (ChipKind::Lo, "random repo", "built straight from a git repo you picked. gurt checks the build script for red flags first"),
        "file" => (ChipKind::Lo, "your file", "a file you installed yourself"),
        "dirt" => (ChipKind::Lo, "DIRT", "from the DIRT repo"),
        _ => return None,
    })
}

// ── rows: the lists are virtual (only what's on screen gets drawn), so 2,700 apps scroll smoothly ──
pub enum Row {
    Head(String),
    Main(usize),
    Dirt(usize),
    Hit(Hit),
    Gh(usize),
    Inst(usize),
    Outside(String, String),
    Up(usize),
    De(usize),
    Empty(String),
    Lotto,
}

pub struct Card {
    pub icon: String,
    pub name: String,
    pub src: String,
    pub ver: String,
    pub desc: String,
    pub extra: String,
    pub chips: Vec<(String, ChipKind, String)>,
    pub btns: Vec<(String, Kind, Btn)>,
}
#[derive(Clone)]
pub enum Btn {
    Run(Act),
    Cmp(String),
    Pick(String),
    Done,
}

fn row_h(app: &App, r: &Row) -> f32 {
    let narrow = app.width < 720.0;
    match r {
        Row::Head(_) => 26.0,
        Row::Empty(_) => 44.0,
        Row::Lotto => 96.0,
        Row::Gh(_) => if narrow { 112.0 } else { 58.0 },
        _ => if narrow { 98.0 } else { 46.0 },
    }
}

pub fn rows(app: &mut App, ui: &mut Ui, rows: &[Row], id: &str) {
    let p = app.pal;
    let heights: Vec<f32> = rows.iter().map(|r| row_h(app, r)).collect();
    let mut tops = Vec::with_capacity(heights.len() + 1);
    let mut y = 0.0;
    for h in &heights {
        tops.push(y);
        y += h;
    }
    let total = y;
    w::list_frame(ui, &p, |ui| {
        egui::ScrollArea::vertical().id_salt(id.to_string()).auto_shrink([false, false]).show_viewport(ui, |ui, vp| {
            ui.set_height(total);
            let origin = ui.max_rect().min;
            let width = ui.available_width();
            let first = tops.partition_point(|t| *t + 60.0 < vp.min.y).saturating_sub(1);
            for i in first..rows.len() {
                if tops[i] > vp.max.y {
                    break;
                }
                let rect = Rect::from_min_size(origin + vec2(0.0, tops[i]), vec2(width, heights[i]));
                let mut child = ui.new_child(UiBuilder::new().max_rect(rect).layout(egui::Layout::top_down(egui::Align::Min)));
                draw_row(app, &mut child, &rows[i], rect, i + 1 < rows.len());
            }
        });
    });
}

fn draw_row(app: &mut App, ui: &mut Ui, row: &Row, rect: Rect, sep: bool) {
    let p = app.pal;
    let card = match row {
        Row::Head(t) => {
            w::list_head(ui, &p, t);
            return;
        }
        Row::Empty(t) => {
            ui.painter().text(pos2(rect.left() + 14.0, rect.center().y), Align2::LEFT_CENTER, t, sans(13.5), p.muted);
            return;
        }
        Row::Lotto => {
            lotto_row(app, ui, rect);
            return;
        }
        Row::Main(i) => {
            let st = app.st.clone();
            let m = &st.main[*i];
            let mut chips = Vec::new();
            if let Some(t) = trust(&m.trust) {
                chips.push((t.1.to_string(), t.0, t.2.to_string()));
            }
            if m.foss == "closed" {
                chips.push(("closed source".into(), ChipKind::Closed, format!("closed source: nobody outside the company can check what's in it (license: {})", m.license)));
            }
            let mut btns = install_btns(app, &m.name);
            btns.push(("compare".into(), Kind::Ghost, Btn::Cmp(m.name.clone())));
            Card { icon: m.name.clone(), name: m.name.clone(), src: "gurt".into(), ver: m.ver.clone(), desc: m.desc.clone(), extra: String::new(), chips, btns }
        }
        Row::Dirt(i) => {
            let st = app.st.clone();
            let m = &st.dirtpkgs[*i];
            Card { icon: m.name.clone(), name: m.name.clone(), src: "dirt".into(), ver: m.ver.clone(), desc: m.desc.clone(), extra: String::new(),
                chips: vec![("DIRT".into(), ChipKind::Lo, "from the DIRT repo".into())], btns: install_btns(app, &format!("dirt/{}", m.name)) }
        }
        Row::Hit(h) => {
            let spec = if h.src == "gurt" { h.name.clone() } else { format!("{}/{}", h.src, h.name) };
            let mut chips = Vec::new();
            if let Some(t) = trust(&h.src) {
                chips.push((t.1.to_string(), t.0, t.2.to_string()));
            }
            Card { icon: h.name.clone(), name: h.name.clone(), src: h.src.clone(), ver: h.ver.clone(), desc: h.desc.clone(), extra: String::new(), chips, btns: install_btns(app, &spec) }
        }
        Row::Gh(i) => {
            let st = app.st.clone();
            let a = &st.ghonly[*i];
            let key = format!("gh:{}", a.repo.split('/').nth(1).unwrap_or("").to_lowercase());
            let btns = match st.installed.iter().find(|x| x.key == key) {
                Some(x) => vec![("installed ✓".into(), Kind::Ghost, Btn::Done), ("remove".into(), Kind::Ghost, Btn::Run(verb(&["-y", "remove", &x.spec], "Remove", &x.spec)))],
                None => {
                    let spec = format!("gh/{}", a.repo);
                    vec![("install".into(), Kind::Primary, Btn::Run(verb(&["-y", "install", &spec], "Install", &spec)))]
                }
            };
            Card { icon: a.name.clone(), name: a.name.clone(), src: "gh".into(), ver: String::new(), desc: a.desc.clone(), extra: format!("github.com/{}", a.repo), chips: vec![], btns }
        }
        Row::Inst(i) => {
            let st = app.st.clone();
            let it = &st.installed[*i];
            let (src, tr) = origin(&st, it);
            let mut chips = Vec::new();
            if let Some(t) = trust(&tr) {
                chips.push((t.1.to_string(), t.0, t.2.to_string()));
            }
            if !it.via.is_empty() || it.src == "gurt" {
                chips.push(("Main GURT recipe".into(), ChipKind::Plain, if it.via.is_empty() { "Main GURT recipe".into() } else { format!("Main GURT recipe → {}", it.via) }));
            }
            if it.reason == "dep" {
                chips.push(("dependency".into(), ChipKind::Plain, String::new()));
            }
            if it.held {
                chips.push(("held".into(), ChipKind::Plain, String::new()));
            }
            if let Some(b) = app.sizes.as_ref().and_then(|s| s.get(&it.key)) {
                chips.push((fmt_size(*b), ChipKind::Plain, "space it takes on your disk".into()));
            }
            let s = it.spec.clone();
            let btns = vec![
                ("remove".into(), Kind::Danger, Btn::Run(verb(&["-y", "remove", &s], "Remove", &s))),
                ("rollback".into(), Kind::Ghost, Btn::Run(verb(&["-y", "rollback", &s], "Roll back", &s))),
                if it.held {
                    ("unhold".into(), Kind::Ghost, Btn::Run(verb(&["-y", "unhold", &s], "Unhold", &s)))
                } else {
                    ("hold".into(), Kind::Ghost, Btn::Run(verb(&["-y", "hold", &s], "Hold", &s)))
                },
            ];
            Card { icon: it.name.clone(), name: it.name.clone(), src, ver: it.ver.clone(), desc: it.desc.clone(), extra: String::new(), chips, btns }
        }
        Row::Outside(n, how) => {
            let st = app.st.clone();
            let desc = st.pkg(n).map(|m| m.desc.clone()).unwrap_or_default();
            let src = if how == "on your PATH" || how == "/opt" { "system".to_string() } else { how.clone() };
            Card { icon: n.clone(), name: n.clone(), src, ver: String::new(), desc, extra: String::new(),
                chips: vec![(format!("installed ✓ ({how})"), ChipKind::Ok, format!("installed with {}, not with gurt", data::how_label(how)))], btns: vec![] }
        }
        Row::Up(i) => {
            let Some(Ok(ups)) = &app.ups else { return };
            let u = &ups[*i];
            Card { icon: u.name.clone(), name: u.name.clone(), src: u.src.clone(), ver: u.ver.clone(), desc: u.desc.clone(), extra: String::new(), chips: vec![], btns: vec![(u.btn.into(), Kind::Primary, Btn::Run(u.act.clone()))] }
        }
        Row::De(i) => {
            let Some(Ok((des, _))) = &app.desktops else { return };
            let (name, title, desc, ok) = des[*i].clone();
            let btns = if ok { vec![("install".into(), Kind::Primary, Btn::Run(verb(&["-y", "de", "install", &name], "Install the desktop", &name)))] } else { vec![] };
            let chips = if ok { vec![] } else { vec![("not in your distro's repos".into(), ChipKind::Plain, String::new())] };
            Card { icon: title.clone(), name: title, src: name, ver: String::new(), desc, extra: String::new(), chips, btns }
        }
    };
    if let Some(b) = card_ui(app, ui, &card, rect, sep) {
        click(app, b);
    }
}

pub fn click(app: &mut App, b: Btn) {
    match b {
        Btn::Run(a) => app.go(a),
        Btn::Cmp(n) => {
            if let Some(i) = app.cmp.iter().position(|x| *x == n) {
                app.cmp.remove(i);
                app.sound.play("unpick");
            } else if app.cmp.len() < 4 {
                app.cmp.push(n);
                app.sound.play("pick");
            } else {
                app.sound.play("err");
            }
        }
        Btn::Pick(n) => {
            app.picked.insert(n);
            app.sound.play("pick");
        }
        Btn::Done => {}
    }
}

/// where an installed app really came from: a Main GURT recipe that installed a Flathub app is a flatpak
fn origin(st: &data::State, i: &data::Installed) -> (String, String) {
    if !i.via.is_empty() {
        let s = i.via.split('/').next().unwrap_or("").to_string();
        let t = if s == "flatpak" { "flatpak".into() } else if s == "snap" { "snap".into() } else if trust(&s).is_some() { s.clone() } else { "official".into() };
        return (s, t);
    }
    let t = if i.src == "gurt" { st.pkg(&i.name).map(|m| m.trust.clone()).unwrap_or_else(|| "gurt".into()) } else { i.src.clone() };
    (i.src.clone(), t)
}

pub fn install_btns(app: &App, spec: &str) -> Vec<(String, Kind, Btn)> {
    match app.st.inst(spec) {
        Some(InstHit::External(how)) => vec![(format!("installed ✓ ({how})"), Kind::Ghost, Btn::Done)],
        Some(InstHit::Gurt(s)) => vec![("installed ✓".into(), Kind::Ghost, Btn::Done), ("remove".into(), Kind::Ghost, Btn::Run(verb(&["-y", "remove", &s], "Remove", &s)))],
        None => vec![("install".into(), Kind::Primary, Btn::Run(verb(&["-y", "install", spec], "Install", spec)))],
    }
}

fn elide(ui: &Ui, text: &str, font: egui::FontId, col: Color32, width: f32, rows: usize) -> std::sync::Arc<egui::Galley> {
    let mut job = egui::text::LayoutJob::simple(text.to_string(), font, col, width.max(10.0));
    job.wrap.max_rows = rows;
    job.wrap.break_anywhere = rows == 1;
    job.wrap.overflow_character = Some('…');
    ui.painter().layout_job(job)
}

/// one row: logo · name src/ ver | what it is | chips | buttons. narrow windows stack it
pub fn card_ui(app: &mut App, ui: &mut Ui, c: &Card, rect: Rect, sep: bool) -> Option<Btn> {
    let p = app.pal;
    let hov = ui.rect_contains_pointer(rect);
    let (ink, sub) = match (hov, p.hl_ink) {
        (true, Some(hi)) => (hi, hex(0xdfe9ff)),
        _ => (p.ink, p.muted),
    };
    if hov {
        ui.painter().rect_filled(rect, CornerRadius::ZERO, p.hl);
    }
    if sep {
        let y = rect.bottom() - 0.5;
        if p.skin == Skin::Hacker {
            ui.painter().extend(egui::Shape::dashed_line(&[pos2(rect.left(), y), pos2(rect.right(), y)], Stroke::new(1.0, p.line), 3.0, 3.0));
        } else if p.skin == Skin::W95 {
            ui.painter().extend(egui::Shape::dotted_line(&[pos2(rect.left(), y), pos2(rect.right(), y)], hex(0xc0c0c0), 3.0, 0.6));
        } else {
            ui.painter().line_segment([pos2(rect.left(), y), pos2(rect.right(), y)], Stroke::new(1.0, p.line));
        }
    }
    let narrow = app.width < 720.0;
    let pad = 10.0;
    let ico = 24.0;
    let name_col = if p.skin == Skin::Vapor { p.accent } else { ink };
    let src_col = if p.skin == Skin::Vapor { crate::skin::VAPOR_CYAN } else { sub };
    let ver_col = if p.skin == Skin::Vapor { crate::skin::VAPOR_YELLOW } else { sub };
    let name_txt = if p.skin == Skin::Hacker { format!("$ {}", c.name) } else { c.name.clone() };
    let desc = data::no_emoji(&c.desc);
    let mut clicked = None;
    let busy = app.busy();
    let cmp = app.cmp.clone();
    // buttons (right side, or their own line when narrow)
    let btn_area = |ui: &mut Ui, r: Rect, clicked: &mut Option<Btn>| {
        let mut child = ui.new_child(UiBuilder::new().max_rect(r).layout(egui::Layout::right_to_left(egui::Align::Center)));
        child.spacing_mut().item_spacing.x = 5.0;
        for (label, kind, b) in c.btns.iter().rev() {
            let on = matches!(b, Btn::Cmp(n) if cmp.contains(n));
            let resp = match b {
                Btn::Done => w::chip(&mut child, &p, label, ChipKind::Ok),
                Btn::Cmp(_) => w::btn_on(&mut child, &p, label, on, true).on_hover_text("compare side by side"),
                _ => w::btn_ex(&mut child, &p, label, *kind, true, false, !busy || matches!(b, Btn::Pick(_))),
            };
            if resp.clicked() && !matches!(b, Btn::Done) {
                *clicked = Some(b.clone());
            }
        }
        child.min_rect().width()
    };
    // XP + 95: a hovered row goes navy/blue, so its chips go white
    let cp = match (hov, p.hl_ink) {
        (true, Some(hi)) => Pal { ink: hi, good: hi, bad: hi, muted: hex(0xdfe9ff), edge: hex(0xdfe9ff), ..p },
        _ => p,
    };
    let chip_area = |ui: &mut Ui, r: Rect| {
        let mut child = ui.new_child(UiBuilder::new().max_rect(r).layout(egui::Layout::left_to_right(egui::Align::Center)));
        child.spacing_mut().item_spacing.x = 4.0;
        for (t, k, tip) in &c.chips {
            let resp = w::chip(&mut child, &cp, t, *k);
            if !tip.is_empty() {
                resp.on_hover_text(tip.as_str());
            }
        }
    };
    if !narrow {
        let cy = rect.center().y;
        let ir = Rect::from_center_size(pos2(rect.left() + pad + ico / 2.0, cy), vec2(ico, ico));
        app.icon(ui, ir, &c.icon);
        // buttons first, from the right: they decide how much room is left
        let bw_guess = c.btns.iter().map(|(l, _, _)| 16.0 + 7.4 * l.chars().count() as f32 + if p.skin == Skin::Hacker { 30.0 } else { 0.0 }).sum::<f32>() + 6.0 * c.btns.len() as f32;
        let br = Rect::from_min_max(pos2(rect.right() - pad - bw_guess.max(10.0) - 40.0, rect.top()), pos2(rect.right() - pad, rect.bottom()));
        let used = btn_area(ui, br, &mut clicked);
        let right_edge = rect.right() - pad - used - 10.0;
        let chip_w: f32 = c.chips.iter().map(|(t, _, _)| 14.0 + 6.8 * t.chars().count() as f32).sum::<f32>() + 4.0 * c.chips.len() as f32;
        let chip_x = right_edge - chip_w;
        chip_area(ui, Rect::from_min_max(pos2(chip_x, rect.top()), pos2(right_edge, rect.bottom())));
        // name column: 22% (at least 150px)
        let x0 = ir.right() + 8.0;
        let col_w = (rect.width() * 0.22).max(150.0);
        let g = elide(ui, &name_txt, monob(13.0), name_col, col_w - 8.0, 1);
        let line2 = format!("{}/ {}", c.src, c.ver);
        if c.extra.is_empty() || true {
            ui.painter().galley(pos2(x0, cy - g.size().y + 1.0), g, name_col);
            let g2 = elide(ui, line2.trim(), mono(11.0), src_col, col_w - 8.0, 1);
            ui.painter().galley(pos2(x0, cy + 2.0), g2, ver_col);
        }
        let dx = rect.left() + pad + ico + 8.0 + col_w + 6.0;
        let dw = (chip_x - dx - 10.0).max(40.0);
        let dg = elide(ui, &desc, sans(13.5), ink, dw, if c.extra.is_empty() { 2 } else { 1 });
        let dh = dg.size().y + if c.extra.is_empty() { 0.0 } else { 16.0 };
        ui.painter().galley(pos2(dx, cy - dh / 2.0), dg.clone(), ink);
        if !c.extra.is_empty() {
            let eg = elide(ui, &c.extra, mono(11.0), sub, dw, 1);
            let er = Rect::from_min_size(pos2(dx, cy - dh / 2.0 + dg.size().y + 2.0), eg.size());
            ui.painter().galley(er.min, eg, sub);
            let r = ui.interact(er, ui.scope_id().with(("link", &c.extra)), Sense::click()).on_hover_cursor(egui::CursorIcon::PointingHand);
            if r.clicked() {
                ui.ctx().open_url(egui::OpenUrl::new_tab(format!("https://{}", c.extra)));
            }
        }
    } else {
        let top = rect.top() + 8.0;
        let ir = Rect::from_min_size(pos2(rect.left() + pad, top), vec2(ico, ico));
        app.icon(ui, ir, &c.icon);
        let x0 = ir.right() + 8.0;
        let g = elide(ui, &name_txt, monob(13.0), name_col, rect.width() * 0.6, 1);
        let gw = g.size().x;
        ui.painter().galley(pos2(x0, top + 4.0), g, name_col);
        ui.painter().text(pos2(x0 + gw + 6.0, top + 5.0), Align2::LEFT_TOP, format!("{}/ {}", c.src, c.ver).trim(), mono(11.0), src_col);
        let dg = elide(ui, &desc, sans(13.0), ink, rect.width() - 2.0 * pad, 2);
        let dy = top + ico + 6.0;
        let dh = dg.size().y;
        ui.painter().galley(pos2(rect.left() + pad, dy), dg, ink);
        let mut ey = dy + dh + 2.0;
        if !c.extra.is_empty() {
            let eg = elide(ui, &c.extra, mono(11.0), sub, rect.width() - 2.0 * pad, 1);
            ui.painter().galley(pos2(rect.left() + pad, ey), eg, sub);
            ey += 15.0;
        }
        let br = Rect::from_min_max(pos2(rect.left() + pad, ey.min(rect.bottom() - 28.0)), pos2(rect.right() - pad, rect.bottom() - 4.0));
        let used = btn_area(ui, br, &mut clicked);
        chip_area(ui, Rect::from_min_max(br.min, pos2(br.right() - used - 6.0, br.bottom())));
    }
    clicked
}

// ── Discover ──
pub fn discover(app: &mut App, ui: &mut Ui) {
    let p = app.pal;
    let st = app.st.clone();
    // source buttons
    ui.horizontal_wrapped(|ui| {
        ui.spacing_mut().item_spacing = vec2(4.0, 4.0);
        for (src, sub) in SOURCES {
            if src == "nix" && !st.nix || src == "snap" && st.nixos {
                continue;
            }
            if w::src_btn(ui, &p, src, sub, app.src == src, src == "dirt").clicked() && app.src != src {
                app.sound.play("click");
                if src == "dirt" {
                    app.dialog = Some(Dialog::DirtGate);
                } else {
                    set_src(app, src);
                }
            }
        }
    });
    ui.add_space(6.0);
    if app.src != "gurt" {
        w::hint(ui, &p, blurb(&app.src));
        ui.add_space(4.0);
    }
    // search
    let main = app.src == "gurt";
    let mut enter = false;
    let narrow = app.width < 720.0;
    let hint = if main { "search Main GURT… (Enter searches every source)".to_string() } else if app.src == "dirt" { "search DIRT…".to_string() } else { format!("search {}/… and hit Enter", app.src) };
    let field = |app: &mut App, ui: &mut Ui, wdt: f32, enter: &mut bool| {
        let te = egui::TextEdit::singleline(&mut app.q).hint_text(hint.clone()).font(mono(14.0)).margin(vec2(10.0, 7.0)).desired_width(wdt);
        let r = ui.add(te);
        if r.lost_focus() && ui.input(|i| i.key_pressed(egui::Key::Enter)) {
            *enter = true;
        }
        if r.changed() && app.q.is_empty() {
            app.all_open = false;
            app.all = None;
        }
        if ui.input(|i| i.key_pressed(egui::Key::Slash)) && !r.has_focus() && app.dialog.is_none() && !ui.ctx().egui_wants_keyboard_input() {
            r.request_focus();
        }
    };
    let buttons = |app: &mut App, ui: &mut Ui, enter: &mut bool| {
        if main && w::btn_ex(ui, &p, "search everywhere", Kind::Primary, false, false, !app.busy()).clicked() {
            *enter = true;
        }
        more_menu(app, ui, "discover", &[("install a file", 1), ("convert a package", 2), ("app lottery", 3)]);
    };
    if narrow {
        field(app, ui, ui.available_width(), &mut enter);
        ui.horizontal(|ui| buttons(app, ui, &mut enter));
    } else {
        ui.horizontal(|ui| {
            let room = ui.available_width() - if main { 260.0 } else { 100.0 };
            field(app, ui, room, &mut enter);
            buttons(app, ui, &mut enter);
        });
    }
    if enter {
        if main { app.search_all() } else { app.search_src() }
    }
    if main {
        w::hint_mono(ui, &p, "tip: aur/yay, apt/cowsay, flatpak/gimp… type a full name with a source and hit install");
    }
    // a full spec typed in: install it straight away
    let q = app.q.trim().to_string();
    let direct = q.contains('/') && !q.starts_with("http") && data::spec_ok(&q) && q.split('/').next().is_some_and(|s| SOURCES.iter().any(|x| x.0 == s) || s == "gh");
    if direct && w::btn_ex(ui, &p, &format!("install {q}"), Kind::Primary, false, false, !app.busy()).clicked() {
        app.go(verb(&["-y", "install", &q], "Install", &q));
    }
    ui.add_space(6.0);
    let mut list: Vec<Row> = Vec::new();
    if app.lotto.as_ref().is_some_and(|l| !l.in_setup) {
        list.push(Row::Lotto);
    }
    let ql = q.to_lowercase();
    match app.src.as_str() {
        "gurt" => {
            if app.all_open {
                list.push(Row::Head("everywhere".into()));
                match &app.all {
                    None => list.push(Row::Empty("searching every source…".into())),
                    Some(Err(e)) => list.push(Row::Empty(e.clone())),
                    Some(Ok(hits)) => list.extend(hits.iter().take(120).cloned().map(Row::Hit)),
                }
                list.push(Row::Head("Main GURT".into()));
            }
            let vk = vibe_key(&ql);
            let vapps: Vec<String> = st.vibes.get(&vk).cloned().unwrap_or_default();
            let mut vhits: Vec<usize> = vapps.iter().filter_map(|n| st.main.iter().position(|m| &m.name == n)).collect();
            vhits.sort_by_key(|i| st.main[*i].foss == "closed");
            let hits: Vec<usize> = (0..st.main.len()).filter(|i| !vapps.contains(&st.main[*i].name) && (ql.is_empty() || st.main[*i].search.contains(&ql))).collect();
            if !vhits.is_empty() {
                list.push(Row::Head(format!("apps like {vk}")));
                list.extend(vhits.into_iter().map(Row::Main));
                if !hits.is_empty() {
                    list.push(Row::Head("everything else that matched".into()));
                }
            }
            if hits.is_empty() && vapps.is_empty() {
                list.push(Row::Empty("nothing in Main GURT matched — try \"search everywhere\" (or \"like photoshop\")".into()));
            }
            list.extend(hits.into_iter().map(Row::Main));
        }
        "dirt" => {
            let ql = ql.trim_start_matches("dirt/").to_string();
            let hits: Vec<Row> = (0..st.dirtpkgs.len()).filter(|i| ql.is_empty() || st.dirtpkgs[*i].search.contains(&ql)).map(Row::Dirt).collect();
            if hits.is_empty() {
                list.push(Row::Empty(if st.dirtpkgs.is_empty() { "DIRT is empty rn".into() } else { "nothing in DIRT matched".into() }));
            }
            list.extend(hits);
        }
        src => match &app.src_res {
            Some(Ok(h)) if !q.is_empty() => list.extend(h.iter().take(120).cloned().map(Row::Hit)),
            Some(Err(e)) if !q.is_empty() => list.push(Row::Empty(e.clone())),
            None if !q.is_empty() && app.busy() => list.push(Row::Empty(format!("searching {src}…"))),
            _ if src == "gh" && !st.ghonly.is_empty() => {
                let mut last = String::new();
                for (i, a) in st.ghonly.iter().enumerate() {
                    if a.cat != last {
                        list.push(Row::Head(format!("only on GitHub: {}", a.cat)));
                        last = a.cat.clone();
                    }
                    list.push(Row::Gh(i));
                }
            }
            _ => list.push(Row::Empty(format!("type something and hit Enter to search {src}"))),
        },
    }
    // the compare tray
    if !app.cmp.is_empty() {
        ui.horizontal(|ui| {
            ui.label(egui::RichText::new(format!("{}{}", app.cmp.join(" · "), if app.cmp.len() < 2 { "  (pick one more)" } else { "" })).font(mono(12.5)).color(p.ink));
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                if w::btn_ex(ui, &p, "compare", Kind::Primary, true, false, app.cmp.len() >= 2).clicked() {
                    if app.sizes.is_none() {
                        app.load_sizes();
                    }
                    app.dialog = Some(Dialog::Compare);
                    let _ = std::process::Command::new(data::gurt()).args(["__achieve", "compare"]).stdout(std::process::Stdio::null()).stderr(std::process::Stdio::null()).spawn();
                }
                if w::btn(ui, &p, "clear", Kind::Ghost, true).clicked() {
                    app.cmp.clear();
                }
            });
        });
        ui.add_space(4.0);
    }
    rows(app, ui, &list, "maingrid");
}

fn vibe_key(q: &str) -> String {
    let mut t = q.trim();
    for pre in ["something ", "apps ", "an app "] {
        t = t.strip_prefix(pre).unwrap_or(t);
    }
    for pre in ["like ", "alternatives to ", "alternative to ", "instead of "] {
        t = t.strip_prefix(pre).unwrap_or(t);
    }
    t.trim().to_string()
}

pub fn set_src(app: &mut App, src: &str) {
    app.src = src.into();
    app.src_res = None;
    app.all_open = false;
    if !app.q.trim().is_empty() && src != "gurt" && src != "dirt" {
        app.search_src();
    }
}

/// a "… more" menu: the stuff you don't need every day
fn more_menu(app: &mut App, ui: &mut Ui, id: &'static str, items: &[(&str, u8)]) {
    let p = app.pal;
    let r = w::btn_on(ui, &p, "… more", app.more_open == Some(id), false);
    if r.clicked() {
        app.more_open = if app.more_open == Some(id) { None } else { Some(id) };
    }
    if app.more_open != Some(id) {
        return;
    }
    let ctx = ui.ctx().clone();
    let mut pick = None;
    let a = egui::Area::new(egui::Id::unique(("more", id))).order(egui::Order::Foreground).fixed_pos(pos2((r.rect.right() - 190.0).max(8.0), r.rect.bottom() + 4.0)).show(&ctx, |ui| {
        w::panel(ui, &p, |ui| {
            ui.set_width(170.0);
            for (label, k) in items {
                let kind = if *k == 3 { Kind::Primary } else { Kind::Ghost };
                if w::btn(ui, &p, label, kind, true).clicked() {
                    pick = Some(*k);
                }
            }
        });
    });
    if pick.is_some() || (ctx.input(|i| i.pointer.any_click()) && !a.response.contains_pointer() && !r.clicked()) || ctx.input(|i| i.key_pressed(egui::Key::Escape)) {
        app.more_open = None;
    }
    match (id, pick) {
        ("discover", Some(1)) => {
            if let Some(f) = pick_file("pick a package to install") {
                app.install_file(f);
            }
        }
        ("discover", Some(2)) => {
            app.tab = crate::app::Tab::Files;
            app.load_zone();
        }
        ("discover", Some(3)) => spin(app, false),
        ("installed", Some(1)) => {
            let out = data::unique_path(&data::downloads_dir(), &format!("gurt-list-{}.txt", today_ymd()));
            let o = out.display().to_string();
            app.go(Act::new(&["export", &o]));
            app.toast(format!("saving your list to {o}. on another computer (any distro): Installed → import a list"));
        }
        ("installed", Some(2)) => {
            if let Some(f) = pick_file("pick a list you exported") {
                let n = std::fs::read_to_string(&f).unwrap_or_default().lines().filter(|l| !l.split('#').next().unwrap_or("").trim().is_empty()).count();
                if n == 0 {
                    app.toast("that list is empty");
                } else {
                    let name = f.file_name().map(|x| x.to_string_lossy().into_owned()).unwrap_or_default();
                    let fp = f.display().to_string();
                    app.go(Act::new(&["-y", "import", &fp]).ask(format!("Install {n} package(s) from {name}?"), "gurt installs everything on the list. Already-installed ones get skipped."));
                }
            }
        }
        ("installed", Some(3)) => app.open_dialog(Dialog::History(vec![]), || Dialog::History(data::history())),
        ("installed", Some(4)) => app.open_dialog(Dialog::Achievements(None), || Dialog::Achievements(Some(data::achievements()))),
        _ => {}
    }
}

fn today_ymd() -> String {
    std::process::Command::new("date").arg("+%Y-%m-%d").output().map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string()).unwrap_or_else(|_| "today".into())
}

/// a file picker (your desktop's own: zenity / kdialog / yad). no picker? drop the file on the window instead
pub fn pick_file(title: &str) -> Option<std::path::PathBuf> {
    let tries: [(&str, Vec<String>); 4] = [
        ("kdialog", vec!["--title".into(), title.into(), "--getopenfilename".into(), data::home().display().to_string()]),
        ("zenity", vec!["--file-selection".into(), format!("--title={title}")]),
        ("qarma", vec!["--file-selection".into(), format!("--title={title}")]),
        ("yad", vec!["--file".into(), format!("--title={title}")]),
    ];
    let kde = std::env::var("XDG_CURRENT_DESKTOP").unwrap_or_default().to_uppercase().contains("KDE");
    let order: Vec<&(&str, Vec<String>)> = if kde { tries.iter().collect() } else { tries.iter().skip(1).chain(tries.iter().take(1)).collect() };
    for (cmd, args) in order {
        if data::has(cmd) {
            let out = std::process::Command::new(cmd).args(args).stderr(std::process::Stdio::null()).output().ok()?;
            let s = String::from_utf8_lossy(&out.stdout).trim().to_string();
            return (!s.is_empty()).then(|| s.into());
        }
    }
    None
}

// ── the app lottery ──
pub fn spin(app: &mut App, in_setup: bool) {
    if app.lotto.as_ref().is_some_and(|l| l.spin_left > 0) || app.st.main.is_empty() {
        return;
    }
    let l = data::lotto_spin();
    let pool = &app.st.main;
    let leg: Vec<&data::Pkg> = pool.iter().filter(|p| data::LEGENDARY.contains(&p.name.as_str())).collect();
    let mut rarity = l.rarity;
    let win = if rarity == "legendary" && !leg.is_empty() {
        leg[data::rand_below(leg.len() as u32) as usize].name.clone()
    } else {
        if rarity == "legendary" {
            rarity = "epic";
        }
        pool[data::rand_below(pool.len() as u32) as usize].name.clone()
    };
    app.lotto = Some(Lotto { win, rarity, streak: l.streak, best: l.best, spin_left: if rarity == "legendary" { 30 } else { 18 }, next: Instant::now(), showing: String::new(), in_setup });
}

fn lotto_row(app: &mut App, ui: &mut Ui, rect: Rect) {
    let p = app.pal;
    let Some(l) = &mut app.lotto else { return };
    if l.spin_left > 0 && Instant::now() >= l.next {
        l.spin_left -= 1;
        let i = data::rand_below(app.st.main.len() as u32) as usize;
        l.showing = app.st.main[i].name.clone();
        l.next = Instant::now() + Duration::from_millis(40 + (30 - l.spin_left.min(30)) as u64 * 6);
        app.sound.play("tick");
        if l.spin_left == 0 {
            let leg = l.rarity == "legendary";
            app.sound.play(if leg { "legendary" } else { "jackpot" });
            let mut ach = vec![];
            if leg {
                ach.push("legendary");
            }
            if l.streak >= 7 {
                ach.push("streak7");
            }
            for a in ach {
                let _ = std::process::Command::new(data::gurt()).args(["__achieve", a]).stdout(std::process::Stdio::null()).stderr(std::process::Stdio::null()).spawn();
            }
        }
        ui.ctx().request_repaint_after(Duration::from_millis(40));
    }
    let l = app.lotto.as_ref().unwrap();
    let pt = ui.painter();
    let legendary = l.rarity == "legendary" && l.spin_left == 0;
    if legendary {
        pt.rect_stroke(rect.shrink(2.0), CornerRadius::same(p.r), Stroke::new(2.0, p.accent), egui::StrokeKind::Inside);
    }
    if l.spin_left > 0 {
        pt.text(rect.center(), Align2::CENTER_CENTER, &l.showing, monob(22.0), p.ink);
        return;
    }
    let (rar, col) = match l.rarity {
        "legendary" => ("LEGENDARY", p.accent),
        "epic" => ("EPIC", p.bad),
        "rare" => ("RARE", p.good),
        _ => ("COMMON", p.muted),
    };
    pt.text(pos2(rect.left() + 12.0, rect.top() + 14.0), Align2::LEFT_CENTER, format!("{rar} · jackpot!"), monob(13.0), col);
    pt.text(pos2(rect.left() + 12.0, rect.bottom() - 12.0), Align2::LEFT_CENTER, format!("{} day streak (best {}) · spin once a day, longer streaks = better odds of a legendary", l.streak, l.best), sans(11.5), p.muted);
    let win = l.win.clone();
    let in_setup = l.in_setup;
    let st = app.st.clone();
    if let Some(m) = st.pkg(&win) {
        let mut btns = install_btns(app, &m.name);
        if in_setup && app.st.inst(&m.name).is_none() {
            btns.push((if app.picked.contains(&m.name) { "added ✓".into() } else { "add to my setup".into() }, Kind::Ghost, Btn::Pick(m.name.clone())));
        }
        let c = Card { icon: m.name.clone(), name: m.name.clone(), src: "gurt".into(), ver: m.ver.clone(), desc: m.desc.clone(), extra: String::new(), chips: vec![], btns };
        let r2 = Rect::from_min_max(pos2(rect.left(), rect.top() + 26.0), pos2(rect.right(), rect.bottom() - 24.0));
        let mut child = ui.new_child(UiBuilder::new().max_rect(r2));
        if let Some(b) = card_ui(app, &mut child, &c, r2, false) {
            if let Btn::Pick(n) = &b {
                if let Some(pk) = st.pkg(n) {
                    app.bcat = cat_of(pk).into();
                }
            }
            click(app, b);
        }
    }
}

// ── Installed ──
pub fn installed(app: &mut App, ui: &mut Ui) {
    let p = app.pal;
    let narrow = app.width < 720.0;
    if narrow {
        ui.add(egui::TextEdit::singleline(&mut app.iq).hint_text("filter installed…").font(mono(14.0)).margin(vec2(10.0, 7.0)).desired_width(ui.available_width()));
    }
    ui.horizontal_wrapped(|ui| {
        if !narrow {
            let te = egui::TextEdit::singleline(&mut app.iq).hint_text("filter installed…").font(mono(14.0)).margin(vec2(10.0, 7.0)).desired_width((ui.available_width() - 340.0).max(120.0));
            ui.add(te);
        }
        let label = if app.bysize && app.sizes.is_none() { "measuring…" } else { "biggest first" };
        if w::btn_on(ui, &p, label, app.bysize, false).on_hover_text("sort by how much disk each app takes").clicked() {
            app.bysize = !app.bysize;
            if app.bysize && app.sizes.is_none() {
                app.load_sizes();
            }
        }
        if w::btn(ui, &p, "free up space", Kind::Ghost, false).on_hover_text("caches, trash + leftovers you can toss, and what's biggest on your disk").clicked() {
            app.open_dialog(Dialog::Disk(None), || Dialog::Disk(Some(data::disk())));
        }
        more_menu(app, ui, "installed", &[("export my list", 1), ("import a list", 2), ("history", 3), ("achievements", 4)]);
    });
    ui.add_space(8.0);
    let st = app.st.clone();
    let q = app.iq.trim().to_lowercase();
    let mut idx: Vec<usize> = (0..st.installed.len()).filter(|i| q.is_empty() || format!("{} {}", st.installed[*i].spec, st.installed[*i].desc).to_lowercase().contains(&q)).collect();
    if app.bysize {
        if let Some(s) = &app.sizes {
            idx.sort_by_key(|i| std::cmp::Reverse(s.get(&st.installed[*i].key).copied().unwrap_or(0)));
        }
    }
    let mut list: Vec<Row> = idx.into_iter().map(Row::Inst).collect();
    if list.is_empty() {
        list.push(Row::Empty(if st.installed.is_empty() { "nothing installed with gurt yet".into() } else { "nothing matched".into() }));
    }
    let mut others: Vec<(&String, &String)> = st.outside.iter().filter(|(n, _)| q.is_empty() || n.to_lowercase().contains(&q)).collect();
    others.sort();
    if !others.is_empty() {
        list.push(Row::Head(format!("on your computer, not from gurt ({})", others.len())));
        list.extend(others.into_iter().map(|(n, h)| Row::Outside(n.clone(), h.clone())));
    }
    rows(app, ui, &list, "igrid");
}

// ── Updates ──
pub fn updates(app: &mut App, ui: &mut Ui) {
    let p = app.pal;
    let busy = app.busy();
    ui.horizontal_wrapped(|ui| {
        if w::btn_ex(ui, &p, "check for updates", Kind::Ghost, false, false, !busy).clicked() {
            app.check(false, false);
        }
        if w::btn_ex(ui, &p, "update everything", Kind::Primary, false, false, !busy).clicked() {
            app.go(verb(&["-y", "upgrade"], "Update everything (your system + apps)", "").then(After::Upgrade));
        }
        if w::btn_ex(ui, &p, "update gurt itself", Kind::Ghost, false, false, !busy).clicked() {
            app.go(verb(&["-y", "self-update"], "Update gurt", ""));
        }
        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
            if w::btn(ui, &p, "GURTd", Kind::Ghost, false).on_hover_text("GURTd, the background daemon: auto-updates, fresh lists, downloads → install").clicked() {
                app.open_dialog(Dialog::Gurtd(None), || Dialog::Gurtd(Some(crate::dialogs::gurtd_view())));
            }
            let n = app.st.notify;
            if w::btn_on(ui, &p, if n { "alerts on" } else { "alert me" }, n, false).on_hover_text("a desktop notification when updates are waiting (checks every 6 hours)").clicked() {
                app.go(Act::new(&["notify", if n { "off" } else { "on" }]).quiet());
            }
        });
    });
    ui.add_space(10.0);
    let list: Vec<Row> = match &app.ups {
        None if app.run.as_ref().is_some_and(|r| matches!(r.act.after, After::Check)) => vec![Row::Empty("checking…".into())],
        None => vec![Row::Empty("hit \"check for updates\"".into())],
        Some(Err(e)) => vec![Row::Empty(e.clone())],
        Some(Ok(u)) if u.is_empty() => vec![Row::Empty("everything's up to date, you're chillin".into())],
        Some(Ok(u)) => (0..u.len()).map(Row::Up).collect(),
    };
    rows(app, ui, &list, "ugrid");
}

// ── Desktops ──
pub fn desktops(app: &mut App, ui: &mut Ui) {
    let p = app.pal;
    w::hint(ui, &p, "Desktop environments come straight from your own distro's repos (never from another distro, that breaks stuff). After installing, log out and pick it on the login screen.");
    ui.add_space(8.0);
    let mut list: Vec<Row> = match &app.desktops {
        None => vec![Row::Empty("loading desktops…".into())],
        Some(Err(e)) => vec![Row::Empty(e.clone())],
        Some(Ok((des, _))) => (0..des.len()).map(Row::De).collect(),
    };
    if let Some(Ok((_, dm))) = &app.desktops {
        list.push(Row::Empty(format!("your login screen: {}", if dm.is_empty() { "none found" } else { dm })));
    }
    if app.desktops.is_none() && !app.busy() {
        app.go(Act::new(&["de", "list"]).quiet().then(After::Desktops));
    }
    rows(app, ui, &list, "dgrid");
}

// ── Setup: build your setup ──
const CATS: [(&str, &str); 13] = [
    ("browsers", "Browsers"), ("chat", "Chat & email"), ("media", "Media"), ("creative", "Creative"), ("office", "Office & notes"), ("dev", "Dev"),
    ("cli", "Terminal tools"), ("gaming", "Gaming"), ("internet", "Files & remote"), ("system", "System"), ("security", "Security"), ("fun", "Fun"), ("other", "Other"),
];
pub fn cat_of(p: &data::Pkg) -> &'static str {
    CATS.iter().find(|c| c.0 == p.category).map(|c| c.0).unwrap_or("other")
}

pub fn setup(app: &mut App, ui: &mut Ui) {
    let p = app.pal;
    let st = app.st.clone();
    egui::ScrollArea::vertical().id_salt("setupscroll").auto_shrink([false, false]).show(ui, |ui| {
        ui.horizontal(|ui| {
            ui.vertical(|ui| {
                w::heading(ui, &p, "Build your setup", 18.0);
                w::hint(ui, &p, "tick everything you want, hit install once. works the same on every distro.");
            });
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                if w::btn(ui, &p, "spin the app lottery", Kind::Primary, false).clicked() {
                    spin(app, true);
                }
            });
        });
        ui.add_space(8.0);
        if app.lotto.as_ref().is_some_and(|l| l.in_setup) {
            let (r, _) = ui.allocate_exact_size(vec2(ui.available_width(), 96.0), Sense::hover());
            let mut child = ui.new_child(UiBuilder::new().max_rect(r));
            w::list_frame(&mut child, &p, |ui| {
                let (r2, _) = ui.allocate_exact_size(vec2(ui.available_width(), 92.0), Sense::hover());
                let mut c2 = ui.new_child(UiBuilder::new().max_rect(r2));
                lotto_row(app, &mut c2, r2);
            });
            ui.add_space(8.0);
        }
        // Android + Hotwyr bars
        w::panel(ui, &p, |ui| {
            ui.horizontal_wrapped(|ui| {
                ui.vertical(|ui| {
                    ui.set_max_width((ui.available_width() - 330.0).max(200.0));
                    ui.label(egui::RichText::new("Android apps").font(sansb(14.0)).color(p.ink));
                    w::hint(ui, &p, if st.cros {
                        "free software from F-Droid, installed into your Chromebook's own Android. a .apk that isn't on F-Droid gets a heads-up first"
                    } else {
                        "free software from F-Droid, running in Waydroid. gurt sets it up. a .apk that isn't on F-Droid gets a heads-up first"
                    });
                });
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    if !st.cros && w::btn(ui, &p, "open Android", Kind::Ghost, true).clicked() {
                        app.go(Act::new(&["-y", "android", "open"]));
                    }
                    if w::btn(ui, &p, "get F-Droid", Kind::Ghost, true).clicked() {
                        app.go(Act::new(&["-y", "android", "fdroid"]));
                    }
                    if w::btn(ui, &p, "set up Android", Kind::Ghost, true).clicked() {
                        app.go(Act::new(&["-y", "android", "setup"]));
                    }
                });
            });
        });
        ui.add_space(6.0);
        w::panel(ui, &p, |ui| {
            ui.horizontal_wrapped(|ui| {
                ui.vertical(|ui| {
                    ui.set_max_width((ui.available_width() - 200.0).max(200.0));
                    ui.label(egui::RichText::new("Hotwyr").font(sansb(14.0)).color(p.ink));
                    w::hint(ui, &p, "GURT backs up your package manager. when it can't find something: sudo apt install yay → apt can't → GURT offers aur/yay. upgrades and searches include GURT too, and so does command not found");
                });
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    let on = st.hook;
                    if w::btn_on(ui, &p, if on { "Hotwyr on ✓ (turn off)" } else { "turn on Hotwyr" }, on, true).clicked() {
                        app.go(Act::new(&["hotwyr", if on { "off" } else { "on" }]).quiet());
                    }
                });
            });
        });
        ui.add_space(10.0);
        // categories
        let mut have: Vec<&str> = st.main.iter().map(cat_of).collect();
        have.sort_by_key(|c| CATS.iter().position(|x| x.0 == *c));
        have.dedup();
        ui.horizontal_wrapped(|ui| {
            ui.spacing_mut().item_spacing = vec2(4.0, 4.0);
            if w::btn_on(ui, &p, &format!("all ({})", st.main.len()), app.bcat == "all", true).clicked() {
                app.bcat = "all".into();
            }
            for c in &have {
                let label = CATS.iter().find(|x| x.0 == *c).unwrap().1;
                if w::btn_on(ui, &p, label, app.bcat == *c, true).clicked() {
                    app.bcat = c.to_string();
                }
            }
        });
        ui.add_space(8.0);
        let cols = ((ui.available_width() / 230.0).floor() as usize).max(1);
        for c in have.iter().filter(|c| app.bcat == "all" || app.bcat == **c) {
            let label = CATS.iter().find(|x| x.0 == *c).unwrap().1;
            w::heading(ui, &p, label, 14.0);
            ui.add_space(2.0);
            let apps: Vec<&data::Pkg> = st.main.iter().filter(|m| cat_of(m) == *c).collect();
            egui::Grid::new(("bgrid", *c)).num_columns(cols).spacing(vec2(6.0, 4.0)).min_col_width(ui.available_width() / cols as f32 - 6.0).show(ui, |ui| {
                for (i, m) in apps.iter().enumerate() {
                    let done = st.inst(&m.name).is_some();
                    let mut on = done || app.picked.contains(&m.name);
                    let mut d = m.desc.clone();
                    if let Some(x) = d.rfind(" (") {
                        if d.ends_with(')') && (d[x..].contains("Flathub") || d[x..].contains("official repo")) {
                            d.truncate(x);
                        }
                    }
                    let d = d.split_once(" — ").map(|x| x.1.to_string()).unwrap_or(d);
                    let sub = if done { "installed ✓".to_string() } else { data::no_emoji(&d) };
                    let title = if m.foss == "closed" { format!("{} (closed)", m.name) } else { m.name.clone() };
                    ui.scope(|ui| {
                        ui.set_max_width(ui.available_width().min(260.0));
                        if w::check_row(ui, &p, &mut on, &title, &sub.chars().take(60).collect::<String>(), !done) {
                            if on {
                                app.picked.insert(m.name.clone());
                                app.sound.play("pick");
                            } else {
                                app.picked.remove(&m.name);
                                app.sound.play("unpick");
                            }
                        }
                    });
                    if (i + 1) % cols == 0 {
                        ui.end_row();
                    }
                }
            });
            ui.add_space(10.0);
        }
        ui.add_space(50.0);
    });
    // the cart
    if !app.picked.is_empty() {
        let n = app.picked.len();
        let r = ui.max_rect();
        let bar = Rect::from_min_max(pos2(r.left(), r.bottom() - 44.0), r.max);
        let mut child = ui.new_child(UiBuilder::new().max_rect(bar));
        w::panel(&mut child, &p, |ui| {
            ui.horizontal(|ui| {
                let names: Vec<String> = app.picked.iter().cloned().collect();
                ui.label(egui::RichText::new(format!("{n} app{} picked", if n == 1 { "" } else { "s" })).font(monob(12.5)).color(p.ink));
                ui.add(egui::Label::new(egui::RichText::new(names.join(", ")).font(mono(12.0)).color(p.muted)).truncate());
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    if w::btn_ex(ui, &p, "install them", Kind::Primary, false, false, !app.busy()).clicked() {
                        let mut a = vec!["-y".to_string(), "install".to_string()];
                        a.extend(names.iter().cloned());
                        let refs: Vec<&str> = a.iter().map(|s| s.as_str()).collect();
                        app.go(verb(&refs, "Install", &names.join(" ")));
                        app.picked.clear();
                    }
                    if w::btn(ui, &p, "clear", Kind::Ghost, true).clicked() {
                        app.picked.clear();
                    }
                });
            });
        });
    }
}

// ── Install a file + The Congurter™ + the Download Zone™ ──
pub const CONV: [(&str, &str, &str); 10] = [
    ("deb", ".deb (Debian, Ubuntu, Mint)", ".deb"), ("rpm", ".rpm (Fedora, openSUSE)", ".rpm"), ("pacman", ".pkg.tar.zst (Arch, CachyOS)", ".pkg.tar.zst"),
    ("apk", ".apk (Alpine)", ".apk"), ("xbps", ".xbps (Void)", ".xbps"), ("eopkg", ".eopkg (Solus)", ".eopkg"), ("appimage", "AppImage (any distro)", ".AppImage"),
    ("gurt", ".gurt", ".gurt"), ("tar.gz", ".tar.gz", ".tar.gz"), ("zip", ".zip", ".zip"),
];
const CURSED: [&str; 5] = ["WHY ARE YOU LIKE THIS", "THE MACHINE HAS SEEN THINGS", "ERROR: TOO CURSED", "THE CONGURTER REFUSES", "THAT'S NOT FOOD"];

fn ext_of(name: &str) -> String {
    let l = name.to_lowercase();
    if let Some(i) = l.find(".pkg.tar.") {
        return l[i + 1..].to_string();
    }
    if let Some(i) = l.find(".tar.") {
        return l[i + 1..].to_string();
    }
    l.rsplit('.').next().unwrap_or("").to_string()
}

impl App {
    pub fn cg_load(&mut self, f: std::path::PathBuf) {
        let name = f.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
        let ext = ext_of(&name);
        if !data::droppable(&name) {
            self.cg_curse(&format!("gurt can't even open {name}"));
            return;
        }
        if ["dmg", "snap", "flatpak", "flatpakref", "7z"].contains(&ext.as_str()) {
            self.cg_curse(&format!("a .{ext} doesn't convert. try a .deb .rpm .pkg.tar.zst AppImage .exe…"));
            return;
        }
        self.sound.play("pop");
        self.cg_screen = format!("LOADED: {name}\npick a format, smash the button");
        self.cg_state = "loaded";
        self.cg_file = Some(f);
    }
    fn cg_curse(&mut self, msg: &str) {
        self.sound.play("cursed");
        self.cg_state = "cursed";
        self.cg_until = Some(Instant::now() + Duration::from_millis(1500));
        self.cg_screen = format!("{}\n{msg}", CURSED[data::rand_below(CURSED.len() as u32) as usize]);
    }
    fn cg_press(&mut self) {
        let Some(f) = self.cg_file.clone() else { return };
        let name = f.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
        let (fmt, label, ext) = CONV[self.cg_fmt];
        let same = match ext_of(&name).as_str() {
            "deb" => "deb", "rpm" => "rpm", "pkg.tar.zst" => "pacman", "apk" => "apk", "xbps" => "xbps", "eopkg" => "eopkg",
            "appimage" => "appimage", "gurt" => "gurt", "tar.gz" => "tar.gz", "zip" => "zip", _ => "",
        };
        let what = label.split(' ').next().unwrap_or(fmt);
        if same == fmt {
            self.cg_curse(&format!("it's ALREADY a {what}. you can't congurt it into itself"));
            return;
        }
        let (stem, _) = data::split_pkg_ext(&name);
        let out = data::unique_path(&crate::app::zone_dir(&self.st), &format!("{stem}-converted{ext}"));
        self.cg_state = "running";
        self.cg_screen = format!("CONGURTING {name} → {what}…");
        let (fp, op) = (f.display().to_string(), out.display().to_string());
        self.go(Act::new(&["-y", "convert", &fp, &op]).quiet().then(After::Convert(name)));
    }
}

pub fn files(app: &mut App, ui: &mut Ui) {
    let p = app.pal;
    if let Some(t) = app.cg_until {
        if Instant::now() >= t {
            app.cg_until = None;
            if app.cg_state == "cursed" {
                app.cg_state = if app.cg_file.is_some() { "loaded" } else { "jam" };
            }
        } else {
            ui.ctx().request_repaint_after(Duration::from_millis(60));
        }
    }
    egui::ScrollArea::vertical().id_salt("filescroll").auto_shrink([false, false]).show(ui, |ui| {
        // the big drop target
        let (r, resp) = ui.allocate_exact_size(vec2(ui.available_width(), 150.0), Sense::click());
        let hot = resp.hovered() || ui.ctx().input(|i| !i.raw.hovered_files.is_empty());
        ui.painter().rect_filled(r, CornerRadius::same(p.r), if hot { p.hl } else { p.panel });
        let pts = [r.left_top(), r.right_top(), r.right_bottom(), r.left_bottom(), r.left_top()].map(|x| x + vec2(0.5, 0.5));
        ui.painter().extend(egui::Shape::dashed_line(&pts, Stroke::new(1.5, if hot { p.accent } else { p.edge }), 6.0, 4.0));
        ui.painter().text(r.center() - vec2(0.0, 34.0), Align2::CENTER_CENTER, "drop a file here, or click to pick one", sansb(16.0), p.ink);
        ui.painter().text(r.center() - vec2(0.0, 10.0), Align2::CENTER_CENTER, "gurt figures out what it is and installs it straight onto your system, any distro, no box", sans(12.5), p.muted);
        let fmts = ".deb  .rpm  .pkg.tar.zst  AppImage  .flatpak  .flatpakref  .snap  .apk  .xbps  .eopkg  .tar.gz  .zip  .7z  .exe  .msi  .dmg";
        let g = elide(ui, fmts, mono(11.5), p.muted, r.width() - 30.0, 2);
        let gs = g.size();
        ui.painter().galley(pos2(r.center().x - gs.x / 2.0, r.center().y + 14.0), g, p.muted);
        if resp.on_hover_cursor(egui::CursorIcon::PointingHand).clicked() {
            if let Some(f) = pick_file("pick a package to install") {
                app.install_file(f);
            } else if !data::has("zenity") && !data::has("kdialog") {
                app.toast("no file picker here: drop the file on the window instead");
            }
        }
        ui.add_space(14.0);
        // The Congurter™
        w::heading(ui, &p, "The Congurter™", 17.0);
        w::hint(ui, &p, "any Linux package goes in, any other one comes out");
        ui.add_space(6.0);
        let narrow = app.width < 720.0;
        let h = if narrow { 300.0 } else { 170.0 };
        let (mr, _) = ui.allocate_exact_size(vec2(ui.available_width(), h), Sense::hover());
        congurter(app, ui, mr, narrow);
        ui.add_space(12.0);
        // the Download Zone™
        ui.horizontal_wrapped(|ui| {
            ui.label(egui::RichText::new("Download Zone™").font(sansb(14.0)).color(if p.skin == Skin::W95 { hex(0xffffff) } else { p.ink }));
            w::hint(ui, &p, &app.zone_msg.clone());
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                if w::btn(ui, &p, "open Downloads", Kind::Ghost, true).clicked() {
                    let _ = std::process::Command::new("xdg-open").arg(data::downloads_dir()).stdout(std::process::Stdio::null()).stderr(std::process::Stdio::null()).spawn();
                }
            });
        });
        ui.add_space(4.0);
        let zd = crate::app::zone_dir(&app.st);
        let mut act: Option<(bool, String)> = None;
        w::list_frame(ui, &p, |ui| {
            ui.set_width(ui.available_width());
            if app.zone.is_empty() {
                ui.add_space(8.0);
                ui.horizontal(|ui| {
                    ui.add_space(10.0);
                    ui.label(egui::RichText::new("empty… for now").font(mono(12.5)).color(p.muted));
                });
                ui.add_space(8.0);
            }
            for it in &app.zone {
                ui.horizontal(|ui| {
                    ui.add_space(10.0);
                    ui.set_min_height(34.0);
                    ui.vertical(|ui| {
                        ui.spacing_mut().item_spacing.y = 0.0;
                        ui.add(egui::Label::new(egui::RichText::new(&it.name).font(monob(12.5)).color(p.ink)).truncate());
                        let s = match &it.signed {
                            Some(x) => format!("{} · signed with your gurt key ({x} next to it)", fmt_size(it.size)),
                            None => fmt_size(it.size),
                        };
                        ui.label(egui::RichText::new(s).font(mono(11.0)).color(p.muted));
                    });
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        ui.add_space(8.0);
                        if w::btn(ui, &p, "toss", Kind::Ghost, true).on_hover_text("toss it").clicked() {
                            act = Some((false, it.name.clone()));
                        }
                        if w::btn(ui, &p, "retrieve", Kind::Primary, true).clicked() {
                            act = Some((true, it.name.clone()));
                        }
                    });
                });
            }
        });
        match act {
            Some((true, n)) => {
                let src = zd.join(&n);
                let dst = data::unique_path(&data::downloads_dir(), &n);
                match std::fs::copy(&src, &dst) {
                    Ok(_) => {
                        for e in [".sig", ".sig2", ".asc"] {
                            let s = zd.join(format!("{n}{e}"));
                            if s.exists() {
                                let _ = std::fs::copy(s, format!("{}{e}", dst.display()));
                            }
                        }
                        app.zone_msg = format!("retrieved saved to {}", dst.display());
                        app.sound.play("ok");
                    }
                    Err(e) => {
                        app.zone_msg = format!("couldn't copy it: {e}");
                        app.sound.play("err");
                    }
                }
            }
            Some((false, n)) => {
                let _ = std::fs::remove_file(zd.join(&n));
                for e in [".sig", ".sig2", ".asc"] {
                    let _ = std::fs::remove_file(zd.join(format!("{n}{e}")));
                }
                app.sound.play("unpick");
                app.load_zone();
            }
            None => {}
        }
        ui.add_space(8.0);
        w::hint_mono(ui, &p, "from a terminal it's gurt outsource ./file.deb (or a download link). only install files you trust");
    });
}

/// the machine: a hopper (drop a package in), a screen, a format dial and the big button
fn congurter(app: &mut App, ui: &mut Ui, r: Rect, narrow: bool) {
    let p = app.pal;
    let shake = if app.cg_state == "cursed" { ((ui.input(|i| i.time) * 60.0).sin() * 3.0) as f32 } else { 0.0 };
    let r = r.translate(vec2(shake, 0.0));
    let body = if p.skin == Skin::W95 { hex(0xc0c0c0) } else { p.panel };
    ui.painter().rect_filled(r, CornerRadius::same(p.r), body);
    if p.skin == Skin::W95 { w::bevel(ui, r, false) } else { w::box_border(ui, &p, r) }
    let (hop, rest) = if narrow {
        let h = Rect::from_min_size(r.min + vec2(10.0, 10.0), vec2(r.width() - 20.0, 100.0));
        (h, Rect::from_min_max(pos2(r.left() + 10.0, h.bottom() + 10.0), r.max - vec2(10.0, 10.0)))
    } else {
        let h = Rect::from_min_size(r.min + vec2(10.0, 10.0), vec2(210.0, r.height() - 20.0));
        (h, Rect::from_min_max(pos2(h.right() + 12.0, r.top() + 10.0), r.max - vec2(10.0, 10.0)))
    };
    // the hopper
    let hresp = ui.interact(hop, ui.scope_id().with("hopper"), Sense::click()).on_hover_cursor(egui::CursorIcon::PointingHand);
    app.cg_hover = ui.ctx().pointer_hover_pos().is_some_and(|pos| hop.contains(pos)) || hresp.hovered();
    let hot = app.cg_hover && ui.ctx().input(|i| !i.raw.hovered_files.is_empty());
    ui.painter().rect_filled(hop, CornerRadius::same(p.r), if hot { p.hl } else { p.tag });
    let hp = [hop.left_top(), hop.right_top(), hop.right_bottom(), hop.left_bottom(), hop.left_top()];
    ui.painter().extend(egui::Shape::dashed_line(&hp, Stroke::new(1.0, if hot { p.accent } else { p.edge }), 5.0, 3.0));
    let label = match &app.cg_file {
        Some(f) => f.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default(),
        None => "drop a package in the hopper".into(),
    };
    let g = elide(ui, &label, monob(12.5), p.ink, hop.width() - 16.0, 2);
    let gs = g.size();
    ui.painter().galley(hop.center() - gs / 2.0 - vec2(0.0, 6.0), g, p.ink);
    ui.painter().text(hop.center() + vec2(0.0, gs.y / 2.0 + 4.0), Align2::CENTER_TOP, "or click to pick one", sans(11.5), p.muted);
    if hresp.clicked() {
        if let Some(f) = pick_file("pick a package to convert") {
            app.cg_load(f);
        }
    }
    // lights + the screen
    let lights = [p.bad, p.accent, p.good];
    for (i, c) in lights.iter().enumerate() {
        let on = match app.cg_state {
            "running" => ((ui.input(|x| x.time) * 6.0) as usize + i) % 3 == 0,
            "jam" | "cursed" => i == 0,
            "done" => i == 2,
            "loaded" => i == 1,
            _ => false,
        };
        let cr = Rect::from_min_size(rest.min + vec2(i as f32 * 16.0, 0.0), vec2(10.0, 10.0));
        ui.painter().circle_filled(cr.center(), 4.0, if on { *c } else { c.gamma_multiply(0.25) });
    }
    if app.cg_state == "running" {
        ui.ctx().request_repaint_after(Duration::from_millis(80));
    }
    let scr_h = if narrow { 70.0 } else { 70.0 };
    let scr = Rect::from_min_size(rest.min + vec2(0.0, 18.0), vec2(rest.width(), scr_h));
    let scr_col = if app.cg_state == "jam" || app.cg_state == "cursed" { hex(0xff5a4f) } else { hex(0x7dff8a) };
    ui.painter().rect_filled(scr, CornerRadius::same(p.r), hex(0x061006));
    ui.painter().rect_stroke(scr, CornerRadius::same(p.r), Stroke::new(1.0, p.edge), egui::StrokeKind::Inside);
    let g = elide(ui, &app.cg_screen, mono(12.5), scr_col, scr.width() - 16.0, 4);
    ui.painter().galley(scr.min + vec2(8.0, 7.0), g, scr_col);
    // the dial + the button
    let ctl = Rect::from_min_max(pos2(rest.left(), scr.bottom() + 10.0), rest.max);
    let mut child = ui.new_child(UiBuilder::new().max_rect(ctl).layout(egui::Layout::left_to_right(egui::Align::Center)));
    child.label(egui::RichText::new("turn it into").font(mono(12.0)).color(p.muted));
    egui::ComboBox::from_id_salt("convfmt").selected_text(CONV[app.cg_fmt].1).width(230.0).show_ui(&mut child, |ui| {
        for (i, c) in CONV.iter().enumerate() {
            if ui.selectable_label(app.cg_fmt == i, c.1).clicked() {
                app.cg_fmt = i;
            }
        }
    });
    child.add_space(8.0);
    let can = app.cg_file.is_some() && app.cg_state != "running" && !app.busy();
    if w::btn_ex(&mut child, &p, "CONVERT", Kind::Primary, false, false, can).clicked() {
        app.cg_press();
    }
    // a little smoke when it's cursed
    if app.cg_state == "cursed" {
        let t = ui.input(|i| i.time) as f32;
        for k in 0..6 {
            let x = r.left() + r.width() * (0.4 + 0.1 * k as f32);
            let y = r.top() + r.height() * 0.5 - ((t * 40.0 + k as f32 * 13.0) % 60.0);
            ui.painter().circle_filled(pos2(x, y), 6.0 + (k % 3) as f32 * 2.0, Color32::from_gray(140).gamma_multiply(0.35));
        }
    }
}

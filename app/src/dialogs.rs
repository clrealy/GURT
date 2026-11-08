//! the dialogs: square, 1px border, a title row with a bottom border, then content
use crate::app::{modal, verb, Act, After, App, Dialog, GurtdView};
use crate::data::{self, fmt_size};
use crate::skin::{mono, monob, sans, sansb};
use crate::widgets::{self as w, ChipKind, Kind};
use egui::{vec2, Ui};
use std::collections::HashMap;

pub fn gurtd_view() -> GurtdView {
    let mut c: HashMap<String, String> = [("autoupdate", "off"), ("watch", "on"), ("fresh", "on"), ("saver", "on"), ("quiet", "off")].into_iter().map(|(a, b)| (a.into(), b.into())).collect();
    for l in std::fs::read_to_string(data::config_dir().join("gurt/daemon.conf")).unwrap_or_default().lines() {
        if let Some((k, v)) = l.trim().split_once('=') {
            if c.contains_key(k) {
                c.insert(k.into(), v.into());
            }
        }
    }
    let running = std::process::Command::new("systemctl").args(["--user", "is-active", "--quiet", "gurtd"]).status().map(|s| s.success()).unwrap_or(false)
        || crate::daemon::url_file().exists();
    let log = std::fs::read_to_string(data::home().join(".cache/gurt/gurtd.log")).unwrap_or_default();
    let lines: Vec<&str> = log.lines().collect();
    let log = lines[lines.len().saturating_sub(12)..].join("\n");
    let holding = if c.get("saver").map(|s| s == "on").unwrap_or(false) { crate::daemon::saver_reason() } else { String::new() };
    GurtdView { running, c, log, holding }
}

impl App {
    pub fn dialogs(&mut self, ctx: &egui::Context) {
        let p = self.pal;
        // sudo wants your password
        if let Some(r) = &self.run {
            if let Some(prompt) = r.job.ask() {
                let job = r.job.clone();
                let mut answer: Option<Option<String>> = None;
                let (_, closed) = modal(ctx, &p, "pw", "password needed", 380.0, |ui| {
                    let extra = if prompt.contains("password") { String::new() } else { prompt.clone() };
                    ui.add(egui::Label::new(egui::RichText::new(format!("gurt needs your password (sudo) to put files in system folders. {extra}")).color(p.muted)).wrap());
                    ui.add_space(6.0);
                    let te = ui.add(egui::TextEdit::singleline(self.pw_mut()).password(true).hint_text("your password").font(mono(14.0)).desired_width(f32::INFINITY));
                    if !te.has_focus() && !te.lost_focus() {
                        te.request_focus();
                    }
                    let enter = te.lost_focus() && ui.input(|i| i.key_pressed(egui::Key::Enter));
                    ui.add_space(6.0);
                    ui.horizontal(|ui| {
                        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                            if w::btn(ui, &p, "ok", Kind::Primary, false).clicked() || enter {
                                answer = Some(Some(std::mem::take(self.pw_mut())));
                            }
                            if w::btn(ui, &p, "cancel", Kind::Ghost, false).clicked() {
                                answer = Some(None);
                            }
                        });
                    });
                });
                if closed && answer.is_none() {
                    answer = Some(None);
                }
                if let Some(a) = answer {
                    self.pw_mut().clear();
                    job.answer(a);
                }
                return;
            }
        }
        // are you sure?
        if let Some(act) = self.confirm.clone() {
            let (t, b) = act.confirm.clone().unwrap_or_default();
            let mut yes = None;
            let (_, closed) = modal(ctx, &p, "confirm", &t, 420.0, |ui| {
                ui.add(egui::Label::new(egui::RichText::new(&b).color(p.muted)).wrap());
                ui.add_space(8.0);
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    if w::btn(ui, &p, "Yeah", Kind::Primary, false).clicked() || ui.input(|i| i.key_pressed(egui::Key::Enter)) {
                        yes = Some(true);
                    }
                    if w::btn(ui, &p, "Nah", Kind::Ghost, false).clicked() {
                        yes = Some(false);
                    }
                });
            });
            if closed {
                yes = Some(false);
            }
            if let Some(y) = yes {
                self.confirm = None;
                if y {
                    let mut a = act;
                    a.confirm = None;
                    self.go(a);
                }
            }
            return;
        }
        let Some(mut d) = self.dialog.take() else { return };
        let mut keep = true;
        let mut then: Option<Act> = None;
        match d {
            Dialog::History(ref items) => {
                let last_tx = items.first().map(|i| i.tx.clone()).unwrap_or_default();
                let (_, closed) = modal(ctx, &p, "hist", "history", 560.0, |ui| {
                    egui::ScrollArea::vertical().max_height(ctx.content_rect().height() - 220.0).show(ui, |ui| {
                        if items.is_empty() {
                            ui.label(egui::RichText::new("nothing yet, your installs and removals show up here.").color(p.muted));
                        }
                        for (n, i) in items.iter().enumerate() {
                            let last = if last_tx.is_empty() { n == 0 } else { i.tx == last_tx };
                            ui.horizontal(|ui| {
                                ui.label(egui::RichText::new(if i.what == "install" { "+" } else { "−" }).font(monob(14.0)).color(if last { p.accent } else { p.muted }));
                                ui.vertical(|ui| {
                                    ui.spacing_mut().item_spacing.y = 0.0;
                                    ui.label(egui::RichText::new(&i.app).font(monob(13.0)).color(p.ink));
                                    let what = if i.what != "install" { "removed".to_string() } else if i.ver.is_empty() { "installed".into() } else { format!("installed · {}", i.ver) };
                                    ui.label(egui::RichText::new(what).font(sans(12.0)).color(p.muted));
                                });
                                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                                    ui.label(egui::RichText::new(&i.when).font(mono(11.0)).color(p.muted));
                                });
                            });
                        }
                    });
                    ui.add_space(6.0);
                    ui.horizontal(|ui| {
                        if !items.is_empty() && w::btn(ui, &p, "undo last", Kind::Ghost, false).on_hover_text("take back the last thing gurt did (gurt undo)").clicked() {
                            then = Some(Act::new(&["-y", "undo"]).ask("Undo the last thing gurt did?", "Undo again puts it back."));
                            keep = false;
                        }
                        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                            if w::btn(ui, &p, "done", Kind::Primary, false).clicked() {
                                keep = false;
                            }
                        });
                    });
                });
                keep &= !closed;
            }
            Dialog::Achievements(ref items) => {
                let (_, closed) = modal(ctx, &p, "ach", "achievements", 520.0, |ui| {
                    match items {
                        None => {
                            ui.label(egui::RichText::new("counting trophies…").color(p.muted));
                        }
                        Some(items) => {
                            let n = items.iter().filter(|i| i.got).count();
                            ui.label(egui::RichText::new(format!("{n}/{} unlocked{}", items.len(), if n == items.len() && n > 0 { " — you beat gurt" } else { "" })).font(monob(12.5)).color(p.accent));
                            egui::ScrollArea::vertical().max_height(ctx.content_rect().height() - 220.0).show(ui, |ui| {
                                for i in items {
                                    ui.horizontal(|ui| {
                                        ui.label(egui::RichText::new(if i.got { "✓" } else { "·" }).font(monob(14.0)).color(if i.got { p.good } else { p.muted }));
                                        ui.vertical(|ui| {
                                            ui.spacing_mut().item_spacing.y = 0.0;
                                            ui.label(egui::RichText::new(data::no_emoji(&i.title)).font(sansb(13.5)).color(if i.got { p.ink } else { p.muted }));
                                            ui.add(egui::Label::new(egui::RichText::new(data::no_emoji(&i.what)).font(sans(12.0)).color(p.muted)).wrap());
                                        });
                                    });
                                }
                            });
                        }
                    }
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        if w::btn(ui, &p, "nice", Kind::Primary, false).clicked() {
                            keep = false;
                        }
                    });
                });
                keep &= !closed;
            }
            Dialog::Disk(ref d) => {
                let keys: Vec<String> = self.st.installed.iter().map(|i| i.spec.clone()).collect();
                let (_, closed) = modal(ctx, &p, "disk", "free up space", 600.0, |ui| {
                    egui::ScrollArea::vertical().max_height(ctx.content_rect().height() - 200.0).show(ui, |ui| {
                        w::heading(ui, &p, "Junk you can toss", 14.0);
                        match d {
                            None => {
                                ui.label(egui::RichText::new("measuring…").color(p.muted));
                            }
                            Some((junk, big)) => {
                                if junk.is_empty() {
                                    ui.label(egui::RichText::new("nothing worth tossing").color(p.muted));
                                }
                                for j in junk {
                                    ui.horizontal(|ui| {
                                        ui.label(egui::RichText::new(fmt_size(j.bytes)).font(monob(12.0)).color(p.ink));
                                        ui.vertical(|ui| {
                                            ui.spacing_mut().item_spacing.y = 0.0;
                                            ui.label(egui::RichText::new(&j.what).font(monob(12.5)).color(p.ink));
                                            ui.add(egui::Label::new(egui::RichText::new(format!("{}{}", data::no_emoji(&j.desc), if j.root { ", asks for your password" } else { "" })).font(sans(12.0)).color(p.muted)).wrap());
                                        });
                                        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                                            if w::btn(ui, &p, "toss", Kind::Danger, true).clicked() {
                                                then = Some(Act::new(&["-y", "hogs", "clean", &j.what]));
                                                keep = false;
                                            }
                                        });
                                    });
                                }
                                ui.add_space(8.0);
                                w::heading(ui, &p, "Biggest on your computer", 14.0);
                                if big.is_empty() {
                                    ui.label(egui::RichText::new("couldn't measure anything").color(p.muted));
                                }
                                for (b, name) in big {
                                    ui.horizontal(|ui| {
                                        ui.label(egui::RichText::new(fmt_size(*b)).font(monob(12.0)).color(p.ink));
                                        let (from, n) = name.split_once('/').unwrap_or(("gurt", name));
                                        ui.label(egui::RichText::new(n).font(monob(12.5)).color(p.ink));
                                        w::chip(ui, &p, from, ChipKind::Plain);
                                        if keys.contains(name) {
                                            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                                                if w::btn(ui, &p, "remove", Kind::Ghost, true).clicked() {
                                                    then = Some(verb(&["-y", "remove", name], "Remove", name));
                                                    keep = false;
                                                }
                                            });
                                        }
                                    });
                                }
                            }
                        }
                    });
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        if w::btn(ui, &p, "done", Kind::Primary, false).clicked() {
                            keep = false;
                        }
                    });
                });
                keep &= !closed;
            }
            Dialog::Gurtd(ref v) => {
                let mut reload = false;
                let (_, closed) = modal(ctx, &p, "gurtd", "GURTd", 560.0, |ui| {
                    ui.add(egui::Label::new(egui::RichText::new("gurt's background daemon. Linus sees you. Same settings as gurt gurtd config in a terminal.").color(p.muted)).wrap());
                    ui.add_space(6.0);
                    match v {
                        None => {
                            ui.label(egui::RichText::new("asking GURTd…").color(p.muted));
                        }
                        Some(v) => {
                            let rows = [
                                ("running", "running", "in the background while you're logged in"),
                                ("autoupdate", "auto-update my apps", "apps that need your password get a notification instead"),
                                ("fresh", "keep package lists fresh", "every 3 hours, so searches and update checks are instant"),
                                ("watch", "watch Downloads", "a new .deb / .rpm / AppImage asks to install it with GURT"),
                                ("saver", "saver", "no update checks on battery or metered data, they wait till you're plugged in"),
                            ];
                            for (k, t, sub) in rows {
                                let on = if k == "running" { v.running } else { v.c.get(k).map(|s| s == "on").unwrap_or(false) };
                                ui.horizontal(|ui| {
                                    ui.vertical(|ui| {
                                        ui.set_max_width(ui.available_width() - 70.0);
                                        ui.spacing_mut().item_spacing.y = 0.0;
                                        ui.label(egui::RichText::new(t).font(sansb(13.5)).color(p.ink));
                                        let s = if k == "saver" && on && !v.holding.is_empty() { format!("holding off right now: {}", v.holding) } else { sub.to_string() };
                                        ui.add(egui::Label::new(egui::RichText::new(s).font(sans(12.0)).color(p.muted)).wrap());
                                    });
                                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                                        if w::btn_on(ui, &p, if on { "on" } else { "off" }, on, true).clicked() {
                                            let arg = if k == "running" { vec![if on { "off" } else { "on" }] } else { vec![k, if on { "off" } else { "on" }] };
                                            let mut a = vec!["gurtd"];
                                            a.extend(arg);
                                            then = Some(Act::new(&a).quiet());
                                            reload = true;
                                        }
                                    });
                                });
                            }
                            ui.horizontal(|ui| {
                                ui.vertical(|ui| {
                                    ui.spacing_mut().item_spacing.y = 0.0;
                                    ui.label(egui::RichText::new("quiet hours").font(sansb(13.5)).color(p.ink));
                                    ui.label(egui::RichText::new("no popups then, they wait till it's over").font(sans(12.0)).color(p.muted));
                                });
                                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                                    let cur = v.c.get("quiet").cloned().unwrap_or_else(|| "off".into());
                                    let show = |q: &str| if q == "off" { "off".to_string() } else { format!("{}:00 – {}:00", q.split('-').next().unwrap_or(""), q.split('-').nth(1).unwrap_or("")) };
                                    egui::ComboBox::from_id_salt("quiet").selected_text(show(&cur)).show_ui(ui, |ui| {
                                        for q in ["off", "21-7", "22-8", "23-8", "0-9"] {
                                            if ui.selectable_label(cur == q, show(q)).clicked() && cur != q {
                                                then = Some(Act::new(&["gurtd", "quiet", q]).quiet());
                                                reload = true;
                                            }
                                        }
                                    });
                                });
                            });
                            ui.add_space(6.0);
                            egui::Frame::new().fill(p.code).inner_margin(8).show(ui, |ui| {
                                ui.set_width(ui.available_width());
                                ui.add(egui::Label::new(egui::RichText::new(if v.log.is_empty() { "GURTd hasn't run yet" } else { &v.log }).font(mono(11.5)).color(p.ink)).wrap());
                            });
                        }
                    }
                    ui.add_space(6.0);
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        if w::btn(ui, &p, "done", Kind::Primary, false).clicked() {
                            keep = false;
                        }
                    });
                });
                keep &= !closed;
                if reload && then.is_some() {
                    // run the change, then show the dialog again with fresh values
                    self.go(then.take().unwrap());
                    self.gurtd_reopen = true;
                }
            }
            Dialog::Compare => {
                let st = self.st.clone();
                let ps: Vec<&data::Pkg> = self.cmp.iter().filter_map(|n| st.pkg(n)).collect();
                let sizes = self.sizes.clone();
                let mut btn: Option<crate::tabs::Btn> = None;
                let (_, closed) = modal(ctx, &p, "cmp", "side by side", 920.0, |ui| {
                    egui::ScrollArea::both().max_height(ctx.content_rect().height() - 200.0).show(ui, |ui| {
                        egui::Grid::new("cmpgrid").striped(true).spacing(vec2(12.0, 8.0)).min_col_width(90.0).show(ui, |ui| {
                            let row = |ui: &mut Ui, label: &str, f: &dyn Fn(&data::Pkg) -> String| {
                                ui.label(egui::RichText::new(label).font(monob(12.5)).color(p.muted));
                                for pk in &ps {
                                    ui.add(egui::Label::new(egui::RichText::new(f(pk)).color(p.ink)).wrap());
                                }
                                ui.end_row();
                            };
                            row(ui, "app", &|pk| pk.name.clone());
                            row(ui, "what it is", &|pk| data::no_emoji(&pk.desc));
                            row(ui, "comes from", &|pk| crate::tabs::trust(&pk.trust).map(|t| t.1.to_string()).unwrap_or_else(|| "Main GURT".into()));
                            row(ui, "version", &|pk| pk.ver.clone());
                            row(ui, "category", &|pk| if pk.category.is_empty() { "–".into() } else { pk.category.clone() });
                            row(ui, "license", &|pk| if pk.license.is_empty() { "–".into() } else { pk.license.clone() });
                            row(ui, "free software", &|pk| match pk.foss { "foss" => "yes".into(), "closed" => "no, closed source".into(), _ => "unknown".into() });
                            row(ui, "installed", &|pk| if st.inst(&pk.name).is_some() { "yes".into() } else { "no".into() });
                            row(ui, "size on disk", &|pk| sizes.as_ref().and_then(|s| s.get(&pk.ikey).or_else(|| s.get(&pk.name))).map(|b| fmt_size(*b)).unwrap_or_else(|| "–".into()));
                            row(ui, "website", &|pk| if pk.url.is_empty() { "–".into() } else { pk.url.trim_start_matches("https://").trim_start_matches("http://").chars().take(40).collect() });
                            ui.label("");
                            for pk in &ps {
                                ui.horizontal(|ui| {
                                    for (label, kind, b) in crate::tabs::install_btns(self, &pk.name) {
                                        let r = if matches!(b, crate::tabs::Btn::Done) { w::chip(ui, &p, &label, ChipKind::Ok) } else { w::btn(ui, &p, &label, kind, true) };
                                        if r.clicked() && !matches!(b, crate::tabs::Btn::Done) {
                                            btn = Some(b);
                                        }
                                    }
                                });
                            }
                            ui.end_row();
                        });
                    });
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        if w::btn(ui, &p, "done", Kind::Primary, false).clicked() {
                            keep = false;
                        }
                    });
                });
                keep &= !closed;
                if let Some(b) = btn {
                    keep = false;
                    crate::tabs::click(self, b);
                }
            }
            Dialog::DirtGate => {
                let mut yes = None;
                let (_, closed) = modal(ctx, &p, "gate", "Are you sure?", 380.0, |ui| {
                    ui.label(egui::RichText::new("18+").font(monob(34.0)).color(crate::skin::hex(0xe0314b)));
                    ui.add(egui::Label::new(egui::RichText::new("This section of the GURT Repository is 18+ ONLY. Explore at your own risk.").color(p.ink)).wrap());
                    ui.add_space(8.0);
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        if w::btn(ui, &p, "Yeah", Kind::Danger, false).clicked() {
                            yes = Some(true);
                        }
                        if w::btn(ui, &p, "Nah", Kind::Ghost, false).clicked() {
                            yes = Some(false);
                        }
                    });
                });
                if closed {
                    yes = Some(false);
                }
                match yes {
                    Some(true) => {
                        keep = false;
                        if !self.st.dirt {
                            let mut a = Act::new(&["dirt", "on"]).quiet();
                            a.stdin = Some("yes\n".into());
                            then = Some(a);
                        }
                        crate::tabs::set_src(self, "dirt");
                    }
                    Some(false) => keep = false,
                    None => {}
                }
            }
            Dialog::DevLock(ref mut pw, ref mut msg) => {
                let mut go = false;
                modal(ctx, &p, "dev", "dev build", 420.0, |ui| {
                    ui.add(egui::Label::new(egui::RichText::new("this is a GURT dev build. type the dev password to keep it. a wrong one swaps in the normal GURT and removes the dev build.").color(p.muted)).wrap());
                    let te = ui.add(egui::TextEdit::singleline(pw).password(true).hint_text("dev password").font(mono(14.0)).desired_width(f32::INFINITY));
                    if te.lost_focus() && ui.input(|i| i.key_pressed(egui::Key::Enter)) {
                        go = true;
                    }
                    if !msg.is_empty() {
                        ui.label(egui::RichText::new(msg.as_str()).font(mono(12.0)).color(p.muted));
                    }
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        if w::btn(ui, &p, "unlock", Kind::Primary, false).clicked() {
                            go = true;
                        }
                    });
                });
                if go && !pw.is_empty() {
                    let mut a = Act::new(&["__devunlock"]).then(After::DevUnlock);
                    a.stdin = Some(format!("{}\n", pw.replace('\n', "")));
                    pw.clear();
                    *msg = "checking…".into();
                    then = Some(a);
                }
                // the dev password comes first: no closing it any other way
            }
            Dialog::Welcome => {
                keep = false;
            }
        }
        if keep && self.dialog.is_none() {
            self.dialog = Some(d);
        }
        if let Some(a) = then {
            self.go(a);
        }
    }
}

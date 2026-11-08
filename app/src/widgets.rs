//! GURT's controls, painted by hand so each skin keeps its identity: GURT flat + yellow, Windows 11 soft underline,
//! XP blue bars + green start tab, 95 bevels, Vaporwave double neon borders, Hacker [ bracketed ] text and dashes.
use crate::skin::{hex, mono, monob, Pal, Skin, VAPOR_CYAN};
use egui::{pos2, vec2, Align2, Color32, CornerRadius, FontId, Rect, Response, Sense, Shape, Stroke, StrokeKind, Ui};

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    Primary,
    Ghost,
    Danger,
}

// ── borders ──
pub fn bevel(ui: &Ui, r: Rect, pressed: bool) {
    let pt = ui.painter();
    let (a, b, c, d) = if pressed { (hex(0x000000), hex(0xffffff), hex(0x808080), hex(0xdfdfdf)) } else { (hex(0xdfdfdf), hex(0x000000), hex(0xffffff), hex(0x808080)) };
    let line = |p1, p2, col| pt.line_segment([p1, p2], Stroke::new(1.0, col));
    let r = r.shrink(0.5);
    line(r.left_top(), r.right_top(), a);
    line(r.left_top(), r.left_bottom(), a);
    line(r.left_bottom(), r.right_bottom(), b);
    line(r.right_top(), r.right_bottom(), b);
    let i = r.shrink(1.0);
    line(i.left_top(), i.right_top(), c);
    line(i.left_top(), i.left_bottom(), c);
    line(i.left_bottom(), i.right_bottom(), d);
    line(i.right_top(), i.right_bottom(), d);
}
/// a sunken white field (95's list views and text boxes)
pub fn sunken(ui: &Ui, r: Rect) {
    let pt = ui.painter();
    let r = r.shrink(0.5);
    let line = |p1, p2, col| pt.line_segment([p1, p2], Stroke::new(1.0, col));
    line(r.left_top(), r.right_top(), hex(0x808080));
    line(r.left_top(), r.left_bottom(), hex(0x808080));
    line(r.left_bottom(), r.right_bottom(), hex(0xffffff));
    line(r.right_top(), r.right_bottom(), hex(0xffffff));
}
pub fn dashed_rect(ui: &Ui, r: Rect, col: Color32) {
    let r = r.shrink(0.5);
    let pts = [r.left_top(), r.right_top(), r.right_bottom(), r.left_bottom(), r.left_top()];
    ui.painter().extend(Shape::dashed_line(&pts, Stroke::new(1.0, col), 4.0, 3.0));
}
pub fn double_rect(ui: &Ui, r: Rect, col: Color32) {
    let pt = ui.painter();
    pt.rect_stroke(r.shrink(0.5), CornerRadius::ZERO, Stroke::new(1.0, col), StrokeKind::Inside);
    pt.rect_stroke(r.shrink(2.5), CornerRadius::ZERO, Stroke::new(1.0, col), StrokeKind::Inside);
}
/// a box's border, the skin's way
pub fn box_border(ui: &Ui, p: &Pal, r: Rect) {
    match p.skin {
        Skin::W95 => sunken(ui, r),
        Skin::Vapor => double_rect(ui, r, p.edge),
        Skin::Hacker => dashed_rect(ui, r, p.edge),
        _ => {
            ui.painter().rect_stroke(r, CornerRadius::same(p.r), Stroke::new(1.0, p.edge), StrokeKind::Inside);
        }
    }
}

/// the list box rows sit in (Discover, Installed, Updates…)
pub fn list_frame<R>(ui: &mut Ui, p: &Pal, add: impl FnOnce(&mut Ui) -> R) -> R {
    let fill = if p.skin == Skin::W95 { hex(0xffffff) } else { p.panel };
    let pad = if matches!(p.skin, Skin::Vapor) { 3 } else { 1 };
    let inner = egui::Frame::new().fill(fill).corner_radius(CornerRadius::same(p.r)).inner_margin(pad).show(ui, add);
    box_border(ui, p, inner.response.rect);
    inner.inner
}

/// a panel with a border (dialogs' insides, the setup bars)
pub fn panel<R>(ui: &mut Ui, p: &Pal, add: impl FnOnce(&mut Ui) -> R) -> R {
    let inner = egui::Frame::new().fill(p.panel).corner_radius(CornerRadius::same(p.r)).inner_margin(egui::Margin::symmetric(10, 8)).show(ui, add);
    if p.skin == Skin::W95 {
        bevel(ui, inner.response.rect, false);
    } else {
        box_border(ui, p, inner.response.rect);
    }
    inner.inner
}

fn label_of(p: &Pal, text: &str) -> String {
    match p.skin {
        Skin::Hacker => format!("[ {text} ]"),
        Skin::Vapor => text.to_uppercase(),
        _ => text.to_string(),
    }
}

/// a button. GURT: yellow fill (primary), outline (ghost), red (danger)
pub fn btn(ui: &mut Ui, p: &Pal, text: &str, kind: Kind, small: bool) -> Response {
    btn_ex(ui, p, text, kind, small, false, true)
}
pub fn btn_on(ui: &mut Ui, p: &Pal, text: &str, on: bool, small: bool) -> Response {
    btn_ex(ui, p, text, if on { Kind::Primary } else { Kind::Ghost }, small, on, true)
}
pub fn btn_ex(ui: &mut Ui, p: &Pal, text: &str, kind: Kind, small: bool, pressed: bool, enabled: bool) -> Response {
    let text = label_of(p, text);
    let size = if small { 12.0 } else { 12.5 };
    let font: FontId = if matches!(p.skin, Skin::Xp | Skin::W95) { crate::skin::sans(size + 0.5) } else if p.skin == Skin::Win11 { crate::skin::sansb(size + 0.5) } else { monob(size) };
    let pad = if small { vec2(8.0, 3.0) } else { vec2(11.0, 6.0) };
    let galley = ui.painter().layout_no_wrap(text.clone(), font.clone(), Color32::WHITE);
    let want = galley.size() + pad * 2.0;
    let want = vec2(want.x.max(if p.skin == Skin::W95 && !small { 72.0 } else { 0.0 }), want.y);
    let (rect, resp) = ui.allocate_exact_size(want, if enabled { Sense::click() } else { Sense::hover() });
    if !ui.is_rect_visible(rect) {
        return resp;
    }
    let hov = enabled && resp.hovered();
    let down = enabled && resp.is_pointer_button_down_on();
    let pt = ui.painter();
    let r = CornerRadius::same(p.r);
    let (mut fill, mut ink, mut border) = match kind {
        Kind::Primary => (p.accent, p.accent_ink, p.accent),
        Kind::Ghost => (Color32::TRANSPARENT, p.ink, p.edge),
        Kind::Danger => (p.bad, Color32::WHITE, p.bad),
    };
    match p.skin {
        Skin::W95 => {
            pt.rect_filled(rect, CornerRadius::ZERO, hex(0xc0c0c0));
            bevel(ui, rect, down || pressed);
            let ink = if kind == Kind::Danger { p.bad } else { hex(0x000000) };
            let f = if pressed { crate::skin::sansb(size + 0.5) } else { font };
            let off = if down || pressed { vec2(1.0, 1.0) } else { vec2(0.0, 0.0) };
            pt.text(rect.center() + off, Align2::CENTER_CENTER, &text, f, if enabled { ink } else { hex(0x808080) });
            return resp.on_hover_cursor(egui::CursorIcon::PointingHand);
        }
        Skin::Hacker => {
            let ink = if kind == Kind::Danger { p.bad } else { p.accent };
            if hov || pressed {
                pt.rect_filled(rect, r, ink);
                pt.text(rect.center(), Align2::CENTER_CENTER, &text, font, hex(0x000000));
            } else {
                pt.text(rect.center(), Align2::CENTER_CENTER, &text, font, if enabled { ink } else { p.muted });
            }
            return resp.on_hover_cursor(egui::CursorIcon::PointingHand);
        }
        Skin::Vapor => {
            if kind == Kind::Ghost {
                border = VAPOR_CYAN;
                ink = VAPOR_CYAN;
            } else if kind == Kind::Primary {
                border = VAPOR_CYAN;
            }
        }
        Skin::Xp => {
            border = hex(0x003c74);
            if kind == Kind::Ghost {
                fill = if hov { hex(0xffffff) } else { hex(0xf4f3ee) };
                ink = hex(0x000000);
                if hov {
                    border = hex(0xe68b2c);
                }
            }
        }
        Skin::Win11 => {
            if kind == Kind::Ghost {
                fill = p.panel;
            }
        }
        Skin::Gurt => {}
    }
    if hov && kind == Kind::Ghost && !matches!(p.skin, Skin::Xp) {
        fill = p.tag;
        border = p.muted;
    }
    if hov && kind != Kind::Ghost && p.skin == Skin::Gurt {
        fill = crate::skin::hex(0xffd54f);
        border = fill;
    }
    if !enabled {
        ink = p.muted;
        if kind != Kind::Ghost {
            fill = p.tag;
            border = p.edge;
        }
    }
    // pressed: an inset look, never a lift
    pt.rect_filled(rect, r, fill);
    pt.rect_stroke(rect, r, Stroke::new(1.0, border), StrokeKind::Inside);
    if down {
        pt.rect_stroke(rect.shrink(1.0), r, Stroke::new(1.0, border.gamma_multiply(0.6)), StrokeKind::Inside);
    }
    if p.skin == Skin::Win11 && kind == Kind::Ghost {
        pt.line_segment([rect.left_bottom() + vec2(p.r as f32, -0.5), rect.right_bottom() + vec2(-(p.r as f32), -0.5)], Stroke::new(1.0, p.muted.gamma_multiply(0.5)));
    }
    pt.text(rect.center() + if down { vec2(0.0, 1.0) } else { vec2(0.0, 0.0) }, Align2::CENTER_CENTER, &text, font, ink);
    if enabled { resp.on_hover_cursor(egui::CursorIcon::PointingHand) } else { resp }
}

/// a header tab (Discover, Installed…)
pub fn tab(ui: &mut Ui, p: &Pal, text: &str, on: bool, badge: Option<usize>) -> Response {
    let font = match p.skin {
        Skin::Xp => crate::skin::sansb(13.0),
        Skin::W95 => if on { crate::skin::sansb(12.5) } else { crate::skin::sans(12.5) },
        Skin::Win11 => if on { crate::skin::sansb(13.0) } else { crate::skin::sans(13.0) },
        _ => monob(12.5),
    };
    let label = match p.skin {
        Skin::Hacker if on => format!("> {text}"),
        Skin::Vapor => text.to_uppercase(),
        _ => text.to_string(),
    };
    let galley = ui.painter().layout_no_wrap(label.clone(), font.clone(), Color32::WHITE);
    let badge_w = badge.map(|n| 10.0 + 7.0 * n.to_string().len() as f32).unwrap_or(0.0);
    let extra = if p.skin == Skin::Xp && on { 8.0 } else { 0.0 };
    let (rect, resp) = ui.allocate_exact_size(galley.size() + vec2(20.0 + badge_w + extra, 12.0), Sense::click());
    let hov = resp.hovered();
    let pt = ui.painter();
    let r = CornerRadius::same(p.r);
    let mut ink = if on { p.accent_ink } else { p.muted };
    match p.skin {
        Skin::Gurt => {
            if on {
                pt.rect_filled(rect, r, p.accent);
            } else if hov {
                pt.rect_stroke(rect, r, Stroke::new(1.0, p.edge), StrokeKind::Inside);
                ink = p.ink;
            }
        }
        Skin::Win11 => {
            ink = p.ink;
            if on || hov {
                pt.rect_filled(rect, r, p.hl);
            }
            if on {
                let w = rect.width() * 0.4;
                pt.rect_filled(Rect::from_center_size(pos2(rect.center().x, rect.bottom() - 2.5), vec2(w, 3.0)), CornerRadius::same(2), p.accent);
            }
        }
        Skin::Xp => {
            ink = hex(0xffffff);
            if on {
                // the green start button: rounded on the right only
                let rr = CornerRadius { nw: 0, sw: 0, ne: 10, se: 10 };
                pt.rect_filled(rect, rr, p.accent);
                pt.rect_stroke(rect, rr, Stroke::new(1.0, hex(0x1d5b06)), StrokeKind::Inside);
            } else if hov {
                pt.rect_filled(rect, r, hex(0x3d77e6));
                pt.rect_stroke(rect, r, Stroke::new(1.0, hex(0x1b4fbf)), StrokeKind::Inside);
            }
        }
        Skin::W95 => {
            if on {
                pt.rect_filled(rect, CornerRadius::ZERO, hex(0xc0c0c0));
                bevel(ui, rect, true);
                ink = hex(0x000000);
            } else {
                ink = hex(0xffffff);
                if hov {
                    pt.rect_stroke(rect, CornerRadius::ZERO, Stroke::new(1.0, hex(0xc0c0c0)), StrokeKind::Inside);
                }
            }
        }
        Skin::Vapor => {
            if on {
                double_rect(ui, rect, p.accent);
                ink = p.accent;
            } else if hov {
                ink = p.ink;
            }
        }
        Skin::Hacker => {
            ink = if on || hov { p.accent } else { p.muted };
        }
    }
    let tx = rect.left() + 10.0 + galley.size().x / 2.0 + if p.skin == Skin::Xp && on { 0.0 } else { 0.0 };
    let font_it = if p.skin == Skin::Xp && on { FontId::new(font.size, font.family.clone()) } else { font };
    pt.text(pos2(tx, rect.center().y), Align2::CENTER_CENTER, &label, font_it, ink);
    if let Some(n) = badge {
        let br = Rect::from_min_size(pos2(rect.right() - badge_w - 6.0 - extra, rect.center().y - 8.0), vec2(badge_w, 16.0));
        pt.rect_filled(br, CornerRadius::same(p.r), if on { p.accent_ink } else { p.bad });
        pt.text(br.center(), Align2::CENTER_CENTER, n.to_string(), mono(11.0), if on { p.accent } else { Color32::WHITE });
    }
    resp.on_hover_cursor(egui::CursorIcon::PointingHand)
}

/// a source button: "aur/ Arch User Repo"
pub fn src_btn(ui: &mut Ui, p: &Pal, src: &str, sub: &str, on: bool, dirt: bool) -> Response {
    let f1 = if matches!(p.skin, Skin::Xp | Skin::W95) { crate::skin::sans(12.5) } else { monob(12.0) };
    let f2 = crate::skin::sans(11.0);
    let g1 = ui.painter().layout_no_wrap(format!("{src}/"), f1.clone(), Color32::WHITE);
    let g2 = ui.painter().layout_no_wrap(sub.to_string(), f2.clone(), Color32::WHITE);
    let w = g1.size().x + 5.0 + g2.size().x + 18.0;
    let (rect, resp) = ui.allocate_exact_size(vec2(w, 24.0), Sense::click());
    let hov = resp.hovered();
    let pt = ui.painter();
    let r = CornerRadius::same(p.r);
    let (mut fill, mut ink, mut sub_ink, mut border) = (p.panel, p.ink, p.muted, if hov { p.muted } else { p.edge });
    if on {
        fill = p.accent;
        ink = p.accent_ink;
        sub_ink = p.accent_ink.gamma_multiply(0.75);
        border = p.accent;
    }
    if dirt {
        // DIRT keeps its own colors in every skin
        (fill, ink, sub_ink, border) = if on { (hex(0xe0314b), hex(0xffffff), hex(0xffffff), hex(0xe0314b)) } else { (hex(0x141012), hex(0xf1e9ea), hex(0xe0314b), if hov { hex(0xe0314b) } else { hex(0x3a2a2e) }) };
    }
    match p.skin {
        Skin::W95 if !dirt => {
            pt.rect_filled(rect, CornerRadius::ZERO, hex(0xc0c0c0));
            bevel(ui, rect, on);
            ink = hex(0x000000);
            sub_ink = hex(0x222222);
        }
        Skin::Hacker if !dirt => {
            if on {
                pt.rect_filled(rect, r, p.accent);
            } else {
                dashed_rect(ui, rect, if hov { p.accent } else { p.edge });
            }
        }
        Skin::Vapor if !dirt => {
            pt.rect_filled(rect, r, if on { p.accent } else { p.panel });
            pt.rect_stroke(rect, r, Stroke::new(1.0, if on { VAPOR_CYAN } else { p.edge }), StrokeKind::Inside);
            if !on {
                ink = p.accent;
                sub_ink = VAPOR_CYAN;
            }
        }
        _ => {
            pt.rect_filled(rect, r, fill);
            pt.rect_stroke(rect, r, Stroke::new(1.0, border), StrokeKind::Inside);
        }
    }
    let y = rect.center().y;
    let x = rect.left() + 9.0;
    pt.text(pos2(x, y), Align2::LEFT_CENTER, format!("{src}/"), if on && p.skin == Skin::W95 { crate::skin::sansb(12.5) } else { f1 }, ink);
    pt.text(pos2(x + g1.size().x + 5.0, y), Align2::LEFT_CENTER, sub, f2, sub_ink);
    resp.on_hover_cursor(egui::CursorIcon::PointingHand)
}

#[derive(Clone, Copy, PartialEq)]
pub enum ChipKind {
    Plain,
    Ok,
    Closed,
    Hi,
    Mid,
    Lo,
}
pub fn chip(ui: &mut Ui, p: &Pal, text: &str, kind: ChipKind) -> Response {
    let text = if p.skin == Skin::Hacker { format!("<{text}>") } else { text.to_string() };
    let font = monob(11.0);
    let g = ui.painter().layout_no_wrap(text.clone(), font.clone(), Color32::WHITE);
    let (rect, resp) = ui.allocate_exact_size(g.size() + vec2(if p.skin == Skin::Hacker { 4.0 } else { 12.0 }, 4.0), Sense::hover());
    let pt = ui.painter();
    let (ink, border) = match kind {
        ChipKind::Ok => (p.good, p.good),
        ChipKind::Closed => (p.bad, p.bad),
        ChipKind::Hi => (p.good, p.edge),
        ChipKind::Mid => (p.ink, p.edge),
        ChipKind::Lo => (p.muted, p.edge),
        ChipKind::Plain => (p.ink, p.edge),
    };
    if p.skin != Skin::Hacker {
        pt.rect_stroke(rect, CornerRadius::same(p.r), Stroke::new(1.0, border), StrokeKind::Inside);
    }
    pt.text(rect.center(), Align2::CENTER_CENTER, text, font, ink);
    resp
}

/// a section heading row inside a list ("apps like photoshop", "only on GitHub: games")
pub fn list_head(ui: &mut Ui, p: &Pal, text: &str) {
    let (bg, ink) = match p.skin {
        Skin::Xp => (hex(0xd6dff7), hex(0x0a246a)),
        Skin::W95 => (hex(0xc0c0c0), hex(0x000000)),
        _ => (p.tag, p.ink),
    };
    let w = ui.available_width();
    let (rect, _) = ui.allocate_exact_size(vec2(w, 26.0), Sense::hover());
    ui.painter().rect_filled(rect, CornerRadius::ZERO, bg);
    ui.painter().line_segment([rect.left_bottom(), rect.right_bottom()], Stroke::new(1.0, if p.skin == Skin::W95 { hex(0x808080) } else { p.line }));
    ui.painter().text(pos2(rect.left() + 10.0, rect.center().y), Align2::LEFT_CENTER, text, monob(13.0), ink);
}

/// a big heading (sentence case, the sans bold), Vaporwave gets its hard pink offset
pub fn heading(ui: &mut Ui, p: &Pal, text: &str, size: f32) {
    let font = if p.skin == Skin::Hacker { monob(size) } else { crate::skin::sansb(size) };
    let ink = match p.skin {
        Skin::Vapor => crate::skin::VAPOR_YELLOW,
        Skin::Xp => hex(0x0a246a),
        Skin::W95 => hex(0xffffff),
        _ => p.ink,
    };
    let g = ui.painter().layout_no_wrap(text.to_string(), font.clone(), ink);
    let (rect, _) = ui.allocate_exact_size(g.size() + vec2(2.0, 2.0), Sense::hover());
    if p.skin == Skin::Vapor {
        ui.painter().text(rect.left_top() + vec2(2.0, 2.0), Align2::LEFT_TOP, text, font.clone(), p.accent);
    }
    ui.painter().text(rect.left_top(), Align2::LEFT_TOP, text, font, ink);
}

/// muted helper text; on 95's teal desktop it's white
pub fn hint(ui: &mut Ui, p: &Pal, text: &str) -> Response {
    let ink = if p.skin == Skin::W95 { hex(0xffffff) } else { p.muted };
    ui.add(egui::Label::new(egui::RichText::new(text).font(crate::skin::sans(12.5)).color(ink)).wrap())
}
pub fn hint_mono(ui: &mut Ui, p: &Pal, text: &str) -> Response {
    let ink = if p.skin == Skin::W95 { hex(0xffffff) } else { p.muted };
    ui.add(egui::Label::new(egui::RichText::new(text).font(mono(12.0)).color(ink)).wrap())
}

/// a letter tile: the logo for apps that don't have one
pub fn letter_tile(ui: &Ui, p: &Pal, r: Rect, name: &str) {
    let pt = ui.painter();
    pt.rect_filled(r, CornerRadius::same(p.r), p.tag);
    pt.rect_stroke(r, CornerRadius::same(p.r), Stroke::new(1.0, p.edge), StrokeKind::Inside);
    let c = name.chars().find(|c| c.is_alphanumeric()).map(|c| c.to_uppercase().to_string()).unwrap_or_else(|| "?".into());
    pt.text(r.center(), Align2::CENTER_CENTER, c, monob(12.0), p.muted);
}

/// a status dot (physically round: the only round thing)
pub fn dot(ui: &mut Ui, col: Color32) {
    let (r, _) = ui.allocate_exact_size(vec2(10.0, 10.0), Sense::hover());
    ui.painter().circle_filled(r.center(), 4.0, col);
}

/// a checkbox row: [x] title / small subtitle
pub fn check_row(ui: &mut Ui, p: &Pal, on: &mut bool, title: &str, sub: &str, enabled: bool) -> bool {
    let mut changed = false;
    ui.horizontal_top(|ui| {
        let r = ui.add_enabled(enabled, egui::Checkbox::without_text(on));
        changed = r.changed();
        ui.vertical(|ui| {
            ui.spacing_mut().item_spacing.y = 1.0;
            let lr = ui.add(egui::Label::new(egui::RichText::new(title).font(crate::skin::sansb(13.5)).color(p.ink)).wrap().sense(Sense::click()));
            if lr.clicked() && enabled {
                *on = !*on;
                changed = true;
            }
            if !sub.is_empty() {
                ui.add(egui::Label::new(egui::RichText::new(sub).font(crate::skin::sans(12.0)).color(p.muted)).wrap());
            }
        });
    });
    changed
}

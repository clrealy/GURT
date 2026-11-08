//! the six skins: one palette + fonts + how controls are drawn each. GURT's look rules: flat, 1px borders, square-ish
//! corners, one accent per skin, data in monospace, no shadows / glows / gradients.
use egui::{Color32, CornerRadius, FontFamily, FontId, Stroke};
use std::process::{Command, Stdio};

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Skin {
    Gurt,
    Win11,
    Xp,
    W95,
    Vapor,
    Hacker,
    Gold, // 🔑 a GURT key unlocks it
}
pub const SKINS: [(Skin, &str, &str); 7] = [
    (Skin::Gurt, "gurt", "GURT"),
    (Skin::Win11, "win11", "Windows 11"),
    (Skin::Xp, "xp", "Windows XP"),
    (Skin::W95, "w95", "Windows 95"),
    (Skin::Vapor, "vapor", "Vaporwave"),
    (Skin::Hacker, "hacker", "Hacker"),
    (Skin::Gold, "gold", "Golden Duck"),
];
impl Skin {
    pub fn from_id(s: &str) -> Skin {
        SKINS.iter().find(|x| x.1 == s).map(|x| x.0).unwrap_or(Skin::Gurt)
    }
    pub fn id(self) -> &'static str {
        SKINS.iter().find(|x| x.0 == self).unwrap().1
    }
    /// XP, 95, Vaporwave and Hacker look one way only, like the real things
    pub fn fixed_theme(self) -> Option<bool> {
        match self {
            Skin::Xp | Skin::W95 => Some(false),
            Skin::Vapor | Skin::Hacker | Skin::Gold => Some(true),
            _ => None,
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Pal {
    pub skin: Skin,
    pub dark: bool,
    pub r: u8, // corner radius
    pub bg: Color32,
    pub panel: Color32,
    pub ink: Color32,
    pub muted: Color32,
    pub line: Color32,
    pub edge: Color32,
    pub accent: Color32,
    pub accent_ink: Color32,
    pub tag: Color32,
    pub code: Color32,
    pub good: Color32,
    pub bad: Color32,
    pub hl: Color32,        // hover / selected row
    pub hl_ink: Option<Color32>, // XP + 95: rows go navy with white text on hover
    pub header: Color32,
    #[allow(dead_code)]
    pub header_ink: Color32,
    pub logo_ink: Color32,
}

pub const fn hex(c: u32) -> Color32 {
    Color32::from_rgb((c >> 16) as u8, (c >> 8) as u8, c as u8)
}
fn mix(a: Color32, b: Color32, t: f32) -> Color32 {
    let l = |x: u8, y: u8| (x as f32 + (y as f32 - x as f32) * t).round() as u8;
    Color32::from_rgb(l(a.r(), b.r()), l(a.g(), b.g()), l(a.b(), b.b()))
}

pub fn pal(skin: Skin, dark: bool) -> Pal {
    let dark = skin.fixed_theme().unwrap_or(dark);
    // GURT's own colors first; every other skin starts from them
    let mut p = if dark {
        Pal { skin, dark, r: 2, bg: hex(0x0a0a0b), panel: hex(0x111113), ink: hex(0xe7e7ea), muted: hex(0x8e8e97), line: hex(0x222226), edge: hex(0x2f2f35),
            accent: hex(0xffc629), accent_ink: hex(0x111113), tag: hex(0x19191c), code: hex(0x070708), good: hex(0x4ade80), bad: hex(0xf05252),
            hl: Color32::TRANSPARENT, hl_ink: None, header: hex(0x111113), header_ink: hex(0xe7e7ea), logo_ink: hex(0xe7e7ea) }
    } else {
        Pal { skin, dark, r: 2, bg: hex(0xececee), panel: hex(0xfafafa), ink: hex(0x111113), muted: hex(0x5b5b63), line: hex(0xd9d9de), edge: hex(0xb9b9c1),
            accent: hex(0xffc629), accent_ink: hex(0x111113), tag: hex(0xe2e2e6), code: hex(0xf4f4f5), good: hex(0x17803d), bad: hex(0xc62828),
            hl: Color32::TRANSPARENT, hl_ink: None, header: hex(0xfafafa), header_ink: hex(0x111113), logo_ink: hex(0x111113) }
    };
    match skin {
        Skin::Gurt | Skin::Gold => {}
        Skin::Win11 if dark => {
            p = Pal { r: 4, bg: hex(0x202020), panel: hex(0x2b2b2b), ink: hex(0xffffff), muted: hex(0xc5c5c5), line: hex(0x333333), edge: hex(0x3d3d3d),
                accent: hex(0x60cdff), accent_ink: hex(0x000000), tag: hex(0x323232), code: hex(0x1c1c1c), header: hex(0x2b2b2b), header_ink: hex(0xffffff), ..p };
            p.hl = Color32::from_rgba_unmultiplied(255, 255, 255, 13);
        }
        Skin::Win11 => {
            p = Pal { r: 4, bg: hex(0xf3f3f3), panel: hex(0xfbfbfb), ink: hex(0x1b1b1b), muted: hex(0x5d5d5d), line: hex(0xebebeb), edge: hex(0xdedede),
                accent: hex(0x005fb8), accent_ink: hex(0xffffff), tag: hex(0xf0f0f0), code: hex(0xf9f9f9), header: hex(0xfbfbfb), header_ink: hex(0x1b1b1b), ..p };
            p.hl = Color32::from_rgba_unmultiplied(0, 0, 0, 10);
        }
        Skin::Xp => {
            p = Pal { r: 3, bg: hex(0xece9d8), panel: hex(0xffffff), ink: hex(0x000000), muted: hex(0x444444), line: hex(0xe1ddca), edge: hex(0x7f9db9),
                accent: hex(0x3c8d0d), accent_ink: hex(0xffffff), tag: hex(0xf4f3ee), code: hex(0x000000), good: hex(0x2c7a0b), bad: hex(0xc4271b),
                hl: hex(0x316ac5), hl_ink: Some(hex(0xffffff)), header: hex(0x245edb), header_ink: hex(0xffffff), logo_ink: hex(0x141414), ..p };
        }
        Skin::W95 => {
            p = Pal { r: 0, bg: hex(0x008080), panel: hex(0xc0c0c0), ink: hex(0x000000), muted: hex(0x222222), line: hex(0xc0c0c0), edge: hex(0x808080),
                accent: hex(0x000080), accent_ink: hex(0xffffff), tag: hex(0xc0c0c0), code: hex(0xffffff), good: hex(0x006400), bad: hex(0xa00000),
                hl: hex(0x000080), hl_ink: Some(hex(0xffffff)), header: hex(0x000080), header_ink: hex(0xffffff), logo_ink: hex(0x141414), ..p };
        }
        Skin::Vapor => {
            p = Pal { r: 2, bg: hex(0x1a0b2e), panel: hex(0x22103f), ink: hex(0xfde7ff), muted: hex(0xc79bd8), line: hex(0x3d1d66), edge: hex(0xb967ff),
                accent: hex(0xff71ce), accent_ink: hex(0x1a0b2e), tag: hex(0x2e1557), code: hex(0x140726), good: hex(0x05ffa1), bad: hex(0xff4f81),
                hl: Color32::from_rgba_unmultiplied(1, 205, 254, 34), header: hex(0x22103f), header_ink: hex(0xfde7ff), logo_ink: hex(0xf1ede2), ..p };
        }
        Skin::Hacker => {
            p = Pal { r: 0, bg: hex(0x000000), panel: hex(0x000000), ink: hex(0x33ff66), muted: hex(0x1fa83f), line: hex(0x0b2a10), edge: hex(0x145a22),
                accent: hex(0x33ff66), accent_ink: hex(0x000000), tag: hex(0x031105), code: hex(0x000000), good: hex(0x33ff66), bad: hex(0xff3355),
                hl: Color32::from_rgba_unmultiplied(51, 255, 102, 20), header: hex(0x000000), header_ink: hex(0x33ff66), logo_ink: hex(0xf1ede2), ..p };
        }
    }
    if skin == Skin::Gold {
        // 🦆✨ black lacquer + gold leaf: everything that isn't black is gold, in three strengths
        p = Pal { r: 0, bg: hex(0x0b0906), panel: hex(0x13100a), ink: hex(0xf2e6c2), muted: hex(0xb3a06b), line: hex(0x2a2213), edge: hex(0x8c6f2b),
            accent: hex(0xd4af37), accent_ink: hex(0x0b0906), tag: hex(0x1c170d), code: hex(0x070604), good: hex(0xa8d17f), bad: hex(0xe0614b),
            hl: Color32::from_rgba_unmultiplied(212, 175, 55, 26), header: hex(0x0b0906), header_ink: hex(0xd4af37), logo_ink: hex(0xf2e6c2), ..p };
    }
    if p.hl == Color32::TRANSPARENT {
        // GURT: the accent at 18% over the panel
        p.hl = mix(p.panel, p.accent, 0.18);
    }
    p
}

// vaporwave's second neon (borders, sources) and its yellow (versions, headings)
pub const VAPOR_CYAN: Color32 = hex(0x01cdfe);
pub const VAPOR_YELLOW: Color32 = hex(0xfffb96);

// ── fonts: each skin's own, found with fontconfig (fc-match always answers with the closest one you have) ──
fn fc(pattern: &str) -> Option<Vec<u8>> {
    let out = Command::new("fc-match").args(["-f", "%{file}", pattern]).stderr(Stdio::null()).output().ok()?;
    let f = String::from_utf8_lossy(&out.stdout).into_owned();
    let low = f.to_lowercase();
    if f.is_empty() || !(low.ends_with(".ttf") || low.ends_with(".otf") || low.ends_with(".ttc")) {
        return None;
    }
    std::fs::read(f).ok()
}

pub fn fonts(skin: Skin) -> egui::FontDefinitions {
    let (sans, mono): (&[&str], &[&str]) = match skin {
        Skin::Gurt => (&["Inter", "Noto Sans", "Cantarell", "DejaVu Sans", "sans-serif"], &["JetBrains Mono", "DejaVu Sans Mono", "monospace"]),
        Skin::Win11 => (&["Segoe UI Variable", "Segoe UI", "Noto Sans", "sans-serif"], &["Cascadia Mono", "Cascadia Code", "DejaVu Sans Mono", "monospace"]),
        Skin::Xp => (&["Tahoma", "Verdana", "DejaVu Sans", "sans-serif"], &["Lucida Console", "DejaVu Sans Mono", "monospace"]),
        Skin::W95 => (&["Microsoft Sans Serif", "Arial", "Liberation Sans", "sans-serif"], &["Courier New", "Liberation Mono", "monospace"]),
        Skin::Vapor => (&["Noto Sans", "DejaVu Sans", "sans-serif"], &["VT323", "DejaVu Sans Mono", "monospace"]),
        Skin::Hacker => (&["JetBrains Mono", "DejaVu Sans Mono", "monospace"], &["JetBrains Mono", "DejaVu Sans Mono", "monospace"]),
        Skin::Gold => (&["Noto Serif", "DejaVu Serif", "Liberation Serif", "serif"], &["DejaVu Sans Mono", "monospace"]),
    };
    let mut defs = egui::FontDefinitions::default();
    // the first family name fontconfig really has (fc-match falls back by itself; ask for the exact family first)
    let pick = |names: &[&str], bold: bool| -> Option<Vec<u8>> {
        for n in names {
            let pat = if bold { format!("{n}:bold") } else { format!("{n}:regular") };
            if let Ok(o) = Command::new("fc-match").args(["-f", "%{family}", &pat]).stderr(Stdio::null()).output() {
                let fam = String::from_utf8_lossy(&o.stdout).to_lowercase();
                if fam.split(',').any(|f| f.trim() == n.to_lowercase()) || *n == "sans-serif" || *n == "monospace" || *n == "serif" {
                    if let Some(b) = fc(&pat) {
                        return Some(b);
                    }
                }
            }
        }
        None
    };
    let mut add = |key: &str, data: Option<Vec<u8>>, fam: FontFamily| {
        if let Some(d) = data {
            defs.font_data.insert(key.into(), std::sync::Arc::new(egui::FontData::from_owned(d)));
            defs.families.entry(fam).or_default().insert(0, key.into());
        }
    };
    add("sans", pick(sans, false), FontFamily::Proportional);
    add("mono", pick(mono, false), FontFamily::Monospace);
    let fallback_p = defs.families.get(&FontFamily::Proportional).cloned().unwrap_or_default();
    let fallback_m = defs.families.get(&FontFamily::Monospace).cloned().unwrap_or_default();
    let mut bold = |key: &str, data: Option<Vec<u8>>, fam: &str, fallback: &[String]| {
        let mut list: Vec<String> = Vec::new();
        if let Some(d) = data {
            defs.font_data.insert(key.into(), std::sync::Arc::new(egui::FontData::from_owned(d)));
            list.push(key.into());
        }
        list.extend(fallback.iter().cloned());
        defs.families.insert(FontFamily::Name(fam.into()), list);
    };
    bold("sansb", pick(sans, true), "sansb", &fallback_p);
    bold("monob", pick(mono, true), "monob", &fallback_m);
    defs
}

// the text styles GURT uses
pub fn mono(size: f32) -> FontId {
    FontId::new(size, FontFamily::Monospace)
}
pub fn monob(size: f32) -> FontId {
    FontId::new(size, FontFamily::Name("monob".into()))
}
pub fn sans(size: f32) -> FontId {
    FontId::new(size, FontFamily::Proportional)
}
pub fn sansb(size: f32) -> FontId {
    FontId::new(size, FontFamily::Name("sansb".into()))
}

/// egui's own widgets (text fields, checkboxes, combo boxes, scrollbars) in the skin's colors
pub fn style(p: &Pal, base: &egui::Style) -> egui::Style {
    let mut s = base.clone();
    let r = CornerRadius::same(p.r);
    let v = &mut s.visuals;
    *v = if p.dark { egui::Visuals::dark() } else { egui::Visuals::light() };
    v.override_text_color = Some(p.ink);
    v.panel_fill = p.bg;
    v.window_fill = p.panel;
    v.window_stroke = Stroke::new(1.0, p.edge);
    v.window_shadow = egui::Shadow::NONE;
    v.popup_shadow = egui::Shadow::NONE;
    v.window_corner_radius = r;
    v.menu_corner_radius = r;
    v.extreme_bg_color = if p.skin == Skin::W95 { hex(0xffffff) } else { p.panel };
    v.text_edit_bg_color = Some(if p.skin == Skin::W95 { hex(0xffffff) } else { p.panel });
    v.faint_bg_color = p.tag;
    v.code_bg_color = p.code;
    v.hyperlink_color = if p.skin == Skin::Gurt { p.ink } else { p.accent };
    v.selection.bg_fill = if p.skin == Skin::Gurt { mix(p.panel, p.accent, 0.45) } else { p.hl.to_opaque() };
    v.selection.stroke = Stroke::new(1.0, p.accent);
    v.warn_fg_color = p.accent;
    v.error_fg_color = p.bad;
    for (w, fill, stroke) in [
        (&mut v.widgets.noninteractive, p.panel, p.line),
        (&mut v.widgets.inactive, p.panel, p.edge),
        (&mut v.widgets.hovered, p.tag, p.muted),
        (&mut v.widgets.active, p.tag, p.accent),
        (&mut v.widgets.open, p.tag, p.accent),
    ] {
        w.bg_fill = fill;
        w.weak_bg_fill = fill;
        w.bg_stroke = Stroke::new(1.0, stroke);
        w.corner_radius = r;
        w.fg_stroke = Stroke::new(1.0, p.ink);
        w.expansion = 0.0;
    }
    v.widgets.noninteractive.fg_stroke = Stroke::new(1.0, p.ink);
    s.spacing.item_spacing = egui::vec2(6.0, 6.0);
    s.spacing.button_padding = egui::vec2(9.0, 4.0);
    s.spacing.interact_size.y = 22.0;
    s.spacing.scroll.bar_width = 8.0;
    s.spacing.scroll.floating = false;
    s.text_styles.insert(egui::TextStyle::Body, sans(14.0));
    s.text_styles.insert(egui::TextStyle::Button, mono(12.5));
    s.text_styles.insert(egui::TextStyle::Monospace, mono(12.5));
    s.text_styles.insert(egui::TextStyle::Small, sans(12.0));
    s.text_styles.insert(egui::TextStyle::Heading, sansb(16.0));
    if p.skin == Skin::Hacker {
        s.text_styles.insert(egui::TextStyle::Body, mono(13.5));
    }
    s.interaction.selectable_labels = false;
    s.animation_time = 0.0;
    s
}

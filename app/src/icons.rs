//! app logos: Flathub's icon (or a recipe's icon=), then the app's own desktop icon on this computer, then a letter tile.
//! the computer's icons are looked up on a worker thread (icon themes are big folders)
use crate::data::DesktopIcons;
use crate::skin::Pal;
use egui::{Color32, Rect, Ui};
use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use std::sync::mpsc::{channel, Sender};
use std::sync::{Arc, Mutex};

pub struct Icons {
    failed: HashSet<String>,
    local: Arc<Mutex<HashMap<String, Option<PathBuf>>>>,
    asked: HashSet<String>,
    tx: Sender<(String, Vec<String>)>,
}

impl Icons {
    pub fn new() -> Icons {
        let (tx, rx) = channel::<(String, Vec<String>)>();
        let local: Arc<Mutex<HashMap<String, Option<PathBuf>>>> = Default::default();
        let out = local.clone();
        std::thread::spawn(move || {
            let idx = DesktopIcons::scan();
            for (name, wants) in rx {
                let f = idx.find(&wants);
                out.lock().unwrap().insert(name, f);
                if let Some(r) = crate::jobs::REPAINT.get() {
                    r();
                }
            }
        });
        Icons { failed: HashSet::new(), local, asked: HashSet::new(), tx }
    }

    fn try_paint(&mut self, ui: &Ui, r: Rect, uri: &str) -> Option<bool> {
        if self.failed.contains(uri) {
            return Some(false);
        }
        let hint = egui::load::SizeHint::Size { width: 64, height: 64, maintain_aspect_ratio: true };
        match ui.ctx().try_load_texture(uri, egui::TextureOptions::LINEAR, hint) {
            Ok(egui::load::TexturePoll::Ready { texture }) => {
                // keep its shape inside the square
                let s = texture.size;
                let k = (r.width() / s.x).min(r.height() / s.y);
                let rr = Rect::from_center_size(r.center(), s * k);
                ui.painter().image(texture.id, rr, Rect::from_min_max(egui::pos2(0.0, 0.0), egui::pos2(1.0, 1.0)), Color32::WHITE);
                Some(true)
            }
            Ok(egui::load::TexturePoll::Pending { .. }) => None,
            Err(_) => {
                self.failed.insert(uri.to_string());
                Some(false)
            }
        }
    }

    /// paint the logo for an app; false = nothing to show (yet), paint a letter
    pub fn paint(&mut self, ui: &Ui, r: Rect, name: &str, remote: &str, wants: &[String]) -> bool {
        if !remote.is_empty() {
            match self.try_paint(ui, r, remote) {
                Some(true) => return true,
                None => return false,
                Some(false) => {}
            }
        }
        let hit = self.local.lock().unwrap().get(name).cloned();
        match hit {
            Some(Some(path)) => {
                let uri = format!("file://{}", path.display());
                self.try_paint(ui, r, &uri).unwrap_or(false)
            }
            Some(None) => false,
            None => {
                if self.asked.insert(name.to_string()) {
                    let _ = self.tx.send((name.to_string(), wants.to_vec()));
                }
                false
            }
        }
    }
}

const LOGO: &str = include_str!("../assets/logo.svg");
const DIRT: &[u8] = include_bytes!("../../site/assets/dirt-logo.png");

/// the gurt wordmark (its first letter takes the skin's ink), or DIRT's logo in the dirt section
pub fn logo(ui: &mut Ui, p: &Pal, h: f32, dirt: bool) {
    let ctx = ui.ctx().clone();
    if dirt {
        ctx.include_bytes("bytes://dirt-logo.png", DIRT);
        ui.add(egui::Image::new("bytes://dirt-logo.png").fit_to_exact_size(egui::vec2(h * 2.6, h)));
        return;
    }
    let ink = p.logo_ink;
    let hexs = format!("#{:02x}{:02x}{:02x}", ink.r(), ink.g(), ink.b());
    let uri = format!("bytes://gurt-logo-{}.svg", &hexs[1..]);
    ctx.include_bytes(uri.clone(), LOGO.replace("var(--logo-ink)", &hexs).into_bytes());
    ui.add(egui::Image::new(uri).fit_to_exact_size(egui::vec2(h * 3791.0 / 1805.0, h)));
}

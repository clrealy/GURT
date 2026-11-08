//! GURT, the app. a native window for the gurt CLI (gurt gui), the GURT Setup Wizard (--wizard) and GURTd (--daemon)
//!   gurt-app [--gurt <path to gurt>] [--wizard [--from-app]] [--daemon] [file to install]
mod app;
mod daemon;
mod data;
mod dialogs;
mod icons;
mod jobs;
mod skin;
mod sound;
mod tabs;
mod widgets;
mod wizard;

const ICON: &[u8] = include_bytes!("../../site/assets/apple-touch-icon.png");

fn usage() -> ! {
    println!("gurt-app {}: GURT's app window\n\n  gurt-app                  open GURT\n  gurt-app --wizard         the GURT Setup Wizard\n  gurt-app --daemon         run GURTd (gurt gurtd on does this for you)\n  gurt-app <file>           open GURT and install that package\n  --gurt <path>             which gurt to drive (default: gurt on your PATH)", env!("CARGO_PKG_VERSION"));
    std::process::exit(0)
}

fn main() {
    let mut args = std::env::args().skip(1);
    let (mut wizard, mut from_app, mut daemon_mode, mut file, mut gurt, mut size) = (false, false, false, None, None, None);
    while let Some(a) = args.next() {
        match a.as_str() {
            "--askpass" => {
                // sudo runs us like this (see jobs.rs): hand it the password you type in the window
                let prompt: Vec<String> = args.collect();
                std::process::exit(jobs::askpass_main(prompt.join(" ")));
            }
            "--wizard" => wizard = true,
            "--from-app" => from_app = true,
            "--daemon" => daemon_mode = true,
            "--gurt" => gurt = args.next(),
            "--size" => size = args.next(), // for screenshots: WxH
            "--probe" => {
                // there's always a native window now
                println!("native");
                std::process::exit(0);
            }
            "-h" | "--help" => usage(),
            "--version" => {
                println!("gurt-app {}", env!("CARGO_PKG_VERSION"));
                return;
            }
            "--browser" | "--no-window" | "--attach" => {} // the old app's flags: nothing to do anymore
            f if !f.starts_with("--") => {
                let f = f.strip_prefix("file://").unwrap_or(f).to_string();
                let p = std::path::PathBuf::from(&f);
                file = p.is_file().then(|| std::fs::canonicalize(&p).unwrap_or(p));
            }
            _ => {}
        }
    }
    let _ = data::GURT.set(gurt.unwrap_or_else(|| "gurt".into()));
    if daemon_mode {
        std::process::exit(daemon::main());
    }
    // until the setup wizard is finished, opening GURT opens the wizard
    if !wizard && data::conf_str("wizard").as_deref() != Some("done") {
        wizard = true;
    }
    jobs::setup_askpass();
    let (title, w, h, id) = if wizard { ("GURT Setup Wizard", 900.0, 640.0, "gurt-setup") } else { ("GURT", 1100.0, 760.0, "gurt") };
    let (w, h) = size.and_then(|s| s.split_once('x').and_then(|(a, b)| Some((a.parse().ok()?, b.parse().ok()?)))).unwrap_or((w, h));
    let mut vp = egui::ViewportBuilder::default().with_title(title).with_app_id(id).with_inner_size([w, h]).with_min_inner_size([360.0, 420.0]);
    if let Ok(img) = image::load_from_memory(ICON) {
        let rgba = img.to_rgba8();
        let (iw, ih) = rgba.dimensions();
        vp = vp.with_icon(egui::IconData { rgba: rgba.into_raw(), width: iw, height: ih });
    }
    let opts = eframe::NativeOptions { viewport: vp, ..Default::default() };
    let r = eframe::run_native(title, opts, Box::new(move |cc| Ok(Box::new(app::App::new(cc, wizard, from_app, file)))));
    jobs::cleanup_askpass();
    if let Err(e) = r {
        eprintln!("GURT couldn't open its window: {e}");
        std::process::exit(1);
    }
}

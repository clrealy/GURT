//! sound effects + background music, synthesized live (no audio files), every skin with its own set.
//! the samples go to paplay / pw-cat / aplay, so the app needs no audio library of its own
use crate::skin::Skin;
use std::io::Write;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

const SR: f32 = 44100.0;

pub const TRACKS: [(&str, &str); 6] = [("auto", "auto"), ("shop", "shop"), ("lofi", "lofi"), ("chip", "chiptune"), ("synth", "synthwave"), ("shanty", "shanty")];
/// tracks a GURT key unlocks
pub fn track_locked(id: &str) -> bool {
    id == "shanty"
}
pub fn track_name(id: &str) -> &'static str {
    TRACKS.iter().find(|t| t.0 == id).map(|t| t.1).unwrap_or("auto")
}

fn player() -> Option<Vec<&'static str>> {
    let cands: [&[&str]; 3] = [
        &["paplay", "--raw", "--format=s16le", "--rate=44100", "--channels=1", "--client-name=GURT"],
        &["pw-cat", "--playback", "--format", "s16", "--rate", "44100", "--channels", "1", "-"],
        &["aplay", "-q", "-t", "raw", "-f", "S16_LE", "-r", "44100", "-c", "1"],
    ];
    cands.iter().find(|c| crate::data::has(c[0])).map(|c| c.to_vec())
}

fn spawn_player() -> Option<Child> {
    let p = player()?;
    Command::new(p[0]).args(&p[1..]).stdin(Stdio::piped()).stdout(Stdio::null()).stderr(Stdio::null()).spawn().ok()
}

fn to_pcm(buf: &[f32]) -> Vec<u8> {
    let mut out = Vec::with_capacity(buf.len() * 2);
    for s in buf {
        let v = (s.clamp(-1.0, 1.0) * 32000.0) as i16;
        out.extend_from_slice(&v.to_le_bytes());
    }
    out
}

#[derive(Clone, Copy, PartialEq)]
enum Wave {
    Sine,
    Square,
    Saw,
    Tri,
}
use Wave::*;

/// a buffer the notes get mixed into
struct Mix {
    b: Vec<f32>,
    wrap: bool, // music loops: tails wrap around to the start
}
impl Mix {
    fn new(secs: f32, wrap: bool) -> Mix {
        Mix { b: vec![0.0; (secs * SR) as usize + 1], wrap }
    }
    fn add(&mut self, i: usize, v: f32) {
        let n = self.b.len();
        if i < n {
            self.b[i] += v;
        } else if self.wrap {
            self.b[i % n] += v;
        }
    }
    /// one note: freq, start, length, wave, volume, glide-to freq, attack (exponential envelope like WebAudio's)
    fn tone(&mut self, f: f32, t: f32, dur: f32, wave: Wave, vol: f32, f2: f32, atk: f32) {
        let n = (dur * SR) as usize;
        let s0 = (t * SR) as usize;
        let mut ph = 0.0f32;
        for i in 0..n {
            let x = i as f32 / SR;
            let fr = if f2 > 0.0 { f * (f2 / f).powf(x / dur) } else { f };
            ph = (ph + fr / SR).fract();
            let w = match wave {
                Sine => (ph * std::f32::consts::TAU).sin(),
                Square => if ph < 0.5 { 1.0 } else { -1.0 },
                Saw => 2.0 * ph - 1.0,
                Tri => 4.0 * (ph - 0.5).abs() - 1.0,
            };
            // up to vol over atk, then down to ~0 by the end (exponential)
            let env = if x < atk { 0.0001 * (vol / 0.0001).powf(x / atk) } else { vol * (0.0001 / vol).powf(((x - atk) / (dur - atk).max(1e-4)).min(1.0)) };
            self.add(s0 + i, w * env);
        }
    }
    fn bell(&mut self, f: f32, t: f32, dur: f32, vol: f32) {
        self.tone(f, t, dur, Tri, vol, 0.0, 0.004);
        self.tone(f * 2.01, t, dur * 0.6, Sine, vol * 0.35, 0.0, 0.004);
    }
    fn pad(&mut self, fs: &[f32], t: f32, dur: f32, wave: Wave, vol: f32, atk: f32) {
        for &f in fs {
            self.tone(f, t, dur, wave, vol, 0.0, atk);
            self.tone(f * 1.004, t, dur, wave, vol * 0.7, 0.0, atk);
        }
    }
    fn arp(&mut self, fs: &[f32], t: f32, step: f32, dur: f32, wave: Wave, vol: f32) {
        for (i, &f) in fs.iter().enumerate() {
            self.tone(f, t + i as f32 * step, dur, wave, vol, 0.0, 0.004);
        }
    }
    fn arp_bell(&mut self, fs: &[f32], t: f32, step: f32, dur: f32, vol: f32) {
        for (i, &f) in fs.iter().enumerate() {
            self.bell(f, t + i as f32 * step, dur, vol);
        }
    }
    /// filtered noise: drums (highpass hats, bandpass snares)
    fn noise(&mut self, t: f32, vol: f32, freq: f32, band: bool, dur: f32, seed: &mut u32) {
        let n = (dur * SR) as usize;
        let s0 = (t * SR) as usize;
        let mut bq = Biquad::new(freq, band);
        for i in 0..n {
            *seed ^= *seed << 13;
            *seed ^= *seed >> 17;
            *seed ^= *seed << 5;
            let r = (*seed as f32 / u32::MAX as f32) * 2.0 - 1.0;
            let env = vol * (0.0001 / vol).powf(i as f32 / n as f32);
            self.add(s0 + i, bq.run(r) * env);
        }
    }
    fn kick(&mut self, t: f32, vol: f32) {
        let n = (0.3 * SR) as usize;
        let s0 = (t * SR) as usize;
        let mut ph = 0.0f32;
        for i in 0..n {
            let x = i as f32 / SR;
            let f = if x < 0.12 { 130.0 * (42.0f32 / 130.0).powf(x / 0.12) } else { 42.0 };
            ph = (ph + f / SR).fract();
            let env = vol * (0.0001 / vol).powf((x / 0.25).min(1.0));
            self.add(s0 + i, (ph * std::f32::consts::TAU).sin() * env);
        }
    }
}

struct Biquad {
    b0: f32,
    b1: f32,
    b2: f32,
    a1: f32,
    a2: f32,
    x1: f32,
    x2: f32,
    y1: f32,
    y2: f32,
}
impl Biquad {
    fn new(f: f32, band: bool) -> Biquad {
        let w = std::f32::consts::TAU * f.min(SR * 0.45) / SR;
        let (s, c) = w.sin_cos();
        let q = if band { 1.0 } else { 0.707 };
        let a = s / (2.0 * q);
        let a0 = 1.0 + a;
        let (b0, b1, b2) = if band { (a, 0.0, -a) } else { ((1.0 + c) / 2.0, -(1.0 + c), (1.0 + c) / 2.0) };
        Biquad { b0: b0 / a0, b1: b1 / a0, b2: b2 / a0, a1: -2.0 * c / a0, a2: (1.0 - a) / a0, x1: 0.0, x2: 0.0, y1: 0.0, y2: 0.0 }
    }
    fn run(&mut self, x: f32) -> f32 {
        let y = self.b0 * x + self.b1 * self.x1 + self.b2 * self.x2 - self.a1 * self.y1 - self.a2 * self.y2;
        self.x2 = self.x1;
        self.x1 = x;
        self.y2 = self.y1;
        self.y1 = y;
        y
    }
}

/// one sound effect, rendered for a skin
fn sfx(skin: Skin, name: &str) -> Option<Vec<f32>> {
    let mut m = Mix::new(3.6, false);
    let t = 0.01;
    let mut rng = 0x9e3779b9u32 ^ crate::data::rand_below(1 << 30);
    let mut rnd = |a: f32| {
        rng ^= rng << 13;
        rng ^= rng >> 17;
        rng ^= rng << 5;
        (rng as f32 / u32::MAX as f32) * a
    };
    // shared by every skin
    match name {
        "cursed" => {
            for i in 0..8 {
                let (a, b) = (rnd(900.0), rnd(200.0));
                m.tone(90.0 + a, t + i as f32 * 0.07, 0.09, Saw, 0.04, 40.0 + b, 0.004);
            }
            return Some(m.b);
        }
        "legendary" => {
            m.arp(&[523., 659., 784., 1047., 1319., 1568., 2093.], t, 0.07, 0.35, Tri, 0.05);
            m.pad(&[523., 659., 784., 1047.], t + 0.5, 1.6, Sine, 0.03, 0.1);
            return Some(m.b);
        }
        "achieve" => {
            m.arp(&[784., 988., 1175., 1568.], t, 0.09, 0.3, Tri, 0.05);
            return Some(m.b);
        }
        _ => {}
    }
    match (skin, name) {
        (Skin::Gurt, "click") => m.tone(620., t, 0.045, Square, 0.03, 0., 0.004),
        (Skin::Gurt, "tick") => m.tone(700. + rnd(600.), t, 0.03, Square, 0.025, 0., 0.004),
        (Skin::Gurt, "jackpot") => m.arp(&[523., 659., 784., 1047., 1319.], t, 0.08, 0.18, Tri, 0.06),
        (Skin::Gurt, "pick") => m.tone(660., t, 0.07, Tri, 0.05, 990., 0.004),
        (Skin::Gurt, "unpick") => m.tone(660., t, 0.07, Tri, 0.05, 440., 0.004),
        (Skin::Gurt, "ok") => m.arp(&[784., 1047., 1568.], t, 0.07, 0.14, Tri, 0.06),
        (Skin::Gurt, "err") => {
            m.tone(196., t, 0.18, Saw, 0.05, 0., 0.004);
            m.tone(147., t + 0.16, 0.28, Saw, 0.05, 0., 0.004);
        }
        (Skin::Gurt, "theme") => m.tone(300., t, 0.22, Sine, 0.05, 900., 0.004),
        (Skin::Gurt, "pop") => m.tone(400., t, 0.09, Sine, 0.07, 1200., 0.004),
        (Skin::Gurt, "startup") => m.arp(&[392., 523., 659., 784.], t, 0.07, 0.2, Tri, 0.05),

        (Skin::Win11, "click") => m.tone(1400., t, 0.03, Sine, 0.025, 0., 0.004),
        (Skin::Win11, "tick") => m.tone(1100. + rnd(300.), t, 0.035, Sine, 0.03, 0., 0.004),
        (Skin::Win11, "jackpot") => {
            for (i, f) in [659., 784., 988., 1319.].iter().enumerate() {
                m.tone(*f, t + i as f32 * 0.09, 0.5, Sine, 0.05, 0., 0.01);
            }
        }
        (Skin::Win11, "pick") => m.tone(880., t, 0.08, Sine, 0.04, 1175., 0.004),
        (Skin::Win11, "unpick") => m.tone(880., t, 0.08, Sine, 0.04, 660., 0.004),
        (Skin::Win11, "ok") => {
            m.tone(988., t, 0.35, Sine, 0.05, 0., 0.01);
            m.tone(1319., t + 0.12, 0.45, Sine, 0.05, 0., 0.01);
        }
        (Skin::Win11, "err") => {
            m.tone(523., t, 0.25, Sine, 0.06, 0., 0.01);
            m.tone(392., t + 0.14, 0.4, Sine, 0.06, 0., 0.01);
        }
        (Skin::Win11, "theme") => m.tone(500., t, 0.3, Sine, 0.04, 1000., 0.05),
        (Skin::Win11, "pop") => m.tone(700., t, 0.12, Sine, 0.05, 1050., 0.004),
        (Skin::Win11, "startup") => {
            m.pad(&[262., 330., 392., 494.], t, 1.4, Sine, 0.025, 0.35);
            for (i, f) in [784., 988., 1175.].iter().enumerate() {
                m.tone(*f, t + 0.35 + i as f32 * 0.12, 0.6, Sine, 0.035, 0., 0.02);
            }
        }

        (Skin::Xp, "click") => m.tone(1800., t, 0.018, Square, 0.02, 0., 0.004),
        (Skin::Xp, "tick") => m.bell(988. + rnd(500.), t, 0.08, 0.03),
        (Skin::Xp, "jackpot") => {
            m.pad(&[311., 466., 622., 784.], t, 2.2, Sine, 0.025, 0.5);
            m.arp_bell(&[622., 932., 1245., 1568.], t + 0.3, 0.22, 1.0, 0.045);
        }
        (Skin::Xp, "pick") => m.bell(1175., t, 0.18, 0.035),
        (Skin::Xp, "unpick") => m.bell(784., t, 0.18, 0.035),
        (Skin::Xp, "ok") => m.arp_bell(&[622., 784., 932., 1245.], t, 0.1, 0.5, 0.045),
        (Skin::Xp, "err") => m.arp_bell(&[784., 587., 392.], t, 0.13, 0.45, 0.06),
        (Skin::Xp, "theme") => m.tone(400., t, 0.35, Tri, 0.04, 800., 0.05),
        (Skin::Xp, "pop") => m.bell(880., t, 0.25, 0.05),
        (Skin::Xp, "startup") => {
            m.pad(&[156., 233., 311., 392., 466.], t, 3.0, Sine, 0.022, 0.8);
            m.arp_bell(&[622., 932., 1245., 1568., 1865.], t + 0.6, 0.25, 1.4, 0.04);
        }

        (Skin::Vapor, "click") => m.tone(880., t, 0.08, Sine, 0.03, 760., 0.004),
        (Skin::Vapor, "tick") => m.tone(500. + rnd(300.), t, 0.07, Sine, 0.03, 420., 0.004),
        (Skin::Vapor, "jackpot") => {
            m.pad(&[220., 277., 330., 415.], t, 2.4, Saw, 0.012, 0.6);
            for (i, f) in [659., 554., 494., 440.].iter().enumerate() {
                m.tone(*f, t + 0.2 + i as f32 * 0.3, 1.0, Sine, 0.04, f * 0.94, 0.05);
            }
        }
        (Skin::Vapor, "pick") => m.tone(660., t, 0.18, Sine, 0.04, 620., 0.004),
        (Skin::Vapor, "unpick") => m.tone(440., t, 0.18, Sine, 0.04, 400., 0.004),
        (Skin::Vapor, "ok") => m.pad(&[262., 330., 392., 494.], t, 1.2, Sine, 0.025, 0.2),
        (Skin::Vapor, "err") => m.tone(330., t, 0.6, Saw, 0.035, 110., 0.004),
        (Skin::Vapor, "theme") => m.tone(600., t, 0.5, Sine, 0.04, 300., 0.004),
        (Skin::Vapor, "pop") => m.tone(990., t, 0.2, Sine, 0.05, 800., 0.004),
        (Skin::Vapor, "startup") => {
            m.pad(&[131., 165., 196., 247.], t, 3.0, Saw, 0.012, 0.9);
            for (i, f) in [494., 440., 392., 330.].iter().enumerate() {
                m.tone(*f, t + 0.8 + i as f32 * 0.4, 1.2, Sine, 0.035, f * 0.97, 0.1);
            }
        }

        (Skin::Hacker, "click") => m.tone(2400., t, 0.012, Square, 0.02, 0., 0.004),
        (Skin::Hacker, "tick") => m.tone(1200. + rnd(2400.), t, 0.015, Square, 0.02, 0., 0.004),
        (Skin::Hacker, "jackpot") => {
            for i in 0..12 {
                m.tone(800. + rnd(2600.), t + i as f32 * 0.035, 0.03, Square, 0.025, 0., 0.004);
            }
            m.arp(&[523., 784., 1047.], t + 0.45, 0.06, 0.12, Square, 0.03);
        }
        (Skin::Hacker, "pick") => m.tone(1600., t, 0.03, Square, 0.025, 0., 0.004),
        (Skin::Hacker, "unpick") => m.tone(800., t, 0.03, Square, 0.025, 0., 0.004),
        (Skin::Hacker, "ok") => m.arp(&[1047., 1319., 1568., 2093.], t, 0.04, 0.05, Square, 0.03),
        (Skin::Hacker, "err") => {
            m.tone(110., t, 0.3, Square, 0.04, 0., 0.004);
            m.tone(117., t, 0.3, Square, 0.04, 0., 0.004);
        }
        (Skin::Hacker, "theme") => m.tone(200., t, 0.15, Square, 0.03, 2000., 0.004),
        (Skin::Hacker, "pop") => m.tone(1400., t, 0.03, Square, 0.03, 0., 0.004),
        (Skin::Hacker, "startup") => {
            for i in 0..20 {
                m.tone(600. + rnd(1800.), t + i as f32 * 0.04, 0.035, Square, 0.02, 0., 0.004);
            }
            m.tone(1000., t + 0.9, 0.25, Sine, 0.04, 0., 0.004);
        }

        (Skin::W95, "click") => m.tone(1000., t, 0.03, Square, 0.035, 0., 0.004),
        (Skin::W95, "tick") => m.tone(500. + rnd(400.), t, 0.04, Square, 0.03, 0., 0.004),
        (Skin::W95, "jackpot") => {
            for (i, f) in [523., 659., 784.].iter().enumerate() {
                m.tone(*f, t + i as f32 * 0.09, 0.12, Saw, 0.04, 0., 0.01);
            }
            m.pad(&[523., 659., 784., 1047.], t + 0.3, 0.9, Saw, 0.018, 0.02);
        }
        (Skin::W95, "pick") => m.tone(784., t, 0.05, Square, 0.035, 0., 0.004),
        (Skin::W95, "unpick") => m.tone(392., t, 0.05, Square, 0.035, 0., 0.004),
        (Skin::W95, "ok") => {
            m.tone(523., t, 0.1, Saw, 0.04, 0., 0.01);
            m.pad(&[523., 659., 784., 1047.], t + 0.12, 0.7, Saw, 0.018, 0.02);
        }
        (Skin::W95, "err") => m.pad(&[220., 277., 330.], t, 0.35, Square, 0.03, 0.005),
        (Skin::W95, "theme") => m.tone(250., t, 0.25, Square, 0.03, 750., 0.004),
        (Skin::W95, "pop") => m.tone(660., t, 0.06, Square, 0.04, 0., 0.004),
        (Skin::W95, "startup") => {
            m.arp(&[262., 330., 392., 523., 659.], t, 0.11, 0.25, Square, 0.03);
            m.pad(&[523., 659., 784.], t + 0.6, 1.2, Saw, 0.015, 0.1);
        }
        // 🪙 Golden Duck: everything is a coin
        (Skin::Gold, "click") => m.tone(1976., t, 0.03, Square, 0.02, 0., 0.002),
        (Skin::Gold, "tick") => m.tone(1568. + rnd(400.), t, 0.04, Square, 0.02, 0., 0.002),
        (Skin::Gold, "pick") | (Skin::Gold, "pop") => {
            m.tone(988., t, 0.06, Square, 0.035, 0., 0.002);
            m.tone(1319., t + 0.06, 0.28, Square, 0.035, 0., 0.002);
        }
        (Skin::Gold, "unpick") => m.tone(659., t, 0.08, Square, 0.03, 0., 0.002),
        (Skin::Gold, "ok") | (Skin::Gold, "jackpot") => {
            for i in 0..6 {
                let k = i as f32 * 0.07;
                m.tone(988., t + k, 0.05, Square, 0.03, 0., 0.002);
                m.tone(1319., t + k + 0.05, 0.12, Square, 0.03, 0., 0.002);
            }
            m.pad(&[523., 659., 784., 1047.], t + 0.45, 0.8, Tri, 0.02, 0.02);
        }
        (Skin::Gold, "err") => {
            m.tone(330., t, 0.15, Square, 0.035, 220., 0.002);
            m.tone(220., t + 0.15, 0.3, Square, 0.035, 110., 0.002);
        }
        (Skin::Gold, "theme") => m.tone(660., t, 0.3, Tri, 0.04, 1320., 0.01),
        (Skin::Gold, "startup") => {
            m.arp(&[523., 659., 784., 1047., 1319.], t, 0.06, 0.12, Square, 0.025);
            for i in 0..3 {
                m.tone(1976. + i as f32 * 220., t + 0.4 + i as f32 * 0.09, 0.2, Square, 0.02, 0., 0.002);
            }
        }
        _ => return None,
    }
    // trim the silence at the end
    let last = m.b.iter().rposition(|v| v.abs() > 1e-4).unwrap_or(0);
    m.b.truncate(last + 64);
    Some(m.b)
}

// ── background music: 8 bars × 8 eighths, chords + bass + a 64-step melody + drums ──
struct Track {
    bpm: f32,
    swing: f32,
    arp: bool,
    comp: &'static [usize],
    chord: (Wave, f32, f32, f32), // wave, harmonic, volume, length
    bass: Wave,
    octbass: bool,
    lead: (Wave, f32, f32, f32),
    drums: &'static str,
    chords: [&'static [i32]; 8],
    roots: [i32; 8],
    mel: [i32; 64],
}

fn track(id: &str) -> Track {
    match id {
        "lofi" => Track { bpm: 78.0, swing: 0.16, arp: false, comp: &[0, 4], chord: (Tri, 2.0, 0.02, 1.3), bass: Sine, octbass: false, lead: (Sine, 3.0, 0.035, 0.7), drums: "lofi",
            chords: [&[60, 64, 67, 71], &[57, 60, 64, 67], &[62, 65, 69, 72], &[55, 59, 62, 65], &[60, 64, 67, 71], &[52, 55, 59, 62], &[53, 57, 60, 64], &[55, 59, 62, 65]], roots: [36, 33, 38, 31, 36, 40, 41, 43],
            mel: [76,0,0,74,72,0,0,0, 72,0,69,0,67,0,0,0, 74,0,0,72,69,0,72,0, 71,0,0,0,0,0,67,0, 76,0,79,0,76,74,72,0, 72,0,0,74,76,0,0,0, 77,0,76,0,74,0,72,0, 72,0,0,0,0,0,0,0] },
        "chip" => Track { bpm: 140.0, swing: 0.0, arp: true, comp: &[], chord: (Square, 0.0, 0.014, 0.11), bass: Square, octbass: false, lead: (Square, 0.0, 0.028, 0.18), drums: "chip",
            chords: [&[64, 67, 71], &[60, 64, 67], &[67, 71, 74], &[62, 66, 69], &[64, 67, 71], &[60, 64, 67], &[62, 66, 69], &[59, 63, 66]], roots: [40, 36, 43, 38, 40, 36, 38, 35],
            mel: [76,0,79,0,83,0,81,79, 76,0,0,0,72,0,74,76, 79,0,0,79,81,0,83,0, 81,0,79,0,78,0,74,0, 76,0,79,0,83,0,86,0, 84,0,83,0,79,0,76,0, 78,0,79,0,81,0,83,0, 83,0,0,0,0,0,0,0] },
        "synth" => Track { bpm: 100.0, swing: 0.0, arp: false, comp: &[0], chord: (Saw, 0.0, 0.008, 1.9), bass: Saw, octbass: true, lead: (Saw, 2.0, 0.02, 0.5), drums: "synth",
            chords: [&[57, 60, 64], &[53, 57, 60], &[55, 60, 64], &[55, 59, 62], &[57, 60, 64], &[53, 57, 60], &[55, 60, 64], &[56, 59, 64]], roots: [45, 41, 48, 43, 45, 41, 48, 40],
            mel: [69,0,0,72,0,0,76,0, 74,0,72,0,69,0,0,0, 72,0,0,76,0,0,79,0, 79,0,76,0,74,0,72,0, 69,0,0,72,0,0,76,0, 77,0,76,0,72,0,0,0, 76,0,74,0,72,0,71,0, 68,0,0,0,71,0,0,0] },
        // 🏴‍☠️ unlocked with a GURT key: a rolling D-minor shanty, squeezebox lead, stomp + clap
        "shanty" => Track { bpm: 124.0, swing: 0.12, arp: false, comp: &[0, 2, 4, 6], chord: (Square, 2.0, 0.009, 0.22), bass: Tri, octbass: false, lead: (Square, 2.0, 0.026, 0.26), drums: "chip",
            chords: [&[62, 65, 69], &[62, 65, 69], &[60, 64, 67], &[60, 64, 67], &[62, 65, 69], &[58, 62, 65], &[57, 61, 64], &[62, 65, 69]], roots: [38, 38, 36, 36, 38, 34, 33, 38],
            mel: [74,0,74,74,74,0,74,74, 74,0,69,0,72,0,74,0, 72,0,72,72,72,0,72,72, 72,0,67,0,70,0,72,0, 74,0,74,74,77,0,76,74, 70,0,69,0,67,0,65,0, 64,0,67,0,69,0,73,0, 74,0,0,0,74,0,0,0] },
        _ => Track { bpm: 116.0, swing: 0.1, arp: false, comp: &[0, 3, 6], chord: (Sine, 2.0, 0.018, 0.55), bass: Tri, octbass: false, lead: (Sine, 4.0, 0.045, 0.45), drums: "shaker",
            chords: [&[53, 57, 60, 64], &[50, 53, 57, 60], &[55, 58, 62, 65], &[48, 52, 55, 58], &[57, 60, 64, 67], &[50, 54, 57, 60], &[55, 58, 62, 65], &[48, 52, 55, 58]], roots: [41, 38, 43, 36, 45, 38, 43, 36],
            mel: [72,0,76,0,79,77,76,0, 74,0,0,72,69,0,72,0, 70,0,74,0,77,0,76,74, 72,0,0,0,67,0,70,72, 76,0,79,0,81,79,76,0, 78,0,76,74,72,0,0,74, 70,0,72,74,77,76,74,0, 72,0,0,0,0,0,0,0] },
    }
}

fn mtof(m: i32) -> f32 {
    440.0 * 2f32.powf((m - 69) as f32 / 12.0)
}

/// one full loop of a track, tails wrapped to the start so it loops without a seam
fn render_track(id: &str) -> Vec<f32> {
    let tr = track(id);
    let e = 60.0 / tr.bpm / 2.0;
    let len = 64.0 * e; // swing evens out every 2 eighths
    let mut m = Mix::new(len, true);
    let mut seed = 0x1234567u32;
    let voice = |m: &mut Mix, t: f32, f: f32, dur: f32, vol: f32, wave: Wave, harm: f32| {
        m.tone(f, t, dur, wave, vol, 0.0, 0.008);
        if harm > 0.0 {
            m.tone(f * harm, t, dur, wave, vol * 0.25, 0.0, 0.008);
        }
    };
    let mut t = 0.0f32;
    for step in 0..64usize {
        let bar = step / 8;
        let ei = step % 8;
        let (cw, ch, cv, cd) = tr.chord;
        if tr.arp {
            let c = tr.chords[bar];
            voice(&mut m, t, mtof(c[step % c.len()] + 12), cd, cv, cw, ch);
        } else if tr.comp.contains(&ei) {
            for &n in tr.chords[bar] {
                voice(&mut m, t, mtof(n), cd, cv, cw, ch);
            }
        }
        if tr.octbass {
            voice(&mut m, t, mtof(tr.roots[bar] + if ei % 2 == 1 { 12 } else { 0 }), e * 0.9, 0.05, tr.bass, 0.0);
        } else {
            if ei == 0 {
                voice(&mut m, t, mtof(tr.roots[bar]), 0.5, 0.07, tr.bass, 0.0);
            }
            if ei == 3 {
                voice(&mut m, t, mtof(tr.roots[bar] + 7), 0.35, 0.05, tr.bass, 0.0);
            }
            if ei == 6 {
                voice(&mut m, t, mtof(tr.roots[bar] + 12), 0.3, 0.045, tr.bass, 0.0);
            }
        }
        let n = tr.mel[step];
        if n != 0 {
            let (lw, lh, lv, ld) = tr.lead;
            voice(&mut m, t, mtof(n), ld, lv, lw, lh);
        }
        match tr.drums {
            "shaker" => m.noise(t, if ei % 2 == 1 { 0.02 } else { 0.012 }, 7000.0, false, 0.05, &mut seed),
            "lofi" => {
                if ei == 0 || ei == 5 {
                    m.kick(t, 0.09);
                }
                if ei == 2 || ei == 6 {
                    m.noise(t, 0.03, 1500.0, true, 0.14, &mut seed);
                }
                m.noise(t, if ei % 2 == 1 { 0.006 } else { 0.01 }, 8000.0, false, 0.04, &mut seed);
            }
            "chip" => {
                if ei == 0 || ei == 4 {
                    m.kick(t, 0.07);
                }
                if ei == 2 || ei == 6 {
                    m.noise(t, 0.04, 3000.0, true, 0.07, &mut seed);
                }
                if ei % 2 == 1 {
                    m.noise(t, 0.012, 9000.0, false, 0.02, &mut seed);
                }
            }
            _ => {
                if ei % 2 == 0 {
                    m.kick(t, 0.09);
                }
                if ei == 2 || ei == 6 {
                    m.noise(t, 0.05, 1800.0, true, 0.2, &mut seed);
                }
                if ei % 2 == 1 {
                    m.noise(t, 0.012, 9000.0, false, 0.05, &mut seed);
                }
            }
        }
        t += e * if ei % 2 == 1 { 1.0 - tr.swing } else { 1.0 + tr.swing };
    }
    for v in m.b.iter_mut() {
        *v *= 0.55;
    }
    m.b
}

pub struct Sound {
    pub sfx_on: bool,
    pub music_on: bool,
    pub track: String,
    skin: Skin,
    playing: Option<(String, Arc<AtomicBool>)>,
}

impl Sound {
    pub fn new(skin: Skin) -> Sound {
        let track = crate::data::conf_str("track").filter(|t| TRACKS.iter().any(|x| x.0 == t)).unwrap_or_else(|| "auto".into());
        let mut s = Sound { sfx_on: crate::data::conf_bool("sfx", true), music_on: crate::data::conf_bool("music", true), track, skin, playing: None };
        if std::env::var_os("GURT_APP_SILENT").is_some() || player().is_none() {
            s.sfx_on = s.sfx_on && player().is_some() && std::env::var_os("GURT_APP_SILENT").is_none();
        }
        s.sync_music();
        s
    }
    fn silent() -> bool {
        std::env::var_os("GURT_APP_SILENT").is_some()
    }
    pub fn play(&self, name: &str) {
        if !self.sfx_on || Self::silent() {
            return;
        }
        let skin = self.skin;
        let name = name.to_string();
        std::thread::spawn(move || {
            let Some(buf) = sfx(skin, &name) else { return };
            if let Some(mut ch) = spawn_player() {
                if let Some(mut w) = ch.stdin.take() {
                    let _ = w.write_all(&to_pcm(&buf));
                }
                let _ = ch.wait();
            }
        });
    }
    pub fn set_sfx(&mut self, on: bool) {
        self.sfx_on = on;
        crate::data::save_conf("sfx", on.into());
    }
    pub fn set_music(&mut self, on: bool) {
        self.music_on = on;
        crate::data::save_conf("music", on.into());
        self.sync_music();
    }
    pub fn set_track(&mut self, t: &str) {
        self.track = t.into();
        crate::data::save_conf("track", t.into());
        if !self.music_on {
            self.music_on = true;
            crate::data::save_conf("music", true.into());
        }
        self.sync_music();
    }
    pub fn set_skin(&mut self, s: Skin) {
        self.skin = s;
        self.sync_music();
    }
    fn want(&self) -> String {
        if self.track != "auto" {
            return self.track.clone();
        }
        match self.skin {
            Skin::Vapor => "synth",
            Skin::Hacker => "chip",
            _ => "shop",
        }
        .into()
    }
    /// start / stop / switch the music to match the settings
    pub fn sync_music(&mut self) {
        let want = (self.music_on && !Self::silent() && player().is_some()).then(|| self.want());
        if self.playing.as_ref().map(|p| &p.0) == want.as_ref() {
            return;
        }
        if let Some((_, stop)) = self.playing.take() {
            stop.store(true, Ordering::Relaxed);
        }
        let Some(id) = want else { return };
        let stop = Arc::new(AtomicBool::new(false));
        self.playing = Some((id.clone(), stop.clone()));
        std::thread::spawn(move || {
            let pcm = to_pcm(&render_track(&id));
            let Some(mut ch) = spawn_player() else { return };
            let Some(mut w) = ch.stdin.take() else { return };
            // small chunks: the player's pipe paces us, and a stop lands within a fraction of a second
            'outer: while !stop.load(Ordering::Relaxed) {
                for chunk in pcm.chunks(8820) {
                    if stop.load(Ordering::Relaxed) || w.write_all(chunk).is_err() {
                        break 'outer;
                    }
                }
            }
            drop(w);
            let _ = ch.kill();
            let _ = ch.wait();
        });
    }
}

impl Drop for Sound {
    fn drop(&mut self) {
        if let Some((_, stop)) = self.playing.take() {
            stop.store(true, Ordering::Relaxed);
        }
    }
}

#!/usr/bin/env python3
"""the infomercial's soundtrack: espeak-ng announcer + a synthesized chiptune jingle and sound effects (no samples,
no numpy). python3 make-audio.py out.wav"""
import math, os, random, struct, subprocess, sys, tempfile, wave

SR = 22050
LEN = 30.0
N = int(SR * LEN)
music = [0.0] * N
voice = [0.0] * N
random.seed(7)


def note(n):  # midi note → Hz
    return 440.0 * 2 ** ((n - 69) / 12)


def add(buf, start, samples, gain=1.0):
    i0 = int(start * SR)
    for i, v in enumerate(samples):
        j = i0 + i
        if 0 <= j < N:
            buf[j] += v * gain


def tone(freq, dur, kind="square", vol=0.3, attack=0.005, release=0.05, slide=0.0, duty=0.5):
    n = int(dur * SR); out = []; ph = 0.0
    for i in range(n):
        t = i / SR
        f = freq * (2 ** (slide * t / dur / 12)) if slide else freq
        ph += f / SR; ph -= math.floor(ph)
        if kind == "square": v = 1.0 if ph < duty else -1.0
        elif kind == "saw": v = 2 * ph - 1
        elif kind == "tri": v = 4 * abs(ph - 0.5) - 1
        else: v = math.sin(2 * math.pi * ph)
        env = min(1.0, t / attack) if attack else 1.0
        env *= min(1.0, (dur - t) / release) if release else 1.0
        out.append(v * vol * env)
    return out


def noise(dur, vol=0.3, decay=30.0):
    return [(random.random() * 2 - 1) * vol * math.exp(-decay * i / SR) for i in range(int(dur * SR))]


def kick(vol=0.9):
    out = []; ph = 0.0
    for i in range(int(0.18 * SR)):
        t = i / SR; f = 150 * math.exp(-t * 25) + 45; ph += f / SR
        out.append(math.sin(2 * math.pi * ph) * vol * math.exp(-t * 14))
    return out


# ── 0–7s: the sad part. a low drone, then the sad trombone on "womp womp" ──
add(music, 0.0, tone(note(45), 5.5, "tri", 0.12, attack=0.8, release=1.0))
add(music, 0.0, tone(note(52), 5.5, "tri", 0.07, attack=0.8, release=1.0))
for k, (n_, d) in enumerate([(58, 0.32), (57, 0.32), (56, 0.32), (55, 0.9)]):   # wah wah wah waaah
    add(music, 5.55 + k * 0.34, tone(note(n_ - 12), d, "saw", 0.22, attack=0.03, release=0.12, slide=-0.6 if k == 3 else 0))

# ── 7s on: the jingle. 132 bpm, C – G – Am – F, square-wave arpeggios, bass, drums ──
BPM = 132; beat = 60 / BPM; bar = 4 * beat
CHORDS = [(60, 64, 67), (55, 59, 62), (57, 60, 64), (53, 57, 60)]


def jingle(t0, t1, up=0):
    t = t0; k = 0
    while t < t1 - 0.01:
        c = [x + up for x in CHORDS[k % 4]]
        for s in range(16):   # sixteenth-note arpeggio
            st = t + s * beat / 4
            if st >= t1: break
            add(music, st, tone(note(c[s % 3] + (12 if s % 8 >= 4 else 0)), beat / 4 * 0.9, "square", 0.07, duty=0.25))
        for e in range(8):    # bass, eighths
            st = t + e * beat / 2
            if st >= t1: break
            add(music, st, tone(note(c[0] - 24), beat / 2 * 0.85, "tri", 0.22))
        for b in range(4):    # drums
            st = t + b * beat
            if st >= t1: break
            if b % 2 == 0: add(music, st, kick())
            else: add(music, st, noise(0.12, 0.25, 22))
            add(music, st + beat / 2, noise(0.04, 0.08, 80))
        t += bar; k += 1


add(music, 7.0, noise(1.2, 0.35, 3.0))                        # crash on "introducing"
add(music, 7.0, tone(note(48), 0.6, "saw", 0.25, release=0.4))
jingle(7.0, 15.6)
for i in range(3):                                            # record scratch before "but wait"
    add(music, 15.55 + i * 0.07, tone(900, 0.07, "saw", 0.18, slide=-14 if i % 2 else 14))
add(music, 15.75, tone(note(43), 1.3, "saw", 0.12, attack=0.02, release=0.6))   # dun dun
jingle(17.2, 24.4, up=2)                                      # key change, of course
add(music, 24.4, tone(note(50), 2.4, "tri", 0.1, attack=0.3, release=0.5))     # "how much would you pay" suspense
for k in range(3):                                            # ding ding ding on $0.00
    add(music, 27.0 + k * 0.13, tone(note(84 + k * 4), 0.4, "sine", 0.25, release=0.35))
jingle(27.2, 29.2, up=2)
for n_ in (62, 66, 69, 74):                                   # big final chord
    add(music, 29.2, tone(note(n_), 0.75, "square", 0.06, duty=0.3, release=0.6))
add(music, 29.2, kick(1.0))

# ── the announcer ──
LINES = [
    (0.35, "Are you tired of this?"),
    (3.65, "Wrong distro? Womp womp."),
    (7.15, "Introducing... GURT!"),
    (8.75, "The GURT Universal Repository Thingy!"),
    (10.55, "The A. U. R.? On Mint?!"),
    (13.9, "It just works!"),
    (15.75, "But wait! There's more!"),
    (17.4, "Twenty sources! One command!"),
    (20.5, "Plus the GURT app! Six skins! An undo button! Android apps! Even Nix O S!"),
    (24.45, "How much would you pay?"),
    (26.95, "Zero dollars! Free and open source!"),
    (28.45, "Get GURT now! Operators are standing by!"),
]
tmp = tempfile.mkdtemp()
busy = []
for i, (st, text) in enumerate(LINES):
    room = (LINES[i + 1][0] if i + 1 < len(LINES) else LEN) - st - 0.1
    speed = 165
    while True:   # talk faster until the line fits its slot (infomercial energy)
        f = os.path.join(tmp, f"l{i}.wav")
        subprocess.run(["espeak-ng", "-v", "en-us+m3", "-s", str(speed), "-p", "58", "-a", "190", "-g", "1", "-w", f, text], check=True)
        with wave.open(f) as w:
            sr, raw = w.getframerate(), w.readframes(w.getnframes())
        samples = struct.unpack("<%dh" % (len(raw) // 2), raw)
        if len(samples) / sr <= room or speed >= 320: break
        speed += 15
    # espeak talks at 22050 Hz too; if not, resample by stepping
    step = sr / SR
    s2 = [samples[int(k * step)] / 32768 for k in range(int(len(samples) / step))]
    add(voice, st, s2, 0.9)
    busy.append((st, st + len(s2) / SR))

# duck the music under the voice, then mix
out = []
for i in range(N):
    t = i / SR
    talking = any(a - 0.05 <= t <= b + 0.1 for a, b in busy)
    out.append(music[i] * (0.4 if talking else 0.8) + voice[i])
peak = max(abs(v) for v in out) or 1.0
out = [v * 0.92 / peak for v in out]   # loud, but never clipped
with wave.open(sys.argv[1], "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes(b"".join(struct.pack("<h", int(v * 32000)) for v in out))
print("wrote", sys.argv[1], f"{LEN}s")

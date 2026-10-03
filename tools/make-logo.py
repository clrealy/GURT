#!/usr/bin/env python3
# makes the gurt wordmark: g u r t traced from Liberation Serif Bold (SIL OFL), each letter its color,
# a solid offset shadow (no blur, no glow), and a little bounce. writes:
#   assets/gurt-logo.svg, site/assets/gurt-logo.svg   → the logo
#   gui/gurt-gui.py + site/index.html (between <!--logo--> markers) → the same, themeable (the g follows the text color)
#   site/assets/favicon.svg                           → the icon (g + the color stripe)
# then tools/render-logo.js turns them into the PNGs.  needs: pip install fonttools
import os
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.boundsPen import BoundsPen

FONT = "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INK, RED, GREEN, BLUE, SHADOW, GOLD = "#141414", "#e8302a", "#1fa64a", "#2456e0", "#141414", "#ffc629"
f = TTFont(FONT); gs = f.getGlyphSet(); cmap = f.getBestCmap()
upm = f["head"].unitsPerEm

def glyph(ch):
    name = cmap[ord(ch)]; pen = SVGPathPen(gs); gs[name].draw(pen)
    bp = BoundsPen(gs); gs[name].draw(bp)
    return pen.getCommands(), gs[name].width, bp.bounds

# letter, fill, vertical bounce (font units, + = down), tilt (degrees)
LETTERS = [("g", INK, 0, -4), ("u", RED, 40, 3), ("r", GREEN, -70, -5), ("t", BLUE, 10, 4)]
SH = 70          # shadow offset (font units)
TRACK = -30      # letters a bit tighter than the font
x, parts, minx, maxx, miny, maxy = 0, [], 1e9, -1e9, 1e9, -1e9
for ch, fill, dy, rot in LETTERS:
    d, adv, (x0, y0, x1, y1) = glyph(ch)
    cx, cy = x + (x0 + x1) / 2, -(y0 + y1) / 2 + dy
    # font y goes up, svg y goes down → flip, then move + tilt around the letter's middle
    tf = f"rotate({rot} {cx:.0f} {cy:.0f}) translate({x} {dy}) scale(1 -1)"
    parts.append((ch, fill, tf, d))
    minx, maxx = min(minx, x + x0 - 60), max(maxx, x + x1 + SH + 60)
    miny, maxy = min(miny, -y1 + dy - 80), max(maxy, -y0 + dy + SH + 60)
    x += adv + TRACK
W, H = maxx - minx, maxy - miny

def svg(ink=INK, themed=False):
    out = []
    for ch, fill, tf, d in parts:   # the g's shadow is gold: a black g on a black shadow is just a blob
        out.append(f'<path transform="translate({SH} {SH}) {tf}" d="{d}" fill="{GOLD if ch == "g" else SHADOW}"/>')
    for ch, fill, tf, d in parts:
        if ch == "g" and themed:
            out.append(f'<path class="logo-g" transform="{tf}" d="{d}" fill="{ink}" stroke="{SHADOW}" stroke-width="18"/>')
        else:
            out.append(f'<path transform="{tf}" d="{d}" fill="{fill}" stroke="{SHADOW}" stroke-width="18"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{minx:.0f} {miny:.0f} {W:.0f} {H:.0f}" role="img" aria-label="gurt">'
            + "".join(out) + "</svg>")

for p in ("assets/gurt-logo.svg", "site/assets/gurt-logo.svg"):
    open(os.path.join(ROOT, p), "w").write(svg() + "\n")
# the app has the logo inline (between <!--logo--> markers) so the g can follow the app's text color
for page in ("gui/gurt-gui.py", "site/index.html"):   # both have it inline, so the g follows light/dark
    path = os.path.join(ROOT, page); g = open(path).read()
    a, b = g.index("<!--logo-->") + len("<!--logo-->"), g.index("<!--/logo-->")
    open(path, "w").write(g[:a] + svg("var(--logo-ink)", themed=True) + g[b:])

# the icon: a big g on paper, with the red/green/blue stripe under it and a hard shadow box
d, adv, (x0, y0, x1, y1) = glyph("g")
gw, gh = x1 - x0, y1 - y0
S = 1000; pad = 150; sc = (S - 2 * pad) / max(gw, gh) * 0.86
gx = (S - gw * sc) / 2 - x0 * sc - 14; gy = pad + (S - 2 * pad - gh * sc) / 2 - 85 + y1 * sc
icon = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} {S}">'
        f'<rect x="40" y="40" width="{S-80}" height="{S-80}" rx="140" fill="#fbf8ee" stroke="{INK}" stroke-width="44"/>'
        f'<path transform="translate({gx + 34:.0f} {gy + 34:.0f}) scale({sc:.4f} {-sc:.4f})" d="{d}" fill="{GOLD}"/>'
        f'<path transform="translate({gx:.0f} {gy:.0f}) scale({sc:.4f} {-sc:.4f})" d="{d}" fill="{INK}"/>'
        f'<rect x="200" y="800" width="200" height="70" fill="{RED}"/><rect x="400" y="800" width="200" height="70" fill="{GREEN}"/><rect x="600" y="800" width="200" height="70" fill="{BLUE}"/>'
        "</svg>")
open(os.path.join(ROOT, "site/assets/favicon.svg"), "w").write(icon + "\n")
print("logo %dx%d units, wrote svgs" % (W, H))

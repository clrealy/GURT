#!/usr/bin/env python3
# makes the "Get now on gurt" badge, for anyone to put on their app's page (like "Get it on Flathub"):
#   site/assets/get-on-gurt.svg       dark text, for light pages
#   site/assets/get-on-gurt-dark.svg  light text, for dark pages
# the icon is site/assets/favicon.svg, the wordmark is assets/gurt-logo.svg (run tools/make-logo.py first if they
# changed), and "Get now on" is Liberation Serif traced into paths, so it looks the same everywhere.
# then tools/render-logo.js makes the PNGs.  needs: pip install fonttools
import os, re
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT = "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"
read = lambda p: open(os.path.join(ROOT, p)).read()

def inner(svg):   # an svg file → (viewBox, everything inside it)
    vb = re.search(r'viewBox="([^"]+)"', svg).group(1)
    return vb, re.sub(r"^.*?<svg[^>]*>|</svg>\s*$", "", svg.strip(), flags=re.S)

def text_path(s, size):   # → (svg path data, width), baseline at y=0, top of caps at about -0.66*size
    f = TTFont(FONT); gs = f.getGlyphSet(); cmap = f.getBestCmap(); k = size / f["head"].unitsPerEm
    pen = SVGPathPen(gs); x = 0
    for ch in s:
        g = gs[cmap[ord(ch)]]
        g.draw(TransformPen(pen, (k, 0, 0, -k, x, 0)))
        x += g.width * k
    return pen.getCommands(), x

icon_vb, icon = inner(read("site/assets/favicon.svg"))
logo_vb, logo = inner(read("assets/gurt-logo.svg"))
lx, ly, lw, lh = map(float, logo_vb.split())

W, H, PAD = 2000, 720, 30
ICON = H - 2 * PAD                      # the icon: a square, full height
TX = PAD + ICON + 90                    # where the words start
d, tw = text_path("Get now on", 200)
TW = W - PAD - TX                       # "Get now on" fills the space to the right edge
ts = TW / tw
BASE = PAD + 200 * ts * 0.70            # its baseline
GAP = 75                                # the wordmark's letters bounce + tilt past its box, so keep clear of the text
LH = H - PAD - BASE - GAP; LW = LH * lw / lh   # the wordmark fills what's left under it

def badge(ink, g_ink):
    lg = logo.replace('fill="#141414" stroke="#141414"', f'fill="{g_ink}" stroke="#141414"', 1)   # the g (not the shadows)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="Get now on gurt">'
            f'<svg x="{PAD}" y="{PAD}" width="{ICON}" height="{ICON}" viewBox="{icon_vb}">{icon}</svg>'
            f'<path transform="translate({TX} {BASE:.1f}) scale({ts:.4f})" d="{d}" fill="{ink}"/>'
            f'<svg x="{TX + TW * 0.05:.0f}" y="{H - PAD - LH:.0f}" width="{LW:.0f}" height="{LH:.0f}" viewBox="{logo_vb}">{lg}</svg>'
            "</svg>\n")

open(os.path.join(ROOT, "site/assets/get-on-gurt.svg"), "w").write(badge("#141414", "#141414"))
open(os.path.join(ROOT, "site/assets/get-on-gurt-dark.svg"), "w").write(badge("#f4f1e6", "#f4f1e6"))
print("wrote site/assets/get-on-gurt.svg + get-on-gurt-dark.svg")

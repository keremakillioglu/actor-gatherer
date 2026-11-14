"""logo.py: draws AGUI's mark -- three robot actors (sky, pink, teal) held in a G, the gatherer, whose stroke turns in
and ends in an antenna bulb like theirs -- with the avatars' own kit (avatars/kit.py: its palette, its kawaii face), and
writes it where it is used:

- frontend/index.html, between <!--LOGO--> and <!--/LOGO-->: the mark in the page's top bar, in the page's colours
  (--halo, the G's; --side, the bar's, cut round each robot so the three stay apart);
- frontend/index.html, between <!--FAVICON--> and <!--/FAVICON-->: the same as the page's icon, its colours fixed,
  light or dark as the browser is;
- assets/agui.svg: that icon, as a file.

    python3 assets/src/logo.py
"""

import math
import os
import re
import sys
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "avatars"))
from kit import CREAM, P, face, shine  # noqa: E402

ROOT = os.path.join(HERE, "..", "..")
PAGE = os.path.join(ROOT, "frontend", "index.html")
ICON = os.path.join(ROOT, "assets", "agui.svg")

f = lambda v: f"{v:.2f}".rstrip("0").rstrip(".")  # noqa: E731


def robot(hue, kind):
    """A robot on the avatars' 64x64 canvas, no circle: its antennae, head, ear bolts, a cream screen, the face on it."""
    p, s = P(hue), []
    if kind == "box":  # a square head, one antenna
        s.append(f'<path d="M32 13.5 V7.5" stroke="{p.dark}" stroke-width="2.4" stroke-linecap="round"/>')
        s.append(f'<circle cx="32" cy="6.6" r="3.6" fill="{p.light}" stroke="{p.dark}" stroke-width="1.6"/>')
        s.append(f'<rect x="5.5" y="27" width="7" height="13" rx="3" fill="{p.dark}"/>'
                 f'<rect x="51.5" y="27" width="7" height="13" rx="3" fill="{p.dark}"/>')
        s.append(f'<rect x="10" y="13" width="44" height="40" rx="13" fill="{p.main}"/>')
        s.append(shine(19, 18.5, 4.6, 2.3))
        s.append(f'<rect x="16" y="22" width="32" height="24" rx="9" fill="{CREAM}"/>')
        s.append(face(32, 32.5, gap=7.6, r=2.6, cheek_dx=10.4, cheek_dy=4.2, mouth_dy=4))
    elif kind == "dome":  # a round head, two antennae
        for x, ang in ((20, -18), (44, 18)):
            s.append(f'<g transform="rotate({ang} {x} 16)"><path d="M{x} 16 V8" stroke="{p.dark}" stroke-width="2.2" '
                     f'stroke-linecap="round"/><circle cx="{x}" cy="7" r="2.8" fill="{p.light}" stroke="{p.dark}" '
                     f'stroke-width="1.4"/></g>')
        s.append(f'<ellipse cx="9.5" cy="34" rx="4" ry="6.5" fill="{p.dark}"/>'
                 f'<ellipse cx="54.5" cy="34" rx="4" ry="6.5" fill="{p.dark}"/>')
        s.append(f'<ellipse cx="32" cy="34" rx="23" ry="21" fill="{p.main}"/>')
        s.append(shine(20, 21, 5, 2.4))
        s.append(f'<ellipse cx="32" cy="35.5" rx="16.5" ry="12.5" fill="{CREAM}"/>')
        s.append(face(32, 34.5, gap=7, r=2.6, cheek_dx=10.2, cheek_dy=4, mouth_dy=4))
    else:  # "tv": a wide head, a short antenna on a little base, a cat's mouth
        s.append(f'<path d="M32 11 V6.6" stroke="{p.dark}" stroke-width="2.6" stroke-linecap="round"/>')
        s.append(f'<circle cx="32" cy="5.2" r="3.9" fill="{p.light}" stroke="{p.dark}" stroke-width="1.6"/>')
        s.append(f'<rect x="27.5" y="9.6" width="9" height="3.6" rx="1.5" fill="{p.dark}"/>')
        s.append(f'<circle cx="7.5" cy="34" r="4.2" fill="{p.dark}"/><circle cx="56.5" cy="34" r="4.2" fill="{p.dark}"/>')
        s.append(f'<rect x="8" y="12" width="48" height="42" rx="15" fill="{p.main}"/>')
        s.append(shine(18, 17.5, 4.6, 2.3))
        s.append(f'<rect x="15" y="22" width="34" height="25" rx="10" fill="{CREAM}"/>')
        s.append(face(32, 33, gap=8, r=2.6, cheek_dx=11, cheek_dy=4.2, mouth_dy=4, mouth="w"))
    return "".join(s)


def placed(body, cx, cy, scale):
    """A robot at (cx, cy), scaled: first a copy of it in the background's colour, a little fatter (.halo, styled), then it."""
    g = f'<g transform="translate({f(cx)} {f(cy)}) scale({scale}) translate(-32 -32)">{body}</g>'
    return f'<g class="halo">{g}</g>{g}'


def mark():
    """The mark, on a 64x64 canvas: the G (--halo: the page's sky blue), the three robots in it, its end turned in to its bulb."""
    r, top, low = 27.4, math.radians(48), math.radians(-4)
    x0, y0 = 32 + r * math.cos(top), 32 - r * math.sin(top)
    x1, y1 = 32 + r * math.cos(low), 32 - r * math.sin(low)
    g = (f'<path d="M{f(x0)} {f(y0)} A{r} {r} 0 1 0 {f(x1)} {f(y1)}" fill="none" stroke="var(--halo)" stroke-width="5.2" '
         f'stroke-linecap="round"/>')
    bots = (placed(robot("sky", "dome"), 21.4, 23.6, .40) + placed(robot("pink", "box"), 40, 22.2, .40)
            + placed(robot("teal", "tv"), 30.4, 42.2, .44))
    bulb = (f'<path d="M{f(x1)} {f(y1)} H{f(x1 - 7.6)}" stroke="var(--halo)" stroke-width="3" stroke-linecap="round"/>'
            f'<circle cx="{f(x1 - 9.6)}" cy="{f(y1)}" r="3.3" fill="{P("sky").light}" stroke="var(--halo)" stroke-width="2"/>')
    return g + bots + bulb


HALO = ".halo *{fill:var(--side)!important;stroke:var(--side)!important;stroke-width:5px!important;opacity:1!important}"


def page_mark():
    return f'<svg class="ag-logo" viewBox="0 0 64 64" aria-hidden="true">{mark()}</svg>'


def icon():
    """The mark as a file: its colours fixed, the G's and the cut round the robots as a browser's light or dark tab is."""
    style = (":root{--halo:#1ea4e4;--side:#fff}@media (prefers-color-scheme:dark){:root{--halo:#38bdf8;--side:#202124}}"
             + HALO)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><style>{style}</style>{mark()}</svg>\n'


def put(text, name, inner):
    """`text` with what is between <!--name--> and <!--/name--> replaced by `inner`."""
    pat = re.compile(f"(<!--{name}-->).*?(<!--/{name}-->)", re.S)
    if not pat.search(text):
        sys.exit(f"{PAGE}: no <!--{name}--> ... <!--/{name}--> in it")
    return pat.sub(lambda m: m.group(1) + inner + m.group(2), text)


def main():
    svg = icon()
    with open(ICON, "w") as fh:
        fh.write(svg)
    with open(PAGE) as fh:
        text = fh.read()
    text = put(text, "LOGO", page_mark())
    text = put(text, "FAVICON", f'<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,{quote(svg.strip(), safe=" =:;/,")}">')
    with open(PAGE, "w") as fh:
        fh.write(text)
    print(f"wrote {os.path.relpath(ICON, ROOT)} and the mark and icon in {os.path.relpath(PAGE, ROOT)}")


if __name__ == "__main__":
    main()

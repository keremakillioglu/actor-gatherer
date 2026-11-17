"""logo.py: draws AGUI's mark -- three robot actors (sky, pink, teal) held in a G, the gatherer, whose stroke turns in
and ends in an antenna bulb like theirs -- with the avatars' own kit (avatars/kit.py: its palette, its kawaii face), and
writes it where it is used:

- frontend/index.html, between <!--LOGO--> and <!--/LOGO-->: the mark in the page's top bar, in the page's colours
  (--side, the bar's, cut round each robot so the three stay apart);
- frontend/index.html, between <!--FAVICON--> and <!--/FAVICON-->: the same as the page's icon, its colours fixed,
  light or dark as the browser is;
- assets/agui.svg: that icon, as a file;
- the app's icon, the mark on a white tile, as pictures (PNG, drawn by a headless Chrome: $CHROME, else where it is
  installed): ag_dashboard/icons/, what the page's manifest names -- the icon a browser installs the page as an app
  with, as Chrome's "Install" does, and puts in the Dock or the task bar -- and desktop/icon.png, the desktop app's
  in the Dock, drawn as a macOS app's icon is (its rounded square inset, a shadow under it).

    python3 assets/src/logo.py
"""

import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "avatars"))
from kit import CREAM, P, face, shine  # noqa: E402

ROOT = os.path.join(HERE, "..", "..")
PAGE = os.path.join(ROOT, "frontend", "index.html")
ICON = os.path.join(ROOT, "assets", "agui.svg")
ICONS = os.path.join(ROOT, "ag_dashboard", "icons")
DESKTOP_ICON = os.path.join(ROOT, "desktop", "icon.png")

# the app's icons (the server's manifest names each, api/page.py): (file, how it is drawn, its size in pixels) --
# "tile", the mark on a white rounded square, for where an icon is shown as it is; "full", on white to its edges, the
# mark inside the middle 80% every mask keeps (a "maskable" icon: Chrome on macOS cuts it to the Dock's rounded square,
# Safari to its own)
APP_ICONS = [("agui-192.png", "tile", 192), ("agui-512.png", "tile", 512), ("agui-maskable-192.png", "full", 192),
             ("agui-maskable-512.png", "full", 512), ("apple-touch-icon.png", "full", 180)]

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


# the G's colour, top to bottom: the robots' own -- pink at its top, by the pink one; sky down its side; teal at its foot,
# by the teal one -- over the canvas (userSpaceOnUse), so the G, its arm and its bulb share it
GRAD = ('<defs><linearGradient id="agui-g" gradientUnits="userSpaceOnUse" x1="0" y1="4.6" x2="0" y2="59.4">'
        f'<stop offset="0" stop-color="{P("pink").main}"/><stop offset=".5" stop-color="{P("sky").main}"/>'
        f'<stop offset="1" stop-color="{P("teal").main}"/></linearGradient></defs>')
G = "url(#agui-g)"


def mark():
    """The mark, on a 64x64 canvas: the G (the robots' colours, GRAD), the three robots in it, its end turned in to its bulb."""
    r, top, low = 27.4, math.radians(48), math.radians(-4)
    x0, y0 = 32 + r * math.cos(top), 32 - r * math.sin(top)
    x1, y1 = 32 + r * math.cos(low), 32 - r * math.sin(low)
    g = (f'<path d="M{f(x0)} {f(y0)} A{r} {r} 0 1 0 {f(x1)} {f(y1)}" fill="none" stroke="{G}" stroke-width="5.2" '
         f'stroke-linecap="round"/>')
    bots = (placed(robot("sky", "dome"), 21.4, 23.6, .40) + placed(robot("pink", "box"), 40, 22.2, .40)
            + placed(robot("teal", "tv"), 30.4, 42.2, .44))
    bulb = (f'<path d="M{f(x1)} {f(y1)} H{f(x1 - 7.6)}" stroke="{G}" stroke-width="3" stroke-linecap="round"/>'
            f'<circle cx="{f(x1 - 9.6)}" cy="{f(y1)}" r="3.3" fill="{P("sky").light}" stroke="{G}" stroke-width="2"/>')
    return GRAD + g + bots + bulb


HALO = ".halo *{fill:var(--side)!important;stroke:var(--side)!important;stroke-width:5px!important;opacity:1!important}"


def page_mark():
    return f'<svg class="ag-logo" viewBox="0 0 64 64" aria-hidden="true">{mark()}</svg>'


def icon():
    """The mark as a file: the cut round the robots in a browser's light or dark tab's colour."""
    style = (":root{--side:#fff}@media (prefers-color-scheme:dark){:root{--side:#202124}}"
             + HALO)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><style>{style}</style>{mark()}</svg>\n'


def put(text, name, inner):
    """`text` with what is between <!--name--> and <!--/name--> replaced by `inner`."""
    pat = re.compile(f"(<!--{name}-->).*?(<!--/{name}-->)", re.S)
    if not pat.search(text):
        sys.exit(f"{PAGE}: no <!--{name}--> ... <!--/{name}--> in it")
    return pat.sub(lambda m: m.group(1) + inner + m.group(2), text)


WHITE = "#fff"


def app_icon(kind, px):
    """The app's icon, `px` pixels square, on a 1024 canvas: the mark 73% across its white ground, the robots cut round in
    white. "mac": Apple's grid -- the ground a rounded square 824 across, 100 in, a soft shadow under it -- the mark
    600 across it; "tile": the ground the whole canvas, its corners rounded; "full": the whole canvas, square (the
    mark, 750 across, inside the middle 80%: what a mask keeps)."""
    if kind == "mac":
        ground = ('<filter id="drop" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="10" '
                  'stdDeviation="12" flood-color="#000" flood-opacity=".3"/></filter>'
                  f'<rect x="100" y="100" width="824" height="824" rx="185" fill="{WHITE}" filter="url(#drop)"/>')
        side = 640
    else:
        corner = ' rx="230"' if kind == "tile" else ""
        ground = f'<rect width="1024" height="1024"{corner} fill="{WHITE}"/>'
        side = 800
    at = f((1024 - side) / 2)
    style = HALO.replace("var(--side)", WHITE)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{px}" height="{px}" viewBox="0 0 1024 1024">'
            f'<style>{style}</style>{ground}'
            f'<svg x="{at}" y="{at}" width="{side}" height="{side}" viewBox="0 0 64 64">{mark()}</svg></svg>\n')


def chrome():
    """A Chrome to draw the app's icons with: $CHROME, else Chrome or Chromium where macOS installs them, else on the
    PATH."""
    if os.environ.get("CHROME"):
        return os.environ["CHROME"]
    for top in ("/Applications", os.path.expanduser("~/Applications")):
        for app in ("Google Chrome.app/Contents/MacOS/Google Chrome", "Chromium.app/Contents/MacOS/Chromium"):
            if os.access(os.path.join(top, app), os.X_OK):
                return os.path.join(top, app)
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        if shutil.which(name):
            return shutil.which(name)
    sys.exit("no Chrome to draw the app's icons with: set CHROME to one")


def draw(svg, px, out):
    """`svg` drawn as a PNG `px` pixels square at `out`, its background clear, by a headless Chrome of its own."""
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "icon.svg")
        with open(src, "w") as fh:
            fh.write(svg)
        subprocess.run([chrome(), "--headless", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                        "--default-background-color=00000000", f"--window-size={px},{px}", "--no-first-run",
                        "--no-default-browser-check", f"--user-data-dir={os.path.join(tmp, 'profile')}",
                        f"--screenshot={os.path.abspath(out)}", "file://" + src],
                       check=True, capture_output=True, timeout=120)


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
    os.makedirs(ICONS, exist_ok=True)
    for name, kind, px in APP_ICONS:
        draw(app_icon(kind, px), px, os.path.join(ICONS, name))
    draw(app_icon("mac", 1024), 1024, DESKTOP_ICON)
    print(f"drew the app's icons in {os.path.relpath(ICONS, ROOT)}/ and {os.path.relpath(DESKTOP_ICON, ROOT)}")


if __name__ == "__main__":
    main()

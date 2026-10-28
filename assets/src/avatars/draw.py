"""draw.py: writes the dashboard's actor avatars, ag_dashboard/avatars/<kind>/<name>.svg, from the
characters drawn here -- animals.py, food.py, charms.py and people.py (most in a hue of their own, a few in
every hue), and roles.py's, the pictures of actors with a role -- and, with --preview, a page showing them all.

    python3 assets/src/avatars/draw.py [--preview PATH]

It writes only its own files: an SVG put in ag_dashboard/avatars by hand is left as it is (see the
README there). To add a character, write a function in the kind's module, list it in its ICONS and say
how it moves while its actor works in its MOTIONS."""

import argparse
import os
import re

import animals
import charms
import food
import people
import roles
from kit import PALETTE

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "..", "..", "ag_dashboard", "avatars")
KINDS = {"animal": animals.ICONS, "food": food.ICONS, "charm": charms.ICONS, "person": people.ICONS,
         "roles": roles.ICONS}             # an actor's with a role (roles.py): never given out at random


def preview(names, out):
    """A page of every avatar, by hue: large, and at the sidebar's size on light and dark."""
    hue = lambda n: re.search(r'data-hue="(\w+)"', open(os.path.join(OUT, n + ".svg")).read()).group(1)
    order = sorted(names, key=lambda n: (list(PALETTE).index(hue(n)), n))
    src = lambda n: os.path.relpath(os.path.join(OUT, n + ".svg"), os.path.dirname(os.path.abspath(out)))
    big = "".join(f'<figure><img src="{src(n)}" width="80"><figcaption>{n}</figcaption></figure>' for n in order)
    row = lambda bg, s: (f'<div style="background:{bg};padding:10px 16px;display:flex;flex-wrap:wrap;gap:8px">'
                         + "".join(f'<img src="{src(n)}" width="{s}" height="{s}" title="{n}">' for n in order) + "</div>")
    with open(out, "w") as fh:
        fh.write(f'<!doctype html><meta charset="utf-8"><title>Actor avatars</title><body style="margin:0;font-family:system-ui">'
                 f'<h3 style="margin:14px 16px 8px">{len(order)} avatars, by hue</h3>'
                 f'<div style="display:flex;flex-wrap:wrap;gap:4px;padding:0 12px">{big}</div>'
                 f'<h3 style="margin:14px 16px 8px">At 28px</h3>{row("#faf9f7", 28)}{row("#1d1d1f", 28)}'
                 '<style>figure{margin:0;width:92px;text-align:center;font-size:10px;color:#555;overflow-wrap:anywhere}</style></body>')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--preview", metavar="PATH", help="also write a page showing them all")
    args = ap.parse_args()
    names = []
    for kind, icons in KINDS.items():
        os.makedirs(os.path.join(OUT, kind), exist_ok=True)
        for name, text in icons.items():
            with open(os.path.join(OUT, kind, name + ".svg"), "w") as fh:
                fh.write(text)
            names.append(f"{kind}/{name}")
    print(f"{len(names)} avatars in {os.path.normpath(OUT)}")
    if args.preview:
        preview(names, args.preview)


if __name__ == "__main__":
    main()

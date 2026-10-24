"""Animals: each in its own hue, the default of its `p`."""

import math

from kit import INK, PALETTE, P, face, svg  # noqa: F401

WHITE = "#fff8f0"        # a muzzle's, a belly's cream
PINK = "#f9a8b8"         # a nose, an inner ear
BEAK = "#f97316"


def fox(p=P("orange")):
    return svg(p,
        f'<path d="M12.5 32 L16 8.5 L31 21 Z M51.5 32 L48 8.5 L33 21 Z" fill="{p.main}" stroke="{p.main}" stroke-width="2" stroke-linejoin="round"/>'
        f'<path d="M17 26 L18.5 14.5 L26.5 21.5 Z M47 26 L45.5 14.5 L37.5 21.5 Z" fill="{p.light}"/>'
        f'<ellipse cx="32" cy="36" rx="21" ry="17" fill="{p.main}"/>'
        '<path d="M11.5 37 C16 37 25 39.5 32 48.5 C39 39.5 48 37 52.5 37 C51 47 43 53 32 53 C21 53 13 47 11.5 37Z" fill="#fff8f0"/>'
        + face(32, 33.5, gap=7.5, eye=(2.7, 3.3), mouth=None, cheek_dx=14, cheek_dy=8)
        + f'<ellipse cx="32" cy="47.3" rx="2.6" ry="1.9" fill="{INK}"/>'
        f'<path d="M28.8 50.2 q1.6 1.8 3.2 0 q1.6 1.8 3.2 0" fill="none" stroke="{INK}" stroke-width="1.5" stroke-linecap="round"/>')


def panda(p=P("gray")):
    return svg(p,
        '<circle cx="16" cy="19" r="7.5" fill="#2b2b2b"/><circle cx="48" cy="19" r="7.5" fill="#2b2b2b"/>'
        '<ellipse cx="32" cy="36" rx="22" ry="19" fill="#fff"/>'
        '<ellipse cx="23" cy="35" rx="5.6" ry="7.6" fill="#2b2b2b" transform="rotate(32 23 35)"/>'
        '<ellipse cx="41" cy="35" rx="5.6" ry="7.6" fill="#2b2b2b" transform="rotate(-32 41 35)"/>'
        '<circle cx="23.8" cy="33.8" r="2.5" fill="#fff"/><circle cx="40.2" cy="33.8" r="2.5" fill="#fff"/>'
        '<circle cx="24.2" cy="34.2" r="1.4" fill="#2b2b2b"/><circle cx="39.8" cy="34.2" r="1.4" fill="#2b2b2b"/>'
        '<ellipse cx="32" cy="41.5" rx="2.8" ry="2" fill="#2b2b2b"/>'
        '<path d="M28.8 44.3 q1.6 1.8 3.2 0 q1.6 1.8 3.2 0" fill="none" stroke="#2b2b2b" stroke-width="1.5" stroke-linecap="round"/>'
        '<ellipse cx="16.5" cy="43" rx="3.2" ry="2" fill="#ff8fa3" opacity=".65"/><ellipse cx="47.5" cy="43" rx="3.2" ry="2" fill="#ff8fa3" opacity=".65"/>')


def frog(p=P("green")):
    return svg(p,
        f'<circle cx="20" cy="21" r="9.5" fill="{p.main}"/><circle cx="44" cy="21" r="9.5" fill="{p.main}"/>'
        f'<ellipse cx="32" cy="39" rx="24" ry="17" fill="{p.main}"/>'
        '<circle cx="20" cy="21" r="6.2" fill="#fff"/><circle cx="44" cy="21" r="6.2" fill="#fff"/>'
        f'<circle cx="21" cy="22" r="3.7" fill="{p.deep}"/><circle cx="43" cy="22" r="3.7" fill="{p.deep}"/>'
        '<circle cx="22.3" cy="20.5" r="1.3" fill="#fff"/><circle cx="44.3" cy="20.5" r="1.3" fill="#fff"/>'
        f'<circle cx="29.5" cy="35" r=".9" fill="{p.dark}"/><circle cx="34.5" cy="35" r=".9" fill="{p.dark}"/>'
        f'<path d="M21 41 Q32 50 43 41" fill="none" stroke="{p.deep}" stroke-width="2.2" stroke-linecap="round"/>'
        '<ellipse cx="14.5" cy="42" rx="3.6" ry="2.2" fill="#ff8fa3" opacity=".75"/><ellipse cx="49.5" cy="42" rx="3.6" ry="2.2" fill="#ff8fa3" opacity=".75"/>')


def axolotl(p=P("pink")):
    return svg(p,
        f'<g stroke="{p.main}" stroke-width="5" stroke-linecap="round">'
        '<line x1="16" y1="28" x2="7" y2="20"/><line x1="14" y1="34" x2="4" y2="33"/><line x1="16" y1="40" x2="7" y2="47"/>'
        '<line x1="48" y1="28" x2="57" y2="20"/><line x1="50" y1="34" x2="60" y2="33"/><line x1="48" y1="40" x2="57" y2="47"/></g>'
        f'<ellipse cx="32" cy="35" rx="19.5" ry="16" fill="{p.light}"/>'
        + face(32, 32.5, gap=8.5, eye=(2.5, 2.7), mouth=None, blush=p.main, blush_op=.55, cheek_dx=13, cheek_dy=6.5)
        + f'<path d="M25.5 39 Q32 44.5 38.5 39" fill="none" stroke="{INK}" stroke-width="1.8" stroke-linecap="round"/>')


def bear(p=P("brown")):
    return svg(p,
        f'<circle cx="16.5" cy="18" r="7.5" fill="{p.main}"/><circle cx="47.5" cy="18" r="7.5" fill="{p.main}"/>'
        f'<circle cx="16.5" cy="18" r="3.8" fill="{p.light}"/><circle cx="47.5" cy="18" r="3.8" fill="{p.light}"/>'
        f'<ellipse cx="32" cy="35" rx="21.5" ry="19.5" fill="{p.main}"/>'
        f'<ellipse cx="32" cy="42.5" rx="9" ry="7" fill="{p.light}"/>'
        + face(32, 32, gap=8, eye=(2.6, 3.2), mouth=None, cheek_dx=14, cheek_dy=7, blush_op=.6)
        + f'<ellipse cx="32" cy="39.8" rx="3.1" ry="2.2" fill="{INK}"/>'
        f'<path d="M28.8 43.5 q1.6 1.8 3.2 0 q1.6 1.8 3.2 0" fill="none" stroke="{INK}" stroke-width="1.5" stroke-linecap="round"/>')


def whale(p=P("sky")):
    return svg(p,
        f'<path d="M30.5 13 C30 9 27.5 7 25 6.5 M30.5 13 C31 9 33.5 7 36 6.5 M30.5 13 V6" fill="none" stroke="{p.main}" stroke-width="2.3" stroke-linecap="round"/>'
        f'<path d="M48 33 C52 27 52.5 21 50.5 16.5 C53.5 17.5 56 15.5 57 11.5 C59.5 15.5 58.5 19.5 55.5 21.5 C58.5 20.5 61 21.5 62 23.5 C60 27.5 56 30 52.5 35Z" fill="{p.main}"/>'
        f'<path d="M8 38 C8 24 19 16.5 31 16.5 C45 16.5 54 26 54 38 C54 48.5 44 53.5 31 53.5 C17 53.5 8 48.5 8 38Z" fill="{p.main}"/>'
        f'<path d="M11.5 43 C18 50 44 50 50.5 43 C48 50 41 53.5 31 53.5 C21 53.5 14 50 11.5 43Z" fill="{p.light}"/>'
        + face(28, 34.5, gap=6.5, eye=(2.6, 3.2), cheek_dx=11, cheek_dy=5, mouth_dy=4.6))


def _spikes(cx, cy, rx, ry, out, start, end, n, fill):
    """n triangles standing out `out` from the ellipse (cx, cy, rx, ry), from angle `start` to `end` (degrees,
    SVG's: 0 right, 90 down)."""
    tris = []
    for i in range(n):
        a = math.radians(start + (end - start) * (i + .5) / n)
        w = math.radians((end - start) / n * .55)
        b1 = (cx + rx * math.cos(a - w), cy + ry * math.sin(a - w))
        b2 = (cx + rx * math.cos(a + w), cy + ry * math.sin(a + w))
        tip = (cx + (rx + out) * math.cos(a), cy + (ry + out) * math.sin(a))
        tris.append("M{:.1f} {:.1f} L{:.1f} {:.1f} L{:.1f} {:.1f}Z".format(*b1, *tip, *b2))
    return f'<path d="{" ".join(tris)}" fill="{fill}" stroke="{fill}" stroke-width="1.5" stroke-linejoin="round"/>'


def _eye(x, y, r=4.2):
    """A round white eye with the family's pupil, for an eye that stands apart (on a stalk)."""
    return (f'<circle cx="{x}" cy="{y}" r="{r}" fill="#fff"/><ellipse cx="{x}" cy="{y + .4}" rx="2.3" ry="2.8" fill="{INK}"/>'
            f'<circle cx="{x + .8}" cy="{y - .7}" r="1" fill="#fff"/>')


def crab(p=P("red")):
    return svg(p,
        f'<path d="M15 42 L7 45 M15.5 47 L9 52.5 M49 42 L57 45 M48.5 47 L55 52.5" fill="none" stroke="{p.dark}" stroke-width="2.8" stroke-linecap="round"/>'
        f'<path d="M18 37 L12.5 25 M46 37 L51.5 25" stroke="{p.main}" stroke-width="4.5" stroke-linecap="round"/>'
        f'<circle cx="12" cy="19.5" r="7.5" fill="{p.main}"/><circle cx="52" cy="19.5" r="7.5" fill="{p.main}"/>'
        f'<path d="M12 19.5 L8.5 10 L16 11 Z M52 19.5 L55.5 10 L48 11 Z" fill="{p.bg}"/>'
        f'<path d="M27 30 L25.5 21 M37 30 L38.5 21" stroke="{p.main}" stroke-width="2.8" stroke-linecap="round"/>'
        f'<ellipse cx="32" cy="40" rx="19" ry="13.5" fill="{p.main}"/>'
        + _eye(25.5, 19) + _eye(38.5, 19)
        + f'<ellipse cx="22" cy="40" rx="3.2" ry="2" fill="#ffc4cc" opacity=".95"/><ellipse cx="42" cy="40" rx="3.2" ry="2" fill="#ffc4cc" opacity=".95"/>'
        f'<path d="M28.5 38.5 q3.5 3.6 7 0" fill="none" stroke="{INK}" stroke-width="1.8" stroke-linecap="round"/>')


def ladybug(p=P("red")):
    return svg(p,
        f'<path d="M27 15 Q24.5 8 19.5 7.5 M37 15 Q39.5 8 44.5 7.5" fill="none" stroke="{p.deep}" stroke-width="2" stroke-linecap="round"/>'
        f'<circle cx="19.5" cy="7.5" r="2.4" fill="{p.deep}"/><circle cx="44.5" cy="7.5" r="2.4" fill="{p.deep}"/>'
        f'<circle cx="32" cy="38" r="20" fill="{p.main}"/>'
        f'<path d="M32 30 V58" stroke="{p.deep}" stroke-width="1.8"/>'
        f'<g fill="{p.deep}"><circle cx="20.5" cy="42" r="3.6"/><circle cx="43.5" cy="42" r="3.6"/><circle cx="26" cy="52" r="2.6"/>'
        '<circle cx="38" cy="52" r="2.6"/><circle cx="15.5" cy="33" r="2.2"/><circle cx="48.5" cy="33" r="2.2"/></g>'
        f'<ellipse cx="32" cy="24" rx="13" ry="11" fill="{p.deep}"/>'
        + face(32, 23, gap=5.5, eye=(2.4, 2.9), cheek_dx=9, cheek_dy=4.2, mouth_dy=4.2, ink="#fff", highlight=False,
               blush=p.light, blush_op=.8, mouth_ink="#fff"))


def tiger(p=P("orange")):
    return svg(p,
        f'<circle cx="15" cy="19" r="7.5" fill="{p.main}"/><circle cx="49" cy="19" r="7.5" fill="{p.main}"/>'
        f'<circle cx="15.5" cy="19.5" r="3.8" fill="{p.deep}"/><circle cx="48.5" cy="19.5" r="3.8" fill="{p.deep}"/>'
        f'<ellipse cx="32" cy="36" rx="21.5" ry="19" fill="{p.main}"/>'
        f'<g fill="{p.deep}"><path d="M32 17.2 L29.6 22.5 L32 25 L34.4 22.5Z M25.5 18.8 L26.8 24 L28.6 19.2Z M38.5 18.8 L37.2 24 L35.4 19.2Z"/>'
        '<path d="M10.6 31 L18 33.5 L10.7 35.5Z M11.2 39 L17.5 40 L12.3 43Z M53.4 31 L46 33.5 L53.3 35.5Z M52.8 39 L46.5 40 L51.7 43Z"/></g>'
        f'<ellipse cx="27.5" cy="44" rx="6.5" ry="5" fill="{WHITE}"/><ellipse cx="36.5" cy="44" rx="6.5" ry="5" fill="{WHITE}"/>'
        + face(32, 32.5, gap=8, eye=(2.7, 3.3), mouth=None, cheek_dx=13.5, cheek_dy=7)
        + f'<path d="M29 39.4 h6 q0 2.8 -3 3.4 q-3 -.6 -3 -3.4z" fill="{INK}"/>'
        f'<path d="M28.8 44.2 q1.6 1.8 3.2 0 q1.6 1.8 3.2 0" fill="none" stroke="{INK}" stroke-width="1.5" stroke-linecap="round"/>')


def puppy(p=P("orange")):
    return svg(p,
        f'<ellipse cx="32" cy="35" rx="18.5" ry="18" fill="{p.main}"/>'
        f'<path d="M17 18 C10 16.5 5.5 26 7 36 C8 41.5 13.5 41.5 15.2 37 C17.2 31 18 25 20.5 20.5Z" fill="{p.dark}"/>'
        f'<path d="M47 18 C54 16.5 58.5 26 57 36 C56 41.5 50.5 41.5 48.8 37 C46.8 31 46 25 43.5 20.5Z" fill="{p.dark}"/>'
        f'<ellipse cx="32" cy="44" rx="10" ry="7.5" fill="{WHITE}"/>'
        + face(32, 33, gap=7.5, eye=(2.7, 3.3), mouth=None, cheek_dx=12, cheek_dy=6)
        + f'<ellipse cx="32" cy="40.8" rx="3.3" ry="2.4" fill="{INK}"/>'
        f'<path d="M30.4 45.4 h3.2 v2.4 a1.6 1.6 0 0 1 -3.2 0z" fill="#ff7a8a"/>'
        f'<path d="M28.8 44.4 q1.6 1.8 3.2 0 q1.6 1.8 3.2 0" fill="none" stroke="{INK}" stroke-width="1.5" stroke-linecap="round"/>')


def chick(p=P("yellow")):
    return svg(p,
        f'<g fill="{BEAK}"><ellipse cx="26" cy="56" rx="3.6" ry="1.8"/><ellipse cx="38" cy="56" rx="3.6" ry="1.8"/></g>'
        f'<ellipse cx="12.5" cy="38" rx="4.2" ry="7.5" fill="{p.main}" transform="rotate(30 12.5 38)"/>'
        f'<ellipse cx="51.5" cy="38" rx="4.2" ry="7.5" fill="{p.main}" transform="rotate(-30 51.5 38)"/>'
        f'<path d="M30.5 17.5 C28.5 11.5 30.5 7.5 33.5 8.5 C32 11 32.6 14 33.6 17.5Z M33.2 17.5 C35 12.5 38.8 11 40.3 12.8 C37.6 13.5 36 15.4 35 18Z" fill="{p.main}"/>'
        f'<circle cx="32" cy="36" r="20" fill="{p.main}"/>'
        f'<ellipse cx="32" cy="45" rx="11.5" ry="8.5" fill="{p.light}"/>'
        + face(32, 32, gap=7.5, eye=(2.7, 3.3), mouth=None, cheek_dx=12.5, cheek_dy=5)
        + f'<path d="M29 36.6 L35 36.6 L32 40.6Z" fill="{BEAK}" stroke="{BEAK}" stroke-width="1.4" stroke-linejoin="round"/>')


def lion(p=P("yellow")):
    mane = "".join(f'<circle cx="{32 + 19 * math.cos(math.radians(a)):.1f}" cy="{34 + 19 * math.sin(math.radians(a)):.1f}" r="6.5"/>'
                   for a in range(0, 360, 30))
    return svg(p,
        f'<g fill="{p.main}">{mane}<circle cx="32" cy="34" r="20"/></g>'
        f'<circle cx="21" cy="21.5" r="4.5" fill="{p.light}"/><circle cx="43" cy="21.5" r="4.5" fill="{p.light}"/>'
        f'<circle cx="21" cy="21.5" r="2.2" fill="{p.main}"/><circle cx="43" cy="21.5" r="2.2" fill="{p.main}"/>'
        f'<circle cx="32" cy="35" r="14.5" fill="{p.light}"/>'
        f'<ellipse cx="28.6" cy="41.5" rx="4.2" ry="3.2" fill="#fffaf0"/><ellipse cx="35.4" cy="41.5" rx="4.2" ry="3.2" fill="#fffaf0"/>'
        + face(32, 32, gap=6, eye=(2.4, 3), mouth=None, cheek_dx=10, cheek_dy=5)
        + f'<path d="M29.6 37.6 h4.8 q0 2.4 -2.4 2.9 q-2.4 -.5 -2.4 -2.9z" fill="{INK}"/>'
        f'<path d="M29 41.6 q1.5 1.6 3 0 q1.5 1.6 3 0" fill="none" stroke="{INK}" stroke-width="1.4" stroke-linecap="round"/>')


def bee(p=P("yellow")):
    return svg(p,
        '<ellipse cx="19" cy="15" rx="9" ry="6" fill="#fff" opacity=".9" transform="rotate(-25 19 15)"/>'
        '<ellipse cx="45" cy="15" rx="9" ry="6" fill="#fff" opacity=".9" transform="rotate(25 45 15)"/>'
        f'<path d="M27.5 19 Q25.5 11 21 9 M36.5 19 Q38.5 11 43 9" fill="none" stroke="{p.deep}" stroke-width="2" stroke-linecap="round"/>'
        f'<circle cx="21" cy="9" r="2.2" fill="{p.deep}"/><circle cx="43" cy="9" r="2.2" fill="{p.deep}"/>'
        f'<ellipse cx="32" cy="36" rx="20" ry="18" fill="{p.main}"/>'
        f'<path d="M12.8 41 L51.2 41 A20 18 0 0 1 48.6 46 L15.4 46 A20 18 0 0 1 12.8 41Z'
        f' M19.4 50 L44.6 50 A20 18 0 0 1 38.6 53 L25.4 53 A20 18 0 0 1 19.4 50Z" fill="{p.deep}"/>'
        + face(32, 29.5, gap=7, eye=(2.6, 3.2), cheek_dx=12, cheek_dy=4.5, mouth_dy=4.4))


def caterpillar(p=P("lime")):
    seg = lambda x, y, r: f'<circle cx="{x}" cy="{y}" r="{r}" fill="{p.main}" stroke="{p.bg}" stroke-width="1.6"/>'
    return svg(p,
        f'<g fill="{p.dark}"><ellipse cx="12" cy="51" rx="2" ry="1.5"/><ellipse cx="20" cy="51.5" rx="2.2" ry="1.6"/>'
        '<ellipse cx="25" cy="51.5" rx="2.2" ry="1.6"/><ellipse cx="31" cy="45.5" rx="2.2" ry="1.6"/></g>'
        + seg(12, 45, 6) + seg(21, 43.5, 8)
        + f'<g fill="{p.light}"><circle cx="12" cy="42.5" r="1.6"/><circle cx="21" cy="40" r="2"/></g>'
        f'<path d="M31.5 18 Q28.5 11 24.5 9.5 M42.5 18 Q45.5 11 49.5 9.5" fill="none" stroke="{p.dark}" stroke-width="2" stroke-linecap="round"/>'
        f'<circle cx="24.5" cy="9.5" r="2.4" fill="{p.dark}"/><circle cx="49.5" cy="9.5" r="2.4" fill="{p.dark}"/>'
        + seg(37, 30.5, 14.5)
        + face(37, 29.5, gap=6, eye=(2.5, 3.1), cheek_dx=10, cheek_dy=4.6, mouth_dy=4.4))


def turtle(p=P("green")):
    return svg(p,
        f'<g fill="{p.light}"><ellipse cx="27" cy="48" rx="4.2" ry="5.5"/><ellipse cx="47" cy="48" rx="4.2" ry="5.5"/>'
        '<path d="M55 41 L60 45 L54 46Z"/><ellipse cx="20" cy="40" rx="5" ry="4.5"/></g>'
        f'<path d="M19 43 C19 26 28 18 38 18 C48 18 57 26 57 43Z" fill="{p.main}"/>'
        f'<g fill="none" stroke="{p.dark}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round">'
        '<path d="M33 26 H43 L47 33 L43 40 H33 L29 33Z M33 26 L30 20.5 M43 26 L46 20.5 M47 33 H55 M29 33 H21 M33 40 L31 43 M43 40 L45 43"/></g>'
        f'<rect x="17" y="40.5" width="42" height="5" rx="2.5" fill="{p.dark}"/>'
        f'<circle cx="15" cy="34" r="10.5" fill="{p.light}"/>'
        + face(15, 33, gap=4.6, eye=(2.1, 2.6), cheek_dx=7.2, cheek_dy=3.8, mouth_dy=3.6))


def dinosaur(p=P("green")):
    return svg(p,
        _spikes(32, 34, 18.5, 17.5, 6.5, -160, -20, 5, p.dark)
        + f'<g fill="{p.main}"><ellipse cx="18.5" cy="51" rx="5" ry="4"/><ellipse cx="45.5" cy="51" rx="5" ry="4"/></g>'
        f'<ellipse cx="32" cy="35" rx="19" ry="18" fill="{p.main}"/>'
        f'<ellipse cx="32" cy="45" rx="11" ry="8" fill="{p.light}"/>'
        f'<g fill="{p.main}"><ellipse cx="15.5" cy="42" rx="3" ry="4.5" transform="rotate(-30 15.5 42)"/>'
        '<ellipse cx="48.5" cy="42" rx="3" ry="4.5" transform="rotate(30 48.5 42)"/></g>'
        + face(32, 31, gap=7, eye=(2.6, 3.2), mouth="open", mouth_dy=5, cheek_dx=12.5, cheek_dy=5))


def dragon(p=P("teal")):
    return svg(p,
        f'<g fill="{p.dark}"><path d="M21 40 L6.5 20 Q10 25.5 13 24.5 Q13.5 29.5 17 29.5 Q17.5 33.5 22 33.5Z"/>'
        '<path d="M43 40 L57.5 20 Q54 25.5 51 24.5 Q50.5 29.5 47 29.5 Q46.5 33.5 42 33.5Z"/></g>'
        f'<g fill="{p.main}"><ellipse cx="25.5" cy="56" rx="4" ry="2.6"/><ellipse cx="38.5" cy="56" rx="4" ry="2.6"/></g>'
        f'<ellipse cx="32" cy="46" rx="13" ry="10.5" fill="{p.main}"/>'
        f'<ellipse cx="32" cy="48" rx="7" ry="7" fill="{p.light}"/>'
        f'<path d="M26.5 46 H37.5 M26 50 H38" stroke="{p.main}" stroke-width="1.2"/>'
        f'<g fill="{p.light}"><path d="M23.5 18 Q20 11 21.5 6 Q25 10.5 28.5 15.5Z"/><path d="M40.5 18 Q44 11 42.5 6 Q39 10.5 35.5 15.5Z"/></g>'
        f'<g fill="{p.dark}"><path d="M18.5 25 L11 21 L17.5 32Z"/><path d="M45.5 25 L53 21 L46.5 32Z"/></g>'
        f'<circle cx="32" cy="28.5" r="14.5" fill="{p.main}"/>'
        + face(32, 28, gap=6, eye=(2.5, 3.1), cheek_dx=10, cheek_dy=4.6, mouth_dy=4.6))


def penguin(p=P("sky")):
    return svg(p,
        f'<g fill="{BEAK}"><ellipse cx="25.5" cy="56.5" rx="4" ry="2"/><ellipse cx="38.5" cy="56.5" rx="4" ry="2"/></g>'
        f'<ellipse cx="13" cy="39" rx="4" ry="9" fill="{p.dark}" transform="rotate(20 13 39)"/>'
        f'<ellipse cx="51" cy="39" rx="4" ry="9" fill="{p.dark}" transform="rotate(-20 51 39)"/>'
        f'<ellipse cx="32" cy="35" rx="18.5" ry="21" fill="{p.main}"/>'
        f'<ellipse cx="32" cy="44" rx="12" ry="11" fill="{p.light}"/>'
        '<circle cx="25.5" cy="30" r="7.5" fill="#fff"/><circle cx="38.5" cy="30" r="7.5" fill="#fff"/><ellipse cx="32" cy="35" rx="9" ry="5.5" fill="#fff"/>'
        + face(32, 30, gap=6.5, eye=(2.5, 3.1), mouth=None, cheek_dx=11, cheek_dy=5.5)
        + f'<path d="M29.2 34.4 L34.8 34.4 L32 38Z" fill="{BEAK}" stroke="{BEAK}" stroke-width="1.4" stroke-linejoin="round"/>')


def seal(p=P("sky")):
    return svg(p,
        f'<ellipse cx="14" cy="50" rx="4.2" ry="7.5" fill="{p.dark}" transform="rotate(55 14 50)"/>'
        f'<ellipse cx="50" cy="50" rx="4.2" ry="7.5" fill="{p.dark}" transform="rotate(-55 50 50)"/>'
        f'<ellipse cx="32" cy="37" rx="20" ry="19" fill="{p.main}"/>'
        '<ellipse cx="28.3" cy="43.5" rx="5.2" ry="4.2" fill="#fff"/><ellipse cx="35.7" cy="43.5" rx="5.2" ry="4.2" fill="#fff"/>'
        f'<g fill="{p.dark}"><circle cx="26" cy="43" r=".8"/><circle cx="28" cy="45.5" r=".8"/><circle cx="25" cy="46" r=".8"/>'
        '<circle cx="38" cy="43" r=".8"/><circle cx="36" cy="45.5" r=".8"/><circle cx="39" cy="46" r=".8"/></g>'
        + face(32, 33, gap=8.5, eye=(3.1, 3.7), mouth=None, cheek_dx=14, cheek_dy=7)
        + f'<ellipse cx="32" cy="40.2" rx="2.8" ry="2" fill="{INK}"/>')


def bluebird(p=P("blue")):
    return svg(p,
        f'<path d="M15 42 L4.5 45 L7.5 35.5Z" fill="{p.dark}"/>'
        f'<path d="M31.5 16.5 C29.5 11 32 7.5 35 8.5 C33.6 11 34.4 13.6 35.6 16.5Z" fill="{p.main}"/>'
        f'<circle cx="34" cy="35.5" r="20" fill="{p.main}"/>'
        f'<ellipse cx="36" cy="45" rx="11.5" ry="8.5" fill="{p.light}"/>'
        f'<ellipse cx="19.5" cy="39.5" rx="5" ry="8.5" fill="{p.dark}" transform="rotate(20 19.5 39.5)"/>'
        + face(36, 31.5, gap=6.5, eye=(2.6, 3.2), mouth=None, cheek_dx=10.5, cheek_dy=5)
        + f'<path d="M33 36 L39 36 L36 40Z" fill="#fbbf24" stroke="#fbbf24" stroke-width="1.4" stroke-linejoin="round"/>')


def shark(p=P("blue")):
    return svg(p,
        f'<path d="M15 35 L5 23.5 L8 35.5 L6 46Z" fill="{p.dark}"/>'
        f'<path d="M27 21 L35 7.5 L42 21Z" fill="{p.main}" stroke="{p.main}" stroke-width="2" stroke-linejoin="round"/>'
        f'<ellipse cx="34" cy="35" rx="22" ry="15.5" fill="{p.main}"/>'
        f'<path d="M13 38 C20 51 48 51 56 37 C51 45 21 47 13 38Z" fill="{p.light}"/>'
        f'<path d="M27 46 L22 54 L33 48Z" fill="{p.dark}"/>'
        f'<path d="M19 30 q2 3.5 0 7 M22.5 29.5 q2 4 0 8" fill="none" stroke="{p.dark}" stroke-width="1.6" stroke-linecap="round"/>'
        + face(40, 31, gap=6, eye=(2.5, 3.1), mouth=None, cheek_dx=9.5, cheek_dy=5)
        + f'<path d="M35.5 37.5 Q40 42.5 44.5 37.5Z" fill="{INK}"/>'
        '<path d="M37.4 37.9 l1 1.5 l1 -1.5Z M40.6 37.9 l1 1.5 l1 -1.5Z" fill="#fff"/>')


def octopus(p=P("purple")):
    return svg(p,
        f'<path d="M18 40 C14 46 12 48 11 52 M24 44 C22 49 20 52 18 56 M32 45 C32 50 31.5 53 32 57.5'
        f' M40 44 C42 49 44 52 46 56 M46 40 C50 46 52 48 53 52" fill="none" stroke="{p.main}" stroke-width="6" stroke-linecap="round"/>'
        f'<ellipse cx="32" cy="30" rx="18" ry="17" fill="{p.main}"/>'
        f'<g fill="{p.light}" opacity=".8"><circle cx="23" cy="19.5" r="2.4"/><circle cx="30" cy="16" r="1.6"/><circle cx="42" cy="20" r="1.9"/></g>'
        + face(32, 31, gap=6.5, eye=(2.6, 3.2), cheek_dx=11, cheek_dy=5, mouth_dy=4.6))


def unicorn(p=P("purple")):
    return svg(p,
        f'<g fill="{p.main}"><circle cx="24" cy="16" r="6"/><circle cx="17.5" cy="22" r="6"/><circle cx="14" cy="30.5" r="5.5"/>'
        '<circle cx="14" cy="39" r="5"/><circle cx="16.5" cy="47" r="4.5"/></g>'
        f'<path d="M38.5 21 L44.5 8.5 L47.5 22Z" fill="{p.light}" stroke="{p.light}" stroke-width="2" stroke-linejoin="round"/>'
        f'<path d="M41 19.5 L44 12.5 L45.5 20Z" fill="{p.main}"/>'
        f'<ellipse cx="34" cy="36" rx="16" ry="18" fill="{p.light}"/>'
        f'<ellipse cx="34" cy="47" rx="10" ry="6.5" fill="#ede9fe"/>'
        f'<g fill="{p.dark}"><circle cx="24.5" cy="20.5" r="5"/><circle cx="30" cy="18.5" r="4.5"/><circle cx="20.5" cy="27" r="4"/></g>'
        '<path d="M31.2 19 L35.5 3 L39.8 19Z" fill="#fbbf24" stroke="#fbbf24" stroke-width="1.6" stroke-linejoin="round"/>'
        '<path d="M32.6 14.5 L38 12.5 M33.6 10 L37 8.8" stroke="#d97706" stroke-width="1.3" stroke-linecap="round"/>'
        + face(35, 34, gap=6.5, eye=(2.5, 3.1), mouth=None, cheek_dx=11, cheek_dy=5)
        + f'<g fill="{p.main}"><ellipse cx="31" cy="46" rx="1.2" ry="1.6"/><ellipse cx="37" cy="46" rx="1.2" ry="1.6"/></g>'
        f'<path d="M31.5 49.8 q2.5 2 5 0" fill="none" stroke="{INK}" stroke-width="1.6" stroke-linecap="round"/>')


def pig(p=P("pink")):
    return svg(p,
        f'<path d="M13 27 L14 10 L27 18Z M51 27 L50 10 L37 18Z" fill="{p.main}" stroke="{p.main}" stroke-width="2.5" stroke-linejoin="round"/>'
        f'<path d="M16.5 22 L17 14.5 L23 18.5Z M47.5 22 L47 14.5 L41 18.5Z" fill="{p.dark}" opacity=".55"/>'
        f'<ellipse cx="32" cy="36" rx="20.5" ry="18.5" fill="{p.main}"/>'
        f'<ellipse cx="32" cy="42.5" rx="8" ry="5.8" fill="{p.light}"/>'
        f'<g fill="{p.dark}"><ellipse cx="29.2" cy="42.5" rx="1.4" ry="2"/><ellipse cx="34.8" cy="42.5" rx="1.4" ry="2"/></g>'
        + face(32, 32, gap=8.5, eye=(2.6, 3.2), mouth=None, cheek_dx=15, cheek_dy=6, blush=p.dark, blush_op=.3)
        + f'<path d="M29.5 50.2 q2.5 2.2 5 0" fill="none" stroke="{INK}" stroke-width="1.7" stroke-linecap="round"/>')


def bunny(p=P("pink")):
    return svg(p,
        f'<ellipse cx="23" cy="17" rx="5.8" ry="13" fill="{p.main}" transform="rotate(-12 23 17)"/>'
        f'<ellipse cx="41" cy="17" rx="5.8" ry="13" fill="{p.main}" transform="rotate(12 41 17)"/>'
        f'<ellipse cx="23" cy="18" rx="2.7" ry="9.5" fill="{p.light}" transform="rotate(-12 23 18)"/>'
        f'<ellipse cx="41" cy="18" rx="2.7" ry="9.5" fill="{p.light}" transform="rotate(12 41 18)"/>'
        f'<ellipse cx="32" cy="40" rx="18.5" ry="16" fill="{p.main}"/>'
        + face(32, 38, gap=7.5, eye=(2.7, 3.3), mouth=None, cheek_dx=12, cheek_dy=5.5, blush=p.dark, blush_op=.3)
        + f'<ellipse cx="32" cy="43" rx="2" ry="1.4" fill="{INK}"/>'
        '<rect x="30.4" y="46" width="3.2" height="3" rx=".6" fill="#fff"/>'
        f'<path d="M28.8 45.2 q1.6 1.8 3.2 0 q1.6 1.8 3.2 0" fill="none" stroke="{INK}" stroke-width="1.5" stroke-linecap="round"/>')


def flamingo(p=P("pink")):
    return svg(p,
        f'<path d="M35 47 V58 M40 47 L40 52 L35.5 54" fill="none" stroke="{p.dark}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<path d="M48 36 L57.5 31.5 L55 41Z" fill="{p.main}"/>'
        f'<ellipse cx="39" cy="40" rx="14" ry="9.5" fill="{p.main}" transform="rotate(-8 39 40)"/>'
        f'<ellipse cx="42" cy="39.5" rx="7.5" ry="4.8" fill="{p.light}" transform="rotate(-8 42 39.5)"/>'
        f'<path d="M30 39 C21 38 17 31 20.5 25 C22.5 21.5 25 20 25.5 17" fill="none" stroke="{p.main}" stroke-width="6.5" stroke-linecap="round"/>'
        f'<circle cx="26.5" cy="15" r="9" fill="{p.main}"/>'
        f'<path d="M20 16.5 C15.5 16 13.2 18.5 14 23" fill="none" stroke="#fff" stroke-width="4.6" stroke-linecap="round"/>'
        f'<path d="M13.9 21.2 L14 23" fill="none" stroke="{p.deep}" stroke-width="4.6" stroke-linecap="round"/>'
        + face(27.5, 13.5, gap=4, eye=(1.9, 2.4), mouth=None, cheek_dx=6.4, cheek_dy=3.6, blush=p.dark, blush_op=.35))


def owl(p=P("brown")):
    return svg(p,
        f'<path d="M14 23 L14.5 9 L24.5 17Z M50 23 L49.5 9 L39.5 17Z" fill="{p.main}" stroke="{p.main}" stroke-width="2" stroke-linejoin="round"/>'
        f'<ellipse cx="32" cy="36" rx="19.5" ry="20" fill="{p.main}"/>'
        f'<ellipse cx="32" cy="46.5" rx="11" ry="8.5" fill="{p.light}"/>'
        f'<path d="M27 44 l2 2 l2 -2 M33 44 l2 2 l2 -2 M30 49 l2 2 l2 -2" fill="none" stroke="{p.main}" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<ellipse cx="13.5" cy="40" rx="4.5" ry="10" fill="{p.dark}" transform="rotate(15 13.5 40)"/>'
        f'<ellipse cx="50.5" cy="40" rx="4.5" ry="10" fill="{p.dark}" transform="rotate(-15 50.5 40)"/>'
        f'<circle cx="24.5" cy="29.5" r="8" fill="{p.light}"/><circle cx="39.5" cy="29.5" r="8" fill="{p.light}"/>'
        + face(32, 29.5, gap=7.5, eye=(3, 3.6), mouth=None, blush=None)
        + '<path d="M29.6 34.5 L34.4 34.5 L32 38.8Z" fill="#f59e0b" stroke="#f59e0b" stroke-width="1.2" stroke-linejoin="round"/>')


def monkey(p=P("brown")):
    return svg(p,
        f'<circle cx="11.5" cy="34" r="7" fill="{p.main}"/><circle cx="52.5" cy="34" r="7" fill="{p.main}"/>'
        f'<circle cx="11.5" cy="34" r="4" fill="{p.light}"/><circle cx="52.5" cy="34" r="4" fill="{p.light}"/>'
        f'<circle cx="32" cy="34" r="19" fill="{p.main}"/>'
        f'<path d="M30 16 C28.5 10.5 33 7.5 36 10 C33.5 10.5 32.5 12.5 33 15.5Z" fill="{p.main}"/>'
        f'<g fill="{p.light}"><circle cx="26" cy="31" r="7.8"/><circle cx="38" cy="31" r="7.8"/><ellipse cx="32" cy="42" rx="12" ry="9"/></g>'
        + face(32, 31, gap=6, eye=(2.5, 3.1), mouth=None, cheek_dx=11, cheek_dy=7)
        + f'<g fill="{p.dark}"><ellipse cx="30.3" cy="39" rx="1" ry="1.3"/><ellipse cx="33.7" cy="39" rx="1" ry="1.3"/></g>'
        f'<path d="M27 42.5 Q32 47.5 37 42.5" fill="none" stroke="{INK}" stroke-width="1.8" stroke-linecap="round"/>')


def hedgehog(p=P("brown")):
    return svg(p,
        _spikes(32, 36, 17.5, 16.5, 7, 150, 390, 13, p.dark)
        + f'<ellipse cx="32" cy="36" rx="18" ry="17" fill="{p.dark}"/>'
        f'<ellipse cx="32" cy="41" rx="15" ry="13" fill="{p.light}"/>'
        f'<path d="M20 34 Q26 29.5 32 33 Q38 29.5 44 34" fill="none" stroke="{p.dark}" stroke-width="3" stroke-linecap="round"/>'
        + face(32, 39, gap=6, eye=(2.5, 3.1), mouth=None, cheek_dx=10, cheek_dy=4.5)
        + f'<ellipse cx="32" cy="44" rx="2.4" ry="1.7" fill="{INK}"/>'
        f'<path d="M29.6 47.4 q2.4 2 4.8 0" fill="none" stroke="{INK}" stroke-width="1.5" stroke-linecap="round"/>')


def cat(p=P("gray")):
    return svg(p,
        f'<path d="M12.5 30 L14 9 L29 19Z M51.5 30 L50 9 L35 19Z" fill="{p.main}" stroke="{p.main}" stroke-width="2" stroke-linejoin="round"/>'
        f'<path d="M17 24 L17.6 14.5 L24.6 19.5Z M47 24 L46.4 14.5 L39.4 19.5Z" fill="{PINK}"/>'
        f'<ellipse cx="32" cy="36" rx="21" ry="17.5" fill="{p.main}"/>'
        f'<path d="M32 19.5 v5 M27 20.5 l1 4.4 M37 20.5 l-1 4.4" stroke="{p.dark}" stroke-width="2" stroke-linecap="round"/>'
        f'<ellipse cx="28.5" cy="42.5" rx="5" ry="3.8" fill="{p.light}"/><ellipse cx="35.5" cy="42.5" rx="5" ry="3.8" fill="{p.light}"/>'
        + face(32, 34, gap=8, eye=(2.7, 3.3), mouth=None, cheek_dx=14, cheek_dy=6)
        + f'<path d="M30.4 39.3 h3.2 l-1.6 2Z" fill="{PINK}" stroke="{PINK}" stroke-width="1" stroke-linejoin="round"/>'
        f'<path d="M28.8 42 q1.6 1.8 3.2 0 q1.6 1.8 3.2 0" fill="none" stroke="{INK}" stroke-width="1.4" stroke-linecap="round"/>'
        f'<path d="M20 41 L11 39.5 M20 44 L11.5 45.5 M44 41 L53 39.5 M44 44 L52.5 45.5" stroke="{p.light}" stroke-width="1.2" stroke-linecap="round"/>')


def koala(p=P("gray")):
    return svg(p,
        f'<circle cx="13" cy="23" r="10" fill="{p.main}"/><circle cx="51" cy="23" r="10" fill="{p.main}"/>'
        f'<circle cx="13.5" cy="23.5" r="6" fill="{p.light}"/><circle cx="50.5" cy="23.5" r="6" fill="{p.light}"/>'
        f'<ellipse cx="32" cy="37" rx="19.5" ry="17.5" fill="{p.main}"/>'
        + face(32, 33, gap=9, eye=(2.5, 3.1), mouth=None, cheek_dx=13.5, cheek_dy=7)
        + f'<ellipse cx="32" cy="40" rx="4.6" ry="6" fill="{p.deep}"/><ellipse cx="30.6" cy="37.5" rx="1.3" ry="1.8" fill="#fff" opacity=".5"/>'
        f'<path d="M29.5 48.6 q2.5 2 5 0" fill="none" stroke="{INK}" stroke-width="1.6" stroke-linecap="round"/>')


def mouse(p=P("gray")):
    fur = "#94a3b8"
    return svg(p,
        f'<circle cx="15" cy="20" r="10.5" fill="{fur}"/><circle cx="49" cy="20" r="10.5" fill="{fur}"/>'
        f'<circle cx="15.5" cy="20.5" r="6.2" fill="{PINK}"/><circle cx="48.5" cy="20.5" r="6.2" fill="{PINK}"/>'
        f'<ellipse cx="32" cy="38" rx="16.5" ry="16" fill="{fur}"/>'
        f'<path d="M23 43 L12 41.5 M23 45.5 L12.5 47.5 M41 43 L52 41.5 M41 45.5 L51.5 47.5" stroke="{p.main}" stroke-width="1.2" stroke-linecap="round"/>'
        + face(32, 36.5, gap=6.5, eye=(2.6, 3.2), mouth=None, cheek_dx=11, cheek_dy=5)
        + f'<circle cx="32" cy="42.5" r="2.2" fill="#f472b6"/>'
        f'<path d="M29 45.2 q1.5 1.6 3 0 q1.5 1.6 3 0" fill="none" stroke="{INK}" stroke-width="1.4" stroke-linecap="round"/>')


ICONS = {f.__name__: f() for f in [
    fox, tiger, puppy, crab, ladybug, chick, lion, bee, caterpillar, frog, turtle, dinosaur, dragon,
    whale, penguin, seal, bluebird, shark, octopus, unicorn, axolotl, pig, bunny, flamingo,
    bear, owl, monkey, hedgehog, panda, cat, koala, mouse]}

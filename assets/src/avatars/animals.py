"""Animals: each in its own hue, the default of its `p` -- but the jellyfish, which comes in every hue
(ICONS: jellyfish-<hue>)."""

import math

from kit import BLUSH, CREAM, INK, PALETTE, P, face, nose_w, shine, svg

BEAK = "#fb923c"


def _spikes(cx, cy, r, out, n, fill):
    """n small triangles standing out `out` all round the circle (cx, cy, r)."""
    tris = []
    for i in range(n):
        a, w = 2 * math.pi * i / n, math.pi / n * .5
        b1 = (cx + r * math.cos(a - w), cy + r * math.sin(a - w))
        b2 = (cx + r * math.cos(a + w), cy + r * math.sin(a + w))
        tip = (cx + (r + out) * math.cos(a), cy + (r + out) * math.sin(a))
        tris.append("M{:.1f} {:.1f} L{:.1f} {:.1f} L{:.1f} {:.1f}Z".format(*b1, *tip, *b2))
    return f'<path d="{" ".join(tris)}" fill="{fill}" stroke="{fill}" stroke-width="1.2" stroke-linejoin="round"/>'


def red_panda(p=P("red")):
    return svg(p,
        f'<circle cx="15" cy="18.5" r="8" fill="{CREAM}"/><circle cx="49" cy="18.5" r="8" fill="{CREAM}"/>'
        f'<circle cx="15.8" cy="19.3" r="4" fill="{p.deep}"/><circle cx="48.2" cy="19.3" r="4" fill="{p.deep}"/>'
        f'<ellipse cx="32" cy="36" rx="22" ry="18" fill="{p.main}"/>'
        f'<ellipse cx="22.5" cy="28" rx="3.6" ry="2.2" fill="{CREAM}"/><ellipse cx="41.5" cy="28" rx="3.6" ry="2.2" fill="{CREAM}"/>'
        f'<path d="M14 40 C17 35 23 37 26 40 C29 38.5 35 38.5 38 40 C41 37 47 35 50 40 C48 49 41 53.5 32 53.5 C23 53.5 16 49 14 40Z" fill="{CREAM}"/>'
        + face(32, 34.5, gap=9, mouth=None, cheek_dx=13.5, cheek_dy=8)
        + f'<path d="M30 41 h4 l-2 2.2z" fill="{INK}" stroke="{INK}" stroke-width="1" stroke-linejoin="round"/>'
        f'<path d="M29.4 44.6 q1.3 1.7 2.6 0 q1.3 1.7 2.6 0" fill="none" stroke="{INK}" stroke-width="1.5" stroke-linecap="round"/>')


def octopus(p=P("red")):
    return svg(p,
        f'<g fill="none" stroke="{p.main}" stroke-width="6" stroke-linecap="round">'
        '<path d="M19 42 C13 48 12 54 17 56.5"/><path d="M27 46 C25 52 24.5 56 28.5 58.5"/>'
        '<path d="M37 46 C39 52 39.5 56 35.5 58.5"/><path d="M45 42 C51 48 52 54 47 56.5"/></g>'
        f'<path d="M12 33 C12 19 21 10 32 10 C43 10 52 19 52 33 C52 43 43 48 32 48 C21 48 12 43 12 33Z" fill="{p.main}"/>'
        + shine(22, 17.5)
        + f'<path d="M12.4 26.5 Q32 20.5 51.6 26.5 L51.9 31 Q32 25 12.1 31Z" fill="#fff"/>'
        f'<path d="M50.5 28 L57.5 23.5 L56.5 29.5Z M50.5 29 L56.5 33.5 L50.5 34Z" fill="#fff" stroke="#fff" stroke-width="1" stroke-linejoin="round"/>'
        + face(32, 36, gap=7.5, mouth=None, blush="#ffc4cc", blush_op=.95, cheek_dy=3.4)
        + f'<ellipse cx="32" cy="41.6" rx="2.6" ry="2.2" fill="{p.dark}"/><ellipse cx="32" cy="41.6" rx="1.2" ry="1" fill="{p.deep}"/>')


def goldfish(p=P("red")):
    return svg(p,
        f'<path d="M40 33 C47 24 57 21 60 25 C56 30 56 37 60 42 C57 46 47 43 40 37Z" fill="{p.light}"/>'
        f'<path d="M46 31 Q52 30 57 26 M46 35 Q52 37 57 41" fill="none" stroke="{p.main}" stroke-width="1.2" stroke-linecap="round" opacity=".6"/>'
        f'<path d="M20 22 C24 14 34 13 38 21Z" fill="{p.light}"/>'
        f'<path d="M22 44 C22 50 26 53 30 52 C29 49 28 47 28 45Z" fill="{p.light}"/>'
        f'<ellipse cx="28" cy="34" rx="16" ry="13.5" fill="{p.main}"/>'
        f'<ellipse cx="27" cy="41" rx="10" ry="4.6" fill="{p.light}" opacity=".55"/>'
        + shine(19.5, 26, rx=3.2, ry=2)
        + face(23, 32.5, gap=5.5, mouth="o", mouth_dy=3.4, blush="#ffc4cc", blush_op=.95, cheek_dx=8.6, cheek_dy=4))


def shiba(p=P("orange")):
    return svg(p,
        f'<path d="M12.5 31 L15 9.5 L29 18.5 Z M51.5 31 L49 9.5 L35 18.5 Z" fill="{p.main}"/>'
        f'<path d="M16.5 25 L17.6 14.5 L25 19 Z M47.5 25 L46.4 14.5 L39 19 Z" fill="{p.light}"/>'
        f'<ellipse cx="32" cy="36" rx="21" ry="18" fill="{p.main}"/>'
        f'<path d="M12.6 39 C14 31 21 31.5 26 35.5 C29.5 33.5 34.5 33.5 38 35.5 C43 31.5 50 31 51.4 39 C50.5 48.5 42.5 53.2 32 53.2 C21.5 53.2 13.5 48.5 12.6 39Z" fill="{CREAM}"/>'
        f'<ellipse cx="23" cy="30.2" rx="2.7" ry="1.6" fill="{CREAM}"/><ellipse cx="41" cy="30.2" rx="2.7" ry="1.6" fill="{CREAM}"/>'
        + face(32, 36.5, gap=9, mouth=None, cheek_dy=5.5) + nose_w(40.6))


def hamster(p=P("orange")):
    return svg(p,
        f'<circle cx="18" cy="20" r="5.5" fill="{p.main}"/><circle cx="46" cy="20" r="5.5" fill="{p.main}"/>'
        f'<circle cx="18.4" cy="20.4" r="2.8" fill="{BLUSH}"/><circle cx="45.6" cy="20.4" r="2.8" fill="{BLUSH}"/>'
        f'<ellipse cx="32" cy="37" rx="22" ry="18.5" fill="{p.main}"/>'
        f'<path d="M14 42 C14 34 20 31.5 25 34 C28 32.6 36 32.6 39 34 C44 31.5 50 34 50 42 C50 50 42 55.5 32 55.5 C22 55.5 14 50 14 42Z" fill="{CREAM}"/>'
        + face(32, 33.5, gap=8, mouth=None, cheek_dx=13, cheek_dy=8.5)
        + '<ellipse cx="32" cy="37.4" rx="1.6" ry="1.1" fill="#ff7a8a"/>'
        f'<path d="M29.4 39.6 q1.3 1.7 2.6 0 q1.3 1.7 2.6 0" fill="none" stroke="{INK}" stroke-width="1.5" stroke-linecap="round"/>')


def koi(p=P("orange")):
    return svg(p,
        f'<path d="M32 45 C26 49 22 55 23.5 60 C27.5 57 30 55 32 52.5 C34 55 36.5 57 40.5 60 C42 55 38 49 32 45Z" fill="{p.light}"/>'
        f'<path d="M20.5 27 C13 25.5 8.5 30.5 9.5 35 C14 34.5 18 32.5 21 31Z M43.5 27 C51 25.5 55.5 30.5 54.5 35 C50 34.5 46 32.5 43 31Z" fill="{p.light}"/>'
        f'<path d="M32 8 C42 8 46 17 45.5 27 C45 37 39 44.5 32 49 C25 44.5 19 37 18.5 27 C18 17 22 8 32 8Z" fill="{CREAM}"/>'
        f'<path d="M20 22 C22 14 27 10 32 10 C37 10 41.5 13 43.5 19 C38 21 30 18.5 26 26 C24 25 22 23.5 20 22Z" fill="{p.main}"/>'
        f'<path d="M24.5 34 C29 31 37 32 44 34.5 C42.5 40 38 45 32 48.5 C28 45.5 25.5 40 24.5 34Z" fill="{p.main}"/>'
        f'<path d="M29 11.5 q-3 -2.5 -5.5 -1 M35 11.5 q3 -2.5 5.5 -1" fill="none" stroke="{p.dark}" stroke-width="1.2" stroke-linecap="round"/>'
        + face(32, 21, gap=5.6, r=2.1, mouth="smile", mouth_dy=3.6, cheek_dx=8.8, cheek_dy=3.8))


def chick(p=P("yellow")):
    return svg(p,
        f'<path d="M31 15 C29 9.5 30.5 6.5 33.5 6 C33 9 34 11 36.5 12 C34.5 12.3 32.5 13.4 31 15Z" fill="{p.main}"/>'
        f'<path d="M13.5 37 C8 37 6.5 44 9.5 47.5 C13 46.5 15.5 43 15.5 39.5Z M50.5 37 C56 37 57.5 44 54.5 47.5 C51 46.5 48.5 43 48.5 39.5Z" fill="{p.dark}" opacity=".55"/>'
        f'<path d="M32 14 C44 14 51.5 25 51.5 37 C51.5 49 43 56 32 56 C21 56 12.5 49 12.5 37 C12.5 25 20 14 32 14Z" fill="{p.main}"/>'
        f'<ellipse cx="32" cy="46" rx="13" ry="8.5" fill="{p.light}" opacity=".8"/>'
        + shine(22, 23)
        + face(32, 32.5, gap=7, mouth=None, cheek_dy=4.2)
        + f'<path d="M29.6 35.6 h4.8 l-2.4 3z" fill="{BEAK}" stroke="{BEAK}" stroke-width="1" stroke-linejoin="round"/>')


def pufferfish(p=P("yellow")):
    return svg(p,
        _spikes(31, 35, 18, 3.6, 18, p.dark)
        + f'<path d="M48 35 L57 28.5 L57 41.5Z" fill="{p.dark}" stroke="{p.dark}" stroke-width="2" stroke-linejoin="round"/>'
        f'<circle cx="31" cy="35" r="18" fill="{p.main}"/>'
        f'<path d="M14.5 40 C18 50 44 50 47.5 40 C45 52 17 52 14.5 40Z" fill="{p.light}"/>'
        f'<ellipse cx="31" cy="44.5" rx="12" ry="5.5" fill="{p.light}"/>'
        f'<g fill="{p.dark}" opacity=".45"><circle cx="21" cy="24" r="1.4"/><circle cx="31" cy="20" r="1.4"/><circle cx="41" cy="24" r="1.4"/></g>'
        f'<path d="M44 36 C48 37 49 40 47 42 C45.5 40.5 44.5 38.5 44 36Z" fill="{p.dark}" opacity=".7"/>'
        + face(29, 33, gap=6.5, mouth="o", mouth_dy=3.6, cheek_dx=10.4, cheek_dy=4.2))


def mejiro(p=P("lime")):
    return svg(p,
        f'<path d="M19 45 L7 51 L10 55 L22 49Z" fill="{p.dark}"/>'
        f'<ellipse cx="32" cy="36" rx="19" ry="18" fill="{p.main}"/>'
        f'<ellipse cx="32" cy="46" rx="12" ry="8" fill="#fff6d6"/>'
        '<ellipse cx="32" cy="40.5" rx="7" ry="3.2" fill="#fde047"/>'
        f'<path d="M44 33 C51 36 52 44 47 49 C44 45 42.5 40 44 33Z" fill="{p.dark}"/>'
        + shine(23, 23, op=.3)
        + '<circle cx="25" cy="31" r="4" fill="#fff"/><circle cx="39" cy="31" r="4" fill="#fff"/>'
        + face(32, 31, gap=7, r=2.1, mouth=None, cheek_dx=10.5, cheek_dy=5.6)
        + f'<path d="M30.4 34.8 h3.2 l-1.6 2.2z" fill="{INK}" stroke="{INK}" stroke-width=".8" stroke-linejoin="round"/>')


def frog(p=P("green")):
    return svg(p,
        f'<circle cx="20" cy="22" r="8.5" fill="{p.main}"/><circle cx="44" cy="22" r="8.5" fill="{p.main}"/>'
        f'<ellipse cx="32" cy="38" rx="23" ry="16" fill="{p.main}"/>'
        f'<ellipse cx="32" cy="46" rx="14" ry="7.5" fill="{p.light}" opacity=".7"/>'
        + shine(16, 18, rx=2.6, ry=1.6, op=.4) + shine(40, 18, rx=2.6, ry=1.6, op=.4)
        + face(32, 22.5, gap=12, r=2.4, mouth=None, cheek_dx=15, cheek_dy=13.5)
        + f'<path d="M27.5 35 q4.5 4 9 0" fill="none" stroke="{INK}" stroke-width="1.6" stroke-linecap="round"/>')


def turtle(p=P("green")):
    return svg(p,
        f'<g fill="{p.light}"><ellipse cx="25" cy="50" rx="4.5" ry="5"/><ellipse cx="44" cy="50" rx="4.5" ry="5"/>'
        '<path d="M52 44 L58 46.5 L52 48Z"/></g>'
        f'<path d="M20 46 C20 30 27 20 38 20 C49 20 55 30 55 46Z" fill="{p.main}"/>'
        f'<path d="M30 46 C30 37 33 29 38 25 C43 29 46 37 46 46 M22 37 H54" fill="none" stroke="{p.dark}" stroke-width="1.6" opacity=".7"/>'
        f'<path d="M18 46 H57" stroke="{p.dark}" stroke-width="4" stroke-linecap="round"/>'
        f'<circle cx="17" cy="31" r="11.5" fill="{p.light}"/>'
        + face(16, 30.5, gap=4.8, r=2, mouth="smile", mouth_dy=3.6, cheek_dx=7.6, cheek_dy=3.6))


def whale(p=P("sky")):
    return svg(p,
        f'<path d="M30.5 13 C30 9 27.5 7 25 6.5 M30.5 13 C31 9 33.5 7 36 6.5 M30.5 13 V6" fill="none" stroke="{p.main}" stroke-width="2.3" stroke-linecap="round"/>'
        f'<path d="M48 33 C52 27 52.5 21 50.5 16.5 C53.5 17.5 56 15.5 57 11.5 C59.5 15.5 58.5 19.5 55.5 21.5 C58.5 20.5 61 21.5 62 23.5 C60 27.5 56 30 52.5 35Z" fill="{p.main}"/>'
        f'<path d="M8 38 C8 24 19 16.5 31 16.5 C45 16.5 54 26 54 38 C54 48.5 44 53.5 31 53.5 C17 53.5 8 48.5 8 38Z" fill="{p.main}"/>'
        f'<path d="M11.5 43 C18 50 44 50 50.5 43 C48 50 41 53.5 31 53.5 C21 53.5 14 50 11.5 43Z" fill="{p.light}"/>'
        + shine(18, 24)
        + face(28, 34.5, gap=7, mouth="smile", mouth_dy=3.8, cheek_dy=4))


def seal(p=P("sky")):
    return svg(p,
        f'<ellipse cx="12.5" cy="48" rx="6.5" ry="3.2" fill="{p.light}" transform="rotate(-25 12.5 48)"/>'
        f'<ellipse cx="51.5" cy="48" rx="6.5" ry="3.2" fill="{p.light}" transform="rotate(25 51.5 48)"/>'
        '<path d="M10 44 C10 30 20 19 32 19 C44 19 54 30 54 44 C54 52 46 55.5 32 55.5 C18 55.5 10 52 10 44Z" fill="#fff"/>'
        f'<path d="M12 48 C16 53 48 53 52 48 C50 53.5 44 55.5 32 55.5 C20 55.5 14 53.5 12 48Z" fill="{p.light}"/>'
        + face(32, 35.5, gap=9, r=2.4, mouth=None, cheek_dy=5)
        + f'<ellipse cx="28.6" cy="41" rx="3.4" ry="2.8" fill="{p.light}"/><ellipse cx="35.4" cy="41" rx="3.4" ry="2.8" fill="{p.light}"/>'
        + f'<g fill="{p.main}" opacity=".6"><circle cx="27.6" cy="41" r=".6"/><circle cx="29.6" cy="42" r=".6"/><circle cx="36.4" cy="41" r=".6"/><circle cx="34.4" cy="42" r=".6"/></g>'
        + f'<ellipse cx="32" cy="38.6" rx="2" ry="1.4" fill="{INK}"/>')


def penguin(p=P("blue")):
    return svg(p,
        f'<ellipse cx="12.5" cy="38" rx="4" ry="9" fill="{p.dark}" transform="rotate(20 12.5 38)"/>'
        f'<ellipse cx="51.5" cy="38" rx="4" ry="9" fill="{p.dark}" transform="rotate(-20 51.5 38)"/>'
        f'<ellipse cx="25" cy="56" rx="4.5" ry="2" fill="{BEAK}"/><ellipse cx="39" cy="56" rx="4.5" ry="2" fill="{BEAK}"/>'
        f'<path d="M32 9 C45 9 52 20 52 34 C52 48 44 56 32 56 C20 56 12 48 12 34 C12 20 19 9 32 9Z" fill="{p.main}"/>'
        '<path d="M32 22 C36 17 46 18 46 28 C46 34 44 38 44 44 C44 52 38 54 32 54 C26 54 20 52 20 44 C20 38 18 34 18 28 C18 18 28 17 32 22Z" fill="#fff"/>'
        + face(32, 30.5, gap=6.5, mouth=None, cheek_dx=9.8, cheek_dy=4)
        + f'<path d="M29.6 33.8 h4.8 l-2.4 2.8z" fill="{BEAK}" stroke="{BEAK}" stroke-width="1" stroke-linejoin="round"/>')


def shark(p=P("blue")):
    return svg(p,
        f'<path d="M29 15 C31 7 37 4.5 42 4 C39 8 38 12 39.5 16Z" fill="{p.main}"/>'
        f'<path d="M11.5 40 L4 46.5 L13.5 45.5Z M52.5 40 L60 46.5 L50.5 45.5Z" fill="{p.dark}" stroke="{p.dark}" stroke-width="1.6" stroke-linejoin="round"/>'
        f'<ellipse cx="32" cy="35" rx="22" ry="19" fill="{p.main}"/>'
        '<path d="M12.5 39 C18 46 46 46 51.5 39 C49 50 41 54 32 54 C23 54 15 50 12.5 39Z" fill="#fff"/>'
        f'<path d="M15 28 q2 2.4 0 5 M18.5 27 q2 2.8 0 6" fill="none" stroke="{p.dark}" stroke-width="1.3" stroke-linecap="round"/>'
        + shine(22, 22)
        + face(32, 33, gap=8.5, mouth=None, cheek_dy=4.2)
        + f'<path d="M27.5 40.5 Q32 44 36.5 40.5" fill="none" stroke="{INK}" stroke-width="1.6" stroke-linecap="round"/>'
        '<path d="M29.4 41.7 l1.1 1.5 l1 -1.1z M34.6 41.7 l-1.1 1.5 l-1 -1.1z" fill="#fff"/>')


def mochi_usagi(p=P("pink")):
    return svg(p,
        f'<ellipse cx="23" cy="17" rx="5" ry="11.5" fill="{CREAM}" transform="rotate(-14 23 17)"/>'
        f'<ellipse cx="41" cy="17" rx="5" ry="11.5" fill="{CREAM}" transform="rotate(14 41 17)"/>'
        f'<ellipse cx="23" cy="18" rx="2.4" ry="7.5" fill="{p.main}" transform="rotate(-14 23 18)"/>'
        f'<ellipse cx="41" cy="18" rx="2.4" ry="7.5" fill="{p.main}" transform="rotate(14 41 18)"/>'
        f'<path d="M9.5 46 C9.5 33 19.5 25 32 25 C44.5 25 54.5 33 54.5 46 C54.5 53.5 46 56 32 56 C18 56 9.5 53.5 9.5 46Z" fill="{CREAM}"/>'
        + face(32, 41.5, gap=8.5, mouth="bunny", mouth_dy=2.6, blush=p.main, blush_op=.7, cheek_dy=4.2))


def axolotl(p=P("pink")):
    return svg(p,
        f'<g stroke="{p.main}" stroke-width="5" stroke-linecap="round">'
        '<line x1="16" y1="28" x2="7" y2="20"/><line x1="14" y1="34" x2="4" y2="33"/><line x1="16" y1="40" x2="7" y2="47"/>'
        '<line x1="48" y1="28" x2="57" y2="20"/><line x1="50" y1="34" x2="60" y2="33"/><line x1="48" y1="40" x2="57" y2="47"/></g>'
        f'<ellipse cx="32" cy="35" rx="19.5" ry="16" fill="{p.light}"/>'
        + face(32, 33, gap=9.5, mouth=None, blush=p.main, blush_op=.55, cheek_dx=12.5, cheek_dy=5.5)
        + f'<path d="M26.5 38.5 Q32 43.5 37.5 38.5" fill="none" stroke="{INK}" stroke-width="1.6" stroke-linecap="round"/>')


def capybara(p=P("brown")):
    return svg(p,
        f'<circle cx="16.5" cy="20" r="4.3" fill="{p.dark}"/><circle cx="47.5" cy="20" r="4.3" fill="{p.dark}"/>'
        f'<path d="M12 31 C12 20 21 15.5 32 15.5 C43 15.5 52 20 52 31 V42 C52 51.5 44 55.5 32 55.5 C20 55.5 12 51.5 12 42Z" fill="{p.main}"/>'
        f'<ellipse cx="32" cy="44.5" rx="13" ry="8.5" fill="{p.dark}" opacity=".45"/>'
        f'<ellipse cx="27.5" cy="42" rx="1.4" ry="2" fill="{p.deep}"/><ellipse cx="36.5" cy="42" rx="1.4" ry="2" fill="{p.deep}"/>'
        f'<path d="M29 48 q3 2 6 0" fill="none" stroke="{p.deep}" stroke-width="1.5" stroke-linecap="round"/>'
        + face(32, 31.5, gap=9.5, r=2.2, mouth=None, cheek_dy=4.5, blush_op=.7)
        + '<circle cx="32" cy="12" r="6.5" fill="#fcd34d" stroke="#d99a06" stroke-width="1"/>'
        '<path d="M32 5.8 q3.5 -3 6.5 -1.2 q-2.5 3.6 -6.5 1.2z" fill="#5a9e3a"/>')


def bear(p=P("brown")):
    return svg(p,
        f'<circle cx="16.5" cy="18" r="7.5" fill="{p.main}"/><circle cx="47.5" cy="18" r="7.5" fill="{p.main}"/>'
        f'<circle cx="16.5" cy="18" r="3.8" fill="{p.light}"/><circle cx="47.5" cy="18" r="3.8" fill="{p.light}"/>'
        f'<ellipse cx="32" cy="35" rx="21.5" ry="19.5" fill="{p.main}"/>'
        f'<ellipse cx="32" cy="42.5" rx="8.5" ry="6.5" fill="{p.light}"/>'
        + face(32, 33, gap=9, mouth=None, cheek_dx=14, cheek_dy=6, blush_op=.7) + nose_w(40.4))


def deer(p=P("brown")):
    return svg(p,
        f'<path d="M24.5 17 C23 11 20 8 16.5 7 M23.5 13 C21 12 18.5 12.5 17 14 M39.5 17 C41 11 44 8 47.5 7 M40.5 13 C43 12 45.5 12.5 47 14" fill="none" stroke="{p.dark}" stroke-width="2.6" stroke-linecap="round"/>'
        f'<ellipse cx="12.5" cy="29" rx="8" ry="4.6" fill="{p.main}" transform="rotate(-22 12.5 29)"/>'
        f'<ellipse cx="51.5" cy="29" rx="8" ry="4.6" fill="{p.main}" transform="rotate(22 51.5 29)"/>'
        f'<ellipse cx="12.8" cy="29" rx="4.6" ry="2.2" fill="{p.light}" transform="rotate(-22 12.8 29)"/>'
        f'<ellipse cx="51.2" cy="29" rx="4.6" ry="2.2" fill="{p.light}" transform="rotate(22 51.2 29)"/>'
        f'<path d="M32 15 C44 15 49.5 24 49.5 34 C49.5 46 42 54 32 54 C22 54 14.5 46 14.5 34 C14.5 24 20 15 32 15Z" fill="{p.main}"/>'
        f'<g fill="{CREAM}"><circle cx="26" cy="22.5" r="1.6"/><circle cx="38" cy="22.5" r="1.6"/><circle cx="32" cy="20" r="1.4"/></g>'
        f'<ellipse cx="32" cy="45" rx="8.5" ry="6.8" fill="{p.light}"/>'
        + face(32, 34, gap=8, mouth=None, cheek_dx=12.5, cheek_dy=5) + nose_w(42.6))


def tanuki(p=P("gray")):
    return svg(p,
        f'<circle cx="16.5" cy="19.5" r="6.5" fill="{p.dark}"/><circle cx="47.5" cy="19.5" r="6.5" fill="{p.dark}"/>'
        f'<circle cx="17" cy="20" r="3.2" fill="{p.deep}"/><circle cx="47" cy="20" r="3.2" fill="{p.deep}"/>'
        f'<ellipse cx="32" cy="36" rx="21.5" ry="18.5" fill="{p.main}"/>'
        f'<path d="M32 18.5 C36 18.5 37.5 26 37 31 C40 33 41 38.5 32 38.5 C23 38.5 24 33 27 31 C26.5 26 28 18.5 32 18.5Z" fill="{p.light}"/>'
        f'<ellipse cx="22.5" cy="36" rx="6.8" ry="5.4" fill="{p.deep}" transform="rotate(-18 22.5 36)"/>'
        f'<ellipse cx="41.5" cy="36" rx="6.8" ry="5.4" fill="{p.deep}" transform="rotate(18 41.5 36)"/>'
        f'<ellipse cx="32" cy="44.5" rx="9" ry="7" fill="{p.light}"/>'
        + face(32, 35.2, gap=9.2, r=2.1, ink="#fff", mouth=None, cheek_dx=14.5, cheek_dy=8) + nose_w(41.5)
        + '<path d="M32 17 C27 12 28.5 7 33.5 6 C36 10.5 35.5 14.5 32 17Z" fill="#6aa84f"/>')


def enaga(p=P("gray")):
    return svg(p,
        f'<ellipse cx="17" cy="42" rx="5" ry="8.5" fill="{p.dark}" transform="rotate(28 17 42)"/>'
        f'<ellipse cx="47" cy="42" rx="5" ry="8.5" fill="{p.dark}" transform="rotate(-28 47 42)"/>'
        '<path d="M14 35 C14 23 22 16.5 32 16.5 C42 16.5 50 23 50 35 C50 47 42 53.5 32 53.5 C22 53.5 14 47 14 35Z" fill="#fff"/>'
        '<path d="M25 19 q2.4 -5.4 5 -1.6 q2.4 -5 4.6 -.6 q2.8 -4 4.4 1" fill="#fff" stroke="#fff" stroke-width="2" stroke-linejoin="round"/>'
        + face(32, 34, gap=5.4, r=1.9, mouth=None, cheek_dx=9.8, cheek_dy=4.4, blush_op=.65)
        + f'<path d="M30.6 36.6 h2.8 l-1.4 1.9z" fill="{INK}" stroke="{INK}" stroke-width=".8" stroke-linejoin="round"/>')


def panda(p=P("gray")):
    return svg(p,
        f'<circle cx="16" cy="19" r="7.5" fill="{INK}"/><circle cx="48" cy="19" r="7.5" fill="{INK}"/>'
        '<ellipse cx="32" cy="36" rx="22" ry="19" fill="#fff"/>'
        f'<ellipse cx="22.5" cy="35.5" rx="5.6" ry="7" fill="{INK}" transform="rotate(32 22.5 35.5)"/>'
        f'<ellipse cx="41.5" cy="35.5" rx="5.6" ry="7" fill="{INK}" transform="rotate(-32 41.5 35.5)"/>'
        + face(32, 35, gap=8.6, r=1.9, ink="#fff", blush=None, mouth=None)
        + '<ellipse cx="15.5" cy="43" rx="3.3" ry="2" fill="#ff8fa3" opacity=".8"/><ellipse cx="48.5" cy="43" rx="3.3" ry="2" fill="#ff8fa3" opacity=".8"/>'
        + nose_w(42))


def koala(p=P("gray")):
    return svg(p,
        f'<circle cx="13" cy="24" r="10" fill="{p.main}"/><circle cx="51" cy="24" r="10" fill="{p.main}"/>'
        f'<circle cx="13.5" cy="24.5" r="6" fill="{p.light}"/><circle cx="50.5" cy="24.5" r="6" fill="{p.light}"/>'
        f'<ellipse cx="32" cy="36" rx="20" ry="18" fill="{p.main}"/>'
        + face(32, 33.5, gap=9.5, ink=p.deep, mouth=None, cheek_dy=6)
        + f'<ellipse cx="32" cy="39.5" rx="3.8" ry="4.6" fill="{p.deep}"/>'
        f'<path d="M29.8 46.6 q2.2 2 4.4 0" fill="none" stroke="{p.deep}" stroke-width="1.6" stroke-linecap="round"/>')


def jellyfish(p):
    return svg(p,
        f'<g fill="none" stroke="{p.dark}" stroke-width="2.4" stroke-linecap="round">'
        '<path d="M20 35 q-3 5 0 10 q3 5 0 10"/><path d="M27 36 q3 4.5 0 9 q-3 4.5 0 9"/>'
        '<path d="M37 36 q-3 4.5 0 9 q3 4.5 0 9"/><path d="M44 35 q3 5 0 10 q-3 5 0 10"/></g>'
        f'<path d="M11 34 C11 20 20.5 11.5 32 11.5 C43.5 11.5 53 20 53 34 C49 37 45 33.5 41 36.5 C37 33.5 27 33.5 23 36.5 C19 33.5 15 37 11 34Z" fill="{p.main}"/>'
        + shine(21, 20, rx=4.5, op=.4)
        + face(32, 26, gap=7.5, mouth="v", mouth_dy=3.4, blush="#ffc4e1", blush_op=.9))


SINGLE = [red_panda, octopus, goldfish, shiba, hamster, koi, chick, pufferfish, mejiro, frog, turtle, whale,
          seal, penguin, shark, mochi_usagi, axolotl, capybara, bear, deer, tanuki, enaga, panda, koala]
ICONS = {**{f.__name__.replace("_", "-"): f() for f in SINGLE},
         **{f"jellyfish-{hue}": jellyfish(P(hue)) for hue in PALETTE}}

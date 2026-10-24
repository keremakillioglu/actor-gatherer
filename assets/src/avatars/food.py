"""Food, fruit and vegetables: each in its own hue, the default of its `p`."""

import math

from kit import INK, PALETTE, P, face, svg  # noqa: F401


def strawberry(p=P("red")):
    return svg(p,
        f'<path d="M32 58 C20 54 10 40 11 28 C12 18 22 16 32 18 C42 16 52 18 53 28 C54 40 44 54 32 58Z" fill="{p.main}"/>'
        '<g fill="#ffe08a"><ellipse cx="17.5" cy="30" rx="1.1" ry="1.6"/><ellipse cx="46.5" cy="30" rx="1.1" ry="1.6"/>'
        '<ellipse cx="20.5" cy="42" rx="1.1" ry="1.6"/><ellipse cx="43.5" cy="42" rx="1.1" ry="1.6"/>'
        '<ellipse cx="27" cy="50" rx="1.1" ry="1.6"/><ellipse cx="37" cy="50" rx="1.1" ry="1.6"/></g>'
        '<rect x="31" y="7" width="2" height="8" rx="1" fill="#2e7d32"/>'
        '<g fill="#3f9142"><ellipse cx="26" cy="18.5" rx="5.5" ry="2.4" transform="rotate(-15 26 18.5)"/>'
        '<ellipse cx="38" cy="18.5" rx="5.5" ry="2.4" transform="rotate(15 38 18.5)"/>'
        '<ellipse cx="32" cy="17" rx="2.4" ry="3.6"/></g>'
        + face(32, 32.5, gap=6, eye=(2.5, 3.1), blush="#ffc4cc", blush_op=.95, cheek_dx=11, cheek_dy=4.5, mouth_dy=4.3))


def mushroom(p=P("red")):
    return svg(p,
        '<path d="M22 34 C21 44 20 52 24 55 C28 57.5 36 57.5 40 55 C44 52 43 44 42 34Z" fill="#fff6ea"/>'
        f'<path d="M8 34 C8 18 20 9 32 9 C44 9 56 18 56 34 C56 37.5 50 38.5 32 38.5 C14 38.5 8 37.5 8 34Z" fill="{p.main}"/>'
        '<g fill="#fff"><circle cx="20" cy="24" r="4"/><circle cx="33" cy="16.5" r="3.3"/><circle cx="44.5" cy="25" r="4.4"/>'
        '<circle cx="28.5" cy="30.5" r="2.4"/><circle cx="13.5" cy="32" r="1.8"/><circle cx="51" cy="33" r="1.8"/></g>'
        + face(32, 44, gap=5.2, eye=(2.2, 2.8), cheek_dx=8.2, cheek_dy=4, mouth_dy=4))


def watermelon(p=P("pink")):
    return svg(p,
        '<path d="M6 19 A26 26 0 0 0 58 19 Z" fill="#2f8a3c"/>'
        '<path d="M8 19 A24 24 0 0 0 56 19 Z" fill="#fff4f8"/>'
        '<path d="M10 19 A22 22 0 0 0 54 19 Z" fill="#fb6f92"/>'
        f'<g fill="{INK}"><ellipse cx="16" cy="24" rx="1.1" ry="1.7"/><ellipse cx="48" cy="24" rx="1.1" ry="1.7"/>'
        '<ellipse cx="22.5" cy="35.5" rx="1.1" ry="1.7"/><ellipse cx="41.5" cy="35.5" rx="1.1" ry="1.7"/><ellipse cx="32" cy="38.5" rx="1.1" ry="1.7"/></g>'
        + face(32, 25, gap=6, eye=(2.5, 3), blush="#ffd0dc", blush_op=.95, cheek_dx=10.5, cheek_dy=4.2, mouth_dy=4.2))


def avocado(p=P("lime")):
    return svg(p,
        f'<path d="M32 8 C22 8 19 20 17 28 C13 38 14 56 32 56 C50 56 51 38 47 28 C45 20 42 8 32 8Z" fill="{p.dark}"/>'
        f'<path d="M32 11.5 C24 11.5 21.5 21 19.8 29 C16.5 38 17.5 52.8 32 52.8 C46.5 52.8 47.5 38 44.2 29 C42.5 21 40 11.5 32 11.5Z" fill="{p.light}"/>'
        '<circle cx="32" cy="41" r="7" fill="#9c5b2e"/><ellipse cx="29.6" cy="38.5" rx="2.2" ry="1.4" fill="#c07a45"/>'
        + face(32, 24.5, gap=5.5, eye=(2.3, 2.9), cheek_dx=9, cheek_dy=4, mouth_dy=4))


def broccoli(p=P("green")):
    return svg(p,
        f'<path d="M21 31 C23 38 21 48 21 53 C21 58 43 58 43 53 C43 48 41 38 43 31Z" fill="{p.light}"/>'
        f'<g fill="{p.main}"><circle cx="19" cy="24" r="10"/><circle cx="32" cy="17" r="11.5"/><circle cx="45" cy="24" r="10"/>'
        '<circle cx="25.5" cy="29" r="8"/><circle cx="38.5" cy="29" r="8"/></g>'
        f'<g fill="{p.dark}"><circle cx="15" cy="21" r="1.7"/><circle cx="21" cy="17.5" r="1.5"/><circle cx="29" cy="11" r="1.7"/>'
        '<circle cx="36.5" cy="13.5" r="1.5"/><circle cx="43" cy="19" r="1.7"/><circle cx="49" cy="24" r="1.5"/><circle cx="31" cy="22" r="1.5"/>'
        '<circle cx="19" cy="28" r="1.4"/><circle cx="44.5" cy="29" r="1.4"/></g>'
        + face(32, 41.5, gap=5, eye=(2.2, 2.8), cheek_dx=8.2, cheek_dy=4, mouth_dy=4))


def eggplant(p=P("purple")):
    return svg(p,
        f'<path d="M34 17 C43 17 48 25 48 35 C48 48 41 57 32 57 C23 57 17 50 18 42 C19 34 24.5 30 25.5 24 C26.5 19 29 17 34 17Z" fill="{p.main}"/>'
        f'<ellipse cx="41.5" cy="33" rx="1.8" ry="5.5" fill="{p.light}" opacity=".7" transform="rotate(-12 41.5 33)"/>'
        '<rect x="33" y="6" width="3" height="10" rx="1.5" fill="#4d8b3a" transform="rotate(12 34.5 11)"/>'
        '<path d="M24.5 22 C26.5 15.5 30.5 14 34 14 C38 14 42 16.5 43 22 C40.5 19.8 38.5 20.5 37.5 23 C35.8 20.2 32.8 20.2 31.6 23 C29.8 20.5 27 20.5 24.5 22Z" fill="#4d8b3a"/>'
        + face(32.5, 39, gap=6, eye=(2.5, 3.1), cheek_dx=10.5, cheek_dy=4.5, mouth_dy=4.4))


def onigiri(p=P("gray")):
    return svg(p,
        '<path d="M32 10 C36 10 39 13 42 18 L54 40 C57 46 54 54 46 54 L18 54 C10 54 7 46 10 40 L22 18 C25 13 28 10 32 10Z" fill="#fff"/>'
        f'<path d="M22 40 H42 V54 H22Z" fill="{p.deep}"/><path d="M24 43 H40" stroke="{p.dark}" stroke-width="1"/>'
        + face(32, 30.5, gap=6, eye=(2.5, 3.1), cheek_dx=11, cheek_dy=4.5, mouth="open", mouth_dy=4.6))


LEAF, STEM = "#4caf50", "#4d8b3a"
WOOD, CONE = "#e3b778", "#e6b06a"


def cherries(p=P("red")):
    return svg(p,
        f'<path d="M20 29 C21 21 27 13 35 8 M43 25 C41 18 37 12 35 8" fill="none" stroke="{STEM}" stroke-width="2.4" stroke-linecap="round"/>'
        f'<path d="M35 8 C40 3 48 4 51 9 C45 12 39 11 35 8Z" fill="{LEAF}"/>'
        f'<circle cx="20" cy="41" r="13" fill="{p.main}"/><circle cx="43" cy="37" r="13" fill="{p.main}"/>'
        f'<ellipse cx="13" cy="34" rx="3" ry="1.8" fill="{p.light}" opacity=".85" transform="rotate(-40 13 34)"/>'
        f'<ellipse cx="36" cy="30" rx="3" ry="1.8" fill="{p.light}" opacity=".85" transform="rotate(-40 36 30)"/>'
        + face(20, 41, gap=4.6, eye=(2.1, 2.6), blush="#ffc4cc", blush_op=.9, cheek_dx=7.6, cheek_dy=3.3, mouth_dy=3.5)
        + face(43, 37, gap=4.6, eye=(2.1, 2.6), blush="#ffc4cc", blush_op=.9, cheek_dx=7.6, cheek_dy=3.3, mouth_dy=3.5))


def carrot(p=P("orange")):
    return svg(p,
        f'<g fill="{LEAF}"><ellipse cx="25" cy="14" rx="3.8" ry="8.5" transform="rotate(-28 25 14)"/>'
        '<ellipse cx="39" cy="14" rx="3.8" ry="8.5" transform="rotate(28 39 14)"/>'
        '<ellipse cx="32" cy="12" rx="3.8" ry="8.5"/></g>'
        f'<path d="M17 26 C17 18 47 18 47 26 C47 38 39 50 34 57 C33 58.5 31 58.5 30 57 C25 50 17 38 17 26Z" fill="{p.main}"/>'
        f'<g stroke="{p.dark}" stroke-width="1.8" stroke-linecap="round" fill="none">'
        '<path d="M20.5 40 h3.5"/><path d="M43.5 37 h-3.5"/><path d="M27 50 h3"/></g>'
        + face(32, 30, gap=6, eye=(2.5, 3.1), cheek_dx=10.5, cheek_dy=4.5, mouth_dy=4.3))


def pumpkin(p=P("orange")):
    return svg(p,
        '<path d="M31.5 20 C30.5 14 31 11 34.5 8" fill="none" stroke="#6b8e23" stroke-width="4" stroke-linecap="round"/>'
        f'<path d="M34 14 C38 9 45 10 47.5 14 C42 17 37.5 17 34 14Z" fill="{LEAF}"/>'
        f'<g fill="{p.main}" stroke="{p.dark}" stroke-width="1.6">'
        '<ellipse cx="19.5" cy="38" rx="12" ry="15.5"/><ellipse cx="44.5" cy="38" rx="12" ry="15.5"/>'
        '<ellipse cx="32" cy="37.5" rx="13.5" ry="18"/></g>'
        + face(32, 37, gap=6, eye=(2.5, 3.1), cheek_dx=11, cheek_dy=4.5, mouth="open", mouth_dy=4.6))


def banana(p=P("yellow")):
    return svg(p,
        f'<path d="M53.5 23 L55.5 15.5" stroke="{p.dark}" stroke-width="3.4" stroke-linecap="round"/>'
        f'<path d="M7 24 C8 44 20 55 33 55 C46 55 56 43 57 23 C57 20 53 19.5 52 22.5 C49 32 42 37 32 37 C22 37 15 32 12 23.5 C11 20.5 7 21 7 24Z" fill="{p.main}"/>'
        f'<circle cx="8.6" cy="24.6" r="1.7" fill="{p.deep}"/>'
        + face(32, 44, gap=6, eye=(2.4, 3), cheek_dx=10.5, cheek_dy=4.3, mouth_dy=4.2))


def corn(p=P("yellow")):
    kernels = []
    for row, y in enumerate(range(11, 54, 5)):
        for x in range(14 + (row % 2) * 2, 52, 4):
            if ((x - 32) / 10.5) ** 2 + ((y - 30) / 21) ** 2 < 1 and not (abs(x - 32) < 13 and 24 < y < 40):
                kernels.append(f'<ellipse cx="{x}" cy="{y}" rx="1.6" ry="1.9"/>')
    return svg(p,
        f'<ellipse cx="32" cy="30" rx="13" ry="23" fill="{p.main}"/>'
        f'<g fill="{p.light}">{"".join(kernels)}</g>'
        '<path d="M32 59 C21 57 14.5 48 16 35 C20.5 42 26 49 32 59Z" fill="#6cbf3c"/>'
        '<path d="M32 59 C43 57 49.5 48 48 35 C43.5 42 38 49 32 59Z" fill="#58a830"/>'
        + face(32, 31, gap=5.5, eye=(2.4, 3), cheek_dx=8.8, cheek_dy=4.2, mouth_dy=4.2))


def pear(p=P("lime")):
    return svg(p,
        '<path d="M32 14 C32 10 33 7.5 35.5 5.5" fill="none" stroke="#7a5230" stroke-width="2.6" stroke-linecap="round"/>'
        f'<ellipse cx="41" cy="9.5" rx="6" ry="2.8" fill="{p.dark}" transform="rotate(-25 41 9.5)"/>'
        f'<path d="M32 12 C26 12 23.5 17 23.5 23 C23.5 29 13 33 13 44 C13 53 21 58 32 58 C43 58 51 53 51 44 C51 33 40.5 29 40.5 23 C40.5 17 38 12 32 12Z" fill="{p.main}"/>'
        f'<ellipse cx="20" cy="36" rx="1.8" ry="4" fill="{p.light}" opacity=".8" transform="rotate(30 20 36)"/>'
        + face(32, 42, gap=6.5, eye=(2.6, 3.2), cheek_dx=11.5, cheek_dy=4.6, mouth_dy=4.5))


def kiwi(p=P("lime")):
    seeds = []
    for i in range(14):
        a = 2 * math.pi * i / 14
        x, y = 32 + 15.5 * math.cos(a), 32 + 15.5 * math.sin(a)
        seeds.append(f'<ellipse cx="{x:.2f}" cy="{y:.2f}" rx="1" ry="2" transform="rotate({math.degrees(a) + 90:.1f} {x:.2f} {y:.2f})"/>')
    return svg(p,
        '<circle cx="32" cy="32" r="25" fill="#8a5a33"/>'
        f'<circle cx="32" cy="32" r="22.2" fill="{p.main}"/>'
        f'<circle cx="32" cy="32" r="11" fill="{p.light}"/>'
        f'<g fill="{INK}">{"".join(seeds)}</g>'
        + face(32, 30.5, gap=5.2, eye=(2.3, 2.9), cheek_dx=8.6, cheek_dy=4, mouth_dy=4))


def peapod(p=P("lime")):
    small = dict(gap=3.2, eye=(1.5, 1.9), blush=None, mouth_dy=2.8)
    return svg(p,
        '<g transform="rotate(-22 32 34)">'
        f'<path d="M5 33 C3 30 4 27 7 26" fill="none" stroke="{p.dark}" stroke-width="2.4" stroke-linecap="round"/>'
        f'<path d="M6 31 C10 22 22 19 32 19 C42 19 54 22 58 31 C56 44 44 49 32 49 C20 49 8 44 6 31Z" fill="{p.dark}"/>'
        f'<path d="M10 32 C14 26 22 24.5 32 24.5 C42 24.5 50 26 54 32 C52 41 43 45 32 45 C21 45 12 41 10 32Z" fill="{p.light}"/>'
        f'<g fill="{p.main}"><circle cx="18.5" cy="34.5" r="7.2"/><circle cx="32" cy="34" r="8.6"/><circle cx="45.5" cy="34.5" r="7.2"/></g>'
        + face(18.5, 34, **small) + face(45.5, 34, **small)
        + face(32, 33.5, gap=3.8, eye=(1.7, 2.2), cheek_dx=5.2, cheek_dy=2.8, mouth_dy=3)
        + '</g>')


def pickle(p=P("green")):
    bumps = "".join(f'<ellipse cx="{x}" cy="{y}" rx="1.5" ry="1.2"/>'
                    for x, y in ((25, 19), (39, 20), (22.5, 45), (42, 43), (31, 53), (35, 13), (37, 50)))
    return svg(p,
        '<g transform="rotate(16 32 33)">'
        f'<path d="M32 8 C42 8 45.5 16 45.5 28 C45.5 42 44 58 32 58 C20 58 18.5 42 18.5 28 C18.5 16 22 8 32 8Z" fill="{p.main}"/>'
        f'<g fill="{p.dark}">{bumps}</g>'
        f'<ellipse cx="25" cy="21" rx="1.8" ry="4" fill="{p.light}" opacity=".7"/>'
        '</g>'
        + face(31.5, 31, gap=6, eye=(2.5, 3.1), cheek_dx=9.6, cheek_dy=4.5, mouth="w", mouth_dy=4.3))


def icecream(p=P("teal")):
    lattice = ("M25 38 L35 54.2 M32 38 L38.5 48.5 M38 38 L41.5 43.6 "
               "M39 38 L29 54.2 M32 38 L25.5 48.5 M26 38 L22.5 43.6")
    chips = "".join(f'<ellipse cx="{x}" cy="{y}" rx="1.9" ry="1.3" transform="rotate({r} {x} {y})"/>'
                    for x, y, r in ((24, 16, 30), (37, 14.5, -20), (45.5, 22, 50), (18, 24, -40)))
    return svg(p,
        f'<path d="M19 37 L45 37 L33.5 59 C33 60 31 60 30.5 59Z" fill="{CONE}"/>'
        f'<path d="{lattice}" stroke="#c98b3e" stroke-width="1.3"/>'
        f'<path d="M14.5 33 C13 21 21 10.5 32 10.5 C43 10.5 51 21 49.5 33 C49.5 37.5 46.5 39.5 44.5 37.5 C42.5 41 38.5 41.5 37 38.5 '
        f'C35 42.5 29.5 42.5 27.5 38.5 C25.5 41.5 21.5 41 19.5 37.5 C17 39.5 14.5 37.5 14.5 33Z" fill="{p.main}"/>'
        f'<g fill="#5b3a29">{chips}</g>'
        + face(32, 26, gap=6, eye=(2.5, 3.1), cheek_dx=10.8, cheek_dy=4.5, mouth_dy=4.4))


def macaron(p=P("teal")):
    ruffle = lambda y: "".join(f'<circle cx="{x}" cy="{y}" r="2.1"/>' for x in range(13, 53, 3))
    return svg(p,
        f'<path d="M10 41 C10 38 13 37 16 37 H48 C51 37 54 38 54 41 C54 50 45 55 32 55 C19 55 10 50 10 41Z" fill="{p.main}"/>'
        f'<g fill="{p.dark}" opacity=".55">{ruffle(38.5)}</g>'
        '<rect x="11" y="31.5" width="42" height="7" rx="3.5" fill="#fffaf0"/>'
        f'<g fill="{p.dark}" opacity=".55">{ruffle(32.5)}</g>'
        f'<path d="M9 28 C9 17 19 10 32 10 C45 10 55 17 55 28 C55 31 52 32.5 49 32.5 H15 C12 32.5 9 31 9 28Z" fill="{p.main}"/>'
        f'<ellipse cx="18" cy="17.5" rx="4" ry="1.8" fill="{p.light}" opacity=".8" transform="rotate(-28 18 17.5)"/>'
        + face(32, 21.5, gap=6.5, eye=(2.4, 3), cheek_dx=11, cheek_dy=4.2, mouth_dy=4.1))


def popsicle(p=P("teal")):
    return svg(p,
        f'<rect x="28.5" y="42" width="7" height="18" rx="3.5" fill="{WOOD}"/>'
        f'<path d="M17 22 C17 13 23 7 32 7 C41 7 47 13 47 22 V44 C47 47 45 49 42 49 H22 C19 49 17 47 17 44Z" fill="{p.main}"/>'
        f'<path d="M17 22 C17 13 23 7 32 7 C41 7 47 13 47 22 V23 C45 26 43 22 41 25 C39 29 36 24 34 26 C32 28 29 23 27 26 '
        f'C25 29 22 24 20 26 C18.5 27 17 25 17 24Z" fill="{p.light}"/>'
        f'<circle cx="47.5" cy="13" r="4.5" fill="{p.bg}"/><circle cx="49" cy="20" r="3.6" fill="{p.bg}"/>'
        f'<rect x="20" y="30" width="2.6" height="13" rx="1.3" fill="{p.light}" opacity=".7"/>'
        + face(32, 34, gap=6, eye=(2.5, 3.1), cheek_dx=10, cheek_dy=4.5, mouth="open", mouth_dy=4.4))


def gummybear(p=P("teal")):
    return svg(p,
        f'<g fill="{p.main}">'
        '<circle cx="21.5" cy="12" r="5"/><circle cx="42.5" cy="12" r="5"/>'
        '<ellipse cx="17.5" cy="41" rx="4.6" ry="6.5" transform="rotate(35 17.5 41)"/>'
        '<ellipse cx="46.5" cy="41" rx="4.6" ry="6.5" transform="rotate(-35 46.5 41)"/>'
        '<ellipse cx="23.5" cy="54.5" rx="6.3" ry="4.6"/><ellipse cx="40.5" cy="54.5" rx="6.3" ry="4.6"/>'
        '<ellipse cx="32" cy="44" rx="13.5" ry="12.5"/>'
        '<circle cx="32" cy="23.5" r="13.5"/></g>'
        f'<g fill="{p.dark}" opacity=".45"><circle cx="21.5" cy="12" r="2.4"/><circle cx="42.5" cy="12" r="2.4"/></g>'
        f'<ellipse cx="32" cy="45.5" rx="7" ry="6.5" fill="{p.light}" opacity=".6"/>'
        '<ellipse cx="23.5" cy="16" rx="2.6" ry="1.4" fill="#fff" opacity=".75" transform="rotate(-40 23.5 16)"/>'
        + face(32, 23.5, gap=5.2, eye=(2.3, 2.8), cheek_dx=8.6, cheek_dy=4, mouth="w", mouth_dy=3.9))


def ramune(p=P("sky")):
    return svg(p,
        f'<rect x="26.5" y="5" width="11" height="6" rx="2" fill="{p.dark}"/>'
        f'<g fill="{p.main}"><rect x="27.5" y="10" width="9" height="22"/><circle cx="32" cy="22" r="6.8"/>'
        '<path d="M20 34 C21 29 26 27 32 27 C38 27 43 29 44 34Z"/><rect x="18.5" y="31" width="27" height="27" rx="8.5"/></g>'
        f'<circle cx="32" cy="22" r="4.4" fill="{p.light}"/><circle cx="30.6" cy="20.6" r="1.4" fill="#fff"/>'
        '<rect x="21.5" y="34" width="2.6" height="17" rx="1.3" fill="#fff" opacity=".55"/>'
        '<g fill="#fff" opacity=".7"><circle cx="39.5" cy="52" r="1.5"/><circle cx="36" cy="54.5" r="1"/><circle cx="41" cy="47.5" r="1"/></g>'
        + face(32, 40.5, gap=6, eye=(2.5, 3.1), cheek_dx=9.6, cheek_dy=4.4, mouth_dy=4.3))


def shavedice(p=P("sky")):
    return svg(p,
        f'<path d="M15 40 H49 L45 55 C44.5 57 43 58 41 58 H23 C21 58 19.5 57 19 55Z" fill="{p.dark}"/>'
        f'<path d="M17 46 H47" stroke="{p.light}" stroke-width="2" opacity=".7"/>'
        f'<path d="M12 41 C11 26 20 13 32 13 C44 13 53 26 52 41Z" fill="{p.light}"/>'
        f'<path d="M14.5 27 C18.5 18 25 13 32 13 C39 13 45.5 18 49.5 27 C48 30.5 45.5 28 44 30.5 C42.5 34.5 39.5 34 38.5 30 '
        f'C37 27.5 34.5 28.5 33.5 30.5 C32 33 29 33 28 30 C26.5 27 23.5 28 22 30.5 C20.5 33.5 17.5 33 17 29.5 C16.5 28 15.5 28 14.5 27Z" fill="{p.main}"/>'
        '<rect x="12" y="38.5" width="40" height="4" rx="2" fill="#fff"/>'
        '<ellipse cx="38" cy="18" rx="3" ry="1.5" fill="#fff" opacity=".7" transform="rotate(25 38 18)"/>'
        + face(32, 33.5, gap=5.6, eye=(2.3, 2.9), blush_op=.75, cheek_dx=10, cheek_dy=1.5, mouth="w", mouth_dy=-0.2 + 3.8))


def blueberry(p=P("blue")):
    crown = "M32 11 L34.3 14.8 L38.6 14.2 L36.2 17.7 L37.8 21.6 L32 20.2 L26.2 21.6 L27.8 17.7 L25.4 14.2 L29.7 14.8Z"
    return svg(p,
        f'<path d="M33 13 C34 9 37 7 40 6.5" fill="none" stroke="{STEM}" stroke-width="2.2" stroke-linecap="round"/>'
        f'<path d="M38 7 C42 2.5 49 3.5 51 7.5 C46 10 41 10 38 7Z" fill="{LEAF}"/>'
        f'<circle cx="32" cy="35" r="22" fill="{p.main}"/>'
        f'<path d="{crown}" fill="{p.deep}"/>'
        f'<ellipse cx="18" cy="26" rx="2.4" ry="4.6" fill="{p.light}" opacity=".6" transform="rotate(35 18 26)"/>'
        + face(32, 37, gap=6.5, eye=(2.6, 3.2), cheek_dx=11.5, cheek_dy=4.6, mouth_dy=4.5))


def lollipop(p=P("blue")):
    swirl = "M32 25 A2.5 2.5 0 0 1 37 25 A5 5 0 0 1 27 25 A7.5 7.5 0 0 1 42 25 A10 10 0 0 1 22 25 A12.5 12.5 0 0 1 47 25 A15 15 0 0 1 17 25"
    return svg(p,
        '<rect x="30" y="38" width="4" height="22" rx="2" fill="#fff"/>'
        f'<path d="M32 47 L24.5 43 C23.5 42.5 22.5 43 22.5 44.5 V49.5 C22.5 51 23.5 51.5 24.5 51 Z M32 47 L39.5 43 C40.5 42.5 41.5 43 41.5 44.5 '
        f'V49.5 C41.5 51 40.5 51.5 39.5 51Z" fill="{p.dark}"/><circle cx="32" cy="47" r="2.4" fill="{p.dark}"/>'
        f'<circle cx="32" cy="25" r="19" fill="{p.main}"/>'
        f'<path d="{swirl}" fill="none" stroke="{p.light}" stroke-width="3" stroke-linecap="round" opacity=".8"/>'
        + face(32, 25.5, gap=6.5, eye=(2.6, 3.2), cheek_dx=11, cheek_dy=4.6, mouth_dy=4.5))


def cupcake(p=P("blue")):
    return svg(p,
        f'<path d="M15 37 H49 L45 56 C44.6 57.5 43.5 58 42 58 H22 C20.5 58 19.4 57.5 19 56Z" fill="{p.dark}"/>'
        f'<path d="M22.5 42 L24 57 M29 42 L29.5 57.5 M35 42 L34.5 57.5 M41.5 42 L40 57" stroke="{p.main}" stroke-width="1.8" stroke-linecap="round"/>'
        f'<g fill="{p.main}"><circle cx="17.5" cy="36" r="6"/><circle cx="46.5" cy="36" r="6"/><circle cx="25" cy="38.5" r="6"/>'
        '<circle cx="39" cy="38.5" r="6"/><circle cx="32" cy="39.5" r="6"/><ellipse cx="32" cy="29" rx="17" ry="11"/>'
        '<ellipse cx="32" cy="19" rx="10.5" ry="7.5"/></g>'
        f'<path d="M24 19.5 C26 22 38 22 40 19.5" fill="none" stroke="{p.light}" stroke-width="1.6" stroke-linecap="round" opacity=".8"/>'
        '<path d="M32 8 C33 5 35 4 37 4" fill="none" stroke="#4d8b3a" stroke-width="1.6" stroke-linecap="round"/>'
        '<circle cx="32" cy="10.5" r="4.2" fill="#ef4444"/><circle cx="30.8" cy="9.3" r="1.2" fill="#fff" opacity=".85"/>'
        '<g stroke="#fff" stroke-width="1.6" stroke-linecap="round">'
        '<path d="M24 16 l1.6 -1"/><path d="M40 15.5 l-1.6 -1"/><path d="M19 28 l1 1.4"/><path d="M45 27 l-1 1.4"/></g>'
        + face(32, 30, gap=6.5, eye=(2.6, 3.2), cheek_dx=11, cheek_dy=4.5, mouth="open", mouth_dy=4.6))


def grapes(p=P("purple")):
    grape = lambda x, y, r: (f'<circle cx="{x}" cy="{y}" r="{r}" fill="{p.main}" stroke="{p.dark}" stroke-width="1.2"/>'
                             f'<circle cx="{x - r * .4:.1f}" cy="{y - r * .4:.1f}" r="{r * .22:.1f}" fill="{p.light}" opacity=".8"/>')
    back = [(17, 22, 7.5), (32, 19, 7.5), (47, 22, 7.5), (14, 35, 6.5), (50, 35, 6.5), (21, 47, 7.5), (43, 47, 7.5), (32, 54.5, 6.5)]
    return svg(p,
        '<path d="M32 14 C32 9.5 34 7 37 5" fill="none" stroke="#6b4226" stroke-width="2.6" stroke-linecap="round"/>'
        f'<path d="M33 11 C29.5 4.5 20 4 16.5 8.5 C22 13 28 14 33 11Z" fill="{LEAF}"/>'
        + "".join(grape(*g) for g in back)
        + f'<circle cx="32" cy="35" r="13" fill="{p.main}" stroke="{p.dark}" stroke-width="1.2"/>'
        + face(32, 34.5, gap=5.2, eye=(2.4, 3), cheek_dx=8.4, cheek_dy=4, mouth_dy=4))


def bubbletea(p=P("purple")):
    pearls = "".join(f'<circle cx="{x}" cy="{y}" r="2.6"/>' for x, y in
                     ((24, 53.5), (29.5, 54.5), (35, 54.5), (40.5, 53.5), (21.5, 48.5), (27, 49.5), (32.5, 49.8), (38, 49.5), (43, 48.5)))
    return svg(p,
        f'<rect x="35" y="3" width="5" height="20" rx="2.5" fill="{p.dark}" transform="rotate(14 37.5 13)"/>'
        f'<path d="M15.5 20 H48.5 L44.8 54.5 C44.4 57 42.5 58.5 40 58.5 H24 C21.5 58.5 19.6 57 19.2 54.5Z" fill="{p.main}"/>'
        f'<g fill="{p.deep}">{pearls}</g>'
        f'<rect x="13" y="17" width="38" height="5.5" rx="2.75" fill="{p.light}"/>'
        '<rect x="18.5" y="25" width="2.4" height="15" rx="1.2" fill="#fff" opacity=".5"/>'
        + face(32, 32.5, gap=6, eye=(2.5, 3.1), cheek_dx=10, cheek_dy=4.4, mouth="w", mouth_dy=4.3))


def donut(p=P("pink")):
    sprinkles = "".join(f'<rect x="{x - 2}" y="{y - .8}" width="4" height="1.6" rx=".8" fill="{c}" transform="rotate({r} {x} {y})"/>'
                        for x, y, r, c in ((17, 28, 30, "#fff"), (22, 21, -40, "#ffe08a"), (42, 20, 35, "#fff"),
                                           (47, 27, -25, "#a5d8ff"), (27, 17, 10, "#a5d8ff"), (37, 16.5, -15, "#ffe08a")))
    return svg(p,
        '<ellipse cx="32" cy="37" rx="25" ry="19" fill="#e8b273"/>'
        f'<path d="M9 33 C9 22 20 16 32 16 C44 16 55 22 55 33 C55 38 52.5 41 50.5 40 C48.5 44 45 46 43 43 C40 47.5 36 49 33.5 46 '
        f'C30.5 49 25.5 48.5 23.5 45 C20.5 47 16.5 45 15.5 41 C12.5 42 9 39 9 33Z" fill="{p.main}"/>'
        '<ellipse cx="32" cy="24.5" rx="7.5" ry="3.8" fill="#c98b4a"/>'
        f'<ellipse cx="32" cy="23.6" rx="6.2" ry="2.6" fill="{p.bg}"/>'
        f'{sprinkles}'
        + face(32, 33.5, gap=6.5, eye=(2.5, 3.1), cheek_dx=11.5, cheek_dy=4.5, mouth_dy=4.4))


def cookie(p=P("brown")):
    chips = "".join(f'<ellipse cx="{x}" cy="{y}" rx="2.6" ry="2" transform="rotate({r} {x} {y})"/>'
                    for x, y, r in ((22, 22, 20), (34, 17, -15), (44.5, 28.5, 40), (15.5, 33, -30), (23, 48.5, 10), (36.5, 50, -25), (46, 43, 15)))
    return svg(p,
        f'<circle cx="32" cy="33" r="24" fill="{p.main}" stroke="{p.dark}" stroke-width="1.5"/>'
        f'<g fill="{p.bg}"><circle cx="50" cy="17" r="5.5"/><circle cx="44.5" cy="13" r="4"/><circle cx="53.5" cy="24" r="4"/></g>'
        f'<g fill="{p.deep}">{chips}</g>'
        + face(31, 34, gap=6.5, eye=(2.6, 3.2), cheek_dx=11, cheek_dy=4.6, mouth="open", mouth_dy=4.6))


def toast(p=P("brown")):
    return svg(p,
        f'<path d="M14 29 C7 28 7 11 21 10.5 C25 7.5 39 7.5 43 10.5 C57 11 57 28 50 29 V52 C50 55 48 57 45 57 H19 C16 57 14 55 14 52Z" fill="{p.main}"/>'
        f'<path d="M17.5 27 C12.5 25.5 12.5 14.5 23 14 C26.5 11.5 37.5 11.5 41 14 C51.5 14.5 51.5 25.5 46.5 27 V51 '
        f'C46.5 52.5 45.5 53.5 44 53.5 H20 C18.5 53.5 17.5 52.5 17.5 51Z" fill="{p.light}"/>'
        '<rect x="25.5" y="17" width="13" height="9.5" rx="2.6" fill="#ffe08a"/><rect x="27" y="18.5" width="5.5" height="2.4" rx="1.2" fill="#fff6c8"/>'
        + face(32, 37, gap=6.5, eye=(2.6, 3.2), cheek_dx=10.2, cheek_dy=4.6, mouth_dy=4.5))


def dumpling(p=P("gray")):
    return svg(p,
        '<path d="M25 11 q-2 -2.5 0 -5 M39 11 q-2 -2.5 0 -5" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" opacity=".9"/>'
        f'<ellipse cx="32" cy="52" rx="22" ry="6" fill="{p.main}"/>'
        f'<path d="M8 44 C7 29 18 16 32 16 C46 16 57 29 56 44 C56 50.5 48 53 32 53 C16 53 8 50.5 8 44Z" fill="{p.light}"/>'
        f'<path d="M32 17 C27 19 22 22 19 27 M32 17 C29.5 20 27.5 23 27 27.5 M32 17 C34.5 20 36.5 23 37 27.5 M32 17 C37 19 42 22 45 27" '
        f'fill="none" stroke="{p.main}" stroke-width="1.6" stroke-linecap="round" opacity=".7"/>'
        f'<circle cx="32" cy="16.5" r="2.6" fill="{p.light}" stroke="{p.main}" stroke-width="1.2" stroke-opacity=".7"/>'
        + face(32, 37.5, gap=6.5, eye=(2.6, 3.2), cheek_dx=11.5, cheek_dy=4.6, mouth="open", mouth_dy=4.6))


ICONS = {f.__name__: f() for f in [
    strawberry, cherries, mushroom, carrot, pumpkin, banana, corn, avocado,
    pear, kiwi, peapod, broccoli, pickle, icecream, macaron, popsicle,
    gummybear, ramune, shavedice, blueberry, lollipop, cupcake, eggplant, grapes,
    bubbletea, watermelon, donut, cookie, toast, onigiri, dumpling]}

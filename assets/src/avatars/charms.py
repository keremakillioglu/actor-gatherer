"""Charms: Japanese lucky things and folk figures. Daruma, omamori and kokeshi come in every hue (ICONS:
<name>-<hue>); the rest each in its own, the default of its `p`."""

from kit import CREAM, INK, PALETTE, P, face, shine, svg

SKIN = "#fff1e3"


def daruma(p):
    return svg(p,
        f'<path d="M32 8 C46 8 55 20 55 34 C55 48 45.5 57 32 57 C18.5 57 9 48 9 34 C9 20 18 8 32 8Z" fill="{p.main}"/>'
        f'<ellipse cx="32" cy="30.5" rx="14.5" ry="12.5" fill="{CREAM}"/>'
        f'<path d="M21 23.5 q4 -3 8 -.6 M43 23.5 q-4 -3 -8 -.6" fill="none" stroke="{p.deep}" stroke-width="2.4" stroke-linecap="round"/>'
        + face(32, 30, gap=6, mouth="smile", mouth_dy=4.6, cheek_dx=9.2, cheek_dy=4)
        + f'<path d="M18 46.5 Q25 51.5 32 47.5 Q39 51.5 46 46.5" fill="none" stroke="{p.light}" stroke-width="2.4" stroke-linecap="round"/>')


def omamori(p):
    return svg(p,
        f'<path d="M32 13 C28 7 24 9 26.5 12 M32 13 C36 7 40 9 37.5 12" fill="none" stroke="{p.dark}" stroke-width="2" stroke-linecap="round"/>'
        f'<path d="M30 13 L27 20 M34 13 L37 20" stroke="{p.dark}" stroke-width="2" stroke-linecap="round"/>'
        f'<path d="M17 21 L23 14 H41 L47 21 V52 C47 55 45 57 42 57 H22 C19 57 17 55 17 52Z" fill="{p.main}"/>'
        f'<rect x="21.5" y="40" width="21" height="13" rx="2.5" fill="{p.light}"/>'
        f'<path d="M32 42.5 l1.1 2.6 l2.8 .2 l-2.1 1.8 l.7 2.7 l-2.5 -1.5 l-2.5 1.5 l.7 -2.7 l-2.1 -1.8 l2.8 -.2z" fill="{p.main}"/>'
        f'<circle cx="32" cy="14.5" r="2.3" fill="{p.dark}"/>'
        + shine(22, 25, rx=1.4, ry=4, rot=0, op=.3)
        + face(32, 29.5, gap=6.5, mouth="smile", mouth_dy=3.4, cheek_dx=9.6, cheek_dy=3.6))


def kokeshi(p):
    return svg(p,
        f'<path d="M20.5 41 C18.5 47 18.5 53 20 58.5 L44 58.5 C45.5 53 45.5 47 43.5 41Z" fill="{p.main}"/>'
        f'<path d="M24.5 41 L32 49 L39.5 41" fill="none" stroke="{p.light}" stroke-width="2.2" stroke-linejoin="round"/>'
        f'<g fill="{p.light}"><circle cx="24.5" cy="53" r="1.8"/><circle cx="39.5" cy="53" r="1.8"/><circle cx="32" cy="55.5" r="1.4"/></g>'
        f'<circle cx="32" cy="27" r="15" fill="{SKIN}"/>'
        f'<path d="M15.5 34 C14.5 18 21.5 10 32 10 C42.5 10 49.5 18 48.5 34 L44.5 34 C44.5 28 43.5 24.5 41.5 22.5 L22.5 22.5 C20.5 24.5 19.5 28 19.5 34Z" fill="{INK}"/>'
        f'<g fill="{p.main}"><circle cx="45" cy="13" r="2.4"/><circle cx="48.4" cy="15.4" r="2.4"/><circle cx="47.2" cy="19.2" r="2.4"/>'
        f'<circle cx="43.2" cy="19.2" r="2.4"/><circle cx="41.8" cy="15.4" r="2.4"/></g><circle cx="45" cy="16.6" r="1.4" fill="{p.light}"/>'
        + face(32, 29, gap=5.6, r=2, mouth="smile", mouth_dy=3.6, cheek_dx=8.3, cheek_dy=3.6))


def maneki_neko(p=P("yellow")):
    return svg(p,
        f'<path d="M14 30 L16 11 L28 19 Z M50 30 L48 11 L36 19 Z" fill="{CREAM}"/>'
        f'<path d="M48 11 L36 19 L50 30Z" fill="{p.main}"/>'
        f'<path d="M17.8 24 L18.7 15.5 L24.5 19.5 Z" fill="{p.light}"/>'
        f'<ellipse cx="32" cy="35" rx="20" ry="17" fill="{CREAM}"/>'
        f'<path d="M37.5 18.6 C45 17.6 51.3 23 51.6 31 C45.5 30.6 40.5 26.5 37.5 18.6Z" fill="{p.main}"/>'
        f'<path d="M17 47.5 Q32 55 47 47.5" fill="none" stroke="{p.dark}" stroke-width="3" stroke-linecap="round"/>'
        f'<circle cx="32" cy="52" r="3.8" fill="{p.main}" stroke="{p.dark}" stroke-width="1.2"/>'
        f'<path d="M30 52.4 h4" stroke="{p.dark}" stroke-width="1"/>'
        f'<path d="M8.5 31 C7 24 8 17.5 12.5 16.5 C17 15.5 18.5 22 17.5 31Z" fill="{CREAM}" stroke="{p.bg}" stroke-width="1.6"/>'
        f'<path d="M10 20.5 v2.4 M12.8 19.6 v2.4 M15.6 20.5 v2.4" stroke="{p.main}" stroke-width="1.3" stroke-linecap="round"/>'
        + face(32, 36, gap=7.5, mouth="w", mouth_dy=3.6, cheek_dy=4)
        + f'<path d="M15 37 h-5 M15 40.5 l-4.5 1.5 M49 37 h5 M49 40.5 l4.5 1.5" stroke="{p.dark}" stroke-width="1" stroke-linecap="round" opacity=".7"/>')


def kappa(p=P("green")):
    return svg(p,
        f'<circle cx="32" cy="36" r="20" fill="{p.main}"/>'
        f'<path d="M12.5 31 L15.5 22.5 L19.5 26.5 L22.5 18 L26.5 23.5 L32 15.5 L37.5 23.5 L41.5 18 L44.5 26.5 L48.5 22.5 L51.5 31 C46 26 18 26 12.5 31Z" fill="{p.dark}"/>'
        f'<ellipse cx="32" cy="18.5" rx="10" ry="4.2" fill="#effff4" stroke="{p.dark}" stroke-width="1.6"/>'
        + face(32, 37, gap=8, mouth=None, cheek_dy=4.5)
        + f'<path d="M27.5 42 Q32 39.5 36.5 42 Q32 46 27.5 42Z" fill="#fde68a" stroke="{p.dark}" stroke-width="1" stroke-linejoin="round"/>')


def furin(p=P("teal")):
    return svg(p,
        f'<path d="M32 3 V10" stroke="{p.dark}" stroke-width="1.6" stroke-linecap="round"/>'
        f'<path d="M14 35 C14 20 21.5 10 32 10 C42.5 10 50 20 50 35 C50 37 46 38 32 38 C18 38 14 37 14 35Z" fill="{p.light}" opacity=".9"/>'
        f'<path d="M16.5 26 Q32 30 47.5 26" fill="none" stroke="{p.main}" stroke-width="2.4" stroke-linecap="round"/>'
        f'<g fill="{p.main}"><circle cx="21" cy="17.5" r="1.6"/><circle cx="43" cy="17.5" r="1.6"/></g>'
        + shine(21, 22, rx=1.6, ry=5, rot=20, op=.6)
        + f'<path d="M32 38 V45" stroke="{p.dark}" stroke-width="1.3"/>'
        f'<path d="M27 45 H37 V58 L32 55.5 L27 58Z" fill="{p.main}"/>'
        f'<path d="M29.5 48.5 q2.5 2 5 0" fill="none" stroke="{p.light}" stroke-width="1.2" stroke-linecap="round"/>'
        + face(32, 31, gap=6.5, mouth="smile", mouth_dy=3, cheek_dx=10, cheek_dy=2.6))


def teru_teru(p=P("sky")):
    return svg(p,
        f'<path d="M32 4 V12" stroke="{p.dark}" stroke-width="1.6" stroke-linecap="round"/>'
        f'<path d="M23 34 C18 41 13.5 49 14.5 54 Q19.5 51.5 23 55 Q27.5 51 32 55 Q36.5 51 41 55 Q44.5 51.5 49.5 54 C50.5 49 46 41 41 34Z" fill="#fff"/>'
        f'<circle cx="32" cy="24" r="13" fill="#fff"/>'
        f'<path d="M24 36.5 Q32 39.5 40 36.5" fill="none" stroke="{p.main}" stroke-width="3" stroke-linecap="round"/>'
        f'<path d="M32 38 l-5 -3.4 v7 z M32 38 l5 -3.4 v7 z" fill="{p.main}" stroke="{p.main}" stroke-width="1.2" stroke-linejoin="round"/>'
        f'<circle cx="32" cy="38" r="1.8" fill="{p.dark}"/>'
        + face(32, 24.5, gap=5.6, mouth="smile", mouth_dy=3.6, cheek_dx=8.6))


def yuki_daruma(p=P("blue")):
    return svg(p,
        f'<circle cx="32" cy="45" r="14" fill="#fff"/>'
        f'<circle cx="32" cy="27" r="12.5" fill="#fff"/>'
        f'<path d="M21.5 18 L42.5 18 L39.5 6.5 L24.5 6.5Z" fill="{p.main}"/>'
        f'<path d="M20.5 18.5 H43.5" stroke="{p.dark}" stroke-width="2.6" stroke-linecap="round"/>'
        f'<path d="M21 38 Q32 42.5 43 38" fill="none" stroke="{p.main}" stroke-width="4" stroke-linecap="round"/>'
        f'<path d="M38 40 l2.5 8" stroke="{p.main}" stroke-width="4" stroke-linecap="round"/>'
        + face(32, 28.5, gap=5.4, mouth="smile", mouth_dy=3.6, cheek_dx=8.6)
        + f'<g fill="{p.light}"><circle cx="32" cy="47" r="1.8"/><circle cx="32" cy="53" r="1.8"/></g>')


def uchiwa(p=P("purple")):
    return svg(p,
        f'<rect x="30" y="40" width="4" height="20" rx="2" fill="{p.dark}"/>'
        f'<circle cx="32" cy="27" r="19" fill="{p.main}"/>'
        f'<g stroke="{p.light}" stroke-width="1" opacity=".55">'
        + "".join(f'<line x1="32" y1="44" x2="{32 + 18 * c:.1f}" y2="{27 - 18 * s:.1f}"/>'
                  for c, s in ((-.97, .26), (-.71, .71), (-.26, .97), (.26, .97), (.71, .71), (.97, .26)))
        + '</g>'
        f'<path d="M15 33 C20 30 26 36 32 33 C38 30 44 36 49 33 C47 41 40 46 32 46 C24 46 17 41 15 33Z" fill="{p.light}"/>'
        f'<path d="M41 16 l1 2.3 l2.4 .3 l-1.8 1.6 l.5 2.4 l-2.1 -1.2 l-2.1 1.2 l.5 -2.4 l-1.8 -1.6 l2.4 -.3z" fill="#fff" opacity=".8"/>'
        + face(32, 24.5, gap=6.5, mouth="smile", mouth_dy=3.4, cheek_dy=3.6))


def sakura(p=P("pink")):
    petal = "M0 0 C-9.5 -4 -10.5 -16.5 -4.2 -21 L0 -17.6 L4.2 -21 C10.5 -16.5 9.5 -4 0 0Z"
    return svg(p,
        "".join(f'<path d="{petal}" transform="translate(32 33.5) rotate({a})" fill="{p.main}"/>' for a in (0, 72, 144, 216, 288))
        + f'<circle cx="32" cy="33.5" r="10.5" fill="{p.light}"/>'
        + f'<g fill="{p.dark}"><circle cx="32" cy="20.5" r="1.3"/><circle cx="44.3" cy="29.5" r="1.3"/><circle cx="19.7" cy="29.5" r="1.3"/>'
        '<circle cx="39.6" cy="44" r="1.3"/><circle cx="24.4" cy="44" r="1.3"/></g>'
        + face(32, 33, gap=4.6, r=1.9, mouth="smile", mouth_dy=3.2, blush=p.main, cheek_dx=7.2, cheek_dy=3.2))


def chochin(p=P("red")):
    return svg(p,
        f'<path d="M32 3 V9" stroke="{INK}" stroke-width="1.6" stroke-linecap="round"/>'
        f'<rect x="22" y="8" width="20" height="5" rx="1.5" fill="{INK}"/>'
        f'<rect x="22" y="51" width="20" height="5" rx="1.5" fill="{INK}"/>'
        f'<path d="M32 56 V61" stroke="{p.dark}" stroke-width="2.2" stroke-linecap="round"/>'
        f'<path d="M23 12.5 C10 16 8 25 8 32 C8 39 10 48 23 51.5 H41 C54 48 56 39 56 32 C56 25 54 16 41 12.5Z" fill="{p.main}"/>'
        f'<g fill="none" stroke="{p.dark}" stroke-width="1.2" opacity=".55">'
        '<path d="M14.5 19 H49.5 M10 25.5 H54 M10 38.5 H54 M14.5 45 H49.5"/></g>'
        + shine(17, 24, rx=2, ry=5, rot=10, op=.3)
        + face(32, 30, gap=7.5, mouth="smile", mouth_dy=3.8, blush="#ffc4cc", blush_op=.95, cheek_dy=3.8))


def kitsune(p=P("red")):
    return svg(p,
        f'<path d="M11.5 33 L14 8.5 L29.5 20 Z M52.5 33 L50 8.5 L34.5 20 Z" fill="#fff"/>'
        f'<path d="M16 26 L17 14.5 L25 20.5 Z M48 26 L47 14.5 L39 20.5 Z" fill="{p.main}"/>'
        f'<path d="M10.5 30 C10.5 22 20 17 32 17 C44 17 53.5 22 53.5 30 C53.5 40 44 46 37 51 C35 53 33.5 55 32 55 C30.5 55 29 53 27 51 C20 46 10.5 40 10.5 30Z" fill="#fff"/>'
        f'<path d="M15 33 C18 28 23 28 27 31.5 M49 33 C46 28 41 28 37 31.5" fill="none" stroke="{p.main}" stroke-width="3" stroke-linecap="round"/>'
        f'<path d="M32 19.5 C34 22 34 25 32 27 C30 25 30 22 32 19.5Z" fill="{p.main}"/>'
        f'<path d="M26 22.5 q-2 -1 -4 0 M38 22.5 q2 -1 4 0" fill="none" stroke="{p.main}" stroke-width="1.6" stroke-linecap="round"/>'
        + face(32, 35, gap=7.5, mouth=None, cheek_dx=12.5, cheek_dy=5)
        + f'<ellipse cx="32" cy="45.5" rx="2.3" ry="1.6" fill="{INK}"/>'
        f'<path d="M29.4 48 q1.3 1.7 2.6 0 q1.3 1.7 2.6 0" fill="none" stroke="{p.main}" stroke-width="1.5" stroke-linecap="round"/>')


EVERY_HUE = [daruma, omamori, kokeshi]
SINGLE = [maneki_neko, kappa, furin, teru_teru, yuki_daruma, uchiwa, sakura, chochin, kitsune]
ICONS = {**{f"{f.__name__}-{hue}": f(P(hue)) for f in EVERY_HUE for hue in PALETTE},
         **{f.__name__.replace("_", "-"): f() for f in SINGLE}}

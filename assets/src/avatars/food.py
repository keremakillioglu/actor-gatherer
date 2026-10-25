"""Food: East Asian sweets, dishes and fruit, each in its own hue, the default of its `p`."""

from kit import CREAM, INK, P, face, moving, shine, svg

LEAF = "#5a9e3a"
WOOD = "#e3b778"
NORI = "#24313a"


def nigiri(p=P("orange")):
    return svg(p,
        '<rect x="12.5" y="30" width="39" height="23" rx="11" fill="#fff"/>'
        f'<path d="M8.5 33 C8.5 23.5 18 19.5 32 19.5 C46 19.5 55.5 23.5 55.5 33 C55.5 36.5 50 38 32 38 C14 38 8.5 36.5 8.5 33Z" fill="{p.main}"/>'
        f'<path d="M17 34 L23 22.5 M27 36 L33 21 M37.5 36 L43 22 M47 34.5 L51 26.5" stroke="{p.light}" stroke-width="2.2" stroke-linecap="round"/>'
        + face(32, 44, gap=7, mouth="smile", mouth_dy=3.4, cheek_dx=10.6, cheek_dy=3.4))


def dorayaki(p=P("orange")):
    return svg(p,
        f'<ellipse cx="32" cy="45" rx="22" ry="9" fill="{p.dark}"/>'
        f'<ellipse cx="32" cy="41.5" rx="21" ry="5.5" fill="#5b2a1e"/>'
        f'<path d="M10 37 C10 25 20 18 32 18 C44 18 54 25 54 37 C54 40.5 44 42 32 42 C20 42 10 40.5 10 37Z" fill="{p.main}"/>'
        f'<path d="M14 30 C17 23 25 20 32 20 C39 20 47 23 50 30 C45 27 38 26 32 26 C26 26 19 27 14 30Z" fill="{p.dark}" opacity=".5"/>'
        + shine(22, 25, rx=3.6, ry=1.8, rot=-15, op=.3)
        + face(32, 32.5, gap=7.5, mouth="smile", mouth_dy=3.4, cheek_dy=3.4))


def mikan(p=P("orange")):
    return svg(p,
        f'<circle cx="32" cy="36" r="19" fill="{p.main}"/>'
        f'<g fill="{p.dark}" opacity=".35"><circle cx="20" cy="30" r=".9"/><circle cx="44" cy="30" r=".9"/><circle cx="18" cy="42" r=".9"/>'
        '<circle cx="46" cy="42" r=".9"/><circle cx="25" cy="49" r=".9"/><circle cx="39" cy="49" r=".9"/></g>'
        + shine(23, 25)
        + f'<circle cx="32" cy="18" r="2.4" fill="{LEAF}"/>'
        f'<path d="M33 17.5 C37 11 45 11 48 14.5 C44 19 37 20 33 17.5Z" fill="{LEAF}"/>'
        + face(32, 37, gap=7.5, mouth="smile", mouth_dy=3.6, cheek_dy=3.8))


def taiyaki(p=P("yellow")):
    return svg(p,
        f'<path d="M7 34 C7 22 19 15.5 31 16 C39.5 16.4 45 21 48 26.5 L57 19.5 C59.5 26.5 59.5 37.5 57 44.5 L48 38 C45 45.5 38.5 51.5 30 51.5 C17 51.5 7 46 7 34Z" fill="{p.main}"/>'
        f'<path d="M33 22.5 C29 29 29 38 33 45" fill="none" stroke="{p.dark}" stroke-width="1.6" stroke-linecap="round" opacity=".75"/>'
        f'<g fill="none" stroke="{p.dark}" stroke-width="1.4" stroke-linecap="round" opacity=".6">'
        '<path d="M37 27 q2.5 2.5 5 0 M37 34 q2.5 2.5 5 0 M37 41 q2.5 2.5 5 0 M42.5 30.5 q2.5 2.5 5 0 M42.5 37.5 q2.5 2.5 5 0"/></g>'
        f'<path d="M51 26 v12 M54.5 24 v16" stroke="{p.dark}" stroke-width="1.3" stroke-linecap="round" opacity=".6"/>'
        + face(19.5, 32, gap=5.5, mouth="o", mouth_dy=3.6, cheek_dx=8.5, cheek_dy=4.2, blush_op=.9))


def bao(p=P("yellow")):
    return svg(p,
        f'<path d="M12 33 C12 21 21 14 32 14 C43 14 52 21 52 33 C52 40 44 43 32 43 C20 43 12 40 12 33Z" fill="{CREAM}"/>'
        f'<path d="M32 15 L28.5 21 M32 15 L32 21.5 M32 15 L35.5 21 M32 15 L24.5 19.5 M32 15 L39.5 19.5" stroke="{p.light}" stroke-width="1.6" stroke-linecap="round"/>'
        f'<rect x="9" y="38" width="46" height="17" rx="5" fill="{p.main}"/>'
        f'<path d="M9.5 44 H54.5 M9.5 49.5 H54.5" stroke="{p.dark}" stroke-width="1.3" opacity=".55"/>'
        f'<path d="M20 38.5 V54.5 M32 38.5 V54.5 M44 38.5 V54.5" stroke="{p.dark}" stroke-width="1.1" opacity=".35"/>'
        + face(32, 29, gap=7.5, mouth="smile", mouth_dy=3.6, cheek_dy=3.8))


def melon_pan(p=P("lime")):
    return svg(p,
        f'<path d="M9.5 41 C9.5 26 19.5 16 32 16 C44.5 16 54.5 26 54.5 41 C54.5 49 45 53.5 32 53.5 C19 53.5 9.5 49 9.5 41Z" fill="{p.main}"/>'
        f'<path d="M9.5 41 C9.5 26 19.5 16 32 16 C44.5 16 54.5 26 54.5 41 C46 45 18 45 9.5 41Z" fill="{p.light}"/>'
        f'<g fill="none" stroke="{p.main}" stroke-width="1.4" opacity=".7">'
        '<path d="M14 30 L30 18.5 M14.5 38 L38 19 M21 42 L46 22 M31 43 L51 29"/>'
        '<path d="M50 30 L34 18.5 M49.5 38 L26 19 M43 42 L18 22 M33 43 L13 29"/></g>'
        + face(32, 46.5, gap=7.5, mouth="smile", mouth_dy=3, cheek_dy=2.8, cheek_dx=12.5))


def edamame(p=P("lime")):
    return svg(p,
        f'<path d="M12 24 C10 19 13 15 17 16 C21 17 22 22 26 24 C30 22 34 22 38 24 C42 26 48 27 52 31 C57 36 55 45 48 46 C42 47 38 44 34 44 C30 44 24 46 19 43 C14 40 13 31 12 24Z" fill="{p.main}"/>'
        f'<circle cx="21" cy="31" r="6.5" fill="{p.light}" opacity=".6"/><circle cx="32" cy="34" r="6.5" fill="{p.light}" opacity=".6"/>'
        f'<circle cx="43.5" cy="36" r="6.5" fill="{p.light}" opacity=".6"/>'
        f'<path d="M12 24 C9 20 9 15 12 12" fill="none" stroke="{p.dark}" stroke-width="2" stroke-linecap="round"/>'
        + face(32, 33.5, gap=6.5, r=2.1, mouth="smile", mouth_dy=3.2, cheek_dx=9.8, cheek_dy=3.4))


def bok_choy(p=P("green")):
    return svg(p,
        f'<path d="M32 40 C18 40 9 30 12 17 C15 11 22 12 24 18 C25 12 29 8 32 8 C35 8 39 12 40 18 C42 12 49 11 52 17 C55 30 46 40 32 40Z" fill="{p.main}"/>'
        f'<path d="M32 12 V36 M22 20 L28 36 M42 20 L36 36" stroke="{p.light}" stroke-width="1.3" stroke-linecap="round" opacity=".8"/>'
        f'<path d="M22 36 C22 46 25 56 32 56 C39 56 42 46 42 36Z" fill="#f4fbe9"/>'
        f'<path d="M28 38 V54 M36 38 V54" stroke="{p.light}" stroke-width="1.2" opacity=".9"/>'
        + face(32, 44, gap=5, r=2, mouth="smile", mouth_dy=3.2, cheek_dx=7.8, cheek_dy=3.2))


def matcha(p=P("green")):
    return svg(p,
        f'<path d="M24 16 q-2.5 -3 0 -6 M32 14 q-2.5 -3 0 -6 M40 16 q-2.5 -3 0 -6" fill="none" stroke="{p.light}" stroke-width="1.8" stroke-linecap="round"/>'
        f'<path d="M9 24 H55 C55 40 45 53 32 53 C19 53 9 40 9 24Z" fill="{p.dark}"/>'
        f'<ellipse cx="32" cy="24" rx="23" ry="5" fill="{p.main}"/>'
        f'<ellipse cx="32" cy="23.6" rx="19" ry="3.4" fill="{p.light}" opacity=".7"/>'
        f'<rect x="22" y="52" width="20" height="4" rx="2" fill="{p.deep}"/>'
        + face(32, 36, gap=7.5, ink=p.light, mouth="smile", mouth_dy=3.8, cheek_dy=4, blush_op=.85))


def ramune(p=P("teal")):
    return svg(p,
        f'<rect x="26" y="5.5" width="12" height="6" rx="2" fill="{p.dark}"/>'
        f'<path d="M27 11 H37 V16 C37 19 41 21 41 26 C41 29 38 30 38 33 V33 H26 V33 C26 30 23 29 23 26 C23 21 27 19 27 16Z" fill="{p.light}" opacity=".9"/>'
        f'<circle cx="32" cy="22.5" r="3.6" fill="#fff"/><circle cx="31" cy="21.5" r="1.1" fill="{p.light}"/>'
        f'<path d="M22 33 H42 C45 36 46 40 46 44 V52 C46 56 43 58 40 58 H24 C21 58 18 56 18 52 V44 C18 40 19 36 22 33Z" fill="{p.main}"/>'
        f'<rect x="18" y="39" width="28" height="9" fill="{p.dark}" opacity=".35"/>'
        + shine(22.5, 46, rx=1.4, ry=5, rot=0, op=.4)
        + face(32, 44, gap=6.5, mouth="smile", mouth_dy=3.4, cheek_dx=9.6, cheek_dy=3.4))


def kakigori(p=P("blue")):
    return svg(p,
        '<path d="M15 40 H49 L44 52 C43 55 40 56 37 56 H27 C24 56 21 55 20 52Z" fill="#fff" opacity=".9"/>'
        f'<path d="M15 40 H49 L48 43 H16Z" fill="{p.light}"/>'
        f'<path d="M13 40 C11 32 16 26 21 26 C21 18 27 12 32 12 C37 12 43 18 43 26 C48 26 53 32 51 40Z" fill="#fff"/>'
        f'<path d="M14 36 C14 31 18 28 22 28 C23 22 27 16 32 16 C38 16 42 22 42 28 C46 28 50 31 50 36 C46 38 44 34 40 36 C36 38 34 35 30 37 C26 39 22 35 18 38 C16 39 15 38 14 36Z" fill="{p.main}"/>'
        '<circle cx="32" cy="11.5" r="3.6" fill="#ef4444"/><path d="M32 8 q1 -3 3.5 -3.5" fill="none" stroke="#5a9e3a" stroke-width="1.3" stroke-linecap="round"/>'
        + face(32, 29, gap=6.5, mouth="smile", mouth_dy=3.4, cheek_dy=3.6, blush="#ffc4e1", blush_op=.95))


def boba(p=P("purple")):
    return svg(p,
        f'<path d="M36 4 L33 22" stroke="{p.dark}" stroke-width="3.6" stroke-linecap="round"/>'
        f'<path d="M17 20 C17 13 47 13 47 20Z" fill="#fff" opacity=".85"/>'
        f'<rect x="15" y="19" width="34" height="4" rx="2" fill="#fff"/>'
        f'<path d="M17 23 H47 L44 54 C43.6 57 41 58.5 38 58.5 H26 C23 58.5 20.4 57 20 54Z" fill="{p.light}"/>'
        f'<g fill="{p.deep}"><circle cx="24" cy="53" r="2.5"/><circle cx="29.5" cy="54.5" r="2.5"/><circle cx="35" cy="54" r="2.5"/>'
        '<circle cx="40.3" cy="52.6" r="2.5"/><circle cx="26.5" cy="48.5" r="2.5"/><circle cx="32.5" cy="49.5" r="2.5"/><circle cx="38" cy="48" r="2.5"/></g>'
        + face(32, 34, gap=6.5, mouth="smile", mouth_dy=3.4, cheek_dx=10, cheek_dy=3.6))


def yaki_imo(p=P("purple")):
    return svg(p,
        f'<path d="M9 40 C6 34 10 26 18 23 C27 19.5 38 19 46 22 C53 24.5 58 31 56 37 C54 44 46 47 36 47 C26 47 12 46 9 40Z" fill="{p.main}"/>'
        f'<path d="M46.5 22.2 C53 24.5 58 31 56 37 C54.5 41.5 50 44.5 44.5 46 C47.5 38 48 30 46.5 22.2Z" fill="#fde047"/>'
        f'<path d="M47.5 26 C50 30 50.5 36 48.5 42" fill="none" stroke="#f59e0b" stroke-width="1.3" stroke-linecap="round" opacity=".7"/>'
        f'<path d="M17 28 q3 1 5 -.5 M27 42.5 q3 1 5 -.5 M36 25 q3 1 5 -.5" fill="none" stroke="{p.dark}" stroke-width="1.2" stroke-linecap="round" opacity=".7"/>'
        + shine(18, 30, rx=3.4, ry=1.8, rot=-20, op=.3)
        + face(28, 34, gap=6.5, mouth="smile", mouth_dy=3.4, cheek_dy=3.6, blush="#ffc4e1", blush_op=.95))


def sakura_mochi(p=P("pink")):
    return svg(p,
        f'<path d="M11 40 C11 27 20 19 32 19 C44 19 53 27 53 40 C53 48 44 52 32 52 C20 52 11 48 11 40Z" fill="{p.light}"/>'
        f'<g fill="{p.main}" opacity=".45"><circle cx="20" cy="31" r=".9"/><circle cx="27" cy="25" r=".9"/><circle cx="38" cy="25" r=".9"/>'
        '<circle cx="45" cy="32" r=".9"/><circle cx="17" cy="42" r=".9"/></g>'
        '<path d="M8 47 C14 40 26 44 32 52 C38 44 50 40 56 47 C52 55 42 57 32 57 C22 57 12 55 8 47Z" fill="#7a9a3a"/>'
        '<path d="M16 48 Q24 49 32 55 Q40 49 48 48" fill="none" stroke="#a9c26a" stroke-width="1.1" stroke-linecap="round"/>'
        f'<path d="M32 21 l-2 -3 q2 -2.5 4 0z" fill="{p.main}"/>'
        + face(32, 36, gap=7.5, mouth="smile", mouth_dy=3.6, blush=p.main, blush_op=.6, cheek_dy=3.8))


def peach_bun(p=P("pink")):
    return svg(p,
        f'<path d="M32 12 C40 18 51 26 51 37 C51 47 43 53 32 53 C21 53 13 47 13 37 C13 26 24 18 32 12Z" fill="{CREAM}"/>'
        f'<path d="M32 12 C40 18 51 26 51 37 C51 41 49.5 44 47 46.5 C47 34 41 22 32 12Z" fill="{p.main}" opacity=".55"/>'
        f'<path d="M32 12 C38 17 43 23 44.5 30 C40 25 36 21 32 12Z" fill="{p.main}"/>'
        f'<path d="M32 14 C30 24 30 40 32 52" fill="none" stroke="{p.light}" stroke-width="1.4" stroke-linecap="round"/>'
        f'<path d="M32 53 C26 55 19 55 15 51 C20 48 27 49 32 53Z M32 53 C38 55 45 55 49 51 C44 48 37 49 32 53Z" fill="{LEAF}"/>'
        + face(28, 38, gap=6, mouth="smile", mouth_dy=3.4, blush=p.main, blush_op=.7, cheek_dx=8.6, cheek_dy=3.8))


def ramen(p=P("red")):
    return svg(p,
        f'<path d="M37 6 L22 30 M44 7 L29 30" stroke="{WOOD}" stroke-width="2.6" stroke-linecap="round"/>'
        f'<ellipse cx="32" cy="30" rx="23" ry="6" fill="#fde68a"/>'
        f'<path d="M14 29 q3 -3 6 0 q3 3 6 0 q3 -3 6 0 q3 3 6 0 q3 -3 6 0 q3 3 6 0" fill="none" stroke="#f5c84a" stroke-width="1.6" stroke-linecap="round"/>'
        f'<ellipse cx="42" cy="28" rx="5.5" ry="3.6" fill="#fff"/><ellipse cx="42.6" cy="28.2" rx="2.6" ry="2" fill="#fbbf24"/>'
        '<ellipse cx="22" cy="28" rx="4.6" ry="3.2" fill="#fff"/><path d="M20 28 q2 -2.4 4 0 q-2 1.6 -3 .2" fill="none" stroke="#f472b6" stroke-width="1.1" stroke-linecap="round"/>'
        f'<path d="M8 31 H56 C56 45 46 55 32 55 C18 55 8 45 8 31Z" fill="{p.main}"/>'
        f'<path d="M11 36 H53" stroke="{p.dark}" stroke-width="1.6" opacity=".5"/>'
        f'<rect x="23" y="54" width="18" height="3.5" rx="1.75" fill="{p.dark}"/>'
        + face(32, 42.5, gap=7.5, ink=INK, mouth="smile", mouth_dy=3.6, blush="#ffc4cc", blush_op=.95, cheek_dy=3.6))


def lychee(p=P("red")):
    return svg(p,
        f'<circle cx="32" cy="36" r="19" fill="{p.main}"/>'
        f'<g fill="none" stroke="{p.dark}" stroke-width="1.1" stroke-linejoin="round" opacity=".55">'
        '<path d="M17 28 l3 -2 l3 2 l-3 2z M27 21 l3 -2 l3 2 l-3 2z M37 21 l3 -2 l3 2 l-3 2z M44 28 l3 -2 l3 2 l-3 2z"/>'
        '<path d="M15 39 l3 -2 l3 2 l-3 2z M45 39 l3 -2 l3 2 l-3 2z M22 48 l3 -2 l3 2 l-3 2z M36 48 l3 -2 l3 2 l-3 2z"/></g>'
        + shine(24, 25, op=.3)
        + f'<path d="M32 17 V12" stroke="#6b4226" stroke-width="2" stroke-linecap="round"/>'
        f'<path d="M32 13 C36 8 43 8 46 11 C42 15 36 15 32 13Z" fill="{LEAF}"/>'
        + face(32, 36.5, gap=7.5, mouth="smile", mouth_dy=3.6, blush="#ffc4cc", blush_op=.95, cheek_dy=3.8))


def onigiri(p=P("gray")):
    return svg(p,
        '<path d="M32 10 C36 10 39 13 42 18 L54 40 C57 46 54 54 46 54 L18 54 C10 54 7 46 10 40 L22 18 C25 13 28 10 32 10Z" fill="#fff"/>'
        f'<path d="M22 41 H42 V54 H22Z" fill="{NORI}"/><path d="M24 44 H40" stroke="{p.dark}" stroke-width="1"/>'
        + face(32, 31, gap=6.5, mouth="smile", mouth_dy=3.6, cheek_dy=3.8))


def mitarashi(p=P("brown")):
    balls = [(41.5, 19.5), (23, 45.5), (32.2, 32.5)]          # the middle one last: on top, with the face
    return svg(p,
        f'<path d="M14 61 L51 8" stroke="{WOOD}" stroke-width="2.6" stroke-linecap="round"/>'
        + "".join(f'<circle cx="{x}" cy="{y}" r="9.6" fill="{p.main}"/>'
                  f'<path d="M{x - 8.6} {y + 3.6} C{x - 5} {y + 9.5} {x + 5} {y + 9.5} {x + 8.6} {y + 3.6} C{x + 5} {y + 6.5} {x - 5} {y + 6.5} {x - 8.6} {y + 3.6}Z" fill="{p.light}" opacity=".7"/>'
                  + shine(x - 3.6, y - 4.8, rx=3, ry=1.6, op=.45)
                  for x, y in balls)
        + face(32.2, 33, gap=4.4, r=1.8, mouth="smile", mouth_dy=2.8, cheek_dx=6.6, cheek_dy=2.8))


def mooncake(p=P("brown")):
    import math
    scallops = " ".join(f"M{32 + 19 * math.cos(a):.1f} {35 + 19 * math.sin(a):.1f} m-4.2 0 a4.2 4.2 0 1 0 8.4 0 a4.2 4.2 0 1 0 -8.4 0"
                        for a in (2 * math.pi * i / 14 for i in range(14)))
    return svg(p,
        f'<path d="{scallops}" fill="{p.main}"/>'
        f'<circle cx="32" cy="35" r="19" fill="{p.main}"/>'
        f'<circle cx="32" cy="35" r="14.5" fill="none" stroke="{p.dark}" stroke-width="1.4" opacity=".5"/>'
        f'<path d="M32 22.5 q2.5 3 0 5.5 q-2.5 -2.5 0 -5.5 M32 47.5 q2.5 -3 0 -5.5 q-2.5 2.5 0 5.5" fill="{p.dark}" opacity=".45"/>'
        + shine(24, 26, op=.25)
        + face(32, 35, gap=7, mouth="smile", mouth_dy=3.4, cheek_dy=3.6))


ICONS_FN = [nigiri, dorayaki, mikan, taiyaki, bao, melon_pan, edamame, bok_choy, matcha, ramune, kakigori,
            boba, yaki_imo, sakura_mochi, peach_bun, ramen, lychee, onigiri, mitarashi, mooncake]
# How each moves while its actor works, in the dashboard's Chat view: a move, then an effect round it if
# any (ag_dashboard/avatars/README.md names them all).
MOTIONS = {
    "nigiri": "squish", "dorayaki": "flip", "mikan": "roll", "taiyaki": "swim steam", "bao": "squish steam",
    "melon-pan": "puff", "edamame": "hop", "bok-choy": "sway", "matcha": "whisk steam", "ramune": "wiggle bubbles",
    "kakigori": "bob snow", "boba": "bob bubbles", "yaki-imo": "roll steam", "sakura-mochi": "squish petals",
    "peach-bun": "puff steam", "ramen": "bob steam", "lychee": "hop", "onigiri": "waddle", "mitarashi": "sway",
    "mooncake": "float glow",
}
ICONS = {f.__name__.replace("_", "-"): moving(f(), MOTIONS[f.__name__.replace("_", "-")]) for f in ICONS_FN}

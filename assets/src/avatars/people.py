"""People: famous people of the past, each in its own hue, the default of its `p` -- chibi busts with the
shared kawaii face, told apart by what they are known for (Einstein's hair, Newton's apple, Curie's glowing
flask) and by their hue, which their circle and their clothes are in."""

from kit import INK, P, face, moving, shine, svg

SKIN = {"light": "#ffe1c8", "medium": "#f3c194", "tan": "#dba274", "brown": "#b47a52", "deep": "#8d5b3c"}
DARK = {"blush": "#f4808f", "blush_op": .6}   # face()'s blush on brown and deep skin
WHITE = "#fbfcfd"      # white hair and beards
GRAY_SHADE = "#e1e6ec"  # their shade
GOLD = "#fbbf24"
LEAF = "#22a55a"


def _body(fill):
    """A small round body under the head: shoulders, in the person's clothes."""
    return f'<path d="M16.5 60 C16.5 51 22.5 47 32 47 C41.5 47 47.5 51 47.5 60 C43 62.6 21 62.6 16.5 60Z" fill="{fill}"/>'


def _head(skin, cy=34, rx=13, ry=13):
    return f'<ellipse cx="32" cy="{cy}" rx="{rx}" ry="{ry}" fill="{skin}"/>'


def _ears(skin, cy=35, dx=13, r=2.8):
    return f'<circle cx="{32 - dx}" cy="{cy}" r="{r}" fill="{skin}"/><circle cx="{32 + dx}" cy="{cy}" r="{r}" fill="{skin}"/>'


def _circles(spots, fill):
    return "".join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}"/>' for x, y, r in spots)


def _flower(x, y, r, fill):
    """Five round petals about (x, y), `r` across, a gold heart."""
    petals = [(x + r * .55 * dx, y + r * .55 * dy, r * .55) for dx, dy in
              ((0, -1), (.95, -.31), (.59, .81), (-.59, .81), (-.95, -.31))]
    return _circles(petals, fill) + f'<circle cx="{x}" cy="{y}" r="{r * .38:.2f}" fill="{GOLD}"/>'


def _star(x, y, r, fill):
    """A five-pointed star about (x, y), `r` from its middle to a point."""
    import math
    pts = [(x + (r if i % 2 == 0 else r * .45) * math.sin(math.pi * i / 5), y - (r if i % 2 == 0 else r * .45) * math.cos(math.pi * i / 5))
           for i in range(10)]
    return f'<path d="M{" L".join(f"{a:.1f} {b:.1f}" for a, b in pts)}Z" fill="{fill}" stroke="{fill}" stroke-width="1" stroke-linejoin="round"/>'


def _mirror(spots):
    """`spots` on the left and the same on the right."""
    return spots + [(64 - x, y, r) for x, y, r in spots]


def einstein(p=P("gray")):
    puff = [(17, 30, 7.5), (19, 20, 7.5), (26, 14, 7.5), (34, 12.5, 7.5), (42, 15, 7.5), (47, 22, 7), (48, 31, 6.5),
            (15.5, 38.5, 5), (48.5, 38.5, 5)]
    return svg(p,
        _body(p.main)
        + '<path d="M27 47.2 L32 53 L37 47.2Z" fill="#fff"/>'
        + _circles([(x + .8, y + 1.2, r) for x, y, r in puff], GRAY_SHADE) + _circles(puff, WHITE)
        + _head(SKIN["light"], cy=34.5, rx=13.5)
        + f'<path d="M22 25.5 q2 -4.5 5.5 -2 q2.5 -4 6 -.8 q3.5 -3.4 6.5 .8 q2 -.6 2.6 2" fill="{WHITE}"/>'
        + face(32, 35, gap=6.6, r=2.1, mouth=None, cheek_dx=10.2, cheek_dy=4.4)
        + '<path d="M30 41.6 h4 v1.9 a2 2 0 0 1 -4 0z" fill="#ff7a8a"/>'
        + f'<path d="M24.5 41.6 C25.5 38.6 29.5 38 32 39.6 C34.5 38 38.5 38.6 39.5 41.6 C37 42.8 34.5 42.4 32 41.4 C29.5 42.4 27 42.8 24.5 41.6Z" fill="{WHITE}"/>')


def newton(p=P("red")):
    wig, shade = "#f1e7d6", "#dccdb6"
    curls = _mirror([(16, 29, 5.5), (15, 37, 5.5), (15.5, 45, 5.5), (17.5, 52, 4.6)])
    return svg(p,
        _body(p.main)
        + f'<ellipse cx="32" cy="28" rx="16" ry="15" fill="{wig}"/>'
        + _circles([(x + .7, y + 1, r) for x, y, r in curls], shade) + _circles(curls, wig)
        + '<path d="M28 46.4 h8 l-1.6 6 l-2.4 -1.6 l-2.4 1.6z" fill="#fff"/>'
        + _head(SKIN["light"], cy=34.5, rx=12, ry=12.5)
        + f'<path d="M20 29 C20 20 25.5 16 32 16 C38.5 16 44 20 44 29 C41 25 36.5 24 32 25.5 C27.5 24 23 25 20 29Z" fill="{wig}"/>'
        + face(32, 35.5, gap=6, r=2, mouth="smile", mouth_dy=3.6, cheek_dx=9, cheek_dy=4)
        # the apple, just landed on his head
        + f'<path d="M37 5.5 C40 3.5 44.5 5 44.5 9.5 C44.5 14 41 16 37 15 C33 16 29.5 14 29.5 9.5 C29.5 5 34 3.5 37 5.5Z" fill="{p.main}"/>'
        + shine(33.5, 8.2, rx=2.2, ry=1.4, op=.45)
        + '<path d="M37 5.6 q.2 -2.4 1.6 -3.4" fill="none" stroke="#6b4226" stroke-width="1.3" stroke-linecap="round"/>'
        + f'<path d="M38.4 2.8 c1.8 -1.8 4.4 -1.4 5.2 .2 c-1.8 1.2 -3.8 1.2 -5.2 -.2z" fill="{LEAF}"/>')


def curie(p=P("lime")):
    hair = "#4a3326"
    fx, top = 18.5, 40
    return svg(p,
        _body(p.dark)
        + '<path d="M26.5 47.4 Q32 51.5 37.5 47.4" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/>'
        + f'<ellipse cx="32" cy="31" rx="16" ry="15" fill="{hair}"/><circle cx="32" cy="14.5" r="6.5" fill="{hair}"/>'
        + _head(SKIN["light"], cy=35.5, rx=13, ry=12.2)
        + f'<path d="M19 32 C18 23 24 19 32 19 C40 19 46 23 45 32 C42 27 37 25.5 32 26.5 C27 25.5 22 27 19 32Z" fill="{hair}"/>'
        + face(32, 36, gap=6.2, r=2, mouth="smile", mouth_dy=3.4, cheek_dx=9.4, cheek_dy=3.8)
        # her flask of radium, glowing
        + f'<circle cx="{fx}" cy="{top + 11}" r="9" fill="{p.light}" opacity=".9"/>'
        + f'<path d="M{fx - 2} {top} h4 v4.5 l5.2 8.3 c.9 1.5 -.2 3.2 -2 3.2 h-10.4 c-1.8 0 -2.9 -1.7 -2 -3.2 l5.2 -8.3z" fill="#f7fee7"/>'
        + f'<path d="M{fx - 4.8} {top + 9} h9.6 l2.4 3.8 c.9 1.5 -.2 3.2 -2 3.2 h-10.4 c-1.8 0 -2.9 -1.7 -2 -3.2z" fill="{p.main}"/>'
        + f'<g fill="{p.main}"><circle cx="{fx - 6}" cy="{top - 1}" r="1.1"/><circle cx="{fx + 5}" cy="{top + 1}" r=".9"/></g>')


def darwin(p=P("green")):
    brow = "#e6e9ee"
    return svg(p,
        _body(p.main)
        + _head(SKIN["light"], cy=31, rx=13.5, ry=14)
        + shine(26, 21, rx=4, ry=2.2, op=.55)
        + f'<ellipse cx="18.8" cy="33" rx="3.4" ry="5" fill="{WHITE}"/><ellipse cx="45.2" cy="33" rx="3.4" ry="5" fill="{WHITE}"/>'
        + f'<path d="M18.5 33 C18.5 45 24 55 32 56.5 C40 55 45.5 45 45.5 33 C43 39.5 38 41.5 32 41.5 C26 41.5 21 39.5 18.5 33Z" fill="{WHITE}"/>'
        + f'<path d="M27 47 q2 3 5 3.5 M37 47 q-2 3 -5 3.5" fill="none" stroke="{GRAY_SHADE}" stroke-width="1.2" stroke-linecap="round"/>'
        + f'<ellipse cx="25.2" cy="27.4" rx="3.4" ry="1.6" fill="{brow}"/><ellipse cx="38.8" cy="27.4" rx="3.4" ry="1.6" fill="{brow}"/>'
        + face(32, 31.5, gap=6.6, r=2.1, mouth=None, cheek_dx=10.4, cheek_dy=3.6)
        + f'<path d="M25.5 40.6 C27.5 37.8 31 37.8 32 39.4 C33 37.8 36.5 37.8 38.5 40.6 C36 42 28 42 25.5 40.6Z" fill="{WHITE}"/>'
        + f'<path d="M30.2 43.2 q1.8 1.6 3.6 0" fill="none" stroke="{INK}" stroke-width="1.5" stroke-linecap="round"/>'
        # a finch, perched on his head
        + f'<path d="M43.5 16.5 l5 -1.2 l-1.6 3.4z" fill="{p.dark}"/><ellipse cx="41" cy="16.8" rx="4.4" ry="3.3" fill="{p.dark}"/>'
        + f'<circle cx="38" cy="14" r="2.7" fill="{p.dark}"/><path d="M35.6 13.4 l-2.2 .9 l2.3 .8z" fill="#fb923c"/>'
        + f'<circle cx="37.3" cy="13.4" r=".7" fill="#fff"/>')


def lovelace(p=P("purple")):
    hair = "#3b2a22"
    return svg(p,
        _body(p.main)
        + f'<path d="M24.5 47.3 C27 51.5 37 51.5 39.5 47.3Z" fill="{SKIN["light"]}"/>'
        + f'<ellipse cx="32" cy="31" rx="15.5" ry="14.5" fill="{hair}"/>'
        + f'<circle cx="17.6" cy="37.5" r="4.8" fill="{hair}"/><circle cx="46.4" cy="37.5" r="4.8" fill="{hair}"/>'
        + _head(SKIN["light"], cy=34.8, rx=12.8, ry=12.4)
        + f'<path d="M19.2 34 C18 23 24 18.6 32 18.6 C40 18.6 46 23 44.8 34 C43 27.5 38 24.8 32.6 25.2 L32 23.6 L31.4 25.2 C26 24.8 21 27.5 19.2 34Z" fill="{hair}"/>'
        + f'<path d="M18.8 26.8 C22.5 19.6 41.5 19.6 45.2 26.8" fill="none" stroke="{p.main}" stroke-width="2.4" stroke-linecap="round"/>'
        + f'<path d="M14.6 25.6 l4.4 2.2 l-4.4 2.2z M23.4 25.6 l-4.4 2.2 l4.4 2.2z" fill="{p.dark}"/><circle cx="19" cy="27.8" r="1.5" fill="{p.dark}"/>'
        + face(32, 35.8, gap=6, r=2, mouth="smile", mouth_dy=3.4, cheek_dx=9.2, cheek_dy=3.8)
        + f'<circle cx="32" cy="53" r="1.6" fill="{p.light}"/>')


def kahlo(p=P("pink")):
    hair = "#241a1c"
    return svg(p,
        _body(p.main)
        + f'<path d="M23 50.5 C27 53.5 37 53.5 41 50.5" fill="none" stroke="{p.light}" stroke-width="2.2" stroke-linecap="round"/>'
        + f'<ellipse cx="32" cy="31.5" rx="15.5" ry="14.5" fill="{hair}"/>'
        + _head(SKIN["tan"], cy=35, rx=12.8, ry=12.5)
        + f'<path d="M19.2 33.5 C18 23 24 19 32 19 C40 19 46 23 44.8 33.5 C43 27.5 38 25.4 32.6 25.6 L32 24 L31.4 25.6 C26 25.4 21 27.5 19.2 33.5Z" fill="{hair}"/>'
        + f'<path d="M14.5 19.5 q3 -3 6 -1 M43.5 18.5 q3 -2 6 1" fill="none" stroke="{LEAF}" stroke-width="2" stroke-linecap="round"/>'
        + _flower(19.5, 20.5, 5.6, p.main) + _flower(44.5, 20.5, 5.6, p.main) + _flower(32, 14.5, 6.6, p.dark)
        + f'<path d="M24.6 30.4 q3.6 -2 7.4 .2 q3.8 -2.2 7.4 -.2" fill="none" stroke="{INK}" stroke-width="1.3" stroke-linecap="round"/>'
        + face(32, 35.5, gap=6.2, r=2, mouth="smile", mouth_dy=3.6, cheek_dx=9.4, cheek_dy=3.8))


def van_gogh(p=P("orange")):
    straw = p.light
    return svg(p,
        _body(p.dark)
        + _head(SKIN["light"], cy=34, rx=13, ry=13)
        + f'<ellipse cx="19.6" cy="30" rx="2.8" ry="4.4" fill="{p.main}"/><ellipse cx="44.4" cy="30" rx="2.8" ry="4.4" fill="{p.main}"/>'
        + f'<path d="M19 33 C19 43 24.5 50 32 50.5 C39.5 50 45 43 45 33 C43 38.5 38 40.5 32 40.5 C26 40.5 21 38.5 19 33Z" fill="{p.main}"/>'
        + face(32, 33.5, gap=6.4, r=2.1, mouth=None, cheek_dx=9.8, cheek_dy=3.6)
        + f'<path d="M26 40.4 C28 38 31 38.2 32 39.4 C33 38.2 36 38 38 40.4 C36 41.6 28 41.6 26 40.4Z" fill="{p.main}"/>'
        + f'<path d="M30.2 43 q1.8 1.6 3.6 0" fill="none" stroke="{INK}" stroke-width="1.5" stroke-linecap="round"/>'
        # his straw hat
        + f'<ellipse cx="32" cy="23" rx="20" ry="4.6" fill="{straw}"/>'
        + f'<path d="M21 23 C21 13.5 25 9.5 32 9.5 C39 9.5 43 13.5 43 23Z" fill="{straw}"/>'
        + f'<path d="M21.2 19.4 h21.6 v3.2 h-21.6z" fill="{p.main}"/>'
        + f'<path d="M25 13.5 q7 -2 14 0 M14.5 23.5 q17.5 3.6 35 0" fill="none" stroke="{p.main}" stroke-width=".9" opacity=".5"/>')


def cleopatra(p=P("teal")):
    hair = "#1d1a22"
    eye_y, gap = 35.5, 6
    return svg(p,
        _body(p.main)
        + f'<path d="M18 52 C22 46.5 42 46.5 46 52 C42 57 22 57 18 52Z" fill="{GOLD}"/>'
        + f'<path d="M21 50.2 C25 47 39 47 43 50.2 C39 53.4 25 53.4 21 50.2Z" fill="{p.dark}"/>'
        + f'<path d="M16 30 C16 18 23 13 32 13 C41 13 48 18 48 30 V46 C48 47.5 46.5 48 45 48 H19 C17.5 48 16 47.5 16 46Z" fill="{hair}"/>'
        + _head(SKIN["medium"], cy=35, rx=12, ry=12.5)
        + f'<path d="M19.6 30.5 C19.6 21.5 25 17.5 32 17.5 C39 17.5 44.4 21.5 44.4 30.5Z" fill="{hair}"/>'
        + f'<path d="M17 24.8 C22 20.8 42 20.8 47 24.8" fill="none" stroke="{GOLD}" stroke-width="2.2" stroke-linecap="round"/>'
        + f'<path d="M32 12.5 c2.2 0 3 2.2 2 4 l-1.2 2.4 v3 h-1.6 v-3 l-1.2 -2.4 c-1 -1.8 -.2 -4 2 -4z" fill="{GOLD}"/>'
        + f'<circle cx="32" cy="15" r="1" fill="{p.main}"/>'
        + face(32, eye_y, gap=gap, r=2, mouth="smile", mouth_dy=3.6, cheek_dx=9, cheek_dy=3.8)
        + f'<path d="M{32 - gap - 1.4} {eye_y - .2} l-2.6 -1.2 l.9 1.5z M{32 + gap + 1.4} {eye_y - .2} l2.6 -1.2 l-.9 1.5z" fill="{INK}" stroke="{INK}" stroke-width=".9" stroke-linejoin="round"/>')


def tesla(p=P("sky")):
    hair = "#2b2526"
    bolt = lambda x, y, s: (f'<path transform="translate({x} {y}) scale({s})" d="M3 0 h6 l-3 5 h4 l-9 10 l3 -7 h-4z" fill="{p.main}"/>')
    return svg(p,
        _body(p.dark)
        + '<path d="M27.5 47.2 L32 53.5 L36.5 47.2Z" fill="#fff"/>'
        + f'<path d="M31 49 h2 l.8 5 l-1.8 1.6 l-1.8 -1.6z" fill="{p.deep}"/>'
        + _ears(SKIN["light"], cy=35, dx=12.8)
        + _head(SKIN["light"], cy=34, rx=12.8, ry=13)
        + f'<path d="M19.2 31.5 C18.5 21 24 17 32 17 C40 17 45.5 21 44.8 31.5 C43 26 38 23.6 32.6 24 L32 22.4 L31.4 24 C26 23.6 21 26 19.2 31.5Z" fill="{hair}"/>'
        + face(32, 34.5, gap=6.2, r=2, mouth=None, cheek_dx=9.6, cheek_dy=3.8)
        + f'<path d="M26.5 40.2 C28.5 38.2 31 38.4 32 39.4 C33 38.4 35.5 38.2 37.5 40.2 C35.5 41.1 33.5 41 32 40.4 C30.5 41 28.5 41.1 26.5 40.2Z" fill="{hair}"/>'
        + bolt(8, 9, 1) + bolt(46, 7, .85))


def shakespeare(p=P("yellow")):
    hair = "#6b4226"
    ruff = [(32 + 12 * dx, 47.6 + 3.6 * dy, 2.9) for dx, dy in
            ((-1, 0), (-.8, .6), (-.45, .9), (0, 1), (.45, .9), (.8, .6), (1, 0), (.7, -.7), (-.7, -.7), (0, -.8))]
    return svg(p,
        _body(p.main)
        + f'<g fill="{p.dark}"><circle cx="32" cy="55" r="1"/><circle cx="32" cy="58.6" r="1"/></g>'
        + _circles([(x + .5, y + .8, r) for x, y, r in ruff], GRAY_SHADE) + _circles(ruff, "#fff")
        # his quill
        + f'<g transform="translate(11 56) rotate(7)"><path d="M0 -5 C-4.6 -10 -5 -21 0 -29 C4.6 -22 4.4 -10 0 -5Z" fill="#fff"/>'
        f'<path d="M0 0 V-27" stroke="{p.dark}" stroke-width="1" stroke-linecap="round"/></g>'
        + _head(SKIN["light"], cy=32.5, rx=12.5, ry=13.5)
        + shine(27, 22.5, rx=3.6, ry=2, op=.55)
        + f'<path d="M19.6 29 C17 34 17.6 41.5 20.8 44.5 C22.2 41 22 35.5 21.8 30Z M44.4 29 C47 34 46.4 41.5 43.2 44.5 C41.8 41 42 35.5 42.2 30Z" fill="{hair}"/>'
        + face(32, 33.5, gap=6.2, r=2, mouth=None, cheek_dx=9.6, cheek_dy=3.6)
        + f'<path d="M27 39.8 C29 38.2 31 38.4 32 39.2 C33 38.4 35 38.2 37 39.8 C35 40.6 29 40.6 27 39.8Z" fill="{hair}"/>'
        + f'<path d="M30.4 41.6 q1.6 1.4 3.2 0" fill="none" stroke="{INK}" stroke-width="1.4" stroke-linecap="round"/>'
        + f'<path d="M30.6 43.6 h2.8 l-1.4 2.6z" fill="{hair}"/>')


def mozart(p=P("blue")):
    wig, shade = "#f6f7fb", "#d9dfeb"
    rolls = _mirror([(18.2, 31, 3.8), (18.2, 37.4, 3.8)])
    note = (f'<g fill="{p.dark}"><ellipse cx="12.4" cy="20.6" rx="2.7" ry="2" transform="rotate(-20 12.4 20.6)"/>'
            f'<path d="M14.4 20 V10 h1.3 v10z"/><path d="M15.7 10 c3 1 4.4 3 3.8 6 c-.4 -2 -1.8 -3 -3.8 -3.4z"/></g>')
    return svg(p,
        _body(p.main)
        + f'<path d="M16.5 60 C16.5 51 22.5 47 32 47 C41.5 47 47.5 51 47.5 60" fill="none" stroke="{GOLD}" stroke-width="1.2" opacity=".8"/>'
        + '<path d="M28.5 46.5 h7 l-1 3 l1.6 2.6 l-3.1 2.4 l-3.1 -2.4 l1.6 -2.6z" fill="#fff"/>'
        + _head(SKIN["light"], cy=35, rx=12.6, ry=12.6)
        + f'<path d="M19.4 33 C18.4 21 24 15.5 32 15.5 C40 15.5 45.6 21 44.6 33 C42 27 38 25 32 25 C26 25 22 27 19.4 33Z" fill="{wig}"/>'
        + _circles([(x, y + 1, r) for x, y, r in rolls], shade) + _circles(rolls, wig)
        + face(32, 36, gap=6, r=2, mouth="smile", mouth_dy=3.4, cheek_dx=9.2, cheek_dy=3.8)
        + note)


def earhart(p=P("brown")):
    return svg(p,
        _body(p.dark)
        + f'<path d="M21 50.5 C24.5 47 39.5 47 43 50.5 C39.5 53 24.5 53 21 50.5Z" fill="#f3e9dc"/>'
        + _head(SKIN["light"], cy=35, rx=12.4, ry=12.2)
        + f'<path d="M18.6 36 C18 23.5 24 16.5 32 16.5 C40 16.5 46 23.5 45.4 36 L45 41.5 C44.6 43.8 41.6 43.8 41.4 41.5 L41 33.5 C39.6 29.4 36 27.6 32 27.6 C28 27.6 24.4 29.4 23 33.5 L22.6 41.5 C22.4 43.8 19.4 43.8 19 41.5Z" fill="{p.main}"/>'
        + f'<path d="M32 17 V27.4" stroke="{p.dark}" stroke-width="1.1" opacity=".55"/>'
        + f'<path d="M17.8 25.2 H46.2" stroke="{p.deep}" stroke-width="1.8"/>'
        + f'<circle cx="26.4" cy="24.6" r="4.3" fill="{p.dark}"/><circle cx="37.6" cy="24.6" r="4.3" fill="{p.dark}"/>'
        + '<circle cx="26.4" cy="24.6" r="2.9" fill="#dbeafe"/><circle cx="37.6" cy="24.6" r="2.9" fill="#dbeafe"/>'
        + shine(25.5, 23.6, rx=1.2, ry=.7, op=.85) + shine(36.7, 23.6, rx=1.2, ry=.7, op=.85)
        + face(32, 36, gap=6, r=2, mouth="smile", mouth_dy=3.6, cheek_dx=9, cheek_dy=3.6)
        # her scarf, knotted at the neck
        + '<path d="M23.5 47.6 C27 50.6 37 50.6 40.5 47.6 L40.5 50 C37 53 27 53 23.5 50Z" fill="#fff"/>'
        + '<path d="M26.5 50.5 L22.5 58 L26.2 57.6 L29.6 51.5Z" fill="#fff"/>')


def sejong(p=P("red")):
    hat, sk = "#221c22", SKIN["light"]
    return svg(p,
        _body(p.main)
        + '<path d="M26.5 47.6 L32 53.4 L37.5 47.6" fill="none" stroke="#fff" stroke-width="1.8" stroke-linejoin="round"/>'
        + f'<circle cx="32" cy="57" r="3.4" fill="{GOLD}"/><circle cx="32" cy="57" r="1.8" fill="{p.dark}"/>'
        # his hat, its two wings standing up behind
        + f'<ellipse cx="21.5" cy="16" rx="3.4" ry="6.2" transform="rotate(-14 21.5 16)" fill="{hat}"/>'
        + f'<ellipse cx="42.5" cy="16" rx="3.4" ry="6.2" transform="rotate(14 42.5 16)" fill="{hat}"/>'
        + _ears(sk, cy=36, dx=12.6)
        + _head(sk, cy=35, rx=12.6, ry=12.6)
        + f'<path d="M19.6 31 C19.6 21 25 16.5 32 16.5 C39 16.5 44.4 21 44.4 31 C40 27.6 24 27.6 19.6 31Z" fill="{hat}"/>'
        + face(32, 35.5, gap=6.2, r=2, mouth=None, cheek_dx=9.6, cheek_dy=3.8)
        + f'<path d="M27.6 40.6 q2.4 -1.6 4.4 -.4 q2 -1.2 4.4 .4" fill="none" stroke="{hat}" stroke-width="1.3" stroke-linecap="round"/>'
        + f'<path d="M30.4 42.4 q1.6 1.3 3.2 0" fill="none" stroke="{INK}" stroke-width="1.4" stroke-linecap="round"/>'
        + f'<path d="M31 44.4 h2 l-1 3z" fill="{hat}"/>'
        # the first letters of Hangul, his alphabet: giyeok and nieun
        + f'<path d="M8 16 h5.5 v6 M16.5 15 v7 h5.5" fill="none" stroke="{p.dark}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/>')


def rumi(p=P("orange")):
    beard, sk = "#3d2a22", SKIN["medium"]
    return svg(p,
        _body(p.main)
        + '<path d="M27 47.4 L32 54 L37 47.4Z" fill="#fff"/>'
        + _head(sk, cy=35, rx=12.6, ry=12.6)
        # his tall felt hat, wound round with a white turban
        + f'<path d="M24.5 27 L26 7.5 C26.4 4.4 37.6 4.4 38 7.5 L39.5 27Z" fill="{p.light}"/>'
        + f'<path d="M29.4 8 L28.8 24 M34.6 8 L35.2 24" stroke="{p.main}" stroke-width=".8" opacity=".5"/>'
        + '<path d="M19.6 30 C19 22.5 25 20.5 32 20.5 C39 20.5 45 22.5 44.4 30 C40 26.5 24 26.5 19.6 30Z" fill="#fff"/>'
        + f'<path d="M21 26.6 C27 23.6 37 23.6 43 26.6" fill="none" stroke="{GRAY_SHADE}" stroke-width="1.2"/>'
        + face(32, 35.6, gap=6.2, r=2, mouth=None, cheek_dx=9.6, cheek_dy=3.6)
        + f'<path d="M20.5 37 C21 45 26 50.5 32 51 C38 50.5 43 45 43.5 37 C41 41.5 37 43 32 43 C27 43 23 41.5 20.5 37Z" fill="{beard}"/>'
        + f'<path d="M27 41.4 C29 39.6 31 39.8 32 40.6 C33 39.8 35 39.6 37 41.4 C35 42.4 29 42.4 27 41.4Z" fill="{beard}"/>')


def mansa_musa(p=P("yellow")):
    hair, sk = "#1f1a1a", SKIN["deep"]
    points = [(19, 13), (28, 11), (36, 11), (45, 13)]
    return svg(p,
        _body(p.dark)
        + f'<path d="M26.5 47.4 L32 53 L37.5 47.4" fill="none" stroke="{p.main}" stroke-width="1.8" stroke-linejoin="round"/>'
        + _ears(sk, cy=36, dx=12.4)
        + _head(sk, cy=35, rx=12.6, ry=12.6)
        + f'<path d="M19.6 32 C19.6 23 25 19.5 32 19.5 C39 19.5 44.4 23 44.4 32 C41 28.5 23 28.5 19.6 32Z" fill="{hair}"/>'
        # his gold crown
        + f'<path d="M20 26 L19 13 L24.5 18.5 L28 11 L32 17.5 L36 11 L39.5 18.5 L45 13 L44 26 C37 24 27 24 20 26Z" fill="{p.main}"/>'
        + _circles([(x, y, 1.3) for x, y in points], p.main)
        + f'<path d="M20 26 C27 24 37 24 44 26 L44.2 23 C37 21 27 21 19.8 23Z" fill="{p.dark}"/>'
        + _circles([(26, 23.3, 1), (32, 22.6, 1.2), (38, 23.3, 1)], "#fff")
        + face(32, 35.8, gap=6.2, r=2, mouth="smile", mouth_dy=3.4, cheek_dx=9.6, cheek_dy=3.6, **DARK)
        + f'<path d="M23 41.5 C24 47 28 49.6 32 49.6 C36 49.6 40 47 41 41.5 C39 44.6 36 45.6 32 45.6 C28 45.6 25 44.6 23 41.5Z" fill="{hair}"/>'
        # a piece of his gold
        + f'<circle cx="16.5" cy="51.5" r="5.4" fill="{p.main}"/><circle cx="16.5" cy="51.5" r="3.5" fill="none" stroke="{p.dark}" stroke-width="1"/>'
        + shine(14.8, 49.6, rx=1.6, ry=1, op=.7))


def carver(p=P("lime")):
    sk, gray, shell = SKIN["deep"], "#e4e4e2", "#e3c49f"
    return svg(p,
        _body(p.dark)
        + '<path d="M27.5 47.2 L32 53.5 L36.5 47.2Z" fill="#fff"/>'
        + f'<path d="M31 49 h2 l.8 5 l-1.8 1.6 l-1.8 -1.6z" fill="{p.deep}"/>'
        + _flower(41, 52, 4.4, p.light)
        + _ears(sk, cy=35.5, dx=12.6)
        + _head(sk, cy=34.5, rx=12.6, ry=12.8)
        + f'<path d="M19.6 31 C19.4 22 25 17.6 32 17.6 C39 17.6 44.6 22 44.4 31 C42 25.5 37 23.5 32 23.5 C27 23.5 22 25.5 19.6 31Z" fill="{gray}"/>'
        + face(32, 34.8, gap=6.2, r=2, mouth=None, cheek_dx=9.6, cheek_dy=3.6, **DARK)
        + f'<path d="M26.8 40.4 C28.8 38.4 31 38.6 32 39.6 C33 38.6 35.2 38.4 37.2 40.4 C35.2 41.4 33.4 41.2 32 40.6 C30.6 41.2 28.8 41.4 26.8 40.4Z" fill="{gray}"/>'
        + f'<path d="M30.4 42.6 q1.6 1.3 3.2 0" fill="none" stroke="{INK}" stroke-width="1.4" stroke-linecap="round"/>'
        # a peanut
        + f'<g transform="translate(15.5 48.5) rotate(-25) scale(1.1)"><path d="M0 -7 C3 -7 3.6 -4 2.6 -2.2 C2 -1 2 1 2.8 2.4 C4 4.6 3 8 0 8 C-3 8 -4 4.6 -2.8 2.4 C-2 1 -2 -1 -2.6 -2.2 C-3.6 -4 -3 -7 0 -7Z" fill="{shell}"/>'
        '<g fill="#c49a6c"><circle cx="-.8" cy="-4" r=".55"/><circle cx="1" cy="-2.6" r=".55"/><circle cx="-1" cy="3.4" r=".55"/><circle cx="1" cy="5" r=".55"/></g></g>')


def basho(p=P("green")):
    straw, weave, sk = "#eedfb4", "#d6c38e", SKIN["light"]
    return svg(p,
        _body(p.main)
        + f'<path d="M26.5 47.4 L32 53.5 L37.5 47.4" fill="none" stroke="{p.dark}" stroke-width="2.2" stroke-linejoin="round"/>'
        + _head(sk, cy=36, rx=12.4, ry=12)
        # his traveller's straw hat, a frog on it
        + f'<path d="M7.5 29.5 L32 10 L56.5 29.5 C48 32.5 16 32.5 7.5 29.5Z" fill="{straw}"/>'
        + f'<path d="M32 10 L19 31.4 M32 10 L45 31.4 M32 10 V32" stroke="{weave}" stroke-width=".9"/>'
        + face(32, 37.2, gap=6, r=2, mouth="smile", mouth_dy=3.4, cheek_dx=9, cheek_dy=3.6)
        + f'<ellipse cx="32" cy="10.4" rx="4.8" ry="3.2" fill="{p.main}"/>'
        + _circles([(29.7, 7.6, 1.9), (34.3, 7.6, 1.9)], p.main) + _circles([(29.7, 7.4, .85), (34.3, 7.4, .85)], INK))


def al_khwarizmi(p=P("teal")):
    beard, sk = "#2e2420", SKIN["medium"]
    return svg(p,
        _body(p.dark)
        + '<path d="M27 47.4 L32 53.5 L37 47.4Z" fill="#fff"/>'
        + _head(sk, cy=35.5, rx=12.4, ry=12.4)
        + f'<path d="M17.5 27.5 C16 17 23 11 32 11 C41 11 48 17 46.5 27.5 C40 30 24 30 17.5 27.5Z" fill="{p.main}"/>'
        + f'<path d="M18.5 22 C26 26 38 26 45.5 22 M21 15.5 C28 20 38 19 44 16" fill="none" stroke="{p.light}" stroke-width="1.4" opacity=".85"/>'
        + face(32, 35.8, gap=6.2, r=2, mouth=None, cheek_dx=9.6, cheek_dy=3.6)
        + f'<path d="M20.6 37 C21 45.5 26 50.5 32 51 C38 50.5 43 45.5 43.4 37 C41 41.5 37 43.2 32 43.2 C27 43.2 23 41.5 20.6 37Z" fill="{beard}"/>'
        + f'<path d="M27 41.4 C29 39.6 31 39.8 32 40.6 C33 39.8 35 39.6 37 41.4 C35 42.4 29 42.4 27 41.4Z" fill="{beard}"/>'
        # algebra: an unknown, and a plus
        + f'<path d="M8.5 14.5 l5 6 M13.5 14.5 l-5 6 M51 10.5 v6.4 M47.8 13.7 h6.4" fill="none" stroke="{p.dark}" stroke-width="1.9" stroke-linecap="round"/>')


def ramanujan(p=P("sky")):
    hair, sk = "#1f1a1c", SKIN["brown"]
    return svg(p,
        _body(p.dark)
        + '<path d="M27.5 47.2 L32 53.5 L36.5 47.2Z" fill="#fff"/>'
        + _ears(sk, cy=35.5, dx=12.6)
        + _head(sk, cy=34.5, rx=12.6, ry=12.8)
        + f'<path d="M19.4 32 C18.6 21.5 24 17 32 17 C40 17 45.4 21.5 44.6 32 C43.4 27 40 24.6 36 24.4 C33 24.2 30 25 27.5 23.4 C24 25 21 27.5 19.4 32Z" fill="{hair}"/>'
        + face(32, 35, gap=6.2, r=2, mouth="smile", mouth_dy=3.6, cheek_dx=9.6, cheek_dy=3.8, **DARK)
        # infinity
        + f'<path d="M46 12.5 c-1.8 -2.8 -5.6 -2.8 -5.6 0 c0 2.8 3.8 2.8 5.6 0 c1.8 -2.8 5.6 -2.8 5.6 0 c0 2.8 -3.8 2.8 -5.6 0z" fill="none" stroke="{p.dark}" stroke-width="1.9"/>'
        + _circles([(12, 15, 1.3), (16, 10, .9), (53.5, 20, .9)], p.main))


def hokusai(p=P("blue")):
    sk = SKIN["light"]
    return svg(p,
        # his great wave, behind him, curling over
        f'<path d="M3.5 52 C2.5 36 8.5 22.5 18.5 16.8 C23.5 14 29 14.8 30.6 19.2 C28.4 17.6 25.4 17.8 24 20.2 C26.2 21 26.8 23.8 25 25.4 C21.6 23.4 17.4 26 15.8 32 C14.4 38 14.8 45 16.4 52Z" fill="{p.main}"/>'
        + f'<path d="M6.6 48 C6.4 36 11 26 18.6 20.6" fill="none" stroke="{p.light}" stroke-width="1.6" stroke-linecap="round"/>'
        + _circles([(16.6, 18.6, 1.6), (20.2, 16.2, 1.6), (24.2, 15.2, 1.5), (28, 15.8, 1.4), (30.6, 18.4, 1.2), (24.6, 21.4, 1.1)], "#fff")
        + _body(p.main)
        + f'<path d="M26 47.5 L32 54 L38 47.5" fill="none" stroke="{p.dark}" stroke-width="2.4" stroke-linejoin="round"/>'
        + _ears(sk, cy=36, dx=12.6)
        + _head(sk, cy=34.5, rx=12.8, ry=13)
        + shine(27, 24, rx=3.6, ry=2, op=.55)
        # his headband, knotted at the side
        + f'<path d="M19.4 28.5 C24 25.2 40 25.2 44.6 28.5 L44.4 31.4 C40 28.4 24 28.4 19.6 31.4Z" fill="{p.dark}"/>'
        + f'<path d="M44 28.6 l4.6 -2.2 l-1.2 3.6z M44 30.4 l4.4 2.4 l-3.8 .6z" fill="{p.dark}"/>'
        + face(32, 36, gap=6.2, r=2, mouth="smile", mouth_dy=3.6, cheek_dx=9.6, cheek_dy=3.8))


def murasaki(p=P("purple")):
    hair, sk = "#1d1a22", SKIN["light"]
    return svg(p,
        f'<path d="M17.5 30 C17.5 18 24 13.5 32 13.5 C40 13.5 46.5 18 46.5 30 V46 H17.5Z" fill="{hair}"/>'
        + _body(p.main)
        # the layers of her robes, at the neck
        + f'<path d="M22.5 47.6 L32 60 L41.5 47.6" fill="none" stroke="{p.dark}" stroke-width="2.4" stroke-linejoin="round"/>'
        + f'<path d="M25 47.4 L32 56.6 L39 47.4" fill="none" stroke="{p.light}" stroke-width="2.2" stroke-linejoin="round"/>'
        + '<path d="M27.2 47.3 L32 53.6 L36.8 47.3" fill="none" stroke="#fff" stroke-width="1.8" stroke-linejoin="round"/>'
        + _head(sk, cy=34, rx=12, ry=12.4)
        + f'<path d="M19.6 36 C19 23 25 18.5 32 18.5 C39 18.5 45 23 44.4 36 C43 28 38.5 24.6 32.5 25 L32 23.6 L31.5 25 C25.5 24.6 21 28 19.6 36Z" fill="{hair}"/>'
        # her long hair, down over her robes
        + f'<path d="M18.2 31 C17.4 42 17 50 16.8 58 C18.2 59.4 21.2 59.4 22.6 58 C22.2 50 22 42 22.2 34Z" fill="{hair}"/>'
        + f'<path d="M45.8 31 C46.6 42 47 50 47.2 58 C45.8 59.4 42.8 59.4 41.4 58 C41.8 50 42 42 41.8 34Z" fill="{hair}"/>'
        # brows painted high, as at court
        + f'<ellipse cx="27.2" cy="27.8" rx="1.9" ry="1.1" fill="{INK}" opacity=".4"/><ellipse cx="36.8" cy="27.8" rx="1.9" ry="1.1" fill="{INK}" opacity=".4"/>'
        + face(32, 35, gap=5.6, r=1.9, mouth="smile", mouth_dy=3.4, cheek_dx=8.8, cheek_dy=3.6))


def tubman(p=P("pink")):
    sk = SKIN["deep"]
    return svg(p,
        _body(p.dark)
        + '<path d="M25 47.6 C28 51.4 36 51.4 39 47.6" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round"/>'
        + _head(sk, cy=35, rx=12.6, ry=12.6)
        # her headscarf, knotted
        + f'<path d="M18.8 33 C18 21 24.5 15.5 32 15.5 C39.5 15.5 46 21 45.2 33 C43 27.6 38 25.4 32 25.4 C26 25.4 21 27.6 18.8 33Z" fill="{p.main}"/>'
        + f'<path d="M23 21.5 C28 19.6 36 19.6 41 21.5" fill="none" stroke="{p.dark}" stroke-width="1" opacity=".5"/>'
        + f'<ellipse cx="42.4" cy="16" rx="4.2" ry="2.8" transform="rotate(-30 42.4 16)" fill="{p.main}"/>'
        + f'<ellipse cx="46" cy="19.8" rx="3" ry="2.1" transform="rotate(25 46 19.8)" fill="{p.dark}"/>'
        + face(32, 36, gap=6.2, r=2, mouth="smile", mouth_dy=3.6, cheek_dx=9.6, cheek_dy=3.8, **DARK)
        # the North Star
        + _star(13, 15, 5, GOLD) + _circles([(19.5, 9, .9), (8, 23, .8)], GOLD))


def douglass(p=P("brown")):
    sk, hair, shade = SKIN["deep"], "#ecebe8", "#cfcdc8"
    mane = _mirror([(17.4, 36, 4.6), (16.8, 28.5, 5.4), (20, 20.5, 6), (26.5, 15, 6.4)]) + [(32, 13.5, 6.4)]
    return svg(p,
        _body(p.dark)
        + '<path d="M27.5 47.2 L32 53 L36.5 47.2Z" fill="#fff"/>'
        + f'<path d="M28.6 49.4 l3.4 1.8 l3.4 -1.8 v3.6 l-3.4 -1.8 l-3.4 1.8z" fill="{p.deep}"/>'
        # his great mane, parted at the side
        + _circles([(x + .7, y + 1, r) for x, y, r in mane], shade) + _circles(mane, hair)
        + _head(sk, cy=35, rx=12.4, ry=12.6)
        + f'<path d="M19.8 31 C19 21 24 16.5 30 16.5 C36 16 44 19 44.4 30 C42 25 37 22.6 31 24 C27 22.8 22 25.5 19.8 31Z" fill="{hair}"/>'
        + f'<path d="M25.6 17.8 C26.8 20.2 28.4 22.2 31 24" fill="none" stroke="{shade}" stroke-width="1.2" stroke-linecap="round"/>'
        + face(32, 35.4, gap=6.2, r=2, mouth=None, cheek_dx=9.6, cheek_dy=3.6, **DARK)
        + f'<path d="M20 36 C20.5 45 25.5 50.5 32 51 C38.5 50.5 43.5 45 44 36 C42 41 37.5 43 32 43 C26.5 43 22 41 20 36Z" fill="{hair}"/>'
        + f'<path d="M26.8 41.2 C28.8 39.2 31 39.4 32 40.4 C33 39.4 35.2 39.2 37.2 41.2 C35.2 42.2 28.8 42.2 26.8 41.2Z" fill="{hair}"/>'
        + f'<path d="M30.4 44.2 q1.6 1.3 3.2 0" fill="none" stroke="{INK}" stroke-width="1.4" stroke-linecap="round"/>')


def nefertiti(p=P("gray")):
    sk = SKIN["tan"]
    eye_y, gap = 37, 5.8
    return svg(p,
        _body(p.main)
        + f'<path d="M18 53 C22 47.5 42 47.5 46 53 C42 58 22 58 18 53Z" fill="{GOLD}"/>'
        + f'<path d="M21 51 C25 48 39 48 43 51 C39 54.2 25 54.2 21 51Z" fill="{p.light}"/>'
        + _head(sk, cy=36.2, rx=11.6, ry=12)
        # her tall flat-topped crown, a gold band round it
        + f'<path d="M20.4 33 L17.5 10 C17.3 7.4 19 6 21.5 6 H42.5 C45 6 46.7 7.4 46.5 10 L43.6 33 C39 29.6 25 29.6 20.4 33Z" fill="{p.dark}"/>'
        + f'<path d="M19.4 27 C25 24.6 39 24.6 44.6 27 L44.4 29.4 C39 27 25 27 19.6 29.4Z" fill="{GOLD}"/>'
        + f'<path d="M18.2 16 C26 13.4 38 13.4 45.8 16" fill="none" stroke="{GOLD}" stroke-width="1.2" opacity=".85"/>'
        + f'<path d="M32 19.5 c1.8 0 2.4 1.8 1.6 3.2 l-1 2 v2.4 h-1.2 v-2.4 l-1 -2 c-.8 -1.4 -.2 -3.2 1.6 -3.2z" fill="{GOLD}"/>'
        + face(32, eye_y, gap=gap, r=2, mouth="smile", mouth_dy=3.4, cheek_dx=8.8, cheek_dy=3.6)
        + f'<path d="M{32 - gap - 1.4} {eye_y - .2} l-2.6 -1.2 l.9 1.5z M{32 + gap + 1.4} {eye_y - .2} l2.6 -1.2 l-.9 1.5z" fill="{INK}" stroke="{INK}" stroke-width=".9" stroke-linejoin="round"/>')


SINGLE = [newton, van_gogh, shakespeare, curie, darwin, cleopatra, tesla, mozart, lovelace, kahlo, earhart, einstein,
          sejong, rumi, mansa_musa, carver, basho, al_khwarizmi, ramanujan, hokusai, murasaki, tubman, douglass, nefertiti]
# How each moves while its actor works, in the dashboard's Chat view: a move, then an effect round it if
# any (ag_dashboard/avatars/README.md names them all).
MOTIONS = {
    "newton": "nod", "van-gogh": "sway breeze", "shakespeare": "beckon", "curie": "sway glow",
    "darwin": "lookabout", "cleopatra": "glide sparkle", "tesla": "pulse glow", "mozart": "sway notes",
    "lovelace": "nod sparkle", "kahlo": "sway petals", "earhart": "glide breeze", "einstein": "wiggle sparkle",
    "sejong": "nod", "rumi": "spin notes", "mansa-musa": "bob sparkle", "carver": "bob", "basho": "nod ripple",
    "al-khwarizmi": "lookabout", "ramanujan": "float sparkle", "hokusai": "sway spout", "murasaki": "fan petals",
    "tubman": "lookabout sparkle", "douglass": "nod", "nefertiti": "glide glow",
}
ICONS = {f.__name__.replace("_", "-"): moving(f(), MOTIONS[f.__name__.replace("_", "-")]) for f in SINGLE}

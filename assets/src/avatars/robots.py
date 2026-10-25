"""Robots: each drawn from a hue's shades, so each comes in every hue (ICONS: <shape>-<hue>)."""

from kit import INK, PALETTE, P, face, svg  # noqa: F401


def bolt(p):
    return svg(p,
        f'<line x1="32" y1="15" x2="32" y2="8" stroke="{p.dark}" stroke-width="2.6" stroke-linecap="round"/>'
        f'<circle cx="32" cy="7" r="3.6" fill="{p.light}"/><circle cx="30.8" cy="5.8" r="1.1" fill="#fff" opacity=".85"/>'
        f'<rect x="9" y="25" width="7" height="13" rx="3" fill="{p.dark}"/><rect x="48" y="25" width="7" height="13" rx="3" fill="{p.dark}"/>'
        f'<rect x="28" y="45" width="8" height="5" fill="{p.dark}"/>'
        f'<rect x="19.5" y="48" width="25" height="13" rx="6" fill="{p.dark}"/><circle cx="32" cy="54.5" r="3" fill="{p.light}"/>'
        f'<rect x="13" y="13" width="38" height="33" rx="10" fill="{p.main}"/>'
        f'<rect x="18" y="18.5" width="28" height="22" rx="7" fill="{p.deep}"/>'
        + face(32, 28, gap=6, eye=(2.6, 3.4), ink=p.light, highlight=False, cheek_dx=9.5, cheek_dy=5, blush_op=.8, mouth_dy=5))


def pip(p):
    return svg(p,
        f'<path d="M32 15 Q30 9 35 6.5" fill="none" stroke="{p.dark}" stroke-width="2.4" stroke-linecap="round"/>'
        f'<circle cx="36" cy="6" r="3.4" fill="{p.light}"/>'
        f'<rect x="8" y="28" width="8" height="12" rx="3" fill="{p.dark}"/><rect x="48" y="28" width="8" height="12" rx="3" fill="{p.dark}"/>'
        f'<circle cx="32" cy="34" r="19.5" fill="{p.main}"/>'
        f'<circle cx="25.5" cy="20.5" r="1.5" fill="{p.dark}"/><circle cx="38.5" cy="20.5" r="1.5" fill="{p.dark}"/>'
        f'<ellipse cx="32" cy="37" rx="14" ry="10.5" fill="#fff" opacity=".92"/>'
        + face(32, 35.5, gap=6, eye=(2.6, 3.2), cheek_dx=9.5, cheek_dy=4.5, mouth="w", mouth_dy=4.2))


def googly(p):
    return svg(p,
        f'<g stroke="{p.dark}" stroke-width="2.4" stroke-linecap="round"><line x1="23" y1="16" x2="18" y2="8"/><line x1="41" y1="16" x2="46" y2="8"/></g>'
        f'<circle cx="18" cy="7.5" r="3.2" fill="{p.light}"/><circle cx="46" cy="7.5" r="3.2" fill="{p.light}"/>'
        f'<rect x="20" y="47" width="24" height="13" rx="6" fill="{p.dark}"/>'
        f'<path d="M32 57 C28 54.5 27.5 52 29.5 51 C30.8 50.4 31.6 51.2 32 52 C32.4 51.2 33.2 50.4 34.5 51 C36.5 52 36 54.5 32 57Z" fill="{p.light}"/>'
        f'<rect x="12" y="14" width="40" height="35" rx="12" fill="{p.main}"/>'
        f'<circle cx="24" cy="29" r="7.5" fill="#fff"/><circle cx="40" cy="29" r="7.5" fill="#fff"/>'
        f'<circle cx="25.5" cy="30" r="3.8" fill="{p.deep}"/><circle cx="41.5" cy="30" r="3.8" fill="{p.deep}"/>'
        f'<circle cx="26.8" cy="28.4" r="1.3" fill="#fff"/><circle cx="42.8" cy="28.4" r="1.3" fill="#fff"/>'
        f'<ellipse cx="16.5" cy="40" rx="3" ry="2" fill="#ff8fa3" opacity=".75"/><ellipse cx="47.5" cy="40" rx="3" ry="2" fill="#ff8fa3" opacity=".75"/>'
        f'<rect x="25" y="39.5" width="14" height="5.5" rx="2.75" fill="{p.deep}"/>'
        f'<g stroke="{p.main}" stroke-width="1.2"><line x1="29.7" y1="39.5" x2="29.7" y2="45"/><line x1="34.3" y1="39.5" x2="34.3" y2="45"/></g>')


def whirly(p):
    return svg(p,
        f'<rect x="31" y="9" width="2" height="6" fill="{p.dark}"/>'
        f'<ellipse cx="26" cy="8" rx="5.5" ry="1.9" fill="{p.dark}"/><ellipse cx="38" cy="8" rx="5.5" ry="1.9" fill="{p.light}"/>'
        f'<circle cx="32" cy="8" r="1.9" fill="{p.dark}"/>'
        f'<circle cx="12.5" cy="31" r="4.2" fill="{p.dark}"/><circle cx="51.5" cy="31" r="4.2" fill="{p.dark}"/>'
        f'<rect x="21" y="46" width="22" height="14" rx="5" fill="{p.dark}"/>'
        f'<g fill="{p.light}"><circle cx="27.5" cy="53" r="1.8"/><circle cx="32" cy="53" r="1.8"/><circle cx="36.5" cy="53" r="1.8"/></g>'
        f'<rect x="13" y="14.5" width="38" height="33" rx="15" fill="{p.main}"/>'
        f'<rect x="17.5" y="22" width="29" height="13" rx="6.5" fill="{p.deep}"/>'
        f'<path d="M22.5 30.5 q3 -4 6 0 M35.5 30.5 q3 -4 6 0" fill="none" stroke="{p.light}" stroke-width="2.2" stroke-linecap="round"/>'
        f'<ellipse cx="19.5" cy="40.5" rx="3" ry="2" fill="#ff8fa3" opacity=".75"/><ellipse cx="44.5" cy="40.5" rx="3" ry="2" fill="#ff8fa3" opacity=".75"/>'
        f'<path d="M29.2 39.5 q2.8 3 5.6 0" fill="none" stroke="{INK}" stroke-width="1.8" stroke-linecap="round"/>')


def capsule(p):
    return svg(p,
        f'<line x1="32" y1="14.5" x2="32" y2="10" stroke="{p.dark}" stroke-width="2.4" stroke-linecap="round"/>'
        f'<circle cx="32" cy="8.5" r="3" fill="{p.light}"/>'
        f'<ellipse cx="13" cy="39" rx="3.6" ry="7.5" fill="{p.dark}" transform="rotate(14 13 39)"/>'
        f'<ellipse cx="51" cy="39" rx="3.6" ry="7.5" fill="{p.dark}" transform="rotate(-14 51 39)"/>'
        f'<ellipse cx="32" cy="36" rx="17.5" ry="22" fill="{p.main}"/>'
        f'<ellipse cx="22.5" cy="23" rx="2.6" ry="5" fill="#fff" opacity=".35" transform="rotate(25 22.5 23)"/>'
        f'<ellipse cx="32" cy="30" rx="13" ry="8.5" fill="{p.deep}"/>'
        + face(32, 30, gap=5.5, eye=(2.5, 3.3), ink=p.light, highlight=False, blush=None, mouth=None)
        + f'<ellipse cx="21.5" cy="41" rx="3" ry="2" fill="#ff8fa3" opacity=".75"/><ellipse cx="42.5" cy="41" rx="3" ry="2" fill="#ff8fa3" opacity=".75"/>'
        f'<path d="M29.2 41.5 q2.8 3 5.6 0" fill="none" stroke="{INK}" stroke-width="1.8" stroke-linecap="round"/>'
        f'<circle cx="32" cy="51" r="2.4" fill="{p.light}"/>')


SHAPES = [bolt, pip, googly, whirly, capsule]
ICONS = {f"{shape.__name__}-{hue}": shape(P(hue)) for shape in SHAPES for hue in PALETTE}

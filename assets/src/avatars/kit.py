"""What every avatar shares: the palette of hues, the face, and the frame (a 64x64 SVG on a circle of
its hue). An avatar is drawn in one hue -- its circle and most of its character -- so color alone tells
actors apart; the hue is named on its root (data-hue), which the dashboard reads to keep the actors in
view in different hues (ag_dashboard/avatars.py). The face is the kawaii one: small solid eyes set low
and wide, a tiny mouth between them and blush below."""

INK = "#3a2a2a"        # eyes, mouths, noses: a soft near-black
BLUSH = "#ff8fa3"
CREAM = "#fffaf3"      # a muzzle's, a belly's, a mochi's white

# each hue: bg (the circle), light, main, dark, deep
PALETTE = {
    "red":    ("#ffd4d4", "#fca5a5", "#ef4444", "#b91c1c", "#4c1010"),
    "orange": ("#ffdcbf", "#fdba74", "#f97316", "#c2410c", "#4a1d06"),
    "yellow": ("#ffefb0", "#fde68a", "#fbbf24", "#b45309", "#4a3206"),
    "lime":   ("#e3f5bd", "#d9f99d", "#84cc16", "#4d7c0f", "#22350a"),
    "green":  ("#c9ecd6", "#86efac", "#22a55a", "#166534", "#0b2e1a"),
    "teal":   ("#c4efe8", "#99f6e4", "#14b8a6", "#0f766e", "#08332f"),
    "sky":    ("#cce9fc", "#bae6fd", "#38bdf8", "#0369a1", "#082f49"),
    "blue":   ("#d3defe", "#a5bffc", "#3b6cf6", "#1e40af", "#0f1d4a"),
    "purple": ("#e4d9ff", "#c4b5fd", "#8b5cf6", "#5b21b6", "#24104a"),
    "pink":   ("#ffd6e8", "#fbcfe8", "#f472b6", "#be185d", "#4a0a26"),
    "brown":  ("#ead8c4", "#e3c49f", "#a0683a", "#6b4226", "#2e1c10"),
    "gray":   ("#cdd4dc", "#f1f5f9", "#64748b", "#334155", "#151c26"),
}


class P:
    """One hue's shades, by name: p.bg, p.light, p.main, p.dark, p.deep."""

    def __init__(self, hue):
        self.hue = hue
        self.bg, self.light, self.main, self.dark, self.deep = PALETTE[hue]


def face(cx, cy, gap=7, r=2.3, mouth="smile", mouth_dy=3.4, ink=INK, blush=BLUSH, blush_op=.8,
         cheek_dx=None, cheek_dy=3.6):
    """The shared face, centered on its eyes' midpoint (cx, cy): two solid eyes `gap` from it, `r` across;
    blush below and outside them (`cheek_dx` from the middle, or None: just outside the eyes); a tiny mouth
    `mouth_dy` below -- "smile", "w" (a cat's), "o", "v", "bunny", or None to draw your own."""
    s = [f'<ellipse cx="{cx + d}" cy="{cy}" rx="{r}" ry="{r * 1.12:.2f}" fill="{ink}"/>' for d in (-gap, gap)]
    if blush:
        dx = gap + 3.4 if cheek_dx is None else cheek_dx
        s += [f'<ellipse cx="{cx + d}" cy="{cy + cheek_dy}" rx="3.3" ry="2" fill="{blush}" opacity="{blush_op}"/>'
              for d in (-dx, dx)]
    my = cy + mouth_dy
    st = f'fill="none" stroke="{ink}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"'
    if mouth == "smile":
        s.append(f'<path d="M{cx - 1.9} {my} q1.9 2 3.8 0" {st}/>')
    elif mouth == "w":
        s.append(f'<path d="M{cx - 2.6} {my} q1.3 1.7 2.6 0 q1.3 1.7 2.6 0" {st}/>')
    elif mouth == "o":
        s.append(f'<ellipse cx="{cx}" cy="{my + .6}" rx="1.3" ry="1.6" fill="{ink}"/>')
    elif mouth == "v":
        s.append(f'<path d="M{cx - 1.9} {my} l1.9 1.9 l1.9 -1.9" {st}/>')
    elif mouth == "bunny":
        s.append(f'<path d="M{cx} {my - .4} v1.2 M{cx - 2.2} {my + 1.4} q1.1 .9 2.2 -.6 q1.1 1.5 2.2 .6" {st}/>')
    return "".join(s)


def nose_w(cy, ink=INK):
    """A small nose at (32, cy) and a cat's "w" mouth under it: a muzzle's."""
    return (f'<ellipse cx="32" cy="{cy}" rx="2.3" ry="1.6" fill="{ink}"/>'
            f'<path d="M29.4 {cy + 2.4} q1.3 1.7 2.6 0 q1.3 1.7 2.6 0" fill="none" stroke="{ink}" stroke-width="1.5" stroke-linecap="round"/>')


def shine(cx, cy, rx=4, ry=2.4, rot=-30, op=.35):
    """A soft white highlight, for something round and glossy."""
    return f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="#fff" opacity="{op}" transform="rotate({rot} {cx} {cy})"/>'


def svg(p, body):
    """The avatar: `body` on the circle of p's hue."""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" data-hue="{p.hue}">'
            f'<circle cx="32" cy="32" r="32" fill="{p.bg}"/>{body}</svg>\n')

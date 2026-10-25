"""What every avatar shares: the palette of hues, the face, and the frame (a 64x64 SVG on a circle of
its hue). An avatar is drawn in one hue -- its circle and most of its character -- so color alone tells
actors apart; the hue is named on its root (data-hue), which the dashboard reads to keep the actors in
view in different hues (ag_dashboard/avatars.py)."""

INK = "#3a2a2a"        # eyes, mouths, noses: a soft near-black
BLUSH = "#ff8fa3"

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


def face(cx, cy, gap=6.5, eye=(2.8, 3.4), ink=INK, highlight=True, blush=BLUSH, blush_op=0.65,
         cheek_dx=11.5, cheek_dy=5, mouth="smile", mouth_dy=4.6, mouth_ink=None):
    """The shared face, centered on its eyes' midpoint (cx, cy): two oval eyes `gap` from it, each with a
    highlight; cheeks; a mouth `mouth_dy` below -- "smile", "w" (a cat's), "open", or None to draw your own."""
    mi = mouth_ink or ink
    s = []
    for ex in (cx - gap, cx + gap):
        s.append(f'<ellipse cx="{ex}" cy="{cy}" rx="{eye[0]}" ry="{eye[1]}" fill="{ink}"/>')
        if highlight:
            s.append(f'<circle cx="{ex + eye[0] * .35:.2f}" cy="{cy - eye[1] * .4:.2f}" r="{eye[0] * .42:.2f}" fill="#fff"/>')
    if blush:
        for bx in (cx - cheek_dx, cx + cheek_dx):
            s.append(f'<ellipse cx="{bx}" cy="{cy + cheek_dy}" rx="3.2" ry="2" fill="{blush}" opacity="{blush_op}"/>')
    my = cy + mouth_dy
    stroke = f'fill="none" stroke="{mi}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"'
    if mouth == "smile":
        s.append(f'<path d="M{cx - 2.6} {my} q2.6 2.8 5.2 0" {stroke}/>')
    elif mouth == "w":
        s.append(f'<path d="M{cx - 3.2} {my} q1.6 2 3.2 0 q1.6 2 3.2 0" {stroke}/>')
    elif mouth == "open":
        s.append(f'<path d="M{cx - 2.8} {my - .4} h5.6 q0 3.8 -2.8 3.8 q-2.8 0 -2.8 -3.8 z" fill="{mi}"/>'
                 f'<path d="M{cx - 1.6} {my + 2.6} q1.6 -1.4 3.2 0 q-1.6 1 -3.2 0z" fill="#ff7a8a"/>')
    return "".join(s)


def svg(p, body):
    """The avatar: `body` on the circle of p's hue."""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" data-hue="{p.hue}">'
            f'<circle cx="32" cy="32" r="32" fill="{p.bg}"/>{body}</svg>\n')

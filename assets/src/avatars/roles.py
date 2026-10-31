"""The pictures of actors with a role, not given out at random: each is the picture of every actor in that role
(ag_dashboard/avatars.py's ROLES), on a gold-edged hexagon rather than a circle (`badge`). A gatherer's gatherer agent
-- the coordinator of its actors -- is the manager: an owl in a suit, glasses on, a tie, its clipboard under its wing
(its corner, bottom right, free for its harness's mark, as every avatar's is).

draw.py writes them to ag_dashboard/avatars/roles/, which the pool of pictures to give out leaves out."""

from kit import INK, P, face, moving, shine, svg

TIE = "#ef4444"         # a manager's red tie: the one thing not in its hue
BEAK = "#f59e0b"
BOARD = "#a0683a"       # the clipboard's board


# A role's picture is not drawn on a circle, as every other avatar is, but on a badge of its own -- a hexagon edged in
# gold -- so it is never taken for one of them. The badge is the picture's FRAME, a group the dashboard takes away when it
# shows the character alone (ag_dashboard/avatars.py's `bare`), as it takes away another avatar's circle.
GOLD = "#f5b400"
FRAME = ('<g data-frame="1"><path d="M32 3.2 L57.2 17.6 V46.4 L32 60.8 L6.8 46.4 V17.6Z" fill="{bg}" stroke="{gold}" '
         'stroke-width="4.4" stroke-linejoin="round"/></g>')


def badge(p, body):
    """`body` on the gold-edged hexagon of p's hue: a role's picture (svg()'s circle, left out)."""
    return svg(p, FRAME.format(bg=p.bg, gold=GOLD) + body).replace(f'<circle cx="32" cy="32" r="32" fill="{p.bg}"/>', "", 1)


def manager(p=P("blue")):
    return badge(p,
        # the owl, a little smaller than an avatar's, inside its badge: its tufts, its wings behind it, then the owl
        '<g transform="translate(32 34.5) scale(.82) translate(-32 -33.5)">'
        f'<path d="M19.5 16.5 L11.5 7.5 L26.5 12.5Z M44.5 16.5 L52.5 7.5 L37.5 12.5Z" fill="{p.dark}" stroke="{p.dark}" '
        'stroke-width="2" stroke-linejoin="round"/>'
        f'<ellipse cx="13" cy="39" rx="4.5" ry="10" fill="{p.dark}" transform="rotate(16 13 39)"/>'
        f'<ellipse cx="51" cy="39" rx="4.5" ry="10" fill="{p.dark}" transform="rotate(-16 51 39)"/>'
        f'<path d="M32 10 C46 10 53 21 53 35 C53 49 45 57 32 57 C19 57 11 49 11 35 C11 21 18 10 32 10Z" fill="{p.main}"/>'
        + shine(21, 17, rx=4.5, ry=2.2, op=.3)
        # the discs round its eyes
        + f'<circle cx="24.5" cy="28" r="7.6" fill="{p.light}"/><circle cx="39.5" cy="28" r="7.6" fill="{p.light}"/>'
        # its shirt and tie
        + '<path d="M23.5 41 Q32 38 40.5 41 L36 54.5 Q32 56.5 28 54.5Z" fill="#fff"/>'
        + f'<path d="M30.3 41.2 h3.4 l-.7 2.3 l1.9 7.4 l-2.9 2.8 l-2.9 -2.8 l1.9 -7.4z" fill="{TIE}"/>'
        # the face: eyes in its discs, its glasses round them, a small beak
        + face(32, 28, gap=7.5, r=2.2, mouth=None, blush_op=.55, cheek_dx=9.5, cheek_dy=6.5)
        + f'<circle cx="24.5" cy="28" r="5.2" fill="none" stroke="{INK}" stroke-width="1.5"/>'
        + f'<circle cx="39.5" cy="28" r="5.2" fill="none" stroke="{INK}" stroke-width="1.5"/>'
        + f'<path d="M29.7 27.4 q2.3 -1.6 4.6 0" fill="none" stroke="{INK}" stroke-width="1.5" stroke-linecap="round"/>'
        + f'<path d="M30.2 32 h3.6 l-1.8 2.6z" fill="{BEAK}" stroke="{BEAK}" stroke-width="1" stroke-linejoin="round"/>'
        # its clipboard, under its left wing
        + f'<g transform="rotate(-10 13 47)"><rect x="6.5" y="39" width="12.5" height="16" rx="1.8" fill="{BOARD}"/>'
        '<rect x="8.3" y="41.6" width="8.9" height="11.6" rx=".8" fill="#fff"/>'
        f'<rect x="10" y="37.8" width="5.5" height="3.2" rx="1" fill="{p.deep}"/>'
        f'<path d="M9.8 45 h5.6 M9.8 47.6 h5.6 M9.8 50.2 h3.8" stroke="{p.main}" stroke-width="1.1" stroke-linecap="round"/></g>'
        '</g>')


#: name -> its picture, with how it moves while its actor works: a nod, as one who has heard and will see to it.
ICONS = {"manager": moving(manager(), "nod")}

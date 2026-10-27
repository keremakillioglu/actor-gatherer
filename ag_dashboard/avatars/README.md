# Actor avatars

Each actor in the dashboard's list has one of these pictures (ag_dashboard/avatars.py gives them out
and keeps who has which), with its harness's mark small at the corner. Every SVG here is in the pool:
`<kind>/<name>.svg`, where kind and name are lowercase letters, digits, `-` and `_`.

The ones here are drawn by `python3 assets/src/avatars/draw.py` (kawaii animals, East Asian food and
Japanese charms, a few in every hue); it writes only its own files. To add one by hand, put an SVG here
that

- is square: `viewBox="0 0 64 64"`, drawn on a circle of its hue filling it, its first shape
  (`<circle cx="32" cy="32" r="32" .../>`), so it sits with the others;
- is in one hue, named on its root, `data-hue="teal"`: one of red, orange, yellow, lime, green, teal,
  sky, blue, purple, pink, brown, gray (assets/src/avatars/kit.py has their shades). The dashboard
  keeps the open actors of a gatherer in different hues; one with no `data-hue` is a hue of its own;
- reads at 28px, its corner (bottom right) free for the harness's mark;
- is a picture only: no scripts or links to other files (the dashboard serves it so that none runs).

While its actor works, the Chat view shows the character out of its circle (the circle left out), moving,
with "Working…" in its hue. How it moves is named on its root too, `data-motion="swim bubbles"`: a move,
then an effect round it if any. With none, or a move the page does not know, it bobs.

- moves: `bob`, `float`, `hop`, `swim`, `glide`, `pulse`, `puff`, `waddle`, `wobble` (a roly-poly's, about its
  foot), `swing` (hanging from its top), `sway`, `nod`, `peck`, `roll`, `fan`, `beckon`, `squish`, `crawl`, `wag`,
  `patter`, `flutter`, `lookabout`, `flip`, `whisk`, `wiggle`, `spin`;
- effects: `steam`, `bubbles`, `spout`, `petals`, `snow`, `sparkle`, `notes`, `breeze`, `ripple`, `glow`.

They are page.html's `.m-<move>` and `.buddy.f-<effect>`; the drawn ones name theirs in their kind's
MOTIONS (assets/src/avatars).

It works on a stage (page.html's `stage`), the same for every avatar: for each kind of call its turn makes
(ag_dashboard/work.py's), the character holds the same tool, so a tool means one thing whatever the character --
a book (read), a magnifying glass (search), a pencil and sheet (edit), a checklist (test), gears (run), a parcel
sent off (ship), an hourglass (wait), little copies of itself (team). As a call ends it slows to a stop and puts
the tool away, then thinks until the next, with a thought bubble whose dots are in its hue; only then does it
move as its own character, its move and its effect. It reacts the same way to how a call ended: a failure, failures
in a row, tests passed or failed, a commit. Its turn over, it sits small under it, done. Before its first
message, it waves hello (page.html's `greeting`): a hand in its hue raised beside it, waving a few times, then resting.
The dashboard's settings can switch this to "Simple" instead (kept in the browser): the character small,
with only its own move and effect.

Under it waving, it says something to start: one of its lines in `hello.toml`, here, under its name (one in
every hue, `daruma-red`, under its name without the hue, `daruma`). The drawn ones have four each, one of each
style -- playful, plain with its name, its sound and "Ready when you are.", a haiku. Each actor says one, the
same always: the next actor given a picture says another, at random, every style coming round in turn
(ag_dashboard/avatars.py's `next_said`). The dashboard reads the file again whenever it changes, so an edited
line shows from the next update, or a reload of the page. With none, it says only that there are no messages yet.

A dashboard running sees a new one at once. Removing one gives its actors another.

`roles/` holds the pictures of actors with a role, which are never given out: every actor in the role has its role's
picture (ag_dashboard/avatars.py's `ROLES`). A gatherer's gatherer agent, the actor that coordinates the others, is the
manager, `roles/manager.svg` (drawn by assets/src/avatars/roles.py); what it says is under `manager` in hello.toml.
A role's picture is drawn on a gold-edged hexagon, not a circle, so it is never taken for another actor's: its first
shape is that badge, in a group `<g data-frame="1">`, which the dashboard takes away to show the character alone.

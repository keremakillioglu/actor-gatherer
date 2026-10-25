# Actor avatars

Each actor in the dashboard's list has one of these pictures (ag_dashboard/avatars.py gives them out
and keeps who has which), with its harness's mark small at the corner. Every SVG here is in the pool:
`<kind>/<name>.svg`, where kind and name are lowercase letters, digits, `-` and `_`.

The ones here are drawn by `python3 assets/src/avatars/draw.py` (robots in every hue, animals, food);
it writes only its own files. To add one by hand, put an SVG here that

- is square: `viewBox="0 0 64 64"`, drawn on a circle of its hue filling it
  (`<circle cx="32" cy="32" r="32" .../>`), so it sits with the others;
- is in one hue, named on its root, `data-hue="teal"`: one of red, orange, yellow, lime, green, teal,
  sky, blue, purple, pink, brown, gray (assets/src/avatars/kit.py has their shades). The dashboard
  keeps the open actors of a gatherer in different hues; one with no `data-hue` is a hue of its own;
- reads at 28px, its corner (bottom right) free for the harness's mark;
- is a picture only: no scripts or links to other files (the dashboard serves it so that none runs).

A dashboard running sees a new one at once. Removing one gives its actors another.

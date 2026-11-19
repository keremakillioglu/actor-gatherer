"""Links to things in apps (DESIGN.md, "5d. Links"): `ag://<app>/<path>[?instance=<id>][#<part>]` -- a page of Notes,
a message in Slack, a line of a file -- which an agent writes in a reply as markdown, `[its name](ag://notes/page/x)`,
and the user clicks to open it there. The page opens the app's panel (the instance the link names, else the one the
agent who wrote it is attached to, else the gatherer's) and hands it the link (the SDK's `ag.links.onOpen`); the panel
goes there. A click calls no tool, attaches no agent and is no event: the user only opens something.

An app says which paths it takes in its manifest's [[links]], each a `form` -- segments split by "/", each a word, or a
`<name>` standing for one segment, or a last `<name...>` for the rest of the path -- and what agents are told of it
(`about`). Only a path matching one of its forms is opened; the `<name>` segments are handed to the panel, decoded, as
`values`. `#<part>` (a line of a page, a line of a file) is the app's to read, and `about` says what it takes.

    Link                 one of an app's forms: `form`, `about`, and `match(path)` -> its values, else None
    Href                 an `ag://` link read: app, path (as written, %-encoded), part, instance
    parse(href)          an `ag://` link -> Href, else None (another scheme, or not a link to an app)
    href(app, path, part, instance)   the link to it
    told(manifest)       what agents are told of an app's links, after its own instructions

The page's side is frontend/src/features/apps/links.ts, the panel's app_kit/js/app.js (`ag.links`): the same rules."""

import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Dict, Optional, Pattern, Tuple

SCHEME = "ag"
#: A form's segments: a word ("page"), a `<name>` (one segment), or a last `<name...>` (the rest of the path).
WORD = re.compile(r"^[A-Za-z0-9._~-]+$")
VALUE = re.compile(r"^<([a-z][a-z0-9_]{0,31})(\.\.\.)?>$")
_HREF = re.compile(r"^ag://([a-z][a-z0-9_]{0,23})(?:/([^?#]*))?(?:\?([^#]*))?(?:#(.*))?$", re.S)
ABOUT_CHARS = 400


@dataclass(frozen=True)
class Link:
    """One of an app's [[links]]: its `form` ("page/<id>") and what agents are told of it."""
    form: str
    about: str = ""
    pattern: Pattern = field(default=None, compare=False, repr=False)
    names: Tuple[str, ...] = ()

    def match(self, path: str) -> Optional[Dict[str, str]]:
        """The values of a path (as in a link: %-encoded) of this form, decoded; None: not of this form."""
        m = self.pattern.match(path or "")
        if m is None:
            return None
        out = {}
        for n, v in zip(self.names, m.groups()):
            v = urllib.parse.unquote(v)
            if not v or "\x00" in v:
                return None
            out[n] = v
        return out


def form(text: str, about: str = "") -> Link:
    """The Link of a form, its pattern compiled; ValueError saying what is wrong with it."""
    if not isinstance(text, str) or "" in text.split("/"):
        raise ValueError(f"{text!r}: segments split by \"/\", none empty, no \"/\" at either end")
    parts, names, out = text.split("/"), [], []
    for i, s in enumerate(parts):
        v = VALUE.match(s)
        if v:
            if v.group(1) in names:
                raise ValueError(f"{text!r}: <{v.group(1)}> twice")
            if v.group(2) and i != len(parts) - 1:
                raise ValueError(f"{text!r}: <{v.group(1)}...> takes the rest of the path, so it comes last")
            names.append(v.group(1))
            out.append("(.+)" if v.group(2) else "([^/]+)")
        elif WORD.match(s):
            out.append(re.escape(s))
        else:
            raise ValueError(f"{text!r}: {s!r} is neither a word (letters, digits, . _ ~ -) nor a <name>")
    if len(about) > ABOUT_CHARS:
        raise ValueError(f"about: at most {ABOUT_CHARS} characters")
    return Link(form=text, about=about, pattern=re.compile("^" + "/".join(out) + "$", re.S), names=tuple(names))


@dataclass(frozen=True)
class Href:
    """An `ag://` link read: the app it names, its path (%-encoded, as written), its #part (decoded) and the instance
    its `?instance=` names ("": none)."""
    app: str
    path: str
    part: str = ""
    instance: str = ""


def parse(text: str) -> Optional[Href]:
    """An `ag://<app>/<path>[?instance=<id>][#<part>]` link, read; None if `text` isn't one."""
    m = _HREF.match((text or "").strip())
    if m is None:
        return None
    query = urllib.parse.parse_qs(m.group(3) or "")
    return Href(app=m.group(1), path=m.group(2) or "", part=urllib.parse.unquote(m.group(4) or ""),
                instance=(query.get("instance") or [""])[0])


def href(app: str, path: str, part: str = "", instance: str = "") -> str:
    """The link to `path` (its segments as they are: each %-encoded here) in `app`; with a #part, and the instance."""
    segs = "/".join(urllib.parse.quote(s, safe="") for s in str(path).split("/"))
    q = f"?instance={urllib.parse.quote(instance, safe='')}" if instance else ""
    return f"{SCHEME}://{app}/{segs}{q}" + (f"#{urllib.parse.quote(part, safe='')}" if part else "")


def told(m) -> str:
    """What agents are told of a manifest's links (after its instructions): how to write one in a reply, and its forms.
    "": it takes none."""
    if not m.links:
        return ""
    lines = [f"Links: whenever you refer to one of these in a reply (or in another app), link it -- "
             f"`[its name](ag://{m.name}/{m.links[0].form})`, in one of these forms -- so the user opens it in "
             f"{m.label} with a click, rather than looking for it:"]
    lines += [f"- `ag://{m.name}/{k.form}`" + (f": {k.about}" if k.about else "") for k in m.links]
    if m.instances != "one":
        lines.append(f"Attached to more than one {m.label}, add `?instance=<its id>` before any #.")
    return "\n".join(lines)

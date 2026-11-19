"""What adding an app to an actor or a task does (app_kit's manifest ON_TASK): "join", "folder" or "no" -- as the app's
manifest says (`on_task`), unless the user chose otherwise for it on the Apps page, app by app. A choice an app can't
take (a group app's "join", a value not one of ON_TASK) is not used: the manifest's then.

    of(m)                    what adding app `m` (its Manifest) to an actor or a task does
    listed(apps)             the host's listing of the apps, each's `on_task` what adding it does
    chosen()                 {app: what the user chose}
    choose(m, value)         the user's choice for `m` kept; its manifest's own value: the choice dropped
    of_item(host, gatherer, item)   for an item "app:<id>" of a gatherer, its app's (None: not an app's, or not known)

Kept as the app's "on_task" beside its other choices on the Apps page, by app_settings.py: the one store of them, in
<home>/dashboard/app_settings.json (the dashboard's own file, not config.toml: ag never reads it)."""

from typing import Dict, Optional

import app_kit
from app_kit.manifest import ON_TASK

from . import app_settings, tasks

KEY = "on_task"                                    # its key among an app's choices (app_settings.py)


def chosen() -> Dict[str, str]:
    """The user's choices, {app: value} (none: no file, or one that doesn't parse)."""
    return {k: v for k, v in app_settings.chosen(KEY).items() if isinstance(v, str)}


def allowed(m: "app_kit.Manifest", value: str) -> bool:
    """Whether app `m` may be given `value`: one of ON_TASK, and not "join" for an app in no task (a group app)."""
    return _allowed(m.access, value)


def _allowed(access: Optional[str], value) -> bool:
    return value in ON_TASK and not (value == "join" and access == "group")


def of(m: "app_kit.Manifest", choices: Optional[Dict[str, str]] = None) -> str:
    """What adding app `m` to an actor or a task does: the user's choice, if it may take it, else its manifest's."""
    got = (chosen() if choices is None else choices).get(m.name)
    return got if _allowed(m.access, got) else m.on_task


def listed(apps: list) -> list:
    """Apps as the host lists them (each its manifest's dict): `on_task` what adding each does now, the user's choices
    read once."""
    choices = chosen()
    return [{**a, "on_task": choices[a.get("name")]} if _allowed(a.get("access"), choices.get(a.get("name"))) else a
            for a in apps]


def choose(m: "app_kit.Manifest", value: str) -> str:
    """The user's choice for app `m` kept -> what adding it does now. Its manifest's own value: no choice kept, so a
    later version of the app is followed."""
    if not allowed(m, value):
        raise ValueError(f"{value!r}: one of {', '.join(v for v in ON_TASK if allowed(m, v))} for {m.label}")
    app_settings.keep(m.name, KEY, None if value == m.on_task else value)
    return of(m)


def of_item(host, gatherer: str, item: str) -> Optional[str]:
    """For an item "app:<id>" of `gatherer`, what adding its app to an actor or a task does; None: not an app's
    instance, or one (or an app) the host doesn't know."""
    iid = tasks.app_of(item)
    if iid is None or host is None:
        return None
    with host.lock:
        inst = host.instances.get(iid)
        hosted = host.apps.get(inst.app) if inst is not None and inst.gatherer == gatherer else None
    return of(hosted.manifest) if hosted is not None else None

"""Where apps are, for every host that looks for them (the dashboard's app_host.py, ag's catalog of pollers): each a
folder holding an app.toml, in these, in order -- an app found in a later one wins its name:

    BUILTIN          the apps that come with ag (the package ag_apps, installed with it), less those uninstalled: the
                     names in the home's config.toml, `[apps] removed` (installing.py writes it)
    AG_APPS_PATH     folders named in it, os.pathsep apart
    <home>/apps/     the home's own: what `ag apps install` puts there (installing.py)

An app found is INSTALLED, and on in every group: there is no turning one off in a group.

    search_path(home)   those folders
    find(home)          ({name: Manifest}, {folder: why it can't be read}) of every app in them
    removed(home)       the names of the apps that come with ag uninstalled
    origin(folder, home)  where an app's folder is: "builtin", "home" or "path"

Standard library only."""

import importlib.util
import os
import tomllib
from typing import Dict, List, Tuple

from .manifest import FILE, Manifest, ManifestError, load


def _builtin() -> str:
    """Where the apps that come with ag are: the package ag_apps's folder, wherever it is installed; else beside this
    package (a checkout)."""
    try:
        spec = importlib.util.find_spec("ag_apps")
    except (ImportError, ValueError):
        spec = None
    if spec is not None and spec.submodule_search_locations:
        return list(spec.submodule_search_locations)[0]
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ag_apps")


BUILTIN = _builtin()
PATH_ENV = "AG_APPS_PATH"


def search_path(home: str) -> List[str]:
    given = [p for p in os.environ.get(PATH_ENV, "").split(os.pathsep) if p]
    return [BUILTIN, *given, os.path.join(home, "apps")]


def removed(home: str) -> List[str]:
    """The apps that come with ag the user uninstalled: config.toml's `[apps] removed` (none: an unreadable file, or
    no such key)."""
    try:
        with open(os.path.join(home, "config.toml"), "rb") as fh:
            names = (tomllib.load(fh).get("apps") or {}).get("removed") or []
    except (OSError, tomllib.TOMLDecodeError, AttributeError):
        return []
    return [n for n in names if isinstance(n, str)] if isinstance(names, list) else []


def origin(folder: str, home: str) -> str:
    """Where an app's folder is: "builtin" (it comes with ag), "home" (installed in <home>/apps) or "path"
    (AG_APPS_PATH's)."""
    parent = os.path.dirname(os.path.realpath(folder))
    if parent == os.path.realpath(BUILTIN):
        return "builtin"
    if parent == os.path.realpath(os.path.join(home, "apps")):
        return "home"
    return "path"


def find(home: str) -> Tuple[Dict[str, Manifest], Dict[str, str]]:
    found: Dict[str, Manifest] = {}
    broken: Dict[str, str] = {}
    gone = set(removed(home))
    for root in search_path(home):
        if not os.path.isdir(root):
            continue
        for entry in sorted(os.listdir(root)):
            folder = os.path.join(root, entry)
            if not os.path.isfile(os.path.join(folder, FILE)):
                continue
            try:
                m = load(folder)
            except ManifestError as exc:
                broken[folder] = str(exc)
                continue
            if root == BUILTIN and m.name in gone:
                continue
            found[m.name] = m
    return found, broken

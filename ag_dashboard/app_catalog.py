"""The Apps page's side of the server (app_kit/DESIGN.md, "Apps from outside"; app_kit's installing.py does the work
on disk): what the page lists -- every app installed, what each gives agents and costs them, what it may do, where it
came from, its windows open and its data; the folders that couldn't load; the apps to install -- and the installs,
updates and uninstalls, after each of which the host finds the apps again (app_host's `find`).

An app installed is on in every group (there is no turning one off in a group): its panel opens anywhere, and an
agent gets its tools when its terminal next starts (tool_gateway.py).

    catalog(host)              {installed, broken, available, found}: the folders read again first (`found`: the
                               names added, gone and changed since -- an app put in <home>/apps by hand, or edited)
    stage(host, source)        a folder or git URL staged and checked -> what it is (as `catalog` lists an app), its
                               staging `id`, and -- an app installed of that name -- what changes (`changes`)
    install(host, id, update)  the staged app installed (or, `update`, in place of the one there) -> its name
    restore(host, name)        an app that comes with ag, uninstalled, installed again
    uninstall(host, name, data)   -> how ("home": its folder removed; "builtin": named in config.toml)
    updates(host)              {name: newest commit} of the apps installed from git that have a newer one
"""

import json
import os
import threading
from typing import Dict, List, Optional

import app_kit
from app_kit import finding, installing
from app_kit.installing import InstallError

from . import app_settings, data, home

CHARS_PER_TOKEN = 3.6           # a tool's definition, as the model reads it: about this many characters a token
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def cost(m: "app_kit.Manifest") -> int:
    """About how many tokens an agent given the app's tools carries for them: their definitions and its instructions."""
    tools = [t.mcp(m.name, m.label) for t in m.tools]
    return round((len(json.dumps(tools)) + len(m.told())) / CHARS_PER_TOKEN)


def said_schedule(s) -> str:
    """A schedule in words: "every 30 min", "at 00:15, Mon–Fri"."""
    if s.every:
        n = s.every
        when = f"every {n // 3600} h" if n % 3600 == 0 else f"every {n // 60} min" if n % 60 == 0 else f"every {n} s"
    else:
        when = "at " + ", ".join(s.at)
    days = sorted(s.days)
    if days and days == list(range(days[0], days[-1] + 1)) and len(days) > 2:
        when += f", {DAYS[days[0]]}–{DAYS[days[-1]]}"
    elif days:
        when += ", " + ", ".join(DAYS[d] for d in days)
    return when


def described(m: "app_kit.Manifest", where: str, src: Optional[dict] = None) -> dict:
    """What the page shows of an app: its manifest's words, what agents get of it and what it may do."""
    src = src or {}
    return {"name": m.name, "label": m.label, "version": m.version, "description": m.description,
            "mark": bool(m.mark), "origin": where, "kind": src.get("kind") or ("builtin" if where == "builtin" else ""),
            "source": src.get("source") or "", "commit": src.get("commit") or "",
            "installed_at": src.get("at") or None, "access": m.access, "with_agent": m.agent.offered,
            "opens_with_agent": app_settings.opens_with_agent(m), "instances": m.instances,
            "tools": [app_kit.tool_name(m.name, t.name) for t in m.tools], "tokens": cost(m),
            "can": m.capabilities.asked(), "own_process": bool(m.backend.command),
            "panel": bool(m.panel), "schedules": [said_schedule(s) for s in m.schedules]}


def _data_of(name: str) -> dict:
    path = os.path.join(home.HOME, "apps", name, installing.KEEP)
    size = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                size += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    mine = os.path.expanduser("~")
    shown = "~" + path[len(mine):] if path == mine or path.startswith(mine + os.sep) else path
    return {"path": shown, "bytes": size, "there": os.path.isdir(path)}


def _windows(host) -> Dict[str, Dict[str, int]]:
    """{app: {gatherer: its instances open there}}, every gatherer's records read first."""
    for g in data.gatherer_names():
        try:
            host.instances_of(g)
        except Exception:  # noqa: BLE001 - one gatherer's records unreadable: the rest are still counted
            continue
    out: Dict[str, Dict[str, int]] = {}
    with host.lock:
        for i in host.instances.values():
            per = out.setdefault(i.app, {})
            per[i.gatherer] = per.get(i.gatherer, 0) + 1
    return out


def catalog(host) -> dict:
    found = host.find()                                         # a few ms: what is there now, whoever put it there
    windows = _windows(host)
    with host.lock:
        apps = sorted(host.apps.items())
        broken = sorted(host.broken.items())
    installed = []
    for name, h in apps:
        m = h.manifest
        where = finding.origin(m.folder, home.HOME)
        installed.append({**described(m, where, installing.source(m.folder) if where == "home" else None),
                          "open": windows.get(name, {}), "data": _data_of(name), "failed": h.failed})
    available = []
    for name in finding.removed(home.HOME):                     # those that come with ag, uninstalled
        try:
            m = app_kit.load(os.path.join(finding.BUILTIN, name))
        except (app_kit.ManifestError, OSError):
            continue
        if name not in host.apps:
            available.append({**described(m, "builtin"), "data": _data_of(name), "needs": ""})
    names = {n for n, _ in apps}
    for e in installing.index():
        if e["name"] not in names:
            available.append({"name": e["name"], "label": e["label"], "description": e["description"],
                              "origin": "index", "kind": "git", "source": e["source"], "needs": e["needs"]})
    return {"installed": installed, "available": available, "found": found,
            "broken": [{"folder": f, "name": os.path.basename(f), "error": e.replace(f + os.sep, ""),
                        "origin": finding.origin(f, home.HOME)} for f, e in broken]}


def stage(host, source: str) -> dict:
    st = installing.stage(home.HOME, source)
    out = {**described(st.manifest, "staged", st.source), "id": st.id}
    with host.lock:
        there = host.apps.get(st.manifest.name)
    if there is not None:
        out["installed"] = described(there.manifest, finding.origin(there.manifest.folder, home.HOME))
        out["changes"] = _changes(there.manifest, st.manifest)
    return out


def _changes(old: "app_kit.Manifest", new: "app_kit.Manifest") -> dict:
    """What an update changes that the user should see: tools added and gone, what it may do that it couldn't."""
    was = {t.name for t in old.tools}
    now = {t.name for t in new.tools}
    return {"version": [old.version, new.version],
            "tools_added": [app_kit.tool_name(new.name, t) for t in sorted(now - was)],
            "tools_gone": [app_kit.tool_name(new.name, t) for t in sorted(was - now)],
            "can_added": [c for c in new.capabilities.asked() if c not in old.capabilities.asked()],
            "own_process": bool(new.backend.command) and not bool(old.backend.command)}


def install(host, staged_id: str, update: bool = False) -> dict:
    m = installing.install(home.HOME, staged_id, update=update)
    host.find()
    return {"name": m.name}


def staged(staged_id: str) -> dict:
    """A staged app, as `stage` described it (its id kept): what an agent's request to install it shows the user."""
    st = installing.staged(home.HOME, staged_id)
    return {**described(st.manifest, "staged", st.source), "id": st.id}


def discard(staged_id: str) -> dict:
    installing.discard(home.HOME, staged_id)
    return {}


def restore(host, name: str) -> dict:
    installing.restore(home.HOME, name)
    host.find()
    return {"name": name}


def uninstall(host, name: str, data_too: bool = False) -> dict:
    with host.lock:
        h = host.apps.get(name)
        folder = h.manifest.folder if h is not None else next(
            (f for f in host.broken if os.path.basename(f) == name and finding.origin(f, home.HOME) == "home"), None)
    if folder is None:                                          # (one that couldn't load: its folder, in <home>/apps)
        raise InstallError(f"{name} isn't installed")
    how = installing.uninstall(home.HOME, name, folder, data=data_too)
    host.find()
    return {"name": name, "how": how}


def updates(host) -> Dict[str, str]:
    """The apps installed from git with a newer commit than theirs: {name: that commit}. Each source asked at once,
    side by side (each `git ls-remote` waits up to installing.LS_WAIT)."""
    with host.lock:
        folders = {n: h.manifest.folder for n, h in host.apps.items()}
    asked: List[tuple] = []
    for name, folder in folders.items():
        src = installing.source(folder) if finding.origin(folder, home.HOME) == "home" else {}
        if src.get("kind") == "git" and src.get("source"):
            asked.append((name, src["source"], src.get("commit") or ""))
    got: Dict[str, str] = {}

    def ask(name: str, url: str, commit: str) -> None:
        newest = installing.latest(url)
        if newest and newest != commit:
            got[name] = newest

    threads = [threading.Thread(target=ask, args=a, daemon=True) for a in asked]
    for t in threads:
        t.start()
    for t in threads:
        t.join(installing.LS_WAIT + 5)
    return dict(got)

"""Installing and uninstalling apps (DESIGN.md, "Apps from outside"): what the dashboard's Apps page and `ag apps
install` do, apart from any host. An app found is installed and on in every group (finding.py); these change what
is found.

    stage(home, source)        a folder or a git URL copied aside, into <home>/apps/.incoming/<id>, and its app.toml
                               read with every check `load` makes -> Staged; a bad one is removed again: InstallError
    staged(home, id)           a staged app, read again
    install(home, id)          a staged app moved to <home>/apps/<name>/ (beside the data/ it may have there from
                               before), with where it came from (SOURCE) -> its Manifest; `update`: in place of the one
                               there, its data/ kept
    discard(home, id)          a staged app removed, not installed
    uninstall(home, name, folder, data=False)   an app found in `folder` uninstalled: one installed in <home>/apps,
                               its folder removed but its data/ (`data`: that too); one that comes with ag, named in
                               config.toml's `[apps] removed` (its data/, `data`: removed); one of AG_APPS_PATH's:
                               InstallError, it is removed there
    restore(home, name)        an app that comes with ag, uninstalled, installed again: out of `[apps] removed`
    source(folder)             where an installed app came from: {kind: "git"|"folder", source, commit, at}
    latest(url)                a git source's newest commit (its HEAD), or None
    index()                    ag's index of apps to install (ag_apps/index.toml): [{name, label, description, source,
                               needs}]
    builtins()                 the names of the apps that come with ag, uninstalled or not

Standard library (and the `git` command, for a git source) only."""

import json
import os
import re
import shutil
import subprocess
import time
import tomllib
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import finding
from .manifest import FILE, Manifest, ManifestError, load

INCOMING = ".incoming"                 # <home>/apps/.incoming/<id>: staged apps, waiting to be installed
SOURCE = ".ag-installed.json"          # in an installed app's folder: where it came from, and when
KEEP = "data"                          # an app's own files, in its folder: kept when it is uninstalled or updated
NOT_COPIED = ("data", ".git", "__pycache__", ".DS_Store")
GIT_WAIT = 120.0                       # seconds a clone may take
LS_WAIT = 20.0                         # and `git ls-remote`
STALE = 24 * 3600.0                    # a staged app older than this is removed when another is staged
GIT_URL = re.compile(r"^(?:https?|ssh|git|file)://|^[\w.-]+@[\w.-]+:|\.git/?$")
HOST_PATH = re.compile(r"^(?:github\.com|gitlab\.com|bitbucket\.org|codeberg\.org)/")


class InstallError(ValueError):
    """Why an app can't be staged, installed or uninstalled, in words the user reads."""


@dataclass
class Staged:
    id: str
    folder: str
    manifest: Manifest
    source: Dict[str, str] = field(default_factory=dict)


def _apps(home: str) -> str:
    return os.path.join(home, "apps")


def _incoming(home: str, staged_id: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{32}", staged_id or ""):
        raise InstallError("no such staged app")
    return os.path.join(_apps(home), INCOMING, staged_id)


def git_url(source: str) -> Optional[str]:
    """A source that is a git repository's URL, as git takes it (a bare github.com/... gets https://); None: not one."""
    s = source.strip()
    if HOST_PATH.match(s):
        return "https://" + s
    return s if GIT_URL.search(s) and not os.path.isdir(os.path.expanduser(s)) else None


def builtins() -> List[str]:
    """The names of the apps that come with ag (their folders' names: each its app's)."""
    root = finding.BUILTIN
    if not os.path.isdir(root):
        return []
    return sorted(e for e in os.listdir(root) if os.path.isfile(os.path.join(root, e, FILE)))


def stage(home: str, source: str) -> Staged:
    """`source` -- a folder, or a git URL -- copied into a staging folder and its manifest read (module doc)."""
    if not (source or "").strip():
        raise InstallError("say where the app is: a folder, or a git URL")
    _sweep(home)
    staged_id = uuid.uuid4().hex
    dest = _incoming(home, staged_id)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    url = git_url(source)
    try:
        if url:
            got = _git(["clone", "--depth", "1", "--quiet", url, dest], GIT_WAIT)
            if got.returncode != 0:
                raise InstallError(f"git couldn't clone {url}: {_last_line(got.stderr) or 'it failed'}")
            commit = _git(["-C", dest, "rev-parse", "HEAD"], 10).stdout.strip()
            shutil.rmtree(os.path.join(dest, ".git"), ignore_errors=True)
            where = {"kind": "git", "source": url, "commit": commit}
        else:
            path = os.path.realpath(os.path.expanduser(source.strip()))
            if not os.path.isdir(path):
                raise InstallError(f"{source} isn't a folder or a git URL")
            if not os.path.isfile(os.path.join(path, FILE)):
                raise InstallError(f"{source}: no {FILE} in it, so it isn't an app")
            shutil.copytree(path, dest, ignore=shutil.ignore_patterns(*NOT_COPIED), symlinks=True)
            where = {"kind": "folder", "source": path, "commit": ""}
        try:
            m = load(dest)
        except ManifestError as exc:
            raise InstallError(f"{FILE}: {exc}") from None
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    _write_json(os.path.join(dest, SOURCE), {**where, "at": time.time()})
    return Staged(staged_id, dest, m, where)


def staged(home: str, staged_id: str) -> Staged:
    dest = _incoming(home, staged_id)
    if not os.path.isfile(os.path.join(dest, FILE)):
        raise InstallError("no such staged app (it was installed, discarded, or is a day old)")
    try:
        m = load(dest)
    except ManifestError as exc:
        raise InstallError(f"{FILE}: {exc}") from None
    return Staged(staged_id, dest, m, source(dest))


def discard(home: str, staged_id: str) -> None:
    shutil.rmtree(_incoming(home, staged_id), ignore_errors=True)


def install(home: str, staged_id: str, update: bool = False) -> Manifest:
    """The staged app moved into <home>/apps/<name>/ (module doc). Refused: a name of an app that comes with ag, and --
    unless `update` -- one installed there already."""
    st = staged(home, staged_id)
    name = st.manifest.name
    if name in builtins():
        raise InstallError(f"an app that comes with ag is named {name}: change the `name` in its {FILE} to install it")
    target = os.path.join(_apps(home), name)
    there = os.path.isfile(os.path.join(target, FILE))
    if there and not update:
        raise InstallError(f"{name} is installed already: update it instead")
    if update and not there:
        raise InstallError(f"{name} isn't installed, so there's nothing to update")
    os.makedirs(target, exist_ok=True)
    if there:
        _clear(target)
    for entry in os.listdir(st.folder):
        if entry != KEEP:
            shutil.move(os.path.join(st.folder, entry), os.path.join(target, entry))
    shutil.rmtree(st.folder, ignore_errors=True)
    return load(target)


def uninstall(home: str, name: str, folder: str, data: bool = False) -> str:
    """App `name`, found in `folder`, uninstalled (module doc) -> how: "home" or "builtin"."""
    where = finding.origin(folder, home)
    if where == "path":
        raise InstallError(f"{name} is in {os.path.dirname(folder)} (on AG_APPS_PATH): remove it there")
    own = os.path.join(_apps(home), name)
    if where == "builtin":
        set_removed(home, sorted(set(finding.removed(home)) | {name}))
        if data:
            shutil.rmtree(os.path.join(own, KEEP), ignore_errors=True)
        return where
    if data:
        shutil.rmtree(own, ignore_errors=True)
    else:
        _clear(own)
    return where


def restore(home: str, name: str) -> None:
    if name not in builtins():
        raise InstallError(f"{name} doesn't come with ag")
    set_removed(home, [n for n in finding.removed(home) if n != name])


def source(folder: str) -> Dict[str, str]:
    """Where the app installed in `folder` came from (SOURCE), {} if it doesn't say."""
    try:
        with open(os.path.join(folder, SOURCE), encoding="utf-8") as fh:
            got = json.load(fh)
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def latest(url: str) -> Optional[str]:
    """The newest commit of a git source (its HEAD), None if git can't say (offline, gone)."""
    try:
        got = _git(["ls-remote", url, "HEAD"], LS_WAIT)
    except InstallError:
        return None
    first = (got.stdout or "").split()
    return first[0] if got.returncode == 0 and first else None


def index() -> List[dict]:
    """ag's index of apps to install, ag_apps/index.toml's [[apps]]: each {name, label, description, source, needs}."""
    try:
        with open(os.path.join(finding.BUILTIN, "index.toml"), "rb") as fh:
            entries = tomllib.load(fh).get("apps") or []
    except (OSError, tomllib.TOMLDecodeError):
        return []
    out = []
    for e in entries if isinstance(entries, list) else []:
        if isinstance(e, dict) and isinstance(e.get("name"), str) and isinstance(e.get("source"), str):
            out.append({"name": e["name"], "label": str(e.get("label") or e["name"]),
                        "description": str(e.get("description") or ""), "source": e["source"],
                        "needs": str(e.get("needs") or "")})
    return out


# -- config.toml's [apps] removed, written in place: the rest of the file as the user wrote it

def set_removed(home: str, names: List[str]) -> None:
    """config.toml's `[apps] removed` set to `names`, the rest of the file untouched -- checked by reading it back."""
    path = os.path.join(home, "config.toml")
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        text = ""
    line = "removed = [" + ", ".join(json.dumps(n) for n in names) + "]"
    head = re.search(r"(?m)^\[apps\][ \t]*(?:#.*)?$", text)
    if head is None:
        text = text.rstrip("\n") + ("\n\n" if text.strip() else "") + f"[apps]\n{line}\n"
    else:
        end = re.search(r"(?m)^\[", text[head.end():])
        stop = head.end() + end.start() if end else len(text)
        body = text[head.end():stop]
        had = re.search(r"(?m)^removed[ \t]*=.*$", body)
        body = body[:had.start()] + line + body[had.end():] if had else "\n" + line + body
        text = text[:head.end()] + body + text[stop:]
    try:
        got = (tomllib.loads(text).get("apps") or {}).get("removed")
    except tomllib.TOMLDecodeError as exc:
        raise InstallError(f"config.toml couldn't be written: {exc}") from None
    if got != names:
        raise InstallError("config.toml's [apps] removed couldn't be written: write it as one line, then try again")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _clear(folder: str) -> None:
    """Everything in an app's folder removed but its data/."""
    if not os.path.isdir(folder):
        return
    for entry in os.listdir(folder):
        if entry == KEEP:
            continue
        p = os.path.join(folder, entry)
        if os.path.isdir(p) and not os.path.islink(p):
            shutil.rmtree(p, ignore_errors=True)
        else:
            os.remove(p)


def _sweep(home: str) -> None:
    """Staged apps a day old removed (never installed or discarded: a page closed mid-install)."""
    root = os.path.join(_apps(home), INCOMING)
    if not os.path.isdir(root):
        return
    now = time.time()
    for entry in os.listdir(root):
        p = os.path.join(root, entry)
        try:
            if now - os.path.getmtime(p) > STALE:
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass


def _git(args: List[str], wait: float) -> "subprocess.CompletedProcess":
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}          # never a password prompt nobody sees
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, timeout=wait, env=env,
                              stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise InstallError("git isn't installed, so an app can't be installed from a git URL") from None
    except subprocess.TimeoutExpired:
        raise InstallError(f"git timed out after {int(wait)} s") from None


def _last_line(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def _write_json(path: str, value: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(value, fh)

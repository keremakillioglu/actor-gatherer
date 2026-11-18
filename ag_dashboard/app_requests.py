"""An AGENT'S ASKING to install, update or uninstall an app -- `ag apps install|update|uninstall` run in an agent's shell,
which says who asks (ag/cli/apps.py: `actor`) -- kept until the user approves or declines it in the dashboard: an app
installed runs its code on the user's computer, unsandboxed, so only the user installs one. The Apps page, and `ag apps`
run in the user's own terminal (no agent's), install at once as before.

    ask(host, rows, actor, op, args)   the request kept, and the page told (home's `app_requests`, read again) -> it
    pending()                          those waiting, oldest first, as the page shows them
    get(rid)                           one, as its asker's `ag apps` waits on it
    settle(host, rid, approve)         the user's answer: approved, done as the Apps page does it (app_catalog.py);
                                       declined, a staged app discarded -- either way the agent told in its conversation,
                                       a message from "Apps" (app_host.py's `tell_agent`)

A request: {id, actor, gatherer, op ("install", "update", "uninstall"), args (what app_catalog's call takes), about (the
staged app, or the installed one, as the Apps page shows it), state ("waiting", "approved", "declined", "failed"), said,
at}. Kept in the dashboard's memory: a restart forgets those waiting (their agents ask again)."""

import secrets
import threading
import time
from typing import Callable, Dict, List, Optional

from app_kit import AppError

from . import app_catalog

OPS = ("install", "update", "uninstall")
KEPT = 50                       # the settled ones kept, for their askers to read their answer

_requests: Dict[str, dict] = {}
_lock = threading.Lock()
RING: Optional[Callable[[], None]] = None      # the page told the requests changed (server.py)


def _ring() -> None:
    if RING is not None:
        try:
            RING()
        except Exception:  # noqa: BLE001 - the page reads them next time all the same
            pass


def ask(host, rows: List[dict], actor: str, op: str, args: dict) -> dict:
    """The agent `actor` asking `op` with `args` -> the request, waiting for the user."""
    if op not in OPS:
        raise AppError(f"{op}: one of {', '.join(OPS)}")
    row = next((r for r in rows if actor in (r.get("session_id"), r.get("started_as"))), None)
    if op == "uninstall":
        about = next((a for a in app_catalog.catalog(host)["installed"] if a["name"] == args.get("name")), None)
        if about is None:
            raise AppError(f"{args.get('name')}: not installed", 404)
    elif args.get("builtin"):
        about = next((a for a in app_catalog.catalog(host).get("available") or []
                      if a["name"] == args["builtin"]), None) or {"name": args["builtin"], "label": args["builtin"]}
    else:
        about = app_catalog.staged(str(args.get("id") or ""))
    r = {"id": secrets.token_hex(6), "actor": actor, "gatherer": (row or {}).get("gatherer"), "op": op,
         "args": dict(args), "about": about, "state": "waiting", "said": "", "at": time.time()}
    with _lock:
        _requests[r["id"]] = r
    _ring()
    return dict(r)


def pending() -> List[dict]:
    with _lock:
        return [dict(r) for r in sorted(_requests.values(), key=lambda r: r["at"]) if r["state"] == "waiting"]


def get(rid: str) -> dict:
    with _lock:
        r = _requests.get(rid)
    if r is None:
        raise AppError(f"{rid}: no such request (the dashboard restarted since? ask again)", 404)
    return dict(r)


def settle(host, rid: str, approve: bool) -> dict:
    """The user's answer to request `rid` (module doc) -> it, settled."""
    with _lock:
        r = _requests.get(rid)
        if r is None or r["state"] != "waiting":
            raise AppError(f"{rid}: no request waiting", 404)
        r["state"] = "settling"
    label = (r.get("about") or {}).get("label") or r["args"].get("name") or "the app"
    try:
        if not approve:
            if r["op"] in ("install", "update") and r["args"].get("id"):
                app_catalog.discard(r["args"]["id"])
            r["state"], r["said"] = "declined", f"The user declined: {label} was not {_done(r['op'])}."
        else:
            if r["op"] == "uninstall":
                app_catalog.uninstall(host, r["args"]["name"], bool(r["args"].get("data")))
            elif r["args"].get("builtin"):
                app_catalog.restore(host, r["args"]["builtin"])
            else:
                app_catalog.install(host, r["args"]["id"], r["op"] == "update")
            r["state"], r["said"] = "approved", (f"The user approved: {label} is {_done(r['op'])}. "
                                                 + ("Agents get its tools at their next start; apps_list lists it."
                                                    if r["op"] != "uninstall" else ""))
    except Exception as exc:  # noqa: BLE001 - the asker is told why, whatever failed
        r["state"], r["said"] = "failed", f"{label} could not be {_done(r['op'])}: {exc}"
    with _lock:
        settled = [k for k, v in _requests.items() if v["state"] != "waiting"]
        for k in settled[:-KEPT]:
            _requests.pop(k, None)
    if r.get("gatherer") and host is not None:
        try:
            host.tell_agent(r["gatherer"], r["actor"], f"Your request to {r['op']} {label}: {r['said']}",
                            {"request": r["id"], "op": r["op"], "state": r["state"], "group": r["gatherer"],
                             "app": (r.get("about") or {}).get("name") or ""})
        except Exception:  # noqa: BLE001 - its `ag apps` reads the answer all the same
            pass
    _ring()
    return dict(r)


def _done(op: str) -> str:
    return {"install": "installed", "update": "updated", "uninstall": "uninstalled"}[op]


def forget() -> None:
    """Every request forgotten (tests)."""
    with _lock:
        _requests.clear()

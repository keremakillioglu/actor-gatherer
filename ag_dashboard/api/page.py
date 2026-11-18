"""The page and the files it loads: its build (static/), the vendored scripts, the avatars, the reader's own chat views,
and what a browser installs it as an app with (its manifest, its icons)."""

import json
import os

from fastapi import APIRouter
from starlette.responses import Response

from .. import avatars, home, libs, server
from .common import Errors, answer, not_found, send

router = APIRouter(route_class=Errors)

ICONS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")
# the app's icons (icons/, drawn by assets/src/logo.py): (file, size, purpose) -- "any", the mark on a white rounded
# square, shown as it is; "maskable", on white to its edges, which the browser cuts to its own shape (Chrome on macOS:
# the Dock's rounded square)
APP_ICONS = [("agui-192.png", 192, "any"), ("agui-512.png", 512, "any"),
             ("agui-maskable-192.png", 192, "maskable"), ("agui-maskable-512.png", 512, "maskable")]
TOUCH_ICON = "apple-touch-icon.png"  # Safari's: on white to its edges, which Safari rounds itself


@router.get("/manifest.webmanifest")
def manifest() -> Response:
    """The page as an app (its web app manifest, which index.html links): its name and the icons a browser installs it
    with -- Chrome's "Install", Safari's "Add to Dock" -- and shows in the Dock or the task bar; opened in a window of
    its own at this dashboard's page."""
    body = {"id": "/", "name": "AGUI", "short_name": "AGUI", "start_url": "/", "scope": "/", "display": "standalone",
            "background_color": "#ffffff",
            "icons": [{"src": f"/icons/{name}", "sizes": f"{px}x{px}", "type": "image/png", "purpose": purpose}
                      for name, px, purpose in APP_ICONS]}
    return send(200, json.dumps(body).encode("utf-8"), "application/manifest+json", cache="max-age=3600")


@router.get("/icons/{name}")
def app_icon(name: str) -> Response:
    """One of the app's icons (icons/<name>, a PNG): those the manifest names, and Safari's (apple-touch-icon.png)."""
    if name not in {n for n, _, _ in APP_ICONS} | {TOUCH_ICON}:
        return not_found()
    with open(os.path.join(ICONS, name), "rb") as fh:
        return send(200, fh.read(), "image/png", cache="max-age=3600")


@router.get("/index.html")
@router.get("/")
def the_page() -> Response:
    """The page: static/index.html, the vendored scripts in it (server.py's `page()`); or, not built yet, how to build
    it."""
    return send(200, server.page().encode("utf-8"), "text/html; charset=utf-8")


@router.get("/assets/{name:path}")
def assets(name: str) -> Response:
    """What the page's build made (static/assets/): its script and styles, kept by the browser for good (named by
    their content)."""
    got = server.asset(name)
    if got is None:
        return not_found()
    return send(200, got, server.ASSET_TYPES.get(os.path.splitext(name)[1], "application/octet-stream"),
                cache="public, max-age=31536000, immutable")


@router.get("/vendor/pdfjs/{rel:path}")
def pdfjs(rel: str) -> Response:
    """pdf.js and its viewer, which the Editor shows a PDF in (libs.py: the copy apps' panels load too)."""
    got = libs.lib_file("pdfjs/" + rel)
    return send(200, *got) if got else not_found()


@router.get("/vendor/{name}")
def vendored(name: str) -> Response:
    """A vendored script or stylesheet the page has inside it (marked, DOMPurify, xterm.js and its add-ons), on its
    own, for the page in development (frontend/'s `vite`)."""
    path = server._VENDOR_FILES.get("/vendor/" + name)
    if path is None:
        return not_found()
    with open(path, "rb") as fh:
        return send(200, fh.read(), server.ASSET_TYPES.get(os.path.splitext(path)[1], "text/plain"))


@router.get("/avatars/{name:path}.svg")
def avatar(name: str, bare: str = "") -> Response:
    """An avatar's picture (ag_dashboard/avatars/<kind>/<name>.svg); ?bare=1: without its circle, the character alone
    (the Chat view's, at work). Kept by the browser a while (the list is drawn again often), its scripts never run
    even opened on its own: a picture put in the folder by hand is the reader's, not ours."""
    found = avatars.path(name)
    if found is None:
        return not_found()
    with open(found, "rb") as fh:
        body = fh.read()
    if bare:
        body = avatars.bare(body)
    return send(200, body, "image/svg+xml", cache="max-age=3600",
                headers={"content-security-policy": "default-src 'none'; style-src 'unsafe-inline'"})


@router.get("/api/views")
def views() -> Response:
    """The reader's own chat views: <home>/dashboard/views/*.js, by name."""
    return answer(home.view_names())


@router.get("/views/{name:path}")
def view(name: str) -> Response:
    """One of the reader's chat views (<name>.js), which the page loads."""
    path = home.view_file(name)
    if path is None:
        return not_found()
    with open(path, "rb") as fh:
        return send(200, fh.read(), "text/javascript; charset=utf-8")

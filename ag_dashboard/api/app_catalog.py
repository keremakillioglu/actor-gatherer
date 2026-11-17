"""The Apps page's routes (app_catalog.py; app_kit's installing.py): what is installed, can't load, or can be
installed, and installing, updating and uninstalling. `ag apps install|uninstall|update|list --all` ask the same.

    GET  /api/apps/catalog                       {installed, broken, available} (app_catalog.catalog)
    GET  /api/apps/updates                       {updates: {name: newest commit}}: apps installed from git, newer
    POST /api/apps/stage      {source}           a folder or git URL copied aside and checked -> what it is, its `id`
    POST /api/apps/install    {id, update?}      the staged app installed (`update`: in place of the one there)
                              {builtin}          an app that comes with ag, uninstalled, installed again
    POST /api/apps/discard    {id}               the staged app removed
    POST /api/apps/uninstall  {name, data?}      uninstalled; `data`: its data/ deleted too

An app installed or uninstalled is found again at once (app_host's `find`): its panel opens, or no longer, anywhere;
agents get its tools, or lose them, when their terminal next starts."""

from fastapi import APIRouter, Depends
from starlette.responses import Response

from app_kit import AppError
from app_kit.installing import InstallError

from .. import app_catalog
from .common import Body, Errors, Parts, answer, failure, local_only

router = APIRouter(route_class=Errors)


def _host(srv):
    if getattr(srv, "app_host", None) is None:
        raise AppError("no apps here", 404)
    return srv.app_host


def _run(fn, *args) -> Response:
    try:
        return answer(fn(*args))
    except InstallError as exc:
        return failure(400, str(exc))
    except AppError as exc:
        return failure(exc.status if 400 <= exc.status < 600 else 400, str(exc))


@router.get("/api/apps/catalog", dependencies=[Depends(local_only)])
def apps_catalog(srv: Parts) -> Response:
    """Every app installed (what it gives agents and costs them, what it may do, where it came from, its windows open,
    its data), the folders that couldn't load, and the apps that can be installed."""
    return _run(lambda: app_catalog.catalog(_host(srv)))


@router.get("/api/apps/updates", dependencies=[Depends(local_only)])
def apps_updates(srv: Parts) -> Response:
    """The apps installed from git that have a newer commit: {updates: {name: commit}} (asks each source)."""
    return _run(lambda: {"updates": app_catalog.updates(_host(srv))})


@router.post("/api/apps/stage")
def apps_stage(srv: Parts, body: Body) -> Response:
    """A folder or git URL copied aside and its app.toml checked: what it is, its staging id, and -- one installed of
    that name -- what an update changes."""
    return _run(lambda: app_catalog.stage(_host(srv), str(body.get("source") or "")))


@router.post("/api/apps/install")
def apps_install(srv: Parts, body: Body) -> Response:
    """The staged app (`id`) installed -- `update`: in place of the one installed -- or (`builtin`) an app that comes
    with ag installed again. On in every group at once."""
    if body.get("builtin"):
        return _run(lambda: app_catalog.restore(_host(srv), str(body["builtin"])))
    return _run(lambda: app_catalog.install(_host(srv), str(body.get("id") or ""), bool(body.get("update"))))


@router.post("/api/apps/discard")
def apps_discard(srv: Parts, body: Body) -> Response:
    """A staged app removed, not installed."""
    return _run(lambda: app_catalog.discard(str(body.get("id") or "")))


@router.post("/api/apps/uninstall")
def apps_uninstall(srv: Parts, body: Body) -> Response:
    """The app uninstalled: its windows close, its backend stops, agents lose its tools at their next start; its data
    kept unless `data`."""
    return _run(lambda: app_catalog.uninstall(_host(srv), str(body.get("name") or ""), bool(body.get("data"))))

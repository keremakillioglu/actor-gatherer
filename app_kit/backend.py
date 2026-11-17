"""What an app's backend is, and what the host gives it (DESIGN.md, "An app is a manifest, a backend and a panel").

    App         what an app's backend subclasses: open and close instances, answer tool calls and its panel's own
                requests, hear of agents attached, do its scheduled work. Every method has a default (`call`'s
                refuses every tool)
    Host        what the host gives an app: insert and read events, the agents of an instance, a message to its
                panels, the app's own folder, a notification to the user, a message to one of its agents and an
                agent of its own started
    Instance    one opened copy of an app: the host makes its id; the app may set its title and data
    Caller      who made a tool call: an agent (its channel), or the user through the panel
    ToolResult  a tool call's answer, as MCP's `tools/call` gives one
    Response    the answer to a request the panel made of the backend (its own routes)
    AppError    a refusal: the tool call answers it as an error, a request with its status

An app in the host's process is one of these directly; an app in its own process is reached through remote.py, which
gives each side the other as these same classes. An app's pollers are not here: ag builds them in its own process from
the manifest's [[pollers]] (manifest.Poller). Standard library only."""

import base64
import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Tuple

from .manifest import Manifest

if TYPE_CHECKING:
    from .docs import Docs  # noqa: F401


class AppError(Exception):
    """A refusal from an app or the host: `str(error)` is what the caller is told; `status` the HTTP status a request
    is answered with."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Instance:
    """One opened copy of an app. `id` is the host's (16 hex digits), `gatherer` the one it was opened in, `folder`
    what it works on, where it has one (per-folder and per-checkout apps). `title` and `data` are the app's: what the
    page shows of it, and anything the app wants kept with it (JSON). `name` is the user's: what they called it, shown
    over its title ("": not named -- the host's `rename`, its `app_named` record)."""
    id: str
    app: str
    gatherer: str
    folder: Optional[str] = None
    title: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    name: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Instance":
        return cls(id=d["id"], app=d["app"], gatherer=d["gatherer"], folder=d.get("folder"),
                   title=d.get("title") or "", data=dict(d.get("data") or {}), name=d.get("name") or "")


@dataclass(frozen=True)
class Caller:
    """Who made a tool call: an agent, by its channel (and its gatherer, harness, and the folder it works in), or the
    user through the app's panel (`channel` None)."""
    channel: Optional[str] = None
    gatherer: Optional[str] = None
    harness: Optional[str] = None
    folder: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "Caller":
        d = d or {}
        return cls(channel=d.get("channel"), gatherer=d.get("gatherer"), harness=d.get("harness"),
                   folder=d.get("folder"))


@dataclass
class ToolResult:
    """A tool call's answer: MCP content items (`{"type": "text", "text": ...}`, `{"type": "image", ...}`), and whether
    it is an error the agent should read as one."""
    content: List[dict]
    is_error: bool = False

    @classmethod
    def text(cls, text: str) -> "ToolResult":
        return cls([{"type": "text", "text": text}])

    @classmethod
    def error(cls, text: str) -> "ToolResult":
        return cls([{"type": "text", "text": text}], is_error=True)

    @classmethod
    def json(cls, value: Any) -> "ToolResult":
        return cls([{"type": "text", "text": json.dumps(value, ensure_ascii=False, indent=1)}])

    @classmethod
    def image(cls, data: bytes, mime_type: str = "image/png") -> "ToolResult":
        return cls([{"type": "image", "data": base64.b64encode(data).decode("ascii"), "mimeType": mime_type}])

    def to_dict(self) -> dict:
        """As MCP's `tools/call` result."""
        return {"content": self.content, "isError": self.is_error}

    @classmethod
    def from_dict(cls, d: dict) -> "ToolResult":
        return cls(list(d.get("content") or []), bool(d.get("isError", d.get("is_error", False))))


@dataclass
class Response:
    """The backend's answer to a request its panel made (`App.request`): a body; or, `events`, server-sent events
    (`Response.stream`); or, `file`, a file on disk served as it is, in the ranges asked for (`Response.file`: a video
    the page seeks in, a large PDF) -- those two an app run inside the dashboard only (an app in its own process answers
    with a body)."""
    status: int = 200
    body: bytes = b""
    headers: Dict[str, str] = field(default_factory=dict)
    events: Optional[Tuple[Callable[[float], Optional[List[Tuple[str, Any]]]], Optional[Callable[[], None]]]] = None
    file: Optional[Dict[str, Any]] = None

    @classmethod
    def json(cls, value: Any, status: int = 200) -> "Response":
        return cls(status, json.dumps(value).encode(), {"Content-Type": "application/json"})

    @classmethod
    def stream(cls, take: Callable[[float], Optional[List[Tuple[str, Any]]]],
               close: Optional[Callable[[], None]] = None) -> "Response":
        """Server-sent events to the panel (its EventSource), until `take` says the stream is over: `take(wait)`,
        called again and again in a thread of its own, returns within `wait` seconds the events to send, each
        (name, JSON value) -- [] none yet (a keepalive goes), None the end. `close()` is called once, when it is over,
        however (the panel gone, the end, the server stopping): what the stream held let go."""
        return cls(200, b"", {"Content-Type": "text/event-stream"}, (take, close))

    @classmethod
    def file_at(cls, path: str, media_type: str, filename: str = "", download: bool = False,
                headers: Optional[Dict[str, str]] = None) -> "Response":
        """The file at `path` (absolute), as `media_type`, inline -- or, `download`, to be saved as `filename` -- its
        ranges served as they are asked for."""
        return cls(200, b"", dict(headers or {}), None, {"path": path, "media_type": media_type,
                                                        "filename": filename, "download": download})


class Host(ABC):
    """What the host gives an app. Every event an app inserts carries `app` and `instance`, which the host sets; an
    app inserts only its own types and the context types (manifest.CONTEXT_TYPES), and reads only what its manifest
    lets it (`Manifest.may_read`). Each method raises AppError for what the host refuses."""

    @abstractmethod
    def insert(self, instance: Instance, events: List[dict], channel: Optional[str] = None) -> None:
        """`events` put into the instance's gatherer, in ag's insert shape (as `ag home insert` and ag's hooks send
        them): each `{"type", "payload", "id"?, "text"?, "properties"?}`, `text` what a policy shows of it. With
        `channel`, an agent's (one attached to the instance); without, the gatherer's, seen by every agent there
        (for the context types). An `id` makes a re-sent event the same event, stored once."""

    @abstractmethod
    def read(self, instance: Instance, types: Sequence[str], after: int = 0, channel: Optional[str] = None,
             limit: int = 500) -> List[dict]:
        """The instance's gatherer's events of `types` after row `after`, oldest first, at most `limit`: each
        `{"row_id", "type", "payload", "text", "properties"}`. The app's own types are read for this instance only;
        `channel` narrows them to one agent's."""

    @abstractmethod
    def attached(self, instance: Instance) -> List[str]:
        """The channels of the agents attached to the instance."""

    @abstractmethod
    def tell_panel(self, instance: Instance, message: dict) -> None:
        """`message` (JSON) to every open panel of the instance, as the SDK's `onMessage` gives it."""

    @abstractmethod
    def folder(self) -> str:
        """The app's own folder (<home>/apps/<name>/data), for what it keeps outside the gatherer."""

    def instances(self) -> List[Instance]:
        """The app's open instances, in every gatherer."""
        return []

    def panels(self, instance: Instance) -> int:
        """How many panels of the instance are open now (a server it runs, left with none, may be stopped)."""
        return 0

    def docs(self) -> "Docs":
        """The host's files shared live (app_kit.docs), for an app whose manifest asks `docs`, run in the host's
        process; AppError otherwise."""
        raise AppError("the host's shared files are not given to this app", 403)

    def notify(self, instance: Instance, title: str, text: str = "", key: Optional[str] = None,
               show: Sequence[str] = ("ag",), where: Any = None) -> str:
        """A notification to the user, for an app whose manifest asks `notify` (manifest.NOTICE_TYPES): `title`, a line
        of `text`; listed by the dashboard until the user looks at the instance, and popped up where `show` says: "ag",
        there; "system", on the computer; neither (`()`), only listed; `where` (JSON) handed back to the panel as the
        user clicks it
        (the SDK's `ag.notices.onOpen`). A newer one of the same `key` takes the open one's place. -> its id."""
        raise AppError("this host takes no notifications", 403)

    def clear_notice(self, instance: Instance, which: str) -> None:
        """The instance's open notification `which` -- its id, or every one of that key -- no longer asking for the
        user."""
        raise AppError("this host takes no notifications", 403)

    def send_agent(self, instance: Instance, channel: str, text: str) -> None:
        """A message to one of the instance's agents, as the user -- for an app whose manifest asks `message_agents` --
        as Chat sends one: typed into its terminal (opened, its agent started, if it is not); while it works, after its
        turn. AppError, 409, while its terminal can't take a message (a dialog or a question open, something typed and
        not sent): nothing typed, try again later."""
        raise AppError("this host passes on no messages", 403)

    def start_agent(self, instance: Instance, text: str, name: Optional[str] = None, harness: Optional[str] = None,
                    model: Optional[str] = None, folder: Optional[str] = None) -> str:
        """A new agent of the app's own -- for an app whose manifest asks `message_agents` -- attached to the instance,
        in its gatherer, named `name`, on `harness` and `model` (none: the host's defaults), working in `folder` (none:
        the instance's, else the app's own folder), with `text` as its first message, sent as the user. -> its
        channel."""
        raise AppError("this host starts no agents", 403)


class App:
    """An app's backend. The host sets `manifest` and calls `start` once, before anything else; then, from any thread,
    the rest. Override what the app does; the defaults do nothing (and `call` refuses every tool)."""

    manifest: Optional[Manifest] = None
    host: Optional[Host] = None

    def start(self, host: Host) -> None:
        self.host = host

    def stop(self) -> None:
        """The host is closing: let go of what it holds (processes, files)."""

    def open(self, instance: Instance, args: dict) -> Instance:
        """A new instance, made by the host (its id, gatherer, folder) from `args` (what opened it: a tool, the
        user, an intent). Returns it, its `title` and `data` set as the app wants."""
        return instance

    def close(self, instance: Instance) -> None:
        """The instance closed: by the user, or its gatherer gone."""

    def sleep(self, instance: Instance) -> None:
        """The instance put to sleep -- its task closed: it stays open, and what runs for it (a process, a page) is let
        go of, its state kept to come back as it was once it is used again. Nothing runs for it: nothing to do."""

    def folded(self, instance: Instance, was: str, title: str) -> None:
        """The group `was` (titled `title`, as the user reads it) merged into the instance's group, as a folder of it:
        what the app keeps for a group apart from its instances (a notebook, say) carried from `was` into the
        instance's, the instance being that group's one of the app now (its own, or `was`'s moved). Called once for
        each instance `was` had. Nothing kept per group: nothing to do."""

    def call(self, instance: Instance, tool: str, args: dict, caller: Caller) -> ToolResult:
        """A call of one of its tools (its own name) handled by the backend, on `instance`, by `caller`. Raise
        AppError, or return ToolResult.error, to refuse it."""
        raise AppError(f"{tool}: not a tool of this app's backend")

    def request(self, instance: Optional[Instance], method: str, path: str, query: Dict[str, str],
                body: bytes) -> Response:
        """A request the panel made of the backend: `path` is what follows /apps/<name>/api/. Its data that are not
        events (a file's contents, a picture). `query` holds the host's own `_here`: "1" when the page asking is on the
        host's machine (a system dialog the app opens shows on that machine's screen), else "0"."""
        return Response(404, b"not found")

    def attached(self, instance: Instance, channel: str) -> None:
        """An agent was attached to the instance: tell it what it needs to know now, by inserting a context_stream
        into its channel."""

    def detached(self, instance: Instance, channel: str) -> None:
        """An agent was detached from the instance."""

    def native(self, send: Callable[[str], None], close: Callable[[], None]) -> Optional[Callable[[Optional[str]], None]]:
        """The ag desktop app connected (an app whose manifest asks `native_view`, run inside the dashboard): its link,
        over which the app drives its native pages with the Chrome DevTools Protocol, the desktop app playing the
        browser (desktop/DESIGN.md, "The app link"; the pages this app makes are its own, apart from another app's).
        `send(text)` a message to it, `close()` the link ended. Returns what takes each message from it (None: the link
        gone) -- or None, not taken."""
        return None

    def scheduled(self, schedule: str, due: float) -> Optional[float]:
        """One of its manifest's [[schedules]] is due (schedules.py): the run that was due at `due` (epoch seconds),
        called by the host in a thread of its own, one run of a schedule at a time, while the app has an open instance
        somewhere. Not one instance's: the app does what it does for each of its instances (`host.instances()`).
        Returns when to try again, in seconds, when the work couldn't be done yet (what it reads isn't out yet, the
        network is down) -- None when it is done. An exception is tried again too, a while later."""
        return None

    def guard(self, instance: Instance, path: str, caller: Caller) -> Optional[str]:
        """An agent attached to the instance is about to change `path` with its harness's own edit tools (an app whose
        manifest asks `edit_guard`): why it must not -- the file is one the app has open, say, and the agent should use
        the app's tools -- or None to let it."""
        return None

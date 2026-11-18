"""What the main routes return, as Pydantic models: the home (/api/home), one actor (/api/agent), its transcript,
history and files. They describe the JSON for FastAPI's schema (each route's `response_model`) and are checked against
real answers in the tests (test_dashboard_app.py: each validates, and gives back exactly what it was given); the routes
do not serialize through them -- they send the JSON json.dumps writes, as the page has always read it.

Every field may be left out (an answer's {error} when its gatherer has no database, its fields then absent), and a
field not named here is kept (`extra="allow"`): the models say what the page reads, not all there is."""

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict


Number = Union[int, float]


class Answer(BaseModel):
    """What the main routes answer: its fields, or {error} when its gatherer has none to give."""
    model_config = ConfigDict(extra="allow")

    error: Optional[str] = None


class HomeAgent(Answer):
    """An actor, as the list shows it (data.py's `_agents`), with its avatar (avatars.py's `attach`)."""

    channel: Optional[str] = None
    harness: Optional[str] = None
    name: Optional[str] = None
    status: Optional[str] = None
    cwd: Optional[str] = None
    created: Optional[Number] = None
    last: Optional[Number] = None
    last_event: Optional[Number] = None
    last_user_message: Optional[str] = None
    recap: Optional[str] = None
    events: Optional[int] = None
    reads: Optional[int] = None
    tasks: Optional[int] = None
    est_tokens: Optional[int] = None
    real_tokens: Optional[int] = None
    limit_tokens: Optional[int] = None
    sent_tokens: Optional[int] = None
    running: Optional[bool] = None
    building: Optional[bool] = None
    turn_over: Optional[bool] = None
    chattable: Optional[bool] = None
    asking: Optional[Dict[str, Any]] = None
    background: Optional[List[Any]] = None
    avatar: Optional[str] = None
    avatar_hue: Optional[str] = None
    avatar_motion: Optional[Any] = None
    avatar_hello: Optional[Any] = None


class Gatherer(Answer):
    """A gatherer and its actors, newest first."""

    name: Optional[str] = None
    policy: Optional[str] = None
    agents: Optional[List[HomeAgent]] = None
    last: Optional[Number] = None
    created: Optional[Number] = None


class _Home(Answer):
    """The home (/api/home, and the stream's `home`): every gatherer and its actors, what the reader keeps of them, and
    what a new session starts from; what each app says of itself (`Home`)."""

    home: Optional[str] = None
    now: Optional[Number] = None
    running_seconds: Optional[Number] = None
    gatherers: Optional[List[Gatherer]] = None
    hook_servers: Optional[List[Any]] = None
    hiding: Optional[Dict[str, Any]] = None
    titles: Optional[Dict[str, Any]] = None
    saved: Optional[Dict[str, Any]] = None
    folders: Optional[Dict[str, Any]] = None
    gatherer_folders: Optional[Dict[str, Any]] = None
    places: Optional[Dict[str, Any]] = None
    tasks: Optional[Dict[str, Any]] = None
    seen: Optional[Dict[str, Any]] = None
    harness_info: Optional[Dict[str, Any]] = None
    harness_default: Optional[str] = None
    cwd: Optional[str] = None
    permission_modes: Optional[List[str]] = None
    terminals: Optional[Any] = None
    harnesses: Optional[List[Any]] = None
    shells: Optional[List[Any]] = None
    home_dir: Optional[str] = None
    branches: Optional[List[Any]] = None


Home = _Home


class Agent(Answer):
    """One actor over time (/api/agent, and the stream's `agent`): its calls and reads, what is pending, its tasks,
    builds and checks, the Gatherer's model calls for it."""

    gatherer: Optional[str] = None
    channel: Optional[str] = None
    harness: Optional[str] = None
    reads: Optional[List[Dict[str, Any]]] = None
    pending: Optional[List[Any]] = None
    typed: Optional[List[Any]] = None
    after_read: Optional[List[Any]] = None
    tasks: Optional[List[Any]] = None
    builds: Optional[List[Any]] = None
    checks: Optional[List[Any]] = None
    rebuilds: Optional[int] = None
    llm: Optional[Dict[str, Any]] = None
    usage: Optional[Dict[str, Any]] = None


class Transcript(Answer):
    """An actor's transcript (/api/transcript): its events, oldest first, each {row_id, type, at, parts}."""

    items: Optional[List[Dict[str, Any]]] = None
    earlier: Optional[bool] = None
    newest: Optional[bool] = None


class History(Answer):
    """An actor's own events from a row (/api/history), each {type, size, at, text, clipped}; `more` counts the rest."""

    first_row: Optional[int] = None
    last_row: Optional[int] = None
    items: Optional[List[Dict[str, Any]]] = None
    more: Optional[int] = None


class Files(Answer):
    """An actor's turns and the files of one (/api/files): what it changed, read and made, its commands."""

    turns: Optional[List[Dict[str, Any]]] = None
    turn: Optional[int] = None
    files: Optional[List[Dict[str, Any]]] = None
    commands: Optional[List[Dict[str, Any]]] = None
    home: Optional[str] = None

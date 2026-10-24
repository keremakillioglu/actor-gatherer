"""ag's own settings, as the page shows and edits them: the home's config.toml (<home>/config.toml),
which ag makes and reads -- the dashboard never imports ag:

    [policies.llm]      the Gatherer's model: set through `ag model`, as from the command line
    [policies] default  the policy a new gatherer gets
    [pollers] default   the pollers a new gatherer gets
    [cli] gatherer      the gatherer `ag <harness>` files into when none is named
    the rest            the catalog of policies and pollers, and each harness's launcher: shown,
                        and edited as the file itself

Every write keeps the file's other lines, comments included, and is refused when the file would not
parse, or when it changed since the page read it (`version`, a hash of its text)."""

import hashlib
import os
import subprocess
import tomllib
from typing import Any, Dict, List, Optional

from . import home, sessions

#: The environment variables that override the model's settings in the file, for the processes that have them.
LLM_ENV = (("AG_LLM_MODEL", "model"), ("AG_LLM_URL", "api_base"), ("AG_LLM_KEY", "key"))


class SettingsError(ValueError):
    pass


def path() -> str:
    return os.path.join(home.HOME, "config.toml")


def _version(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _text() -> Optional[str]:
    try:
        with open(path(), encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return None


def read() -> Dict[str, Any]:
    """The settings as the page shows them: the file's text and `version`, and what it says, read --
    `error` when it does not parse. `exists` is False before ag first ran here."""
    text = _text()
    out: Dict[str, Any] = {"path": path(), "exists": text is not None, "text": text or "",
                           "version": _version(text or ""), "error": "",
                           "env": {var: os.environ[var] for var, _ in LLM_ENV if os.environ.get(var)}}
    try:
        cfg = tomllib.loads(text or "")
    except tomllib.TOMLDecodeError as exc:
        cfg, out["error"] = {}, str(exc)
    pol, pol_ = _table(cfg, "policies"), _table(cfg, "pollers")
    llm = _table(pol, "llm")
    out["llm"] = {"model": str(llm.get("model") or ""),
                  "api_base": str(llm.get("api_base") or llm.get("url") or ""),
                  "key_env": str(llm.get("key_env") or "")}
    out["policies"] = {"default": str(pol.get("default") or ""), "available": sorted(_table(pol, "available"))}
    pollers = pol_.get("default")
    out["pollers"] = {"default": [str(p) for p in pollers] if isinstance(pollers, list) else [],
                      "available": sorted(_table(pol_, "available"))}
    cli = _table(cfg, "cli")
    out["cli"] = {"gatherer": str(cli.get("gatherer") or ""),
                  "harnesses": {name: {k: v for k, v in entry.items() if isinstance(v, (str, int, float, bool, list))}
                                for name, entry in _table(cli, "harnesses").items() if isinstance(entry, dict)}}
    return out


def _table(cfg: Any, key: str) -> Dict[str, Any]:
    t = cfg.get(key) if isinstance(cfg, dict) else None
    return t if isinstance(t, dict) else {}


def set_model(model: str, api_base: Optional[str] = None, key_env: Optional[str] = None) -> Dict[str, Any]:
    """[policies.llm] set by `ag model` -- which makes config.toml if there is none, and says what the
    model runs on: the settings, with `said`, its words. api_base / key_env None: left as they are;
    "": removed."""
    model = (model or "").strip()
    if not model:
        raise SettingsError("name a model, e.g. claude-code/sonnet or gemini/gemini-3.8-flash")
    args = [model]
    for flag, value in (("--api-base", api_base), ("--key-env", key_env)):
        if value is not None:
            args += [flag, value.strip()]
    try:
        done = subprocess.run([*sessions.ag_command(), "model", *args], env=sessions.agent_env(), capture_output=True,
                              text=True, timeout=60, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SettingsError(f"could not run ag: {exc}") from exc
    except sessions.SessionError as exc:
        raise SettingsError(str(exc)) from exc
    if done.returncode != 0:
        raise SettingsError((done.stderr or done.stdout).strip() or f"ag model exited {done.returncode}")
    return {**read(), "said": done.stdout.strip()}


def _toml(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(_toml(v) for v in value) + "]"
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return str(value)


def _header(line: str) -> Optional[str]:
    s = line.strip()
    if s.startswith("[") and not s.startswith("[[") and "]" in s:
        return s[1:s.index("]")].strip()
    return None


def _value_end(rest: str) -> int:
    """Where the value that starts `rest` ends: before the first `#` that leaves a value on its own
    (a `#` inside a string does not), else the end."""
    at = rest.find("#")
    while at != -1:
        try:
            tomllib.loads("x = " + rest[:at])
            return at
        except tomllib.TOMLDecodeError:
            at = rest.find("#", at + 1)
    return len(rest)


def set_key(text: str, section: str, key: str, value: Any) -> str:
    """`text` with `key` in [section] set to `value`: its line's value replaced, its comment kept; a
    line added under the section's header when it has none, the section added at the end when the
    file has none."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if _header(line) == section), None)
    if start is None:
        return text.rstrip("\n") + f"\n\n[{section}]\n{key} = {_toml(value)}\n"
    end = next((i for i in range(start + 1, len(lines)) if _header(lines[i]) is not None), len(lines))
    for i in range(start + 1, end):
        head, eq, rest = lines[i].partition("=")
        if eq and head.strip() == key and not head.lstrip().startswith("#"):
            cut = _value_end(rest)
            comment = rest[cut:]
            new = f"{head.rstrip()} = {_toml(value)}"
            lines[i] = new + ((" " * max(1, len(head) + 1 + cut - len(new)) + comment.lstrip()) if comment.strip() else "")
            return "\n".join(lines) + "\n"
    lines.insert(start + 1, f"{key} = {_toml(value)}")
    return "\n".join(lines) + "\n"


def _write(text: str, version: str) -> None:
    """config.toml written as `text`, when it still is what the page read (`version`) and `text` parses."""
    if _version(_text() or "") != version:
        raise SettingsError("config.toml changed since this page read it: reload the settings and try again")
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SettingsError(f"not saved, it would not parse: {exc}") from exc
    os.makedirs(os.path.dirname(path()), exist_ok=True)
    tmp = path() + ".dashboard"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path())


def set_defaults(version: str, policy: Optional[str] = None, pollers: Optional[List[str]] = None,
                 gatherer: Optional[str] = None) -> Dict[str, Any]:
    """[policies] default, [pollers] default, [cli] gatherer: each given set, the rest of the file kept."""
    if _text() is None:
        raise SettingsError("ag has made no config.toml here yet: set the model first, or run ag once")
    now = read()
    text = now["text"]
    if policy is not None:
        if policy not in now["policies"]["available"]:
            raise SettingsError(f"no policy {policy!r} among [policies.available]")
        text = set_key(text, "policies", "default", policy)
    if pollers is not None:
        unknown = [p for p in pollers if p not in now["pollers"]["available"]]
        if unknown:
            raise SettingsError(f"no poller {', '.join(unknown)} among [pollers.available]")
        text = set_key(text, "pollers", "default", list(pollers))
    if gatherer is not None:
        gatherer = gatherer.strip()
        if gatherer != "." and not sessions.GATHERER.fullmatch(gatherer):
            raise SettingsError("a gatherer's name may hold letters, digits, '.', '_' and '-' only (\".\": one per session)")
        text = set_key(text, "cli", "gatherer", gatherer)
    _write(text, version)
    return read()


def save_text(text: str, version: str) -> Dict[str, Any]:
    """config.toml replaced by `text`, as the reader edited it."""
    _write(text if text.endswith("\n") else text + "\n", version)
    return read()

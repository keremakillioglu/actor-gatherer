"""The tool calls and results in a harness's messages, whichever harness: Claude Code's (Anthropic
Messages: `tool_use` and `tool_result` blocks) or codex's (Responses items: `function_call`,
`custom_tool_call`, `local_shell_call` and their outputs) -- as the dashboard reads them from the
stored events (ag_dashboard/data.py's `parts`), here from the messages themselves. A codex
code-mode call (`exec`) is one call to its harness, but its script makes others: `opened` reads them
out of it (commands.opened_script), for what they do to files."""
import json
from typing import Any, Dict, List, Optional, Tuple

from .commands import CODE_MODE, opened_script

CALLS = ("function_call", "custom_tool_call")
OUTPUTS = ("function_call_output", "custom_tool_call_output")


def _blocks(items) -> List[dict]:
    """Every block among the messages or items: a message's content blocks, an item as it is."""
    out = []
    for x in items or []:
        if not isinstance(x, dict):
            continue
        if isinstance(x.get("content"), list) and x.get("role") and x.get("type") in (None, "message"):
            out += [b for b in x["content"] if isinstance(b, dict)]
        else:
            out.append(x)
    return out


def _arguments(raw):
    """A codex call's arguments: a JSON string, read as its object when it is one."""
    if isinstance(raw, str):
        try:
            got = json.loads(raw)
            return got if isinstance(got, dict) else raw
        except ValueError:
            return raw
    return raw


def _output(value) -> str:
    """A tool result's words: a string, or the text of its blocks ("[image]" for an image)."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        words = []
        for b in value:
            if isinstance(b, str):
                words.append(b)
            elif isinstance(b, dict):
                if isinstance(b.get("text"), str):
                    words.append(b["text"])
                elif b.get("type") in ("image", "input_image"):
                    words.append("[image]")
        return "\n".join(words)
    if isinstance(value, dict):
        for k in ("output", "content", "text"):
            if k in value:
                return _output(value[k])
    return "" if value is None else json.dumps(value, ensure_ascii=False)


def calls_in(items) -> Dict[str, Tuple[str, Any]]:
    """The tool calls among the messages (or an answer's items), by id: (name, input)."""
    out = {}
    for b in _blocks(items):
        t = b.get("type")
        if t == "tool_use" and b.get("id"):
            out[b["id"]] = (str(b.get("name") or ""), b.get("input"))
        elif t in CALLS and (b.get("call_id") or b.get("id")):
            out[b.get("call_id") or b["id"]] = (str(b.get("name") or t), _arguments(b.get("arguments", b.get("input"))))
        elif t == "local_shell_call" and (b.get("call_id") or b.get("id")):
            out[b.get("call_id") or b["id"]] = ("local_shell", b.get("action") or {})
    return out


def results_in(items) -> Dict[str, Tuple[str, bool]]:
    """The tool results among the messages, by their call's id: (text, whether it failed)."""
    out = {}
    for b in _blocks(items):
        t = b.get("type")
        if t == "tool_result" and b.get("tool_use_id"):
            out[b["tool_use_id"]] = (_output(b.get("content")), bool(b.get("is_error")))
        elif t in OUTPUTS and b.get("call_id"):
            out[b["call_id"]] = (_output(b.get("output")), False)
    return out


def opened(calls: Dict[str, Tuple[str, Any]], results: Optional[Dict[str, Tuple[str, bool]]] = None):
    """(calls, results): those given, each codex code-mode script among the calls in place of the calls it
    makes (commands.opened_script: by the script's id, or `<id>#<n>` for several), and each of those with
    its own result, where the script's came in. A script whose calls can't be found stays as it is."""
    out_calls, out_results = {}, dict(results or {})
    for cid, (name, inp) in calls.items():
        inner = opened_script(cid, inp, out_results.get(cid)) if name == CODE_MODE and isinstance(inp, str) else []
        if not inner:
            out_calls[cid] = (name, inp)
            continue
        out_results.pop(cid, None)
        for iid, iname, iinp, result in inner:
            out_calls[iid] = (iname, iinp)
            if result is not None:
                out_results[iid] = result
    return out_calls, out_results


def last_results(items) -> List[str]:
    """The ids of the results the messages end with -- after the last thing the model said: those of
    the calls its last answer made."""
    ids = []
    for x in reversed(items or []):
        if not isinstance(x, dict):
            continue
        if x.get("role") == "assistant" or x.get("type") in CALLS + ("local_shell_call", "reasoning"):
            break
        for b in reversed(_blocks([x])):
            if b.get("type") == "tool_result" and b.get("tool_use_id"):
                ids.append(b["tool_use_id"])
            elif b.get("type") in OUTPUTS and b.get("call_id"):
                ids.append(b["call_id"])
    return ids[::-1]

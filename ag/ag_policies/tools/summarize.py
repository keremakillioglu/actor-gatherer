"""Record what each task ESTABLISHED that outlives it.

One model call per task, in parallel: object handling, terminology, metadata and standing
instructions the user set there -- most tasks establish nothing -- and each of
the task's user messages, verbatim but with its boilerplate removed (the wrapper
a harness or template puts around every request), for showing the requests
without the repeated scaffolding.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import List

from ag.ag_interface import LLM
from .groups import AGENT_MESSAGE, TOOL_CALL, TOOL_OUTPUT
from .answers import find_object, pairs
from .history import Task, Turn

@dataclass
class Params:
    """What summarizing is told: how many at once, and which model to ask."""
    workers: int = 0                      # 0 = one thread per task
    model: str = ""
    effort: str = "high"
    timeout: int = 900


FIELDS = ("object_handling", "terminology", "metadata", "carry_forward")
CLEANED = "cleaned_user_messages"        # [{"turn": <turn index>, "text": <the message, cleaned>}]

SUMMARIZE_PROMPT = """\
Below is ONE task from a past agent session -- the user's requests, the agent's
replies, and the tool calls it made -- together with how it has already been
named and described. The session may be about anything: querying data, changing
code, configuring a system, running tools. Nothing below assumes one of those.

Report ONLY what the user ESTABLISHED here that outlives this task. Later work in
this session gets your answer WITHOUT these turns, so anything you leave out is
lost.

An OBJECT is anything addressable in the agent's environment: a database, table
or column, a JSON path, a file or directory, a function, class or module, a
command, flag or config key, a service, a test.

# The task

**{name}** (turns {first}-{last}) -- {description}

{window}

# What to return

Return ONLY a JSON object, no prose and no code fence:

{{"object_handling": [{{"applies_to": "<the object it governs>",
                      "spec": "<how that object must be treated>"}}],
  "terminology":     [{{"applies_to": "<the term the user defined>",
                      "spec": "<what the user said it means>"}}],
  "metadata":        [{{"object": "<the object described>",
                      "value": "<the descriptive fact the user gave about it>"}}],
  "carry_forward":   [{{"applies_to": "<what it applies to, or \"any future work\">",
                      "spec": "<the explicit instruction for future work>"}}],
  "cleaned_user_messages": [{{"turn": <the turn number>,
                             "text": "<the user's message, verbatim, boilerplate removed>"}}]}}

What belongs in each:
- `object_handling` -- how an object must be TREATED: read, filtered, cleaned,
  counted, joined, built, run, edited, named, ordered.
- `terminology` -- a term the USER DEFINED, and what they said it means.
- `metadata` -- a descriptive FACT the user gave about an object: what it holds,
  where it lives, how it behaves, what it is for.
- `carry_forward` -- an EXPLICIT INSTRUCTION about what to do in future work.
- `cleaned_user_messages` -- EVERY user message of this task, one entry per
  `USER:` turn above, in order, with its turn number: the message's content
  VERBATIM, with only its BOILERPLATE removed. Boilerplate is text that is not the
  request itself but wraps it, the same on request after request: a fixed preamble
  or notice (e.g. which directory to read from), a standard instruction about how
  or where to deliver the answer, the template's field labels. Keep every word
  the user actually said about the work, exactly as written -- do not paraphrase,
  shorten, correct, translate or summarise it -- and keep anything specific to this
  one request that later work may refer to (an id it is known by, the database or
  file it is about). If a message has no boilerplate, return it unchanged. This
  field is never empty when the task has user messages.

Rules:
- MOST TASKS ESTABLISH NOTHING. Return [] for each of the first four fields unless the user
  indicated something should keep applying beyond these turns -- a correction, a
  "from now on", a "use X not Y", a definition they supplied. It also counts when
  the user CONFIRMS a choice the agent made where the environment left a real
  alternative (which config file to read, which flag to run a command with):
  record the confirmed choice. Do not record a step merely because the work
  happened to be done that way.
- MAKE IT ACTIONABLE. A later task gets your spec without these turns, so write
  it so someone holding only the environment could act on it directly:
    - resolve a name the user used to the CONCRETE object it refers to, with the
      path if nested: "net revenue" becomes "invoices.amounts $.settled.net_cents";
      "the parser" becomes "src/feed/parse.py::parse_entry";
    - give relationships as PREDICATES -- "orders.customer_id = customers.id" --
      never as a dotted path like "orders.customers.regions", which names no real
      object;
    - give conditions as comparisons: "regions.status = 'active'", "quantity > 0",
      "only when --strict is passed";
    - name the key or unit of work: "grouping on customers.id", not "per customer";
      "per changed file", not "for each thing".
  Take these from what was ACTUALLY RUN above -- the queries, commands and edits.
  Where a later turn replaced an earlier one, record the FINAL form and say what
  it replaced.
- NO DUPLICATES across the four fields: record each thing once, in the field
  that fits it best.
- ONE RULE PER ENTRY, and prefer `object_handling`. Split what the user
  established into separate entries -- one per thing a later task would have to
  get right -- rather than packing the whole method into a single long entry.
  Most of what a task establishes is `object_handling`: which figures or files to
  use, which rows or cases to keep or drop, how to treat a missing value, what to
  group on, which command or flag to run it with. Give each its own `applies_to`
  naming the specific object it governs.
  Reserve `carry_forward` for the standing instruction ITSELF -- what the user
  said to keep doing, and what future work it applies to -- not for a restatement
  of the rules above it.

  So for a task where the user fixed a metric over several turns:

    object_handling: <the source figures>       -> use X not Y, reached by <join>
    object_handling: <the normalisation>        -> divide by Z, require Z > 0
    object_handling: <the missing-value rule>   -> COALESCE the count to 0
    object_handling: <the duplicate rule>       -> average per <key>, not the maximum
    carry_forward:   <the future work it binds> -> use the metric established here

  And for a task where the user fixed how the project is tested:

    object_handling: the fixture directory      -> tests/fixtures/, regenerated by `make fixtures`
    object_handling: the lint step              -> run ruff before pytest, never after
    carry_forward:   any future test changes    -> keep that order

  Several short, separately-scoped entries -- NOT one entry containing all of it.
"""


def render_turn_full(turn: Turn) -> str:
    """A turn as summarizing sees it: every message, and the tool calls and
    their output, truncated."""
    lines = [f"### turn {turn.index}", f"USER: {turn.user_text[:4000]}"]
    for e in turn.entries[1:]:
        if e.type == TOOL_CALL:
            lines.append(f"[tool call] {e.text[:3000]}")
        elif e.type == TOOL_OUTPUT:
            lines.append(f"[tool output] {e.text[:750]}")
        elif e.type == AGENT_MESSAGE and e.text.strip():
            lines.append(f"AGENT: {e.text[:4000]}")
    return "\n".join(lines)


def cleaned_messages(value) -> list:
    """`[{"turn": int, "text": str}]` from the model's `cleaned_user_messages`, in turn order;
    an entry without an int turn or a string text is dropped."""
    out = []
    for x in value if isinstance(value, list) else []:
        if isinstance(x, dict) and isinstance(x.get("text"), str):
            try:
                out.append({"turn": int(x.get("turn")), "text": x["text"]})
            except (TypeError, ValueError):
                continue
    return sorted(out, key=lambda x: x["turn"])


def parse_retention(text: str) -> dict:
    """The four lists, and the cleaned user messages, from a model answer; all empty if it
    is not JSON."""
    empty = {**{f: [] for f in FIELDS}, CLEANED: []}
    data = next((d for d in (find_object(text, f) for f in (*FIELDS, CLEANED)) if d is not None), None)
    if data is None:
        return empty
    return {"object_handling": pairs(data.get("object_handling"), "applies_to", "spec"),
            "terminology": pairs(data.get("terminology"), "applies_to", "spec"),
            "metadata": pairs(data.get("metadata"), "object", "value"),
            "carry_forward": pairs(data.get("carry_forward"), "applies_to", "spec"),
            CLEANED: cleaned_messages(data.get(CLEANED))}


def summarize_one(task: Task, turns: List[Turn], llm: LLM, cfg: Params) -> dict:
    span = [t for t in turns if task.start_turn <= t.index <= task.end_turn]
    prompt = SUMMARIZE_PROMPT.format(name=task.name, first=task.start_turn, last=task.end_turn,
                                  description=task.description,
                                  window="\n\n".join(render_turn_full(t) for t in span))
    return parse_retention(llm.complete(prompt, model=cfg.model,
                                        effort=cfg.effort,
                                        timeout=cfg.timeout, purpose="summarize"))


def summarize(tasks: List[Task], turns: List[Turn], llm: LLM, cfg: Params) -> List[Task]:
    """Fill each task's `retention` (in place, and returned)."""
    if not tasks:
        return tasks
    workers = cfg.workers or len(tasks)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(lambda t: summarize_one(t, turns, llm, cfg), tasks))
    for task, retention in zip(tasks, results):
        task.retention = retention
    return tasks

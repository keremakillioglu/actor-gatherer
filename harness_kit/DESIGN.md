# Harnesses as events: design

The design behind `harness_kit/` and the events ag's hooks record, as built so far. It follows the design doc
"Harnesses as events: design" (a Claude Doc), and says where the build went another way and why. Steps 1–3 of
its order of work are built (the first PR); steps 4–7 are not.

## Goal

Every fact ag learns about a harness session becomes an event in the gatherer, inserted by ag's integration for
that harness, and the dashboard reads only events. Before this work the rules that recognise each kind of message
sat in about 15 files across the hooks, the adaptors, the dashboard and the page, and the dashboard read Claude
Code's and Codex's session files itself (`queued.py`, `rollout.py`).

- **One store.** What the model was sent, its replies, side calls, the harness's own session file and files changed
  on disk all become events. ag's tables for its own work stay: reads, made items, preambles, polls, claims, and
  `_withdrawn` (#133), which changes what a read sees and so is ag's own work, not a record of the harness's.
- **Two families of events.** Conversation events are what the model is sent: the six types the policy reads.
  Harness events (records) are everything else, types the policy groups none of, so they never reach a context.
- **Harness facts live outside ag**, one module per harness, standard library only.
- **The integration inserts, the dashboard reads.** The dashboard never reads a harness's files or parses its text.
- **Rules carry their version**: each harness names the version its rules were read from (`checked_with`), and each
  call records the version that made it (`model_call.version`).

## Three layers

| Layer | Where | Holds | Imports |
|---|---|---|---|
| Harness module | `harness_kit/` (top level, beside `ag/` and `ag_dashboard/`) | facts true without ag: what each call is, which text is the harness's own, what each tool does, the shell parser | the standard library only (`tests/test_harness_kit.py`) |
| ag integration | `ag/integrations/harnesses/<name>/`, `ag/integrations/tools/ag_orchestrator/` | event ids, `to_messages`, the hook flow (`ProxyHook`), the records it inserts | `harness_kit`, ag |
| Policy binding | attributes of the harness's adaptor | which event type each `Kind` becomes (`event_types`, `other`), `outputs`, `accepts`, `properties`, `event_properties` | ag |
| Dashboard | `ag_dashboard/` | reads events, draws them, sends actions | `harness_kit`; nothing of ag (`test_dashboard.SeparateTest`) |

`harness_kit` is the package's name: `harnesses`, the name the doc proposed, is taken on PyPI (so are
`agent_harnesses` and `agent-harnesses`). `pyproject.toml` finds it beside `ag*`.

## The Harness class (`harness_kit/base.py`)

```python
class Harness(ABC):
    name = "claude"; label = "Claude Code"; checked_with = "2.1.310"

    # Level 1: one model call
    def call(self, method, path, headers, body) -> Optional[Call]: ...   # None: no model call
    def title(self, reply: List[Part]) -> Optional[str]: ...             # default: the reply's words
    def recap(self, reply: List[Part]) -> Optional[str]: ...             # default: the reply's words

    # Levels 2 and 3: its pieces, and the tool calls among them
    @abstractmethod
    def items(self, history: list) -> list: ...
    @abstractmethod
    def read(self, items: list) -> List[Part]: ...
    def read_one(self, payload) -> List[Part]: ...                       # a stored piece, its neighbours unknown
    def words(self, text: str) -> tuple: ...                             # (Kind, the user's words as typed)

    # A stored piece's harness, by its shape
    @abstractmethod
    def owns(self, payload) -> bool: ...
```

- `Call(kind, session, cwd, version, history, own, detail)`: `kind` one of TURN, SUBAGENT, SUGGESTION, RECAP,
  TITLE, COMPACTION, OTHER; `own` the call's own messages after the conversation (a suggestion's prompt, a
  compaction's instruction). Claude Code's version comes from its User-Agent (`claude-cli/<v>`), Codex's from
  its (`codex-tui/<v>` from its terminal, `codex_exec/<v>` from `codex exec`).
- `Part(kind, role, text, words, tool, result, cwd, opaque, detail)`. Against the doc: what a kind says besides
  its words is in `detail` (a skill's name and arguments; a report's sender; task notices; the files a note
  loads), and what an asking call asks is on its `ToolCall.ask`, not on the part.
- `ToolCall(id, name, input, action, paths, ask)`, `ToolResult(call_id, error, output, task)`, as the doc has
  them; `task` is a background task a result says started, resumed or was stopped.
- `words(text)` is new: the History outline and the actor list have only an event's text, not its payload.
- `owns(payload)` is new, and is the `recognizes` the user said is not needed: ag now records which harness made
  each call (`model_call.harness`), and the dashboard reads that first. `owns` stays only for events stored before
  `model_call` existed, and goes with step 6, once those channels have their harness recorded.

Not built yet: `record_path` and `follow` (step 4), `answer_keys`, `command` and `models` (step 5).

### Kinds

The doc's kinds, and five more the old rules told apart that the doc's list folded into others:

| Kind | Claude Code | Codex |
|---|---|---|
| USER, USER_COMMAND | the user's words; `! ls`, `/greet Bob` | the user's words |
| MID_TURN (new) | written while the turn ran, sent into it | none |
| ASK_REPLY | none | `<send_user_message_question_reply>` |
| AGENT, REASONING, TOOL_CALL, TOOL_RESULT | its blocks | its items |
| ENVIRONMENT | `<system-reminder>`, a system-role message | `<environment_context>`, AGENTS.md, developer messages |
| COMMAND_PROMPT (new) | the prompt a typed `/name` expands to | none |
| LOCAL_COMMAND (new) | `/context`, `/mcp`: run by Claude Code itself | none |
| COMMAND_OUTPUT | `<bash-stdout>`, `<local-command-stdout>`, /context's report | `<user_shell_command>` |
| ATTACHMENT_NOTE, INTERRUPT, SKILL | as the doc says | `<turn_aborted>`, `<skill>` |
| AGENT_REPORT, PEER_MESSAGE | a subagent's hand-back; another session's message | `agent_message` items (FINAL_ANSWER, or any other) |
| TASK_NOTICE, RETRY_NOTE | `<task-notification>`; its notes after a response went wrong | none |
| HOOK_FEEDBACK (new) | "Stop hook feedback:" and the like | `<hook_prompt` |
| TOOL_NOTICE | "Tool loaded."; tools added or removed (a system-role `tool_addition`) | `additional_tools` |
| COMPACTION_SUMMARY, COMPACTION_REPEAT | its summary (after its "others wrote" notice, #131), and what it sends again | its compaction item, and what precedes it |
| OTHER (new) | anything else of its own | anything else |

The adaptors map them as before: the user's kinds to `user_message`, the model's to their own types, every other
to `context`. A policy that wants skills or interrupts as types of their own subclasses the adaptor and changes
`event_types`.

## The events (step 2 and step 3)

**Conversation events** carry, as properties of their own, what the rules read of them: `kind`, `words` (the
user's words as typed), `action` (a tool call's) and `call_id` (a call's, or the call a result answers). The
adaptor declares them as `event_properties`; `call_ag` refuses any other. Against the doc: no launch-time check
changed. The server declares each on the event's type, optional, the first time it sees it, so no policy has to
declare them, and none is part of an event's identity.

**Records** (`ag/integrations/tools/ag_orchestrator/records.py`), inserted by the hooks with the server's
`insert`, in the session's own lane (#134):

| Type | Properties | Payload | Id |
|---|---|---|---|
| `model_call` | `read_id` | kind, harness, version (Codex's side calls: `source`) | new each time |
| `reply_part` | `answer_id` | the conversation event the part will be: type, payload, text, properties | answer id and place |
| `reply_end` | `answer_id`, `read_id` | stop | answer id |
| `call_failed` | `read_id` | status (499: the harness hung up, #133), error | its read |
| `recap` | | text | new each time |
| `name` | | text, by | new each time |

Against the doc's "Changes to ag's core":
- **No `records` declaration.** The store already registers a type the first time it sees it, and a policy loads
  only the types it groups, so the records needed no declaration and no launch check. A policy that put one of
  them in a group would see them; nothing refuses that yet.
- **`latest` takes `types`.** Claude Code's ids are chained from the channel's last stored events (#125); with
  records among them the chain would break, so the hook asks for the conversation's types alone.
- **The old ops stay.** The hooks no longer call `pending`, `failed`, `recap` or `name` (nor did the TypeScript
  plugins), but a hook server keeps its old code until it restarts, so they stay until step 6, as does
  `call_ag.pending_ag` / `report_failed`.

## The hooks: one ProxyHook

`ProxyHook` (`ag/integrations/tools/ag_orchestrator/proxy_hook.py`) holds what both hooks did alike: recording
every call (`model_call`), a reply's parts as they stream and its end (`reply_part`, `reply_end`), a failed call
(`call_failed`), a side call's recap or title (`side_answered`), and the files a call touched (`before_end`).
Each subclass keeps its own flow: Claude Code's continuity of ids, claims, counting, suggestions and compaction;
Codex's runs, side calls and compaction. On a hang-up (499) the Claude hook also withdraws what the call stored
(#133).

## The dashboard

It reads records where a channel has them, and the old tables where it has not: what is pending (`replies`:
`reply_part`s after the newest conversation event, ended or not; a part that broke off is dropped at the next
turn's call, as `_pending` dropped it), whether a turn is over, a failing or hung-up call (`_newest_reads`), the
recap, the name, the harness. It leaves records out of every view of the conversation (`NOT_RECORD`). The user's
words come as typed, with their kind, from the `words` and `kind` properties, else from `Harness.words`; the page
no longer parses Claude Code's or Codex's wrappers.

It still reads the harnesses' session files: Claude Code's queue and prompts sent between turns (`queued.py`,
#129 added the prompts), its record for questions settled, Esc and given-up calls (`data.py`), and Codex's
rollout (`rollout.py`). Step 4 replaces those reads.

## Order of work

The doc planned a PR per step. Steps 1–3 went into one PR: they were built together while `main` moved under them
(#127–#137), and the dashboard reads the records only once step 3 inserts them.

1. **Built.** The harness package, the rules moved as they were; one shell parser (`harness_kit/shell.py`).
2. **Built.** Conversation events carry `kind`, `words`, `action`, `call_id`.
3. **Built.** Calls and replies as records; `ProxyHook`.
4. **Next.** The session-file watcher in the hook server: `ask_settled`, `turn_stopped`, `message_queued` /
   `sent` / `withdrawn` (Claude Code's prompts sent between turns, #129, among them), Codex's asks and tasks.
   Then `queued.py`, `rollout.py` and the dashboard's session-file reads go. It needs the harness's config folder
   in the hook server's URL, from the launcher.
5. Derived and dashboard events: `asked`, `task_started` / `task_ended`, `file_touched` (with
   `file_touches/calls.py` reading calls from `Part.tool`, which it still parses itself), `chat_sent`,
   `answer_given`, `terminal_input`. The status rules move to events. Open: does the dashboard insert its own
   action events through ag's server, or tell the hook server to (the comment in the doc)?
6. Old tables: copy `_recaps`, `_names`, `_touches`, `_pending` and `_reads.error` into records, record each old
   channel's harness; then drop the dashboard's fallbacks, `Harness.owns`, and the old ops.
7. Fixtures per harness version, and a probe that triggers each feature live.

## Open questions

- Sessions run outside ag's launcher: the watcher learns a session's file from the launcher's URL.
- How often `task_activity` is recorded.
- `codex exec` exits once it has its final answer, before the hook server is through with it, so since #133 that
  last call is recorded as a hang-up (499) and the run shows as interrupted rather than over.
- Pi and OpenCode: their plugins would insert the records themselves; neither inserts any yet.

# Dashboard: future work

## Waiting for you

An actor shows as waiting for the user when its latest answer from the model calls `AskUserQuestion` or
`ExitPlanMode` and no result has come back yet (data.py's `asking`). It stops waiting once Claude Code's own
record of the session has the call's result (`settled`). Where the dashboard runs the session's terminal, the
note under the chat answers it: the keys are worked out from the tool call (answers.py) and typed into the dialog
one at a time (sessions.py's `answer`).

Not detected yet: the actor shows as Running while Claude Code waits.

- [ ] **Permission prompts** ("Do you want to proceed?"). They never appear in what ag records. Claude Code's
  `Notification` hook fires with `permission_prompt` when the dialog opens. ag's launcher could add that hook
  for the run with `--settings`: it runs alongside the user's own hooks without replacing them, and it can POST
  to the hook server ag already runs. The wait ends at the next model call, when a hook says the tool ran,
  failed or was denied, or when keys are typed into the dashboard's terminal.
- [ ] **Other dialogs**, such as an MCP server asking for input (elicitation). The same hook may cover some.
- [ ] **Codex's approval prompts** ("Would you like to run the following command?"). Codex writes nothing of them to
  its rollout file, and ag records only the model's call asking for `require_escalated`. The dashboard runs codex
  with `--approve-for-me`, which sends them to codex's reviewer, so its own terminals never show one; a codex run
  elsewhere with another approval policy does. Codex 0.164 has a `PermissionRequest` hook (hooks.json), which may
  be the way in, as Claude Code's `Notification` is for its permission prompts.

### Codex

Codex asks in three ways, all read from its own record of the thread (rollout.py: `<CODEX_HOME>/sessions/.../rollout-
<time>-<thread>.jsonl`, written as codex goes) and answered by keys typed into the dashboard's terminal (answers.py):

- **A question** (`request_user_input`, Plan mode's; its turn waits): from ag's pending answer, as Claude Code's
  are, until the record has its output -- answered, or "aborted by user" (Esc). Single choice only: codex adds "None
  of the above", with a note in the user's own words.
- **A question asked as it works** (`request_user_input_async`): shown while that turn runs, the actor still Running.
  Once the turn ends it can no longer be opened in the terminal, and the user simply writes back.
- **The plan a Plan-mode turn proposed** ("Implement this plan?", drawn once the turn is over): shown only where
  the dashboard runs the terminal, it opened before the plan, and nothing was typed into it since. Codex records
  neither the prompt nor its dismissal (Esc), so outside that the plan is not known to be asked about. A message
  from any view while it is asked is "No, stay in Plan mode" plus the message (server.py's `codex_dialog`): typed
  as it is, its Enter would have implemented the plan. A message while codex waits on a question there is refused.

Not covered yet:

- [ ] **"Yes, clear context and implement"** (the plan's choice 2) starts another thread: left to the terminal.
- [x] **Codex's wrappers in the Chat view**: a `<proposed_plan>` is drawn as a card headed "Proposed plan"
  (page.html's `markdown`), and the answers to what codex asked as it worked as "question → answer" (`asked`), part
  of the turn that asked (files.py, rollout.py's `replies`).
- [ ] **A question in a codex terminal outside the dashboard** is shown but not answerable, as Claude Code's are.
- The keys are codex 0.164's. As for Claude Code, what codex records is checked against what was picked
  (`recorded`), so a change shows up as a warning.

Shown, but not answerable from the page:

- [ ] **The message-box sessions** (`claude -p --input-format stream-json`, with no terminal). It is untested
  what Claude Code does with `AskUserQuestion` there.
- Sessions in a terminal outside the dashboard: answered there. Nothing can type into that terminal.
- A dashboard terminal with keys typed into it since the question appeared: finished there, because the
  dialog may no longer be as it first showed.

Choices the note does not offer yet (each needs one short live test of its keys):

- [ ] "Chat about this" on a question: the option two past the last one. It rejects the question and the model
  asks what to clarify.
- [ ] The user's own words on a multi-choice question. How "Type something" combines with the ticks is unknown.
- [ ] Approving a plan with feedback (Shift+Tab). Editing the plan (Ctrl+G) opens Vim in the terminal, so it is
  left to the terminal.

Assumptions to check against new Claude Code versions:

- The dialog's keys, and the three plan choices, are the ones Claude Code 2.1.310 shows (answers.py). The page
  checks what Claude Code records against what was picked (`recorded`) and warns on a difference, so a change
  shows up as a warning rather than a wrong answer passing silently.
- The session record (`<config>/projects/<dir>/<session>.jsonl`) and the plan files (`<config>/plans/`) are read
  from the dashboard's own `CLAUDE_CONFIG_DIR`. A session run with another config dir keeps showing its question
  until its next model call, and shows no plan text.

## Stopped on an error

A model call that fails is kept on its read (`_reads.error_status`, `_reads.error`) by ag's hook server, whether the
endpoint answered an error or could not be reached; one that got no answer at all is answered 502 with why, where
the harness would otherwise get a bare 500. The actor shows Running with a note while the harness tries again
(data.py's `failing`), and Error once it gives up: Claude Code's record of the session ends with its API error
(`stopped`), or no try comes for GIVE_UP_SECONDS -- Esc while Claude Code waits to try again stops it without a word
in its record. The same record shows a turn the user
interrupted (Esc) as Idle, where ag's record would go on running.

Not covered yet:

- [ ] **An answer the endpoint breaks off once it has begun** is not kept as a failure. The harness hanging up is
  now told apart (see "Stopped before the answer"); the endpoint breaking off is not. Claude Code's record still
  shows the give-up; for codex it shows as Running until its next call.
- [x] **Codex's own record** (its rollout file, rollout.py) is read: a turn that gave up (`task_complete` with an
  `error`) is Error at once, one interrupted (`turn_aborted`) or completed with no call ag saw is Idle.
- [ ] **Calls with no read** (Claude Code's compaction, recaps) are not kept when they fail.
- [ ] **A session whose record is elsewhere** (another `CLAUDE_CONFIG_DIR`, another machine) waits GIVE_UP_SECONDS
  for Error, and an interruption there is not seen.

## Stopped before the answer (Esc)

Esc before any of the answer's text has come: Claude Code puts the user's message back in its input box, writes
nothing to its record, and drops the call. ag's hook server sees the harness hang up (`hung_up`, looked at every
0.25 s while the model is quiet): the call is not sent on, or is broken off, and is kept on its read as 499. The
actor shows Idle (data.py's `hung_up`). The events the call stored are withdrawn (`_withdrawn`, the server's
`withdraw`): in no read, not in `latest`, and not in Chat, until the harness sends one again -- as Claude Code does
when it kept the message (Esc once some text had come). A message sent from the Chat right after such an Esc first
empties Claude Code's input box with Ctrl+C (sessions.py's `took_back`), so it does not go out joined to the one
put back.

Not covered yet:

- [ ] **Idle only once ag's read for the call ends.** The hook reports the hang-up with the read's id, so a call
  stopped while ag still reads waits for that read: seconds on a busy gatherer. The hang-up could be kept at once
  and tied to its read after.
- [ ] **Claude Code's rewind** (Esc Esc, /rewind): the conversation goes back to an earlier message and on from
  there. ag keeps the branch left behind in every later context. Where Claude Code's notes follow the new message
  (a session's first turn), the Claude adaptor's Continuity can even take the new message for one stored and not
  send it -- the shape the withdrawn calls had. It needs the fork found in the request: the stored chain's piece
  after the last common one differs from the request's, and is a user message (Claude Code rewriting its own notes
  on resume looks alike, but the notes are not the user's). The stored branch after the fork would then be withdrawn.
- [ ] **Codex, stopped before the answer:** the call is kept as 499 and shows Idle, but nothing is withdrawn: what
  codex does with the message (keeps it, or takes it back) is not checked.
- [ ] **A message taken back is not shown in Chat at all.** It is in Claude Code's input box; Chat could show it
  there, as "Taken back".
- [ ] **`took_back` knows only keys typed through the dashboard's terminal**, and relies on Claude Code 2.1.310
  emptying a non-empty input box on Ctrl+C (on an empty one it only says "press again to exit": never send two).

## Sent at once, in Chat

A message shows as sent the moment Claude Code sends it: queued.py reads the line Claude Code writes to its record
as it does (`{"type": "user", "origin": {"kind": "human"}}`), every 0.25 s for each actor a page shows, and the Chat
view draws it as its turn's first, with the actor at work, until ag stores the turn (data.py's `_unstored`).

Not covered yet:

- [ ] **Codex:** a message stays "Pending" until ag stores it. Codex's rollout file has the user's message as codex
  sends it, and could give the same.
- [ ] **The actor list's other actors** turn Running only when ag stores their message: Claude Code's record is read
  only for the actors a page shows.
- [ ] **In the event-based design**, "sent" would be an event the harness's adaptor writes. It must not wait in the
  gatherer server's lane behind the session's read, or the lag comes back.

## ag's server: what a model call waits for

Each session's requests run in a lane of their own (server's `serve`): one session's in order, sessions side by
side, so a read that waits for a check or a build holds only its own session. The file poller's watch leaves out
events with no text and searches each text once (file_changes.py's `names_in`): a read in making_ag went from 6.1 s
to 0.36 s.

Not covered yet:

- [ ] **A side call's context is read from a whole copy of the database** in memory (manager.py's `context_only`): in
  making_ag about 470 MB, and seconds, for every prompt suggestion and recap -- one at a time in the process. It could
  be read in the database itself and the policy's writes undone (a savepoint, rolled back).
- [ ] **Each request sets the manager up again:** `Manager.init` opens a connection and runs the schema's setup, and a
  new manager runs it again on its first use (`_conn`): about 60 ms an op, 5-6 ops a model call (measured before the
  lanes).
- [ ] **`history.rows` reads the whole events table**: its `(p_channel = ? OR p_channel IS NULL)` can't use the index
  (0.07-0.5 s a read in making_ag).
- [ ] **The watch's raw part reaches back to the oldest of every channel's latest reads** (row 374 of 24.7k in
  making_ag): one idle channel keeps nearly the whole history in it. Only channels read lately would cut the first
  watch from 1.4 s to 0.12 s, but a change to a file named only by an idle channel would go unreported.
- [ ] **A user message's read still waits for its task-boundary check** (sync_seconds), by choice: 3.2 s on average
  in making_ag, and 2 of 102 checks found a new task. Lanes keep it to the session.
- [ ] **A plugin poller holding something tied to the thread that made it** (a sqlite connection opened in its
  `__init__`) fails when another lane asks it.

## Context sizes: ag's count and the provider's

ag sizes every event and made item with its own tokenizer (tiktoken's o200k_base) when it stores it. After the call,
the Claude hook asks the API's count_tokens (counting.py) and stores Claude's count in its place (`counted`). A
read's size is the sum of what is stored at the time. The dashboard shows it beside the provider's count of the call.

Not covered yet (found 2026-10-26, on a90fe776 and 85d66f98 in making_ag):

- [ ] **Events older than a call's own are never counted.** `Counter.steps` counts at most STEPS_PER_CALL (25) new
  steps a call, and `event_ids` matches the request's blocks only to the events that call sent ag (`out["events"]`:
  the new ones and the ~20 stored before them). So "the rest after the next ones" never happens: anything a call
  stores beyond 25 steps keeps its tiktoken size for good. On 85d66f98, 143 of the 175 tool calls (and as many
  outputs) a resume stored were still uncounted hours later, ag about 94k under the provider. The store already
  names a context's uncounted events (`uncounted`); they need matching to the request's blocks by their stored ids.
- [ ] **What is not counted yet is ~35% low.** Claude makes 1.17-1.59 tokens per tiktoken token here, by kind
  (tool calls and output ~1.5, ag's sections ~1.3). Each call's newest events are low until counted, and a
  session's first call is low throughout: a90fe776's was 80.7k by ag's count, 100.7k by the provider's. A factor
  per gatherer and harness, learned from its counted items (Claude's count over tiktoken's), would size the
  uncounted ones.
- [ ] **Section budgets are in tiktoken tokens** (layout.py's `every_earlier_request`, `related_tasks`, `clip`), so
  by Claude's count every section is over its own: a90fe776's join build held "Every earlier request" to 40k at
  27.1k (35.2k by Claude's count) and its related tasks to 15k at 15.5k (21.6k). The same factor would bring them in.
- [ ] **The actor list and the monitor drop by the preamble while a call is out.** They show `real_tokens ??
  sent_tokens`, and `_agents`' `sent_tokens` (data.py's `_sent`) adds up the read's items only, without the tools
  and system prompt. Until the provider's count comes (1-4 s), an actor shows ~30k less, then jumps back: a busy one
  flickers. The Context view has it right (`counted_tokens`: `_reads.sent_tokens`, the preamble in it); the list
  and the monitor could show the same.
- [ ] **A hook server keeps running the code it started with, and nothing shows it.** 85d66f98's (:4122) started
  at 08:19, a minute before the checkout pulled #125 (ids from the stored history). Its resume at 12:50, with a
  message taken back by Esc, still went through the in-memory Continuity, which stored the session's history again
  (584 events, ~350k tokens; removed by hand, a backup kept). The hook server and ag's server could log, and give
  the dashboard, the commit they run, and the dashboard could say when one runs older code than the checkout.
- [ ] **Before its compaction, 85d66f98's ag count was ~12% over the provider's** (641k against 572k, build 75):
  not explained yet. A guess to check: thinking blocks counted but no longer sent.

## One process per session, on macOS

ag lets one process at a time run a session (`_open`, store/operations.py's `claim`): a second one -- another
terminal, the dashboard's chat -- is refused while the first runs, and the dashboard's chat agent, idle between
turns, gives way. A process is told by its id and when it started ("<boot id>:<start ticks>"), so a crashed
session's id, reused by another process later, does not hold the session forever. Both come from /proc
(store/processes.py's `identity`), which only Linux has.

- [ ] **On macOS no session is ever claimed, for either harness.** `identity` gives nothing there, so the claim
  answers `{"claimed": null}` and records nothing. Two processes can run the same session at once, each sending
  its own history; and `_reads.pid` stays empty, so the dashboard can't tell from it whether a session's process
  still runs.
  - **Claude Code:** the launcher claims a session it knows (`--resume <id>`, `--session-id`), and the hook claims
    at every call, by the process at the other end of the call's connection (hook_server/peer.py, which reads
    /proc/net/tcp). On macOS neither runs: the launcher's process can't be told, and the hook skips the claim
    when it has no process.
  - **Codex:** the launcher claims a thread resumed by its id (`resume <id>`). A new thread's id is codex's to
    choose, known only at its first call, and codex's hook does not claim at calls -- so a new thread is not
    claimed on Linux either, and `resume --last` or the picker neither.
  - **What it needs:** a process's start time on macOS (`sysctl` KERN_PROC_PID's `p_starttime`, through ctypes;
    or `ps -o lstart= -p <pid>`, to the second), with the boot time (`sysctl kern.boottime`) in place of the boot
    id. The caller's process then comes from the run in the URL, not the connection: codex's launcher already
    puts its process's id there (`/r/<run>/`, `request.run`) -- ag runs the harness in its own process, so the
    run is the harness's -- and Claude Code's launcher could do the same in ANTHROPIC_BASE_URL. Codex's hook
    could then claim at its thread's turns, as Claude Code's does, which covers new threads too.

## Codex

Checked live on codex 0.164 (gpt-5.6-luna, a ChatGPT login): a new session in the Terminal view, the message box
(closed, and into an open terminal), tool calls, `/compact` and a follow-up, a subagent, a second session reading
the first's history through the gatherer, stopping a turn, and `ag codex exec` from the command line.

Not covered yet:

- [x] **Files and file notices in code mode.** Codex's default tool is `exec`, a script that calls
  `tools.apply_patch(...)` and `tools.exec_command({cmd: ...})`. Its calls are now read out of it
  (commands.opened_script) where the script writes their arguments out, each checked as itself would be; the
  Chat view titles the call by them.
- [ ] **A script's calls it does not write out** (`tools.exec_command({cmd})`, `"cat " + name`, a loop) are not
  read: the files they touch show only as changes seen on disk while the call ran, not as the call's reads.
- [ ] **The output of each of several calls in one script** is not known: what the script printed is shown under
  the last, and the others are checked for what they changed, not for what they read.
- [ ] **A new codex thread is not claimed**, and on macOS none is: see "One process per session, on macOS".
- [x] **macOS: a new codex terminal was never renamed to its thread**, so it showed twice: the dashboard's id with
  nothing, the thread with its messages. The dashboard found a terminal's thread by the process that made its
  calls (`_reads.pid`, from /proc). Each read now keeps its run too (`_reads.run`, the process ag started for the
  terminal), which the dashboard matches on any system.
- [x] **Codex's recap and title.** `/recap` (`thread_source=system`) and the thread's title (`thread_title`) run in
  threads of their own that name no other; codex's launcher now puts its run (its process id) in the URL
  (`/r/<run>/`), and the hook keeps each answer for the thread whose own turn that run sent last: the recap in
  `_recaps`, the title in `_names` (by "codex"), shown over the actor's last message.
- [ ] **A message-box codex session has no name.** `codex exec` never asks for a title; it needs ag's own naming.
- [ ] **Codex's automatic recap** (its `auto_recap` setting) should be kept the same way as `/recap`: not seen live.
- [x] **Codex's warning** "Running without the shared background server", shown when that server runs: ag's `-c`
  overrides need codex embedded, so ag now runs it with `--no-daemon` (where its version has it), which says so.
- [x] **Codex's counts are the provider's** (codex/ag_orchestrator/counting.py), as Claude Code's are: each call's
  new steps counted by OpenAI's /v1/responses/input_tokens after it is sent, its reasoning by what the call's own
  count is over that, and the call counted before it is sent near the budget. Without the endpoint, by differencing
  the calls' own counts.
- [ ] **Remind the user to set an OpenAI API key.** Under a ChatGPT login, codex's own endpoint (the ChatGPT backend)
  has no count; the hook counts with OPENAI_API_KEY, if the hook server has it. Without it, counts come from
  differencing the calls' own counts: each call's total is exact, but a reasoning item's cost is carried by the items
  beside it, and there is no exact count before a call is sent. The dashboard or `ag codex` should say so, and how
  to set one.
- [ ] **`memory_consolidation`** side calls are passed through on the strength of the codex binary's strings
  alone: not seen live.
- [ ] **Reasoning across turns, by OpenAI's count.** Live (gpt-6-luna at high effort, three turns), the first
  reasoning item came to 75 tokens against the 73 its answer reported, but the second to 13 against 84. Check
  whether OpenAI counts an earlier turn's reasoning in full when it is sent back, or one answer's reasoning is
  more than the items ag sees.
- [ ] **A build under codex, live.** Not yet watched: with a low `max_context_tokens` on a test gatherer, check that
  builds start before codex's own compaction point (its stated limit, 90% of the window) and codex never compacts
  by itself.
- [x] **Codex's subagents and background terminals** are background work, as Claude Code's background agents and
  commands are: from its rollout (`SubAgentActivity` started/ended; a command's output naming its session, until
  its `CommandExecution` completes). /review's reviewer and the `subagent` side calls are still only passed through.
- [x] **Codex's subagents' reports** are notes, as Claude Code's are: its `agent_message` items (another of its agents'
  message) are context, not the model's (codex adaptor), and the Chat view shows a FINAL_ANSWER as "Subagent's report:
  <its task>" under the turn that started it -- read from the subagent's own record while codex has not handed it
  back yet, which waits for the thread's next call (files.py, rollout.py's `report`). What a subagent was asked is
  encrypted in `spawn_agent`'s call, so it is named by its task name.
- [ ] **The approval reviewer** (`guardian_review`, for `--approve-for-me`, which the dashboard always uses) is passed
  through; its verdict could say why codex did not run something.
- [ ] **Codex tries a WebSocket first.** The hook server answers 426, and codex logs "failed to connect to
  websocket: HTTP error: 426 Upgrade Required" on every run before falling back to HTTP. Harmless, but noise in
  `codex exec`'s output; codex could be told not to try.
- [ ] **A codex patch's command** reads "apply_patch" in the Files view's commands, not the file it changes.
- [x] **Tests that fail on macOS by path alone:** test_dashboard_codex's ExecTest, test_join's guide test and
  test_pi_launch compare paths as written, not through the /var symlink (#128).

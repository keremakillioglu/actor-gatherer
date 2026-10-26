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
- [ ] **Codex**: its approval and waiting prompts need their own look.

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

- [ ] **An answer that breaks off once it has begun** is not kept as a failure: the hook server can't tell the
  endpoint breaking it from the harness closing it (an interrupted turn). Claude Code's record still shows the
  give-up; for codex it shows as Running until its next call.
- [ ] **Codex's own record** (its rollout file) is not read: Error comes only by time, and an interrupted codex turn
  shows as Running.
- [ ] **Calls with no read** (Claude Code's compaction, recaps) are not kept when they fail.
- [ ] **A session whose record is elsewhere** (another `CLAUDE_CONFIG_DIR`, another machine) waits GIVE_UP_SECONDS
  for Error, and an interruption there is not seen.

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
- [ ] **Codex's subagents** (`subagent` side calls, the agents it spawns, /review's reviewer) are passed through, not
  shown as background work the way Claude Code's background agents are.
- [ ] **The approval reviewer** (`guardian_review`, for `--approve-for-me`, which the dashboard always uses) is passed
  through; its verdict could say why codex did not run something.
- [ ] **Codex tries a WebSocket first.** The hook server answers 426, and codex logs "failed to connect to
  websocket: HTTP error: 426 Upgrade Required" on every run before falling back to HTTP. Harmless, but noise in
  `codex exec`'s output; codex could be told not to try.
- [ ] **A codex patch's command** reads "apply_patch" in the Files view's commands, not the file it changes.
- [ ] **Tests that fail on macOS by path alone:** test_dashboard_codex's ExecTest (its work folder under /var, which
  macOS resolves to /private/var: the test should take its realpath), test_join's guide test and test_pi_launch.

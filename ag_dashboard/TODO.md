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

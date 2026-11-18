# Chat from one view: plan

Status: branch `chat-view`. Steps 1-4 built (2026-11-05): the view is made on the server and pushed to the page as
`chat` on its stream, sends carry an id, and Chat draws from the view. Step 5 (old server paths out) is next.

## Why

Chat works out "what is happening now" on every draw, from three feeds the page refreshes separately and six things
it keeps itself, matched by words and times:

- **The feeds:** the stored turns (`/api/files`, files.py), the actor's status (`/api/home`, data.py's `_status`), and
  what the harness recorded or queued of the user's messages (`/api/agent`'s `typed`, `taken_back`; the session's
  `queued`).
- **What the page keeps:** the messages sent from it and not yet stored (`sentHere`, matched by counting their words),
  those it saw arrive (`hadHere`), an Esc under way (`state.interrupting`), when each turn began, was first drawn and
  was last at work (`turnsBegan`, `turnsSeen`, `atWork`).
- **18 time windows** tie them together: `SAME_SEND_MS`, `UNSEEN_MS`, `HOLD_MS`, `FRESH_MS`, `ESC_GONE_MS`, `HAD_MS`,
  `GROW_MS`, `INTERRUPTING_MS`, `TAKEN_SECONDS`, `CHAT_SECONDS`, `SENT_SECONDS`, `PROMPT_SECONDS`, ...

When two feeds arrive a few hundred milliseconds apart, Chat draws a moment that never happened. The bugs fixed on
2026-11-04/05 were each one such moment: "Pending", then the turn jumping into place; a message drawn twice after
Esc (the restored copy at its old time); "Done" for a blink between a stored turn and its status, or between a turn
and the message held for its end; "Interrupting…" for seconds. Each fix added a window, and the next race showed
after it. The status (data.py) and the turns (files.py) are also two derivations of one lifecycle, from different
reads.

## The design

1. **One view, made on the server.** `chat_view.view(conn, channel, session, now)` reads the gatherer once (and the
   session's row) and returns the conversation as Chat shows it:
   - `turns`: as files.py makes them today, each with `began` (when its message was sent) and `cid` (the send, if
     from Chat);
   - `current`: the latest turn's state -- `opening` (sent, not yet stored), `working` (and what it does: thinking,
     a call, retrying), `asking`, `done`, `stopped` (interrupted, an error, a reason), `idle` (no turn) -- with `since`;
   - `waiting`: what waits for the agent's next step: queued in the session, held for the turn's end, sent from Chat
     and not yet in its record -- each with its `cid` if from Chat;
   - `taken_back`: the message Esc put back, with its `cid`;
   - `version`: the gatherer's newest row and the session's change count; the same version is not sent again.

   The state follows explicit events, in order: a user message stored -> `working`; `asked` -> `asking`; its answer
   -> `working`; a `reply_end` that ends the turn -> `done`, unless the session holds a message for that end (then
   `working`: it goes on with it); a hang-up before any words (499, reached nothing) -> the turn taken back; an
   interrupt or an error given up -> `stopped`. No time decides a state, except "not seen for long" (one window).

   What step 2 found it needs of what writes those events (each found by a recorded run, fixed where it is written):
   - **The send, known before it is typed.** The dashboard writes `chat_sent` through `ag home insert` in the
     background: it landed ~0.2 s after ag stored the message it became, so the turn began without it, then moved.
     `sessions.send` keeps each send in memory ({cid, text, at}, the session's `sent`) before it types it, and rings
     the stream; the view reads `chat_sent` and `sent` as one, by `cid`.
   - **The hook withdraws, then records the hang-up.** Claude Code's hook recorded `call_failed` 2-3 ms before ag's
     withdrawal: in between, a message about to be taken back looked like a turn stopped. Withdrawn first now
     (claude's `failed`), and a withdrawal hides nothing until its `call_failed` says what the answer reached
     (data.py's `withdrawn_reads`' `failed`).
   - **The hang-up says whether it took the message back.** Codex records the same hang-up (499, nothing reached) and
     keeps the message, its turn stopped; the view took it for Claude Code's take-back. `call_failed` now says whether
     the hook withdrew what the call stored (`withdrawn`), and only such a hang-up takes a send back (a hook from
     before it: its message hidden).
   - **A held message, known as held.** A message Claude Code holds for the turn's end was a turn of its own for
     ~0.1 s, until its record said it joined. The record now says, as it queues one, from when on it joins
     (`message_queued`'s `joins_after`: Claude's BUSY_SECONDS); files.py's `_turn_starts` uses it.
   - **A message held no longer than it is.** One lost `message_sent` (the hook's insert failed on a locked
     database) left a message queued for good, and every turn after it read `working`. The hook now sends again what
     a locked database failed, in order (records.py's `Outbox`); and the view holds a message only while nothing shows
     it was sent -- not one stored since it was queued, nor one queued before the session's process last ended by a
     harness whose queue lives in its process (`queue_ends_with_process`: Claude Code's), nor a guess its record made
     later that such a one was sent.
   - **A hang-up from before the message's own send** is not its turn's: ag restores a message taken back and sent
     again before it logs the read that sends it.
   - **An answer that ended its turn ends it.** ag stores an answer's events one by one as the next call carries them
     back, its reasoning before its words: for ~30 ms the newest row was reasoning, and the turn was "working" again
     between two "done". Once the latest call's `reply_end` is in, with nothing of the user's or a tool's after it,
     its stop decides (`_over`). The actor list's status (data.py's `turn_over`) has the same gap: step 5.
   - **Esc waits until the harness has the message.** Typed 0.35 s after a first message, Esc reached Claude Code
     before it had submitted the message, and it let the key go by and answered; Chat said "Interrupting…" meanwhile.
     A stop key now waits while the terminal's message box still holds the message the dashboard pasted
     (sessions.py's `_unsent`, at most HOLD_MAX); and, a terminal the message started (its first prompt, on the command
     line), until the turn's first call is recorded (`_began`): Claude Code starting up lets Esc go by too.
   - **Esc before the harness recorded anything.** Codex stopped before the first call of a new session -- the call
     that makes its thread -- so nothing was recorded, and the turn stayed "opening". With a stop key typed after the
     message (the session's `stopped_at`), the terminal's box decides (`_stop_on`): empty, the opening is stopped
     ("Interrupted"); holding the message, it was taken back. The one place the view reads the screen; the terminal's
     reader wakes the stream as the box changes after a stop key.
   - **A send is never after its message.** Kept before it is typed, a send links to a stored message of its words
     only up to SENT_BEFORE (1 s, for sends kept before this) after it: with 5 s, the same words sent again 4 s after
     an Esc (Codex keeps the stopped turn) took the first turn's place.

2. **Sends carry an id.** The page makes a `cid` per send (the dashboard makes one if it does not); `/api/send` takes
   it and `chat_sent` keeps it. The view sorts out each send once, by order (`_sorted_out`): the stored message it
   became (the newest unlinked send of its words before it), the hang-up that took it back, or still pending -- and
   the turn, the opening, the waiting message or the taken-back one carries the `cid`.

3. **One push per change.** The view goes to the page as the `chat` event of its stream (`/api/stream`, over the
   page's WebSocket) whenever the gatherer or the session changes, and every KEEPALIVE (a send not seen for long).
   Turns and state always come from the same moment, so they cannot disagree.

4. **The page draws it.** What the page keeps: only its sends the view does not have yet (by `cid`) -- drawn as the
   turn they open (actor idle) or waiting (actor at a turn) -- dropped once the view has the `cid` anywhere, or as
   taken back. What goes: `heard()`/`heardCount`, the word-counting of `sentHere`, `hadHere`, `atWork` and the hold,
   `turnsBegan`; on the server, `typed()`/`_unstored` for Chat and the Chat-only parts of `_status`.

## Catching errors

- **Recorded runs** (`tests/chat_runs/*.json`): each a live run on a scratch home -- the gatherer's rows for the actor
  (events, reads, withdrawals, with their times), the session's states as the dashboard had them (sampled), and what
  the run did (sent, Esc) -- recorded by `tests/chat_runs/record.py`. Claude Code first: a send to an idle actor, Esc at
  0.3 s and resent, Esc while it answers, a message sent while it works and held for the turn's end, a tool call, a
  question; then Codex and Antigravity.
- **Replay** (`tests/chat_replay.py`): the gatherer rebuilt as it stood at each moment of a run, and the view made
  there -- in order, and again with one source late by 0.4 s: the harness's record (ag follows its file), the
  dashboard's events (a process of their own), the session, the new-task checks and builds. Not ag's conversation,
  reads and withdrawals against each other: ag writes them in order, and one read of the gatherer finds them so.
- **What the stream sent**: each recording also keeps the `chat` events the dashboard's stream sent as it ran
  (`streamed`), checked as they are.
- **Checks** (`tests/chat_check.py`), over the sequence of views: no `done` or `idle` between two `working` states of
  one turn unless it stopped; a `cid` in one place at a time; turns only added at the end, but for one taken back; the
  current state always the latest turn's; `began` never moves.
- A last check, once a run has settled: no send left opening or waiting from Chat (it never became a message).
- Each later step runs them: a change that brings back a blink, a double or a jump fails a test, not a person.

## Steps

1. Recorded runs, their replay, the checks (the checks tested on made-up sequences until step 2). Done.
2. `chat_view.py`, its model and route; the checks pass on every recorded run, late sources too. Done: 5 Claude Code
   runs and 3 Codex runs (a send; Esc before any words, and after its words began, each then the same words again),
   recorded again with the fixes above.
3. Sends with a `cid`; the view's links. Done on the server (the page sends none yet: the dashboard makes one).
4. The page draws the view (React); the legacy pieces above removed. Done:
   - The page keeps the latest view per actor (`state.chatView`, from the stream's `chat`, or a pane's `actor` event,
     which carries its actor's), and its own sends by id (`chatSends`) until the view has the id (bridge's `cidsOf`).
   - `features/chat/view.ts` reads it: the turns, the opening turn (the view's, or a send from here to an actor not at
     work), the state, what waits. Chat draws from it alone; before a view has come, the turns of `/api/files` with no
     state. `/api/files` stays for the files and commands at the left.
   - Gone: `heard()`, `heardCount`, `sentHereNow`, `turnsBegan`, the page's 15 s "not seen" timer (the view's
     `unseen`), the word-matching of sends. The actor list's "running before ag stored it" (`opened`), Esc's "can
     interrupt" and the chat minimized under the Editor read the same view.
   - Two changes to what the reader sees: a message sent to an actor not at work opens its turn at once (no "Pending");
     "not seen by the session yet" is said on that turn, where "Working…" would be.
5. The old server paths for Chat removed; the actor list's status from the same view; DESIGN.md updated.

Still to record: a question answered from Chat, Antigravity runs, Codex's held and mid-turn messages (record.py keeps
the harness). Open: Esc
after a tool call began and before any words (`reached` "tool") hides the message at once, while data.py's
`taken_back` waits TAKEN_SECONDS for Claude Code's record -- not recorded yet.

"""Every text the proactive context manager writes for the agent to read, in one place: the gatherer guide that
opens every context, the messages it adds during a task (messages from a stream, file-change notices, requests made in
parallel, notes of a change of groups, left-out notes), and the history sections' own words (their overview, headings
and notes, and where the full history is). The config's text fields (config.py) take their defaults from here, so a
gatherer's options can still change them; the rest is used as it is (sections.py, assembly.py)."""


# ---------------------------------------------------------------- the gatherer guide (config.gatherer_guide)

# The gatherer guide: the first item of every context, after the harness's own set-up, on
# every read -- with or without a build -- so the agent knows from its first call what the
# gatherer adds to its context and where the rest is. `{db_path}` is the context database. With
# db_hint, the database's layout follows it (sections.DB_HINT). "" = no guide.
GATHERER_GUIDE = ("About this context, from the gatherer.\n\n"
    "This session runs inside a gatherer: it puts your context together on every call, and "
    "other sessions of your group may be working with you, in parallel or before you, for the same "
    "user. Besides the conversation itself, your context may hold these messages from the "
    "gatherer:\n\n"
    "- **History sections**: earlier history, of this session or of your group's other "
    "sessions, put together to fit. The first of them says how they are organised and how to "
    "read them.\n"
    "- **Requests made in parallel** (\"The user sent this to another session working in parallel "
    "with you: ...\"): a request the user made to another session, where it arrived -- before "
    "your user message, or after your latest step if it came mid-turn. It is not your task, but "
    "the same user gave it, on the same material: a definition, convention, correction or "
    "exclusion stated there applies to your work too.\n"
    "- **File-change notices**: a file you read has been modified by someone else since. What "
    "you read from it is out of date; read it again before relying on it.\n"
    "- **Messages from a stream** (\"Message in <stream> from <author> ...\"): information "
    "from outside the conversation, at the point it arrived.\n"
    "- **Left-out notes** (\"[Agent steps were left out here ...]\"): steps of this session "
    "dropped to keep the context within its limit; they name the rows to read them from.\n\n"
    "None of these is the user speaking to you in this session: the user's own messages are the "
    "requests you answer.\n\n"
    "**Other actors, and coordinator agents.** The other sessions of your group are actors like you -- "
    "Claude Code, Codex and other agents -- often working in the same directories at the same time. Each is "
    "known by its session id (the one a request made in parallel names), or its first characters. Run "
    "`ag actors` in your shell to list them -- their ids, names, status, directories and what each was last "
    "asked -- and `ag actors --help` for the rest: what one is doing (`show`), which actors changed a file "
    "(`who`), and `ag actors send <id> \"<message>\"` to message one. A message from another actor reaches you "
    "as a message of this conversation starting \"Message from actor <id>\"; answer it the same way. "
    "`ag actors` talks to the dashboard on this machine. Under Codex, run every `ag actors` command with "
    "sandbox_permissions \"require_escalated\" from the first try: Codex's sandbox has no network, even to this "
    "machine, so it always fails inside it.\n\n"
    "**Coordinator agents.** The user can start a coordinator agent over any folder of the dashboard's list -- a "
    "folder in your group, your group, a folder of groups, or everything. It coordinates, for the user, the actors in "
    "its folder and in the folders inside it. `ag actors` names the ones over you, the nearest first; there may be "
    "none. If you find work conflicting with yours -- another actor changing files you are working on (a "
    "file-change notice for one of them; `ag actors who <file>` names who, in any group), or working on the same "
    "task or one that overlaps it -- don't settle it with the other actor yourself, and don't undo its changes: stop "
    "changing what the conflict touches, and tell the coordinator agent over you both with `ag actors send "
    "coordinator --with <the other actor's id> \"<the conflict, and how you found it>\"` (`--with` once for each "
    "other actor in it). ag sends it to the coordinator agent of the nearest folder that holds you all. Then end your "
    "turn saying so; its answer comes as a new message. If no coordinator agent is over you all, nothing is sent and "
    "the command says so: end your turn telling the user about the conflict -- what it touches, the other actor's "
    "id, and how you found it -- so they can settle it, or start a coordinator agent over a folder that holds you "
    "both.\n\n"
    "A message starting \"Message from the coordinator agent\" is from one of them: it acts for the user, so listen "
    "to it and do as it says, as you would the user's own request -- unless the user tells you otherwise. If two "
    "coordinator agents tell you different things, do as the one over the wider folder says, and tell the other. "
    "Message a coordinator agent back, with the command its message gives, only when it asks you to, or when you "
    "can't do what it says: each message costs it a turn.\n\n"
    "**The LaTeX editor's preview.** The dashboard's LaTeX editor has an Execute button that runs a git project's "
    "preview command -- latexmk on its main .tex, unless another is set -- and shows what it makes beside the file: "
    "the PDF, a file it writes, the page of a server it starts, or its output. When the user asks for a preview, "
    "set it with `ag preview set \"<command>\" --show <file or URL>` "
    "(for the repository you are in); `ag preview` says what it is now, and `ag preview run` runs it, once the user "
    "has let that command run (`ag preview --help`). Under Codex, run it escalated too, as `ag actors`.")


# ---------------------------------------------------------------- messages during a task

# Every file-change notice ends with this: a notice that arrives while the agent works on something
# the change does not touch is otherwise treated as settled by its next answer, and forgotten when a
# later question does depend on the file.
REMEMBER_ONE = (' Remember this for later too: until you have read the file again, any answer or work, in this turn or a later one, that uses its contents must start by re-reading it.')

REMEMBER_MANY = (' Remember this for later too: until you have read them again, any answer or work, in this turn or a later one, that uses their contents must start by re-reading them.')

# The developer message a stream message (a `context_stream` event in the
# verbatim part) is shown as, at its place in the history.
# `{stream}`, `{author}` and `{text}` are the event's; `{timestamp}` is
# the event's, shown as a UTC date and time when it is seconds since the
# epoch.
STREAM_MESSAGE = "Message in {stream} from {author} at {timestamp}: {text}"

# The developer message shown, at its place in the history, for the
# environment updates one poll found (`environment_update` events in the
# verbatim part) whose subjects the verbatim rows before them refer to:
# one message per poll. For one update, `notice`: `{what}` and
# `{subject}` are the event's, `{timestamp}` as above. For up to
# `notice_names` of them, `notice_named`, `{subjects}` naming each; for
# more, `notice_counted`, with their `{count}`.
NOTICE = ("{what} at {timestamp}, after you last read it.{repeat} What you read from it before is now "
               "out of date. Before giving any answer, or writing anything, that relies on its contents, read the "
               "file again." + REMEMBER_ONE)

# {repeat} in `notice`: added when the agent was already notified of an earlier change to the same file,
# so a second change is not taken for the first one, already handled.
NOTICE_REPEAT = (" This is a new change that just happened, separate from any earlier notice you received "
                      "about this file: even a read you made after that notice may not include it.")

NOTICE_NAMED = ("These files in your working directory were changed on disk after you last read them: "
                     "{subjects}. What you read from them before is now out of date. Before giving any answer, "
                     "or writing anything, that relies on their contents, read them again." + REMEMBER_MANY)

NOTICE_COUNTED = ("{count} files in your working directory were changed on disk after you last read them. "
                       "What you read from them before is now out of date. Before giving any answer, or writing "
                       "anything, that relies on one of them, read it again." + REMEMBER_MANY)

# The developer message each request the user made to another channel since
# the build in use (all of them, before one) is shown as: right before the
# user message the agent is working on, or, arriving mid-turn, after the
# turn's latest step -- as Claude Code shows a message the user sends
# mid-turn. Its text is the same wherever it goes: it stays there, and a
# changed text would leave out the thinking after it. `{text}` is the
# request; `{channel}` the other channel's id; `{db_path}` and
# `{channel_column}` where its work can be read. With no build, those made
# before the channel began are messages only while they fit within
# all_task_tokens + parallel_index_tokens; past that, one block of the
# newest that fit (parallel_sessions.py's `make_earlier_requests_block`).
PARALLEL_MESSAGE = ("The user sent this to another session working in parallel with you:\n{text}\n\n"
    "This is how the gatherer shows you what the user asks your group's other sessions, where it arrived in "
    "your conversation. It is not addressed to you: do not answer it or take it up, and carry on with "
    "your own task. But a definition, convention, correction or exclusion the user states in it "
    "applies to your work too. That session's work is in {db_path}, table events, where "
    "{channel_column} = '{channel}'.")

# The developer message shown, at its place in the history, for a change of groups that changes what this
# session is shown (a `group` record in the verbatim part, parallel_sessions.py's `make_group_change_notes`): its own move
# (`group_moved`), or a run of other sessions' moves into (`group_joined`) or out of (`group_left`) its group.
# `{group}` and `{was}` name the groups (the record's `name` and `was_name`, else its ids; the gatherer's own
# group is `group_own`); `{channels}` the sessions moved, by id. Its own move to a group of one -- an actor on its
# own, `self:<channel>` -- is `group_alone`, and back from one `group_back`.
GROUP_MOVED = ("Your group changed: from now on you share work with the sessions of {group}, no longer with "
                    "those of {was}. What you were shown of their work before is no longer part of yours.")

GROUP_JOINED = "These sessions are in your group now, and their work is part of yours: {channels}."

GROUP_LEFT = "These sessions left your group, and their work is no longer part of yours: {channels}."

GROUP_ALONE = ("You work on your own now: from now on you share work with no other session, no longer with "
                    "those of {was}. What you were shown of their work before is no longer part of yours.")

GROUP_BACK = ("Your group changed: from now on you share work with the sessions of {group}. Until now you "
                   "worked on your own.")

GROUP_OWN = "this gatherer's own group"

# The same, for a change of the groups a session reads besides its own (a coordinator agent's over several: its
# `role` record's `reads`): groups it is shown from now on (`reads_added`), and those it no longer is
# (`reads_removed`). `{groups}` names them (the record's `names`, else their ids).
READS_ADDED = "From now on you are also shown the work of the sessions of these groups: {groups}."

READS_REMOVED = ("You are no longer shown the work of the sessions of these groups, and what you were shown of "
                      "it before is no longer part of yours: {groups}.")

# A left-out note (assembly.py's `stub_old_steps`): the agent steps it stands for, and where to read them.
LEFT_OUT_NOTE = ("[Agent steps were left out here to keep the context within max_context_tokens: {count} events, "
                 "{tokens} tokens{calls}. Read event rows {first}-{last} from the context database, {db_path}, if you "
                 "need them.]")
LEFT_OUT_CALLS = "; their calls: {calls}"


# ---------------------------------------------------------------- the history sections (sections.py)

OVERVIEW_HEADER = "# How this history is organised"

REQUESTS_HEADER = "# Every earlier request"

EARLIER_HEADER = "# Earlier messages"

RELATED_HEADER = "# Related earlier tasks"

PREVIOUS_HEADER = "# Previous task"

SO_FAR_HEADER = "# This task so far"

SO_FAR_NOTE = ("The task you are in the middle of, from its request to your latest step, condensed to "
               "fit. Carry on from where it leaves off; anything after it is verbatim.")

CLIPPED = "\n\n[...the middle of this section is left out to fit its budget...]\n\n"

OPENING = """\
This session has run for longer than fits here, so the history before the current task
has been put together as the sections below, oldest and least detailed first. The
current task follows them as it happened -- or, if it has run long, its earlier steps are
in the last section, This task so far, and the rest follows as it happened."""

# A session that joined a gatherer whose other sessions had already built: it starts from their work.
JOINED_OPENING = """\
This session is new, but the gatherer's other sessions worked before it or alongside it,
for the same user on the same material. What they did has been put together as the
sections below: the requests made in them, and their earlier tasks most related to this
session's work. This session's own history follows them as it happened -- or, if it has
run long, its earlier steps are in the last section, This task so far."""

OVERVIEW = """\
The user's messages in these sections are PRUNED: the boilerplate that wraps a request --
a notice repeated on every message, a standard instruction about how or where to deliver
the answer -- is removed, and the words of the request itself are kept exactly. The exact
original of every message is in the `events` table, under the same `[id N]`; the pruned
text is in the `cleaned_messages` table (`row_id` = that N).

1. **Every earlier request** — every message the user sent in this line of work, in
   order, as written (pruned of boilerplate, as above). Complete: nothing is left out or summarised, but what
   was DONE about each request is not here. It also carries the requests made in the
   session's parallel channels, under their own heading. They are tasks given by the same
   user, on the same material. A definition, convention, correction or exclusion the
   user stated there applies to THIS work, and governs the request you are answering
   now as much as one from this channel.
2. **Earlier messages** — the tasks leading up to recent work, whole: the user and
   assistant messages, no tool calls.
3. **Related earlier tasks** — whole tasks from further back, here or in a parallel
   channel, chosen for their bearing on the current work. Re-chosen as the work moves
   on, which is why section 1 keeps every request regardless.
4. **Previous task** — the task worked on just before the current one, in full,
   including its tool calls and their output.
5. **This task so far** — present only when the current task has run long: its request
   and its steps up to a point, condensed to fit. Everything after that point follows
   as it happened.

A task in 2, 3 or 4 still has its requests in section 1. That is deliberate.

Requests the user made in a parallel channel after these sections were put together are
not in them: each is a separate message, where it arrived -- right before the request you
are answering, or after your latest step if it came while you were working. They have the
same standing as the parallel requests in section 1.

HOW TO READ A TASK. Each opens with its name, one sentence on what it did, and then any
of four labelled lines recording what the user ESTABLISHED in it. Those lines are
standing decisions from earlier in this same session, and apply to the request you are
answering now unless it overrides them.

  handling: <what it governs> — how an object must be treated: read, filtered,
    cleaned, counted, joined, built, run, edited or named. Apply it wherever your
    work touches what it governs, even if the request does not mention it.
  term: <the word> — what that word means in this session. Use this meaning.
  about: <an object> — a fact the user stated about that object. Treat it as true.
  standing: <what it applies to> — a decision the user said to keep using. If what
    it applies to covers this request, follow it.

Where two conflict, the more specific scope wins, and a later turn overrides an earlier
one."""

DB_HINT = """

Items in the history sections are labelled `[id N]`. The full history of every session in
this gatherer -- including everything the sections leave out -- is in the SQLite database

    {db_path}

table `events`, one row per event, `ORDER BY row_id` for order: `row_id` (the N of
`[id N]`), `{channel_column}` (NULL = shared by every channel), `event_type_id` (a row of
`event_types`: its `name` -- user_message / agent_message / tool_call /
tool_output / context / agent_reasoning, your own reasoning, encrypted), `text` (what the
event says: a message's words, a call's name and arguments, an output; NULL for one with
nothing to read) and `payload_json` (the event itself, in full). Anything you cannot find
here is worth looking for there before concluding it did not happen:

    sqlite3 {db_path} "SELECT e.row_id, t.name, coalesce(e.text, e.payload_json) FROM events e JOIN event_types t USING (event_type_id) WHERE e.row_id BETWEEN A AND B ORDER BY e.row_id;\""""

# A database every group's sessions share (the home's one, `ag home merge`'s): how to keep to one's own. A query, not a
# view: a view naming a column the events table does not have yet breaks a later ALTER TABLE ... RENAME.
DB_GROUP_HINT = """

That database holds the sessions of every group, not only yours: keep to your group's, `{group}`, by
putting this before a query

    WITH mine AS (SELECT {channel_column} AS ch, json_extract(payload_json, '$.group') AS grp, max(row_id)
                  FROM events JOIN event_types USING (event_type_id) WHERE name = 'group' GROUP BY {channel_column})

and `AND (e.{channel_column} IS NULL OR e.{channel_column} IN (SELECT ch FROM mine WHERE grp = '{group}'))` in its WHERE:
a session's group is the one its latest `group` event names."""

# The same, for a session shown several groups (a coordinator agent's over a folder of groups, or everything).
DB_GROUPS_HINT = """

That database holds the sessions of every group: you are shown those of the groups {groups}, besides your
own. Keep to them by putting this before a query

    WITH mine AS (SELECT {channel_column} AS ch, json_extract(payload_json, '$.group') AS grp, max(row_id)
                  FROM events JOIN event_types USING (event_type_id) WHERE name = 'group' GROUP BY {channel_column})

and `AND (e.{channel_column} IS NULL OR e.{channel_column} IN (SELECT ch FROM mine WHERE grp IN ({listed})))` in its
WHERE: a session's group is the one its latest `group` event names."""

INDEX_HEADER = "## Requests made in parallel sessions"

BEFORE_HEADER = "# Requests made in parallel sessions before this one"

BEFORE_NOTE = ("The requests the user made in the gatherer's other sessions before this session started, in order, "
               "as they wrote them: the newest that fit here. They are not addressed to you: do not answer them or "
               "take them up. But the same user gave them, on the same material: a definition, convention, "
               "correction or exclusion stated in one applies to your work too.")

REQUESTS_INTRO = "Every request the user made in this line of work, in order, as they wrote them."
REQUESTS_OMITTED = "[{count} later requests omitted: ids {first}-{last} — read them from the `events` table]"
BEFORE_OMITTED = "[{count} earlier requests left out: ids {first}-{last} — read them from the `events` table]"
FROM_PARALLEL = " — from parallel channel {channel}"

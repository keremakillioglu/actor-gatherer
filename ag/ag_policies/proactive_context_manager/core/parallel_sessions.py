"""Other sessions: which ones share work with this one, the requests the user made to them, their tasks, and how a
session is told when its group changes.

Not every channel is shown to the others. A channel shares only with those of its GROUP: the latest `group` record
in it (GROUP: the dashboard's, from the folder the actor is in) names it, and a channel with none is in the gatherer's
own group, "" -- so in a gatherer where no channel has one, every channel shares with every other, as before groups.
One in another group is seen neither by its requests, as parallel messages or in the index, nor by its tasks, ranked
into the sections, nor counts for a join (`get_hidden_sessions`). One whose latest `role` record (ROLE: the dashboard's, for a
coordinator agent) says `private` is seen by no other channel, though it sees theirs -- and one whose record lists
groups it `reads` (a coordinator agent over several groups, in a group of its own) sees theirs too, as its own. Nor is a message the
actors send one another (`ag actors`, typed into the receiver's conversation as its user's), known by its opening
(`unshared_openings`): it is the receiver's to act on, not a request of the user's (`is_user_request`).

When a channel's group changes -- a `group` record moves it, or another channel into or out of its group, since its
last read (`has_group_changed`) -- what it is shown follows at once: the parallel requests are worked out at every read, and
the block of requests made before it began is made again. Its sections, made from the build it uses, are built again
at that read, which waits for it as for a join (`rebuild_for_new_group`): a `regrouped` build, for a channel with a build of its
own, adopted mid-turn and whatever its size; a `join` again, for one whose context came from a join or that has
none. Its parallel mark moves up with it, so a joined channel's past requests come in the index, not one by one.
A short message says what changed, at the record's place (`make_group_change_notes`). A record with no channel -- a stream
message, an app's -- that names a group (its payload's `group`) is shown only to that group's channels (`get_visible_events`).

Each request the user made to another channel since the build in
use (since the start, before one) is a developer message (`parallel_message`)
placed, the first time it is shown, just before this channel's latest user
message -- and kept there after (where the channel's last read had it), so
a later user message does not move it and the context only grows at its end. Requests
before the build's mark are in its index section instead. All three are made items,
remade on every read and never reused as sections.

With no build in use, the requests made before the channel's first row are messages too while
they fit within all_task_tokens + parallel_index_tokens; past that -- a session that started
in a busy gatherer and has not taken up its join -- they are one block, the newest that fit
(`make_earlier_requests_block`), made at the channel's first read without a build and reused after, so
it neither moves nor changes. Those made since the channel's first row are messages, as
after a build's mark."""

from typing import Callable, Dict, List, Optional, Tuple

from ag.ag_interface import Row, event_text, property_column
from ag.ag_interface.policy import TypeIds
from ag.ag_policies.tools import channel, history
from ag.ag_policies.tools import tasks as tasks_tool
from ag.ag_policies.tools.channel import CHANNEL, channel_of
from ..db import tables
from ..db.tables import GROUP_CHANGE, PARALLEL_BEFORE, PARALLEL_REQUEST
from . import sections

ROLE = "role"                   # a channel's role, as the dashboard records it: {role, private} (`get_hidden_sessions`)
GROUP = "group"                 # a channel's group, as the dashboard records it: {group, ...} (`get_hidden_sessions`); each
                                # record an id of its own, naming its channel: a read returns an id once, where it
                                # was first stored, whatever its channel
ALONE = "self:"                 # a group of one: an actor on its own (the dashboard's `self:<channel>`)
OPENING_CHARS = 600             # how far into a message its opening is looked for, past a harness's wrapper (`is_user_request`)


def get_groups_read(payload: dict) -> frozenset:
    """The groups a `role` record says its channel reads (`reads`: a coordinator agent's over several groups)."""
    listed = payload.get("reads") if isinstance(payload, dict) else None
    return frozenset(str(group) for group in listed if group) if isinstance(listed, list) else frozenset()


class HiddenSessions:
    """The channels one channel is not shown (`in`): the private ones (`private`, a set), and those of another group
    than its own (`own`) and those it `reads` (a set of groups, its role record's): a channel's group is `groups'` for
    it, "" (its gatherer's own) when it has none."""

    def __init__(self, private: set, groups: Dict[str, str], own: str, reads: frozenset = frozenset()):
        self.private, self.groups, self.own, self.reads = private, groups, own, frozenset(reads)

    def is_shown_group(self, group) -> bool:
        """Whether the channels of `group` are shown: its own group, or one it reads."""
        return group == self.own or group in self.reads

    def is_in_shown_group(self, channel_id) -> bool:
        """Whether `channel_id` is in a group shown, private or not."""
        return self.is_shown_group(self.groups.get(channel_id, ""))

    def __contains__(self, channel_id) -> bool:
        return channel_id in self.private or not self.is_in_shown_group(channel_id)


class ParallelSessions:

    def get_hidden_sessions(self, conn, types: TypeIds, channel_id) -> HiddenSessions:
        """The channels `channel_id` is not shown (`in`): those whose latest ROLE record says `private`, and those of
        another group than its own -- a channel's group the latest GROUP record in it names, "" without one."""
        private: Dict[str, bool] = {}
        reads: Dict[str, frozenset] = {}
        group: Dict[str, str] = {}
        role_ids = types.of(ROLE)
        for row in conn.rows(0, types.of(ROLE, GROUP)):
            row_channel = channel_of(row)
            if row_channel is None or not isinstance(row.payload, dict):
                continue
            if row.type.id in role_ids:
                private[row_channel] = bool(row.payload.get("private"))
                reads[row_channel] = get_groups_read(row.payload)
            else:
                group[row_channel] = str(row.payload.get("group") or "")
        return HiddenSessions({session for session, is_private in private.items() if is_private}, group, group.get(channel_id, ""),
                      reads.get(channel_id, frozenset()))

    def has_group_changed(self, conn, types: TypeIds, channel_id, since_row: int) -> bool:
        """Whether what the channel is shown changed groups after `since_row`: a GROUP record stored since moved a
        channel from one group to another (its `was` given, and not its `group`) -- this one, or another into or out
        of this one's group. A first record (no `was`: an actor starting) changes nothing of the others': its
        requests come to them as any new session's do."""
        group_moves, role_ids = [], types.of(ROLE)
        for row in conn.rows(since_row, types.of(GROUP, ROLE)):
            payload = row.payload if isinstance(row.payload, dict) else {}
            if row.type.id in role_ids:
                if channel_of(row) == channel_id and "reads" in payload:
                    return True                       # the groups it reads changed (the dashboard writes them so)
            elif "was" in payload and str(payload.get("group") or "") != str(payload.get("was") or ""):
                group_moves.append((channel_of(row), str(payload.get("group") or ""), str(payload.get("was") or "")))
        if not group_moves:
            return False
        hidden = self.get_hidden_sessions(conn, types, channel_id)
        return any(moved == channel_id or hidden.is_shown_group(group) or hidden.is_shown_group(was) for moved, group, was in group_moves)

    def get_groups_read_before(self, conn, types: TypeIds, channel_id, row_id: int) -> frozenset:
        """The groups the channel read before the row `row_id`: its latest `role` record before it's."""
        groups_read = frozenset()
        for row in conn.rows(0, types.of(ROLE)):
            if row.row_id >= row_id:
                break
            if channel_of(row) == channel_id and isinstance(row.payload, dict):
                groups_read = get_groups_read(row.payload)
        return groups_read

    def is_user_request(self, row: Row) -> bool:
        """Whether another channel's user message is shown to this one as its user's request: not a message the actors
        sent each other, which opens a line with one of `unshared_openings` -- at its start, or past the wrapper its
        harness put round it (a mid-turn note, a paste's tags)."""
        openings = self.config.unshared_openings
        if not openings:
            return True
        head = (event_text(row) or "")[:OPENING_CHARS]
        return not any(line.lstrip().startswith(openings) for line in head.split("\n"))

    def get_visible_events(self, conn, types: TypeIds, channel_id, verbatim_start: int, name: str) -> list:
        """The events of type `name` the channel can see from `verbatim_start` on -- the
        verbatim part of the context; those a build has condensed past are
        not looked at -- in row order."""
        rows = conn.rows(after_row=max(verbatim_start - 1, 0), match=channel.of(channel_id), type_ids=types.of(name))
        if not any(channel_of(row) is None and isinstance(row.payload, dict) and "group" in row.payload for row in rows):
            return rows
        hidden = self.get_hidden_sessions(conn, types, channel_id)        # a record with no channel, for one group: its channels'
        return [row for row in rows if channel_of(row) is not None or not isinstance(row.payload, dict)
                or hidden.is_shown_group(str(row.payload.get("group", hidden.own) or ""))]

    def make_group_change_notes(self, conn, types: TypeIds, channel_id, verbatim_start: int) -> List[tuple]:
        """("made", row_id, item, (made_id, tokens)) for each change of groups in the verbatim part that changed what
        the channel is shown (`has_group_changed`): its own move (`group_moved`), or a run of other channels' moves into or out
        of its group -- records stored one after another, as a folder's move writes them -- as one message
        (`group_joined`, `group_left`), at its first record's place."""
        group_type_ids, role_ids = types.of(GROUP), types.of(ROLE)
        rows = conn.rows(after_row=max(verbatim_start - 1, 0), type_ids=group_type_ids | role_ids) if group_type_ids else []
        group_moves = [(row, row.payload) for row in rows if isinstance(row.payload, dict) and (
            (row.type.id in role_ids and channel_of(row) == channel_id and "reads" in row.payload)
            or (row.type.id not in role_ids and "was" in row.payload
                and str(row.payload.get("group") or "") != str(row.payload.get("was") or "")))]
        if not group_moves:
            return []
        config = self.config
        hidden = self.get_hidden_sessions(conn, types, channel_id)
        reads_before: Optional[frozenset] = None             # what it read before each role record: the note says the change

        def named(name, group_id: str) -> str:
            return str(name) if name else (f"group {group_id}" if group_id else config.group_own)

        notes, current_run, last_row = [], None, None                 # notes: [row_id, kind, text or [channels]]
        for row, payload in group_moves:
            if row.type.id in role_ids:                        # the groups it reads, changed
                groups_now = get_groups_read(payload)
                if reads_before is None:
                    reads_before = self.get_groups_read_before(conn, types, channel_id, row.row_id)
                added, removed = sorted(groups_now - reads_before), sorted(reads_before - groups_now)
                reads_before = groups_now
                names = payload.get("names") if isinstance(payload.get("names"), dict) else {}
                notes += [[row.row_id, "moved", text.format(groups=", ".join(str(names.get(group) or group) for group in which))]
                         for text, which in ((config.reads_added, added), (config.reads_removed, removed)) if which]
                current_run = None
                last_row = row.row_id
                continue
            group, was, moved = str(payload.get("group") or ""), str(payload.get("was") or ""), channel_of(row)
            if moved == channel_id:
                new_name, old_name = named(payload.get("name"), group), named(payload.get("was_name"), was)
                notes.append([row.row_id, "moved", config.group_alone.format(was=old_name) if group.startswith(ALONE)
                             else config.group_back.format(group=new_name) if was.startswith(ALONE)
                             else config.group_moved.format(group=new_name, was=old_name)])
                current_run = None
            elif hidden.is_shown_group(group) != hidden.is_shown_group(was):
                kind = "joined" if hidden.is_shown_group(group) else "left"
                if current_run is not None and current_run[1] == kind and row.row_id == last_row + 1:
                    current_run[2].append(moved)
                else:
                    current_run = [row.row_id, kind, [moved]]
                    notes.append(current_run)
            else:
                current_run = None
            last_row = row.row_id
        out = []
        for row_id, kind, what in notes:
            text = what if kind == "moved" else (config.group_joined if kind == "joined" else config.group_left).format(
                channels=", ".join(what))
            made_id, item, tokens = tables.make_message(conn, self.format, self.tokenizer, channel_id, text, GROUP_CHANGE, f"group {row_id}")
            out.append(("made", row_id, item, (made_id, tokens)))
        return out

    def get_other_sessions_tasks(self, conn, types: TypeIds, channel_id,
                    stopped: Callable[[], bool] = lambda: False) -> Tuple[List, Dict]:
        """(the other channels' tasks, located in their turns; those turns, by channel): each channel's whole history
        read, so seconds in a big gatherer -- cut short, with what was found so far, once `stopped` (the harness hung
        up on the call: `Read.stopped`)."""
        tasks_found, turns_by_channel, hidden = [], {}, self.get_hidden_sessions(conn, types, channel_id)
        for other in tables.get_channels_with_tasks(conn):
            if stopped():
                break
            if other == channel_id or other is None or other in hidden:
                continue
            _, turns = history.split(history.rows(conn, types, self.groups, other), types, self.groups, self.tokenizer)
            tables.apply_cleaned_texts(conn, [turn.entries[0] for turn in turns])
            turns_by_channel[other] = turns
            tasks_found += tasks_tool.locate(tables.get_own_tasks(conn, other), turns)
        return tasks_found, turns_by_channel

    # ---- the user's requests to the other sessions

    def get_parallel_request_text(self, conn, channel_id, text: str) -> str:
        """A request of channel `channel_id`'s, worded as the config's `parallel_message`."""
        return self.config.parallel_message.format(text=text, channel=channel_id, db_path=conn.path,
                                                   channel_column=property_column(CHANNEL))

    def make_parallel_requests(self, conn, types: TypeIds, channel_id, after_row: int) -> List[tuple]:
        """(made_id, item, tokens, its row id) for each user message stored in
        another channel after `after_row`, oldest first."""
        out, hidden = [], self.get_hidden_sessions(conn, types, channel_id)
        for row in conn.rows(after_row, types.of(*self.groups.user), differ=channel.of(channel_id)):
            other = channel_of(row)
            if other is None or other == channel_id or other in hidden or not self.is_user_request(row):
                continue
            made_id, item, tokens = tables.make_message(conn, self.format, self.tokenizer, channel_id, self.get_parallel_request_text(conn, other, event_text(row) or ""),
                                              PARALLEL_REQUEST, f"request {row.row_id}")
            out.append((made_id, item, tokens, row.row_id))
        return out

    def get_request_positions(self, conn, refs: list, verbatim_from: int, rows, types: TypeIds, channel_id,
                        parallel_requests: List[tuple]) -> List[int]:
        """Where in the context each of `parallel_requests` goes, before any is inserted: where it was in the
        channel's last read (`get_last_read_positions`) -- before the row it came before, or, shown last, before
        the first row after the one it came after -- or, that row condensed away, before the first
        row of the verbatim part (`refs[verbatim_from:]`) after it. A request not shown before goes
        before this channel's latest user message, the call being at it; mid-turn (a step of the
        agent's own after that message), or with none, at the end. Not before the turn's steps: a
        thinking block counts, and the model reads it, only after the history it was written in, so
        a request put before them would leave out all the turn's thinking so far."""
        own_rows = [row for row in rows if channel_of(row) == channel_id]
        user_message_rows = [row.row_id for row in own_rows if history.opens_turn(row, types, self.groups)]
        latest_request_row = user_message_rows[-1] if user_message_rows else None
        steps = types.of(*self.groups.messages, *self.groups.tools, *self.groups.verbatim)
        if latest_request_row is not None and any(row.row_id > latest_request_row and row.type.id in steps for row in own_rows):
            latest_request_row = None                                # mid-turn: a new one goes at the end
        came_before, came_after = self.get_last_read_positions(conn, channel_id)
        places = []
        for _, _, _, row in parallel_requests:
            if row in came_after:                             # shown last: right after the row it followed
                anchor = came_after[row] + 1
            else:
                anchor = came_before.get(row, latest_request_row)
            position = len(refs) if anchor is None else next(
                (i for i in range(verbatim_from, len(refs)) if refs[i].row_id is not None and refs[i].row_id >= anchor),
                len(refs))
            places.append(position)
        return places

    def get_last_read_positions(self, conn, channel_id) -> Tuple[Dict[int, int], Dict[int, int]]:
        """({request row: the row it came before}, {request row: the row it came after}) for each other
        channel's request the channel's last read showed (its made item's source names the request):
        the second for one shown last, with no row after it (shown mid-turn, at the end). Every request
        since the build's mark is shown on every read, so the last read has each one shown before, in
        its place."""
        last_read = conn.last_read(channel.of(channel_id))
        refs = last_read["refs"] if last_read else []
        made_ids = [ref.made_id for ref in refs if ref.made_id is not None]
        if not made_ids:
            return {}, {}
        sources = dict(conn.execute(f"SELECT made_id, source FROM _made_items WHERE name = ? AND made_id IN "
                                    f"({','.join('?' * len(made_ids))})", [PARALLEL_REQUEST, *made_ids]).fetchall())
        out, waiting, previous = {}, [], None
        for ref in refs:
            if ref.made_id in sources and str(sources[ref.made_id]).startswith("request "):
                waiting.append(int(str(sources[ref.made_id]).split()[1]))
            elif ref.row_id is not None:
                out.update((request, ref.row_id) for request in waiting)
                waiting, previous = [], ref.row_id
        return out, ({request: previous for request in waiting} if previous is not None else {})

    def make_earlier_requests_block(self, conn, types: TypeIds, rows, channel_id) -> Tuple[List[tuple], int]:
        """With no build in use: ([(made_id, item, tokens)] of one block of the other channels'
        requests made before the channel's first row, or [] when they fit as messages), and the row
        after which `make_parallel_requests` shows them one by one -- 0, all, without a block.

        As messages they would be at most all_task_tokens + parallel_index_tokens, the budget a
        session that joined gets for them; past it, the block holds the newest that fit it
        (`sections.requests_before`). Made at the first read without a build that needs it and reused
        after (the channel's last read, made without a build, has it), so later reads extend the
        same context."""
        config = self.config
        start = next((row.row_id for row in rows if channel_of(row) == channel_id), None)
        if start is None:
            return [], 0
        last_read = conn.last_read(channel.of(channel_id))
        if last_read and tables.get_basis(last_read) is None:
            made_ids = [ref.made_id for ref in last_read["refs"] if ref.made_id is not None]
            kept = [(made_id, item, tokens) for made_id, (name, item, tokens) in conn.made_items(made_ids).items()
                    if name == PARALLEL_BEFORE]
            if kept and not self.has_group_changed(conn, types, channel_id, last_read.get("row_id") or 0):
                return kept[:1], start
        hidden = self.get_hidden_sessions(conn, types, channel_id)
        earlier_requests = [(other_channel, entry) for other_channel, entry in history.other_requests(conn, types, self.groups, self.tokenizer, channel_id,
                                                            keep=lambda row: channel_of(row) not in hidden and self.is_user_request(row))
                  if entry.row_id < start]
        budget, used = config.all_task_tokens + config.parallel_index_tokens, 0
        for other_channel, entry in earlier_requests:
            used += self.tokenizer.count(self.get_parallel_request_text(conn, other_channel, entry.text or ""))
            if used > budget:
                break
        else:
            return [], 0                                  # they fit: each a message, as always
        tables.apply_cleaned_texts(conn, [entry for _, entry in earlier_requests])
        made_id, item, tokens = tables.make_message(conn, self.format, self.tokenizer, channel_id, sections.requests_before(earlier_requests, budget, self.tokenizer),
                                          PARALLEL_BEFORE, f"requests before {start}")
        return [(made_id, item, tokens)], start

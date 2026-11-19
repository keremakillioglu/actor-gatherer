"""Which sessions share work, and how a session is told when that changes.

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
message, an app's -- that names a group (its payload's `group`) is shown only to that group's channels (`get_visible_events`)."""

from typing import Callable, Dict, List, Optional, Tuple

from ag.ag_interface import Row, event_text
from ag.ag_interface.policy import TypeIds
from ag.ag_policies.tools import channel, history
from ag.ag_policies.tools import tasks as tasks_tool
from ag.ag_policies.tools.channel import channel_of
from . import tables
from .gatherer_messages import GROUP_CHANGE, GathererMessages

ROLE = "role"                   # a channel's role, as the dashboard records it: {role, private} (`get_hidden_sessions`)
GROUP = "group"                 # a channel's group, as the dashboard records it: {group, ...} (`get_hidden_sessions`); each
                                # record an id of its own, naming its channel: a read returns an id once, where it
                                # was first stored, whatever its channel
ALONE = "self:"                 # a group of one: an actor on its own (the dashboard's `self:<channel>`)
OPENING_CHARS = 600             # how far into a message its opening is looked for, past a harness's wrapper (`is_user_request`)


def get_groups_read(payload: dict) -> frozenset:
    """The groups a `role` record says its channel reads (`reads`: a coordinator agent's over several groups)."""
    got = payload.get("reads") if isinstance(payload, dict) else None
    return frozenset(str(g) for g in got if g) if isinstance(got, list) else frozenset()


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


class SessionGroups(GathererMessages):

    def get_hidden_sessions(self, conn, types: TypeIds, channel_id) -> HiddenSessions:
        """The channels `channel_id` is not shown (`in`): those whose latest ROLE record says `private`, and those of
        another group than its own -- a channel's group the latest GROUP record in it names, "" without one."""
        private: Dict[str, bool] = {}
        reads: Dict[str, frozenset] = {}
        group: Dict[str, str] = {}
        role_ids = types.of(ROLE)
        for r in conn.rows(0, types.of(ROLE, GROUP)):
            ch = channel_of(r)
            if ch is None or not isinstance(r.payload, dict):
                continue
            if r.type.id in role_ids:
                private[ch] = bool(r.payload.get("private"))
                reads[ch] = get_groups_read(r.payload)
            else:
                group[ch] = str(r.payload.get("group") or "")
        return HiddenSessions({ch for ch, hidden in private.items() if hidden}, group, group.get(channel_id, ""),
                      reads.get(channel_id, frozenset()))

    def has_group_changed(self, conn, types: TypeIds, channel_id, since_row: int) -> bool:
        """Whether what the channel is shown changed groups after `since_row`: a GROUP record stored since moved a
        channel from one group to another (its `was` given, and not its `group`) -- this one, or another into or out
        of this one's group. A first record (no `was`: an actor starting) changes nothing of the others': its
        requests come to them as any new session's do."""
        moves, role_ids = [], types.of(ROLE)
        for r in conn.rows(since_row, types.of(GROUP, ROLE)):
            p = r.payload if isinstance(r.payload, dict) else {}
            if r.type.id in role_ids:
                if channel_of(r) == channel_id and "reads" in p:
                    return True                       # the groups it reads changed (the dashboard writes them so)
            elif "was" in p and str(p.get("group") or "") != str(p.get("was") or ""):
                moves.append((channel_of(r), str(p.get("group") or ""), str(p.get("was") or "")))
        if not moves:
            return False
        seen = self.get_hidden_sessions(conn, types, channel_id)
        return any(moved == channel_id or seen.is_shown_group(group) or seen.is_shown_group(was) for moved, group, was in moves)

    def get_groups_read_before(self, conn, types: TypeIds, channel_id, row_id: int) -> frozenset:
        """The groups the channel read before the row `row_id`: its latest `role` record before it's."""
        got = frozenset()
        for r in conn.rows(0, types.of(ROLE)):
            if r.row_id >= row_id:
                break
            if channel_of(r) == channel_id and isinstance(r.payload, dict):
                got = get_groups_read(r.payload)
        return got

    def is_user_request(self, r: Row) -> bool:
        """Whether another channel's user message is shown to this one as its user's request: not a message the actors
        sent each other, which opens a line with one of `unshared_openings` -- at its start, or past the wrapper its
        harness put round it (a mid-turn note, a paste's tags)."""
        openings = self.config.unshared_openings
        if not openings:
            return True
        head = (event_text(r) or "")[:OPENING_CHARS]
        return not any(line.lstrip().startswith(openings) for line in head.split("\n"))

    def get_visible_events(self, conn, types: TypeIds, channel_id, cut: int, name: str) -> list:
        """The events of type `name` the channel can see from `cut` on -- the
        verbatim part of the context; those a build has condensed past are
        not looked at -- in row order."""
        rows = conn.rows(after_row=max(cut - 1, 0), match=channel.of(channel_id), type_ids=types.of(name))
        if not any(channel_of(r) is None and isinstance(r.payload, dict) and "group" in r.payload for r in rows):
            return rows
        seen = self.get_hidden_sessions(conn, types, channel_id)        # a record with no channel, for one group: its channels'
        return [r for r in rows if channel_of(r) is not None or not isinstance(r.payload, dict)
                or seen.is_shown_group(str(r.payload.get("group", seen.own) or ""))]

    def make_group_change_notes(self, conn, types: TypeIds, channel_id, cut: int) -> List[tuple]:
        """("made", row_id, item, (made_id, tokens)) for each change of groups in the verbatim part that changed what
        the channel is shown (`has_group_changed`): its own move (`group_moved`), or a run of other channels' moves into or out
        of its group -- records stored one after another, as a folder's move writes them -- as one message
        (`group_joined`, `group_left`), at its first record's place."""
        ids, role_ids = types.of(GROUP), types.of(ROLE)
        rows = conn.rows(after_row=max(cut - 1, 0), type_ids=ids | role_ids) if ids else []
        moves = [(r, r.payload) for r in rows if isinstance(r.payload, dict) and (
            (r.type.id in role_ids and channel_of(r) == channel_id and "reads" in r.payload)
            or (r.type.id not in role_ids and "was" in r.payload
                and str(r.payload.get("group") or "") != str(r.payload.get("was") or "")))]
        if not moves:
            return []
        cfg = self.config
        seen = self.get_hidden_sessions(conn, types, channel_id)
        reads_before: Optional[frozenset] = None             # what it read before each role record: the note says the change

        def named(name, group_id: str) -> str:
            return str(name) if name else (f"group {group_id}" if group_id else cfg.group_own)

        said, run, last_row = [], None, None                 # said: [row_id, kind, text or [channels]]
        for r, p in moves:
            if r.type.id in role_ids:                        # the groups it reads, changed
                now = get_groups_read(p)
                if reads_before is None:
                    reads_before = self.get_groups_read_before(conn, types, channel_id, r.row_id)
                came, left = sorted(now - reads_before), sorted(reads_before - now)
                reads_before = now
                names = p.get("names") if isinstance(p.get("names"), dict) else {}
                said += [[r.row_id, "moved", text.format(groups=", ".join(str(names.get(g) or g) for g in which))]
                         for text, which in ((cfg.reads_added, came), (cfg.reads_removed, left)) if which]
                run = None
                last_row = r.row_id
                continue
            group, was, moved = str(p.get("group") or ""), str(p.get("was") or ""), channel_of(r)
            if moved == channel_id:
                to, fro = named(p.get("name"), group), named(p.get("was_name"), was)
                said.append([r.row_id, "moved", cfg.group_alone.format(was=fro) if group.startswith(ALONE)
                             else cfg.group_back.format(group=to) if was.startswith(ALONE)
                             else cfg.group_moved.format(group=to, was=fro)])
                run = None
            elif seen.is_shown_group(group) != seen.is_shown_group(was):
                kind = "joined" if seen.is_shown_group(group) else "left"
                if run is not None and run[1] == kind and r.row_id == last_row + 1:
                    run[2].append(moved)
                else:
                    run = [r.row_id, kind, [moved]]
                    said.append(run)
            else:
                run = None
            last_row = r.row_id
        out = []
        for row_id, kind, what in said:
            text = what if kind == "moved" else (cfg.group_joined if kind == "joined" else cfg.group_left).format(
                channels=", ".join(what))
            made_id, item, tokens = self.make_message(conn, channel_id, text, GROUP_CHANGE, f"group {row_id}")
            out.append(("made", row_id, item, (made_id, tokens)))
        return out

    def get_other_sessions_tasks(self, conn, types: TypeIds, channel_id,
                    stopped: Callable[[], bool] = lambda: False) -> Tuple[List, Dict]:
        """(the other channels' tasks, located in their turns; those turns, by channel): each channel's whole history
        read, so seconds in a big gatherer -- cut short, with what was found so far, once `stopped` (the harness hung
        up on the call: `Read.stopped`)."""
        found, turns_by_channel, unseen = [], {}, self.get_hidden_sessions(conn, types, channel_id)
        for other in tables.get_channels_with_tasks(conn):
            if stopped():
                break
            if other == channel_id or other is None or other in unseen:
                continue
            _, turns = history.split(history.rows(conn, types, self.groups, other), types, self.groups, self.tokenizer)
            tables.apply_cleaned_texts(conn, [t.entries[0] for t in turns])
            turns_by_channel[other] = turns
            found += tasks_tool.locate(tables.get_own_tasks(conn, other), turns)
        return found, turns_by_channel

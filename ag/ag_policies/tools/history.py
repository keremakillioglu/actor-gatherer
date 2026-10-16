"""A channel's history, by type: entries, turns and tasks.

An ENTRY is one stored event with its readable text (`event_text`) and its type's place in the policy's `Groups`. A TURN is an event whose
type opens one (a real user message) and everything up to the next.
Entries before the first such event are the PREAMBLE: the agent's own set-up,
kept verbatim and never summarised. A TASK is a run of consecutive turns
serving one objective, as segmentation found it.

A task is kept by ROW range (`first_row`..`last_row`), not turn number, so it
stays put if rows are added before it later (e.g. a history loaded into the
no-channel pool of a gatherer already running). Turn numbers are derived from
the rows whenever a history is loaded (`tasks.locate`).

Every load here is by the ids of the types a policy's groups name: nothing
of another type is ever seen.
"""

from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

from ag.ag_interface import Tokenizer
from ag.ag_interface import Row, event_text, property_column
from ag.ag_interface.policy import TypeIds
from . import channel
from .channel import channel_of
from .groups import Groups


@dataclass
class Entry:
    """One stored event with its readable text, and where its type sits in
    the policy's groups (set when it is loaded)."""
    row_id: int
    type: Optional[str]             # its type's name
    text: str
    payload: Any
    tokens: int                     # of the text, by the policy's tokenizer
    is_user: bool = False           # opens a turn
    is_message: bool = False        # rendered in the messages-only parts
    is_tool: bool = False           # rendered in the full parts only
    is_pinned: bool = False         # carried verbatim, never rendered
    type_id: int = 0


@dataclass
class Turn:
    index: int                      # 1-based, in this channel's history
    entries: List[Entry] = field(default_factory=list)

    @property
    def first_row(self) -> int:
        return self.entries[0].row_id

    @property
    def last_row(self) -> int:
        return self.entries[-1].row_id

    @property
    def user_text(self) -> str:
        return self.entries[0].text

    @property
    def message_tokens(self) -> int:
        return sum(e.tokens for e in self.entries if e.is_message)


@dataclass
class Task:
    name: str
    description: str
    first_row: int
    last_row: int
    start_turn: int = 0
    end_turn: int = 0
    tokens: int = 0
    retention: dict = field(default_factory=dict)
    channel_id: Optional[str] = None      # the channel it was found in
    task_index: int = 0                   # position in its channel's task list


# ---------------------------------------------------------------- loading

def opens_turn(row: Row, types: TypeIds, groups: Groups) -> bool:
    """Whether the event is a user message: its type is one of those that
    open a turn."""
    return row.type.id in types.of(*groups.user)


def entry(row: Row, types: TypeIds, groups: Groups, tok: Tokenizer) -> Entry:
    text = event_text(row)
    tid = row.type.id
    # Its size is what it costs the model: the tokens stored with the event (the caller's count,
    # else its text's), not a recount here, which would count an opaque blob as conversation.
    return Entry(row.row_id, row.type.name, text, row.payload, row.tokens,
                 is_user=tid in types.of(*groups.user), is_message=tid in types.of(*groups.messages),
                 is_tool=tid in types.of(*groups.tools), is_pinned=tid in types.of(*groups.pinned),
                 type_id=tid)


def rows(conn, types: TypeIds, groups: Groups, channel_id: Optional[str], after_row: int = 0) -> List[Row]:
    """The rows `channel_id` can see of the groups a policy works from, in order."""
    return conn.rows(after_row, types.of(*groups.history), match=channel.of(channel_id))


def batch_start(conn, channel_id: Optional[str], row_id: int) -> int:
    """The row the channel's last read before event `row_id` was stored
    responded to (0: none). The channel's rows after it, up to `row_id`,
    came in with the same request: for an event a poller stored, what the
    agent did since its previous model call -- the tool calls it made and
    their outputs."""
    col = property_column(channel.CHANNEL)
    found = conn.execute(f"SELECT row_id FROM _reads WHERE ifnull({col}, '') = ? AND read_at < "
                         f"(SELECT inserted_at FROM events WHERE row_id = ?) ORDER BY read_id DESC LIMIT 1",
                         (channel_id or "", row_id)).fetchone()
    return (found[0] or 0) if found else 0


def split(rows: List[Row], types: TypeIds, groups: Groups, tok: Tokenizer) -> Tuple[List[Entry], List[Turn]]:
    """(preamble, turns) from a channel's rows, in order."""
    preamble, turns = [], []
    for row in rows:
        e = entry(row, types, groups, tok)
        if e.is_user:
            turns.append(Turn(len(turns) + 1, [e]))
        elif turns:
            turns[-1].entries.append(e)
        else:
            preamble.append(e)
    return preamble, turns


def turns(conn, types: TypeIds, groups: Groups, tok: Tokenizer, channel_id: Optional[str]) -> Tuple[List[Entry], List[Turn]]:
    """(preamble, turns) of everything `channel_id` can see."""
    return split(rows(conn, types, groups, channel_id), types, groups, tok)


def arrange(rows: List[Row], types: TypeIds, groups: Groups) -> Tuple[list, list]:
    """(preamble, body): the rows before the first turn, and the rest.

    A channel's rows and the no-channel pool's are one stream, but each began
    with its own preamble (the agent's instructions, its environment). The
    channel's own leads -- it describes where the agent is now -- and the
    pool's is left out; without rows of its own, the pool's stands."""
    own = [r for r in rows if channel_of(r) is not None]
    lead = own or rows
    preamble = []
    for r in lead:
        if opens_turn(r, types, groups):
            break
        preamble.append(r)
    skip = {r.row_id for r in preamble}
    if own:
        for r in rows:                                    # the pool's preamble
            if channel_of(r) is not None or opens_turn(r, types, groups):
                break
            skip.add(r.row_id)
    return preamble, [r for r in rows if r.row_id not in skip]


def merge(*row_lists) -> list:
    """Several row lists as one stream, by row id."""
    out = [r for rows_ in row_lists for r in rows_]
    return sorted(out, key=lambda r: r.row_id)


def other_requests(conn, types: TypeIds, groups: Groups, tok: Tokenizer, channel_id: Optional[str],
                   after_row: int = 0) -> List[Tuple[Optional[str], Entry]]:
    """(channel, entry) for every user message stored in another channel
    after `after_row`, oldest first."""
    return [(channel_of(r), entry(r, types, groups, tok))
            for r in conn.rows(after_row, types.of(*groups.user), differ=channel.of(channel_id))]

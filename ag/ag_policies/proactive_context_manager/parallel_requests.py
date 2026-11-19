"""The requests the user made to the session's other channels.

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

from typing import Dict, List, Tuple

from ag.ag_interface import event_text, property_column
from ag.ag_interface.policy import TypeIds
from ag.ag_policies.tools import channel, history
from ag.ag_policies.tools.channel import CHANNEL, channel_of
from . import layout, tables
from .gatherer_messages import PARALLEL_BEFORE, PARALLEL_REQUEST
from .session_groups import SessionGroups


class ParallelRequests(SessionGroups):

    def get_parallel_request_text(self, conn, channel_id, text: str) -> str:
        """A request of channel `channel_id`'s, worded as the config's `parallel_message`."""
        return self.config.parallel_message.format(text=text, channel=channel_id, db_path=conn.path,
                                                   channel_column=property_column(CHANNEL))

    def make_parallel_requests(self, conn, types: TypeIds, channel_id, after_row: int) -> List[tuple]:
        """(made_id, item, tokens, its row id) for each user message stored in
        another channel after `after_row`, oldest first."""
        out, unseen = [], self.get_hidden_sessions(conn, types, channel_id)
        for r in conn.rows(after_row, types.of(*self.groups.user), differ=channel.of(channel_id)):
            other = channel_of(r)
            if other is None or other == channel_id or other in unseen or not self.is_user_request(r):
                continue
            made_id, item, tokens = self.make_message(conn, channel_id, self.get_parallel_request_text(conn, other, event_text(r) or ""),
                                              PARALLEL_REQUEST, f"request {r.row_id}")
            out.append((made_id, item, tokens, r.row_id))
        return out

    def get_request_positions(self, conn, refs: list, tail_from: int, rows, types: TypeIds, channel_id,
                        shown: List[tuple]) -> List[int]:
        """Where in the context each of `format_time` goes, before any is inserted: where it was in the
        channel's last read (`get_last_read_positions`) -- before the row it came before, or, shown last, before
        the first row after the one it came after -- or, that row condensed away, before the first
        row of the verbatim part (`refs[tail_from:]`) after it. A request not shown before goes
        before this channel's latest user message, the call being at it; mid-turn (a step of the
        agent's own after that message), or with none, at the end. Not before the turn's steps: a
        thinking block counts, and the model reads it, only after the history it was written in, so
        a request put before them would leave out all the turn's thinking so far."""
        mine = [r for r in rows if channel_of(r) == channel_id]
        own = [r.row_id for r in mine if history.opens_turn(r, types, self.groups)]
        latest = own[-1] if own else None
        steps = types.of(*self.groups.messages, *self.groups.tools, *self.groups.verbatim)
        if latest is not None and any(r.row_id > latest and r.type.id in steps for r in mine):
            latest = None                                # mid-turn: a new one goes at the end
        before, after = self.get_last_read_positions(conn, channel_id)
        places = []
        for _, _, _, row in shown:
            if row in after:                             # shown last: right after the row it followed
                anchor = after[row] + 1
            else:
                anchor = before.get(row, latest)
            at = len(refs) if anchor is None else next(
                (i for i in range(tail_from, len(refs)) if refs[i].row_id is not None and refs[i].row_id >= anchor),
                len(refs))
            places.append(at)
        return places

    def get_last_read_positions(self, conn, channel_id) -> Tuple[Dict[int, int], Dict[int, int]]:
        """({request row: the row it came before}, {request row: the row it came after}) for each other
        channel's request the channel's last read showed (its made item's source names the request):
        the second for one shown last, with no row after it (shown mid-turn, at the end). Every request
        since the build's mark is shown on every read, so the last read has each one shown before, in
        its place."""
        last = conn.last_read(channel.of(channel_id))
        refs = last["refs"] if last else []
        made = [r.made_id for r in refs if r.made_id is not None]
        if not made:
            return {}, {}
        sources = dict(conn.execute(f"SELECT made_id, source FROM _made_items WHERE name = ? AND made_id IN "
                                    f"({','.join('?' * len(made))})", [PARALLEL_REQUEST, *made]).fetchall())
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
        (`layout.requests_before`). Made at the first read without a build that needs it and reused
        after (the channel's last read, made without a build, has it), so later reads extend the
        same context."""
        cfg = self.config
        start = next((r.row_id for r in rows if channel_of(r) == channel_id), None)
        if start is None:
            return [], 0
        last = conn.last_read(channel.of(channel_id))
        if last and tables.basis_of(last) is None:
            made = [r.made_id for r in last["refs"] if r.made_id is not None]
            kept = [(m, item, tokens) for m, (name, item, tokens) in conn.made_items(made).items()
                    if name == PARALLEL_BEFORE]
            if kept and not self.has_group_changed(conn, types, channel_id, last.get("row_id") or 0):
                return kept[:1], start
        unseen = self.get_hidden_sessions(conn, types, channel_id)
        before = [(c, e) for c, e in history.other_requests(conn, types, self.groups, self.tokenizer, channel_id,
                                                            keep=lambda r: channel_of(r) not in unseen and self.is_user_request(r))
                  if e.row_id < start]
        budget, used = cfg.all_task_tokens + cfg.parallel_index_tokens, 0
        for other, e in before:
            used += self.tokenizer.count(self.get_parallel_request_text(conn, other, e.text or ""))
            if used > budget:
                break
        else:
            return [], 0                                  # they fit: each a message, as always
        tables.apply_cleaned_texts(conn, [e for _, e in before])
        made_id, item, tokens = self.make_message(conn, channel_id, layout.requests_before(before, budget, self.tokenizer),
                                          PARALLEL_BEFORE, f"requests before {start}")
        return [(made_id, item, tokens)], start

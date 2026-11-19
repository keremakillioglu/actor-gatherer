"""The gatherer's messages: what ag adds to an agent's context besides the conversation's own rows -- the gatherer
guide, the history sections, the requests made in parallel, file-change notices, messages from a stream, notes of a
change of groups and left-out notes. Each is a made item, named by its kind (the names below) and stored so the read
log shows what was sent (`make_message`); its words come from wording.py. A read makes every one again but the history
sections, which are laid out once per build and reused (`REMADE_EVERY_READ`), and places each at its own row among the
conversation's (`interleave_messages`)."""

from typing import Any, Dict, List, Tuple

from ag.ag_interface.policy import TypeIds
from ag.ag_policies.tools import channel
from .events import CONTEXT_STREAM, ENVIRONMENT_UPDATE

GUIDE = "gatherer_guide"              # the guide every context opens with
PARALLEL_REQUEST = "parallel_request"   # a request the user made to another session
PARALLEL_BEFORE = "parallel_before"   # with no build: the other channels' requests before the channel began, as one block
LEFT_OUT = "left_out"                 # a step stubbed to keep the context within max_context_tokens
GROUP_CHANGE = "group_change"         # the message saying a change of groups changed what a channel is shown
# A message from a stream and a file-change notice are named by the event types they show (events.py).
REMADE_EVERY_READ = (CONTEXT_STREAM, ENVIRONMENT_UPDATE, PARALLEL_REQUEST, PARALLEL_BEFORE, LEFT_OUT, GUIDE, GROUP_CHANGE)

TOOL_CALL, TOOL_OUTPUT = "tool_call", "tool_output"
CALL_ID = "call_id"             # the property a harness's adaptor gives a tool call and its output alike (`get_call_output_pairs`)


class GathererMessages:
    """A part of ProactiveContextManager (policy.py), as every class of this package is: its methods run on the
    policy, and read what the policy holds -- `config` (the one in force: the read's or the build's), `format`,
    `tokenizer`, `llm`, `jobs` (None: no background work) and `groups` (the config's)."""

    def make_message(self, conn, channel_id, text: str, name: str, source: str) -> Tuple[int, Any, int]:
        """(made_id, item, tokens) of `text` shown to the channel as a developer message named `name`: a made item,
        so the read log shows what was sent, `source` saying what it was made from."""
        item = self.format.make_section(text, name)
        made_id = conn.make_item(item, self.tokenizer, properties=channel.of(channel_id), name=name, source=source)
        return made_id, item, conn.made_items([made_id])[made_id][2]

    def interleave_messages(self, tail, made_here: List[tuple], types: TypeIds) -> List[tuple]:
        """The tail's rows, as ("row", row_id, payload, tokens), and the
        messages and notices made for outside events, together in row
        order: each where its event was stored, which -- the pollers being
        asked at read time -- is where the model first saw it. But never
        between a tool call and its output (`get_call_output_pairs`): one stored there
        goes right after the output. A call and its output come in with one
        request, so nothing is stored between them -- until the harness hangs
        up on the call that sent the output (the output withdrawn: its newest
        user row) and sends it again changed (Claude Code, resumed, puts a
        note of its own inside it): stored again as a new row, after what came
        in meanwhile. The API refuses a tool call with anything but its
        result right after it."""
        entries = [("row", r.row_id, r.payload, r.tokens) for r in tail] + list(made_here)
        spans = self.get_call_output_pairs(tail, types)

        def place(e) -> tuple:
            if e[0] == "row":
                return (e[1], 0, e[1])
            at = e[1]
            moved = True
            while moved:                                     # past every exchange it falls in, nested or chained
                ends = [end for start, end in spans if start < at < end]
                moved = bool(ends)
                at = max(ends) if ends else at
            return (at, 0 if at == e[1] else 1, e[1])        # moved: right after the output, in its own order
        return sorted(entries, key=place)

    @staticmethod
    def get_call_output_pairs(tail, types: TypeIds) -> List[Tuple[int, int]]:
        """(call row, output row) of each tool call of `tail` whose output is in it too, paired by the call id
        the harness's adaptor gives both (CALL_ID); a row without one pairs with nothing."""
        calls_ids, outputs_ids = types.of(TOOL_CALL), types.of(TOOL_OUTPUT)
        calls: Dict[Any, int] = {}
        spans = []
        for r in tail:
            call = (r.properties or {}).get(CALL_ID)
            if call is None:
                continue
            if r.type.id in calls_ids:
                calls.setdefault(call, r.row_id)
            elif r.type.id in outputs_ids and call in calls:
                spans.append((calls[call], r.row_id))
        return spans

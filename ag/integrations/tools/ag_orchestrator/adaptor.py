"""What a harness's adaptor is: the policy-specific half of its hook, turning
the harness's messages into the context manager's events and the context
back into messages -- and saying which of each it handles.

    class MyAdaptor(Adaptor):
        name = "my_harness"
        outputs = (USER_MESSAGE, AGENT_MESSAGE, TOOL_CALL, TOOL_OUTPUT, CONTEXT)
        accepts = outputs + ("ag",)
        properties = (CHANNEL, CWD)
        def to_events(self, messages): ...
        def to_messages(self, context, messages): ...

`outputs` are the event type names `to_events` emits, and nothing else: ag
refuses to run a policy whose `event_types` do not take them all, and
`call_ag` refuses an event of any other type. `accepts` are the context
entries `to_messages` can show -- event type names, and AG (the context
manager's own messages); `call_ag` notes any other it is given.
`properties` are the event properties its harness's routing sets, on every
event and read (e.g. CHANNEL): ag refuses to run a
policy whose types for `outputs` do not declare them all, or require one
not among them, and `call_ag` refuses to send any other. adaptor.ts is the
same in TypeScript.
"""

from abc import ABC, abstractmethod
from typing import ClassVar, List, Tuple

#: The type of the context manager's own messages in a context.
AG = "ag"
#: The property the harnesses' routing sets: which of the harness's threads
#: or sessions an event or a read belongs to -- the name the policies' event
#: types declare it by.
CHANNEL = "channel"
#: The property call_ag sets from the request's working directory: where the
#: agent works, which the file poller's events are matched against.
CWD = "cwd"


class Adaptor(ABC):
    r"""What a harness's adaptor is: the policy-specific half of its hook, turning the harness's
    messages into events and the context back into messages, and saying which of each it handles.

    An adaptor is a Python subclass of `Adaptor`, or a TypeScript class implementing `Adaptor<M>`
    (adaptor.ts) with the same declarations as static fields (`adaptorName`, `outputs`,
    `accepts`, `properties`).

    - `to_events` returns one dict per event: `type` (one of `outputs`), `id`, `payload`, and
      optionally `text` and `tokens`.
        - **`id`:** the harness re-sends its whole conversation on every call, so give each
          message a stable id. Use the harness's own id, or a hash of the message, so that a
          message is stored once.
        - **Splitting:** one event per unit the policy should see. If an assistant message
          holds both text and tool calls, split it, as the Pi adaptor does.
        - **`text`:** what the policy should read: the words, a tool call's name and arguments,
          a tool's output, without ids and metadata.
        - **`tokens`:** set it to 0 for opaque content such as encrypted reasoning.
    - `to_messages` gets back events in the order the model should see them, and must rebuild
      valid messages for the harness's API. It also shows the policy's `ag` messages, as a
      developer, system or user message.
    - The declarations are checked. `ag` refuses to run a policy that does not accept every type
      in `outputs`, or every property in `properties`. An event of an undeclared type makes the
      hook send the harness's own messages unchanged, and a context entry not in `accepts` is
      noted.

    **A sketch** (`TYPES`, `kind_of`, `text_of` and `as_system_message` stand for the harness's own:
    the event type names it emits, and its logic):

    ```python
    from ag.integrations.tools.ag_orchestrator.adaptor import AG, CHANNEL, CWD, Adaptor


    class MyAdaptor(Adaptor):
        name = "mine"
        outputs = TYPES                        # the event type names to_events emits
        accepts = outputs + (AG,)              # what to_messages can show: event types, and ag messages
        properties = (CHANNEL, CWD)            # the properties the hook sets

        def to_events(self, messages):
            return [{"type": kind_of(m), "id": m["id"], "payload": m, "text": text_of(m)} for m in messages]

        def to_messages(self, context, messages):
            return [as_system_message(e["text"]) if e["type"] == AG else e["payload"] for e in context]
    ```

    Working adaptors: `ClaudeAdaptor` (ag/integrations/harnesses/claude/adaptor/), the smallest
    Python one, and `PiAdaptor` and `OpencodeAdaptor` in TypeScript.
    """
    name: ClassVar[str] = ""
    outputs: ClassVar[Tuple[str, ...]] = ()
    accepts: ClassVar[Tuple[str, ...]] = ()
    properties: ClassVar[Tuple[str, ...]] = ()

    @abstractmethod
    def to_events(self, messages: list) -> List[dict]:
        """The harness's messages as events, `{"type", "id", "payload", "tokens"?, "text"?}`,
        each of a type in `outputs`. `text` is what a reader of the history needs of
        the message -- its words, a tool call's name and arguments, a tool's output --
        without the harness's ids and metadata: what the policies show and count."""

    @abstractmethod
    def to_messages(self, context: List[dict], messages: list) -> list:
        """The context -- events as they were sent, and `ag` messages -- as the
        messages the harness sends its model."""

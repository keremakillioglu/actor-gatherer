/**
 * pi's adaptor: its messages as the context manager's events (to_events.ts),
 * and the context back as pi's messages (to_messages.ts).
 */

import type { ContextEntry, Event } from "../../../tools/ag_connection/protocol.ts";
import { type Adaptor, CHANNEL, AG, CWD } from "../../../tools/ag_orchestrator/adaptor.ts";
import { AGENT_MESSAGE, AGENT_REASONING, CONTEXT, type Message, TOOL_CALL, TOOL_OUTPUT, toEvents, USER_MESSAGE } from "./to_events.ts";
import { toMessages } from "./to_messages.ts";

export class PiAdaptor implements Adaptor<Message> {
	static readonly adaptorName = "pi";
	static readonly outputs = [USER_MESSAGE, AGENT_MESSAGE, TOOL_CALL, TOOL_OUTPUT, CONTEXT, AGENT_REASONING];
	static readonly accepts = [...PiAdaptor.outputs, AG];
	static readonly properties = [CHANNEL, CWD];

	toEvents(messages: Message[]): Event[] {
		return toEvents(messages);
	}

	toMessages(context: ContextEntry[], messages: Message[]): Message[] {
		return toMessages(context, messages) as Message[];
	}
}

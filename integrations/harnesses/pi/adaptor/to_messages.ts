/**
 * The context manager's answer as pi's messages -- the policy-specific half of
 * the pi harness, with to_events.ts (the way in).
 *
 *   const messages = toMessages(answer.context);   // what pi's model gets
 *
 * The context is the events the policy kept, as they were sent -- the pieces
 * to_events.ts made -- and the context manager's own messages,
 * {type: "ag", name, text}. Consecutive pieces of one assistant message are
 * joined again; an `ag` message becomes a hidden `custom` message, which pi
 * sends as a user message (it has no developer role).
 */

import { type ContextEntry, isAg, isObject, stableStringify } from "../../../tools/ag_connection/protocol.ts";
import type { Message } from "./to_events.ts";

/** The customType of the messages the context manager makes. */
export const CUSTOM_TYPE = "context_manager";

function withoutContent(m: Message): string {
	const { content: _content, ...rest } = m;
	return stableStringify(rest);
}

/** Whether two pieces came from one assistant message: everything but the content is the same. */
function sameMessage(a: unknown, b: unknown): boolean {
	return isObject(a) && isObject(b) && a.role === "assistant" && b.role === "assistant"
		&& withoutContent(a) === withoutContent(b);
}

/** Items as pi messages: consecutive pieces of one assistant message joined again; everything else as it is. */
export function join(items: Message[]): Message[] {
	const out: Message[] = [];
	for (const item of items) {
		const last = out[out.length - 1];
		if (last && sameMessage(last, item) && Array.isArray(last.content) && Array.isArray(item.content)) {
			out[out.length - 1] = { ...last, content: [...last.content, ...item.content] };
		} else {
			out.push(item);
		}
	}
	return out;
}

/** A hidden `custom` message carrying the context manager's text. */
export function agMessage(text: string, now: number = Date.now()): Message {
	return { role: "custom", customType: CUSTOM_TYPE, content: text, display: false, timestamp: now };
}

/** The context as pi's messages: each event's payload as it was sent, pieces joined, `ag` messages as custom ones. */
export function toMessages(context: ContextEntry[], _messages: Message[] = []): Message[] {
	const items: Message[] = [];
	for (const entry of context) {
		if (isAg(entry)) items.push(agMessage(entry.text));
		else if (isObject(entry) && "payload" in entry) items.push(entry.payload as Message);
	}
	return join(items);
}

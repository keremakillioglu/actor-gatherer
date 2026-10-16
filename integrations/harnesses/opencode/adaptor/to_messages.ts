/**
 * The context manager's answer as opencode's messages -- the policy-specific
 * half of the opencode harness, with to_events.ts (the way in).
 *
 *   const messages = toMessages(answer.context, output.messages);
 *
 * The context is the events the policy kept, as they were sent -- the pieces
 * to_events.ts made -- and the context manager's own messages,
 * {type: "ag", name, text}. A message the context kept anything of is
 * opencode's own current copy of it (this call's `messages`), with only the
 * parts kept, so the parts that were not sent come back in place; one opencode
 * no longer sends is rebuilt from the context; an `ag` message becomes a user
 * message with one synthetic text part.
 */

import { type ContextEntry, isAg, isObject } from "../../../tools/ag_connection/protocol.ts";
import { CALL, type Item, type Message, messageId, PART_TYPES } from "./to_events.ts";

/**
 * Items as opencode messages, given this call's `messages`. An assistant message the manager kept pieces of
 * comes back once, where its first piece is: opencode's current copy of it with only the parts kept (and all
 * its parts that are not items), or, if opencode no longer sends it, rebuilt from the pieces (a tool part from
 * its result; a call whose result was not kept is left out, as a call without a result would be refused). A
 * user message is opencode's current copy, if it sends it. Anything else is as it is.
 */
export function join(items: Item[], messages: Message[] = []): Item[] {
	const current = new Map<string, Message>();
	for (const m of messages) {
		const id = messageId(m);
		if (id) current.set(id, m);
	}
	type Slot = { info: Item; pieces: Item[] };
	const out: (Item | Slot)[] = [];
	const slots = new Map<string, Slot>();
	for (const item of items) {
		const id = messageId(item);
		if (isObject(item) && "part" in item && id) {
			let slot = slots.get(id);
			if (!slot) {
				slot = { info: item.info, pieces: [] };
				slots.set(id, slot);
				out.push(slot);
			}
			slot.pieces.push(item);
		} else if (id && current.has(id)) {
			out.push(current.get(id)!);
		} else {
			out.push(item);
		}
	}
	const result: Item[] = [];
	for (const entry of out) {
		if (!(entry as Slot).pieces || !slots.has(messageId(entry) ?? "")) {
			result.push(entry);
			continue;
		}
		const slot = entry as Slot;
		const keptIds = new Set(slot.pieces.map((p) => p.part?.id));
		const original = current.get(slot.info.id);
		let message: Message;
		if (original) {
			const parts = (original.parts ?? []).filter((p) => !isObject(p) || !(p.type in PART_TYPES) || keptIds.has(p.id));
			message = { info: original.info, parts };
		} else {
			const parts: Item[] = [];
			const seen = new Set<string>();
			for (const p of slot.pieces) {
				if (p.piece === CALL || seen.has(p.part?.id)) continue; // a call's result carries it
				seen.add(p.part?.id);
				parts.push(p.part);
			}
			message = { info: slot.info, parts };
		}
		if (message.parts.length > 0) result.push(message);
	}
	return result;
}

let made = 0;

/** A user message carrying the context manager's text, its one part synthetic. */
export function agMessage(text: string, now: number = Date.now()): Message {
	const id = `msg_ag${now.toString(36)}${(made++).toString(36)}`;
	return {
		info: { id, role: "user", time: { created: now } },
		parts: [{ id: `prt_ag${now.toString(36)}${made.toString(36)}`, messageID: id, type: "text", text, synthetic: true }],
	};
}

/** The context as opencode's messages, given this call's: payloads joined back, `ag` messages as user messages. */
export function toMessages(context: ContextEntry[], messages: Message[] = []): Item[] {
	const items: Item[] = [];
	for (const entry of context) {
		if (isAg(entry)) items.push(agMessage(entry.text));
		else if (isObject(entry) && "payload" in entry) items.push(entry.payload as Item);
	}
	return join(items, messages);
}

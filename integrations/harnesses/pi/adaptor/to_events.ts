/**
 * pi's messages as the context manager's events -- the policy-specific half of
 * the pi harness, with to_messages.ts (the way back).
 *
 *   const events = toEvents(messages);   // what the extension's routing sends in a `rewrite`
 *
 * pi's messages (pi's session format): user, assistant (content blocks:
 * text, thinking, toolCall), toolResult, and pi's own custom, bashExecution,
 * compactionSummary, branchSummary. One assistant message carries its thinking,
 * its answer and its tool calls together, where the policies expect an event
 * each: an assistant message is split into PIECES, one per content block (the
 * message with that block alone); to_messages.ts joins the pieces of one
 * message again. Each piece is typed by its block, every other
 * message by its role, as one of the event types the policies expect (the
 * standard five, and AGENT_REASONING: a thinking block, the model's own
 * reasoning, kept and sent back as it was but never read or counted). Each
 * event carries its text (textOf): what the model reads of it -- a message's
 * words, a tool call's name and arguments, a tool's output -- without pi's
 * ids, timestamps, usage or signatures.
 */

import { contentId, type Event, isObject } from "../../../tools/ag_connection/protocol.ts";

// The event types the policies expect: the standard five, and the model's own reasoning.
export const USER_MESSAGE = "user_message";
export const AGENT_MESSAGE = "agent_message";
export const TOOL_CALL = "tool_call";
export const TOOL_OUTPUT = "tool_output";
export const CONTEXT = "context";
export const AGENT_REASONING = "agent_reasoning";

/** A message's role -> its event type; an assistant piece is typed by its block. pi's own messages are CONTEXT. */
export const ROLE_TYPES: Record<string, string> = {
	user: USER_MESSAGE,
	toolResult: TOOL_OUTPUT,
	custom: CONTEXT,
	bashExecution: CONTEXT,
	compactionSummary: CONTEXT,
	branchSummary: CONTEXT,
};
export const BLOCK_TYPES: Record<string, string> = { text: AGENT_MESSAGE, thinking: AGENT_REASONING, toolCall: TOOL_CALL };

export type Message = Record<string, any>;

/** The items a message list is: each assistant message split into one piece per content block, in order. */
export function pieces(messages: Message[]): Message[] {
	const out: Message[] = [];
	for (const m of messages) {
		const blocks = isObject(m) && m.role === "assistant" ? m.content : undefined;
		if (Array.isArray(blocks) && blocks.length > 1) {
			for (const b of blocks) out.push({ ...m, content: [b] });
		} else {
			out.push(m);
		}
	}
	return out;
}

function hasText(content: unknown): boolean {
	if (typeof content === "string") return content.trim().length > 0;
	if (!Array.isArray(content)) return false;
	return content.some((p) => isObject(p) && (p.type === "image" || (p.type === "text" && String(p.text ?? "").trim())));
}

/**
 * The name of an item's event type. An assistant piece is typed by its block (one with no block is
 * AGENT_MESSAGE; an unsplit message with a call is a TOOL_CALL); any other message by its role, except a
 * user message with nothing in it, which is CONTEXT. A block or role pi does not have, or an item with no
 * role, is CONTEXT too: carried as it is, and always one of the types the adaptor declares.
 */
export function classify(item: unknown): string {
	if (!isObject(item)) return CONTEXT;
	const role = item.role;
	if (role === "assistant") {
		const kinds = Array.isArray(item.content) ? item.content.filter(isObject).map((b) => b.type) : [];
		if (kinds.length === 0) return AGENT_MESSAGE;
		if (kinds.some((k) => BLOCK_TYPES[k] === TOOL_CALL)) return TOOL_CALL;
		return BLOCK_TYPES[kinds[0]] ?? CONTEXT;
	}
	if (role === "user" && !hasText(item.content)) return CONTEXT;
	if (typeof role === "string" && role in ROLE_TYPES) return ROLE_TYPES[role];
	return CONTEXT;
}

function partsText(content: unknown): string {
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";
	return content.filter(isObject).map((p) => (p.type === "text" ? String(p.text ?? "") : p.type === "image" ? "[image]" : ""))
		.filter((t) => t).join("\n");
}

/**
 * What the model reads of an item, without pi's bookkeeping; undefined when it has nothing to read (a thinking
 * piece) -- its payload as JSON then stands in. An assistant piece: its text block's words, or a tool call as
 * `name(arguments)`. A user or custom message: its words (an image as `[image]`). A tool result: its output. A
 * bash execution: `$ command` and its output. A summary: the summary.
 */
export function textOf(item: Message): string | undefined {
	if (!isObject(item)) return undefined;
	switch (item.role) {
		case "assistant": {
			const blocks = Array.isArray(item.content) ? item.content.filter(isObject) : [];
			const texts = blocks.map((b) => {
				if (b.type === "text") return String(b.text ?? "");
				if (b.type === "toolCall") return `${b.name}(${JSON.stringify(b.arguments ?? {})})`;
				return "";
			}).filter((t) => t);
			return texts.length || !blocks.some((b) => b.type === "thinking") ? texts.join("\n") : undefined;
		}
		case "user":
		case "custom":
		case "toolResult":
			return partsText(item.content);
		case "bashExecution":
			return `$ ${item.command ?? ""}\n${item.output ?? ""}`;
		case "compactionSummary":
		case "branchSummary":
			return String(item.summary ?? "");
	}
	return undefined;
}

/**
 * The event an item is. pi's messages have no ids: the id is a hash of the item's content, which carries
 * the time it was made, so it is the same on every re-send and on resume. (Tool call ids are not used: some
 * providers number calls per response, so they repeat.) A thinking piece costs 0 tokens: its
 * `thinkingSignature` is an opaque blob that says nothing of its cost.
 */
export function event(item: Message): Event {
	const out: Event = { type: classify(item), id: contentId(item), payload: item };
	const text = textOf(item);
	if (text !== undefined) out.text = text;
	const blocks = isObject(item) && item.role === "assistant" ? item.content : undefined;
	if (Array.isArray(blocks) && blocks.length === 1 && isObject(blocks[0]) && blocks[0].type === "thinking") out.tokens = 0;
	return out;
}

/** The events pi's messages are, in order. */
export function toEvents(messages: Message[]): Event[] {
	return pieces(messages).map(event);
}

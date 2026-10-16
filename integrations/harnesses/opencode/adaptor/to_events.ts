/**
 * opencode's messages as the context manager's events -- the policy-specific
 * half of the opencode harness, with to_messages.ts (the way back).
 *
 *   const events = toEvents(output.messages);   // what the plugin's routing sends in a `rewrite`
 *
 * Each opencode message is `{info, parts}` (session/message-v2.ts): parts of
 * type text, reasoning, file, tool (a call and its result together:
 * `{callID, tool, state: {status, input, output | error}}`), and opencode's own
 * structure (step-start, step-finish, snapshot, patch, agent, retry,
 * compaction, subtask).
 *
 * What becomes an event, as one of the event types the policies expect (the
 * standard five, and AGENT_REASONING: a reasoning part, the model's own
 * reasoning, kept and sent back as it was but never read or counted):
 *   - a USER message is one event, the message as it is, under its message id
 *     (opencode appends reminder parts to the last one on every step, with a new
 *     part id each time and without saving them, so part ids would store a new
 *     copy on every call);
 *   - an ASSISTANT message is an event per text, reasoning and file part, and
 *     two per tool part -- its call (`tool_call`: the part without its result)
 *     and its result (`tool_output`: the whole part). Its other parts are
 *     opencode's structure, no policy has a role for them, and they are not
 *     sent; to_messages.ts puts them back.
 * Each event carries its text (textOf): what the model reads of it -- the
 * message's words, a tool call as its name and input, a tool's output --
 * without opencode's ids, times, tokens and metadata.
 */

import { contentId, type Event, isObject } from "../../../tools/ag_connection/protocol.ts";

// The event types the policies expect: the standard five, and the model's own reasoning.
export const USER_MESSAGE = "user_message";
export const AGENT_MESSAGE = "agent_message";
export const TOOL_CALL = "tool_call";
export const TOOL_OUTPUT = "tool_output";
export const CONTEXT = "context";
export const AGENT_REASONING = "agent_reasoning";

export type Message = { info: Record<string, any>; parts: Record<string, any>[] };
export type Item = Record<string, any>;

/** An assistant part's type -> its event type; a tool part is two events. A type not listed is structure. */
export const PART_TYPES: Record<string, string | null> = { text: AGENT_MESSAGE, reasoning: AGENT_REASONING, file: AGENT_MESSAGE, tool: null };
export const CALL = "call";
export const OUTPUT = "output";

function callView(part: Item): Item {
	const state = isObject(part.state) ? part.state : {};
	const kept: Item = {};
	for (const [k, v] of Object.entries(state)) {
		if (!["output", "error", "attachments", "title", "metadata"].includes(k)) kept[k] = v;
	}
	return { ...part, state: kept };
}

/** The items a message list is: a user message as it is; an assistant message's parts, a tool part as two. */
export function pieces(messages: Message[]): Item[] {
	const out: Item[] = [];
	for (const m of messages) {
		const info = isObject(m) ? m.info : undefined;
		if (!isObject(info) || info.role !== "assistant") {
			out.push(m);
			continue;
		}
		for (const part of m.parts ?? []) {
			const kind = isObject(part) ? part.type : undefined;
			if (kind === "tool") {
				out.push({ info, part: callView(part), piece: CALL });
				out.push({ info, part, piece: OUTPUT });
			} else if (typeof kind === "string" && kind in PART_TYPES) {
				out.push({ info, part });
			}
		}
	}
	return out;
}

export function messageId(item: unknown): string | undefined {
	const info = isObject(item) ? item.info : undefined;
	return isObject(info) && typeof info.id === "string" ? info.id : undefined;
}

function userSaysSomething(parts: unknown): boolean {
	if (!Array.isArray(parts)) return false;
	return parts.some((p) => isObject(p) && !p.synthetic && !p.ignored
		&& ((p.type === "text" && String(p.text ?? "").trim()) || p.type === "file"));
}

/**
 * The name of an item's event type. A user message that says something (a text or file part that is neither
 * synthetic nor ignored) is USER_MESSAGE; one made only of opencode's own parts is CONTEXT. An assistant piece
 * is typed by its part, a tool part's call and result as TOOL_CALL and TOOL_OUTPUT. Anything else is
 * CONTEXT: carried as it is, and always one of the types the adaptor declares.
 */
export function classify(item: unknown): string {
	if (!isObject(item)) return CONTEXT;
	const role = isObject(item.info) ? item.info.role : undefined;
	if ("part" in item) {
		const kind = isObject(item.part) ? item.part.type : undefined;
		if (kind === "tool") return item.piece === OUTPUT ? TOOL_OUTPUT : TOOL_CALL;
		return (typeof kind === "string" && PART_TYPES[kind]) || CONTEXT;
	}
	if (role === "user") return userSaysSomething(item.parts) ? USER_MESSAGE : CONTEXT;
	return CONTEXT;
}

/** opencode's own id: `msg:<message id>`, or `prt:<part id>` (`:call` / `:output` for a tool part's two). */
export function itemId(item: unknown): string {
	if (isObject(item)) {
		if (isObject(item.part) && typeof item.part.id === "string" && item.part.id) {
			return `prt:${item.part.id}${item.piece ? `:${item.piece}` : ""}`;
		}
		const id = messageId(item);
		if (id) return `msg:${id}`;
	}
	return contentId(item);
}

/**
 * What the model reads of an item, without opencode's bookkeeping; undefined when it has nothing to read (a
 * reasoning piece) -- its payload as JSON then stands in. A user message: its text parts' words (a file part as
 * `[file <name>]`), not the synthetic or ignored ones. An assistant text part: its words; a file part `[file]`. A
 * tool call: `tool(input)`; a tool's result: its output, or its error.
 */
export function textOf(item: Item): string | undefined {
	if (!isObject(item)) return undefined;
	if ("part" in item) {
		const part = isObject(item.part) ? item.part : {};
		if (part.type === "text") return String(part.text ?? "");
		if (part.type === "file") return `[file ${part.filename ?? part.url ?? ""}]`.replace(" ]", "]");
		if (part.type === "tool") {
			const state = isObject(part.state) ? part.state : {};
			if (item.piece === OUTPUT) {
				const out = state.output ?? state.error ?? "";
				return typeof out === "string" ? out : JSON.stringify(out);
			}
			return `${part.tool}(${JSON.stringify(state.input ?? {})})`;
		}
		return undefined;
	}
	const parts = Array.isArray(item.parts) ? item.parts.filter((p: unknown) => isObject(p) && !p.synthetic && !p.ignored) : [];
	return parts.map((p: Item) => (p.type === "text" ? String(p.text ?? "") : p.type === "file" ? `[file ${p.filename ?? ""}]` : ""))
		.filter((t: string) => t).join("\n");
}

/**
 * The events opencode's messages are, in order. A reasoning piece costs 0 tokens: it is sent back as it
 * was, and what it holds (a provider's encrypted reasoning, in its metadata) says nothing of its cost.
 */
export function toEvents(messages: Message[]): Event[] {
	return pieces(messages).map((item) => {
		const type = classify(item);
		const event: Event = { type, id: itemId(item), payload: item };
		const text = textOf(item);
		if (text !== undefined) event.text = text;
		if (type === AGENT_REASONING) event.tokens = 0;
		return event;
	});
}

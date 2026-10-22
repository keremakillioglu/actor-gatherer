/**
 * One model call, for a harness whose plugin runs in Node or Bun:
 * the harness's messages through its adaptor and the context manager's
 * server, and back. Routing only -- it never looks inside a message: turning
 * messages into events and the context back into messages is the harness's
 * adaptor's (adaptor.ts); where the call belongs (gatherer, the properties of its
 * events -- e.g. { [CHANNEL]: session } -- working directory) is its plugin's.
 *
 *   const routed = await call_ag(server, { gatherer, properties: { [CHANNEL]: id }, cwd }, messages, adaptor);
 *   routed.messages ?? messages      // null: send the harness's own
 *   routed.readId                    // the read; its count goes with the next call:
 *   await call_ag(server, where, next, adaptor, { read_id: routed.readId, tokens });
 *
 * It holds the adaptor to what it declares: an event of a type not in its
 * `outputs`, or a property not in its `properties`, sends nothing (null), and
 * a context entry not in its `accepts` is noted. The working directory, when
 * given, goes on the events and the read as the property CWD too. It never
 * throws: an adaptor that fails, a server that errors or does not answer, a
 * context that is not a list -- each gives null messages and a note.
 * call_ag.py is the same in Python.
 */

import type { Answer } from "../ag_connection/ag_client.ts";
import type { ContextEntry, Event } from "../ag_connection/protocol.ts";
import { type Adaptor, CWD, declarations } from "./adaptor.ts";

export type Where = { gatherer: string; properties: Record<string, string | number | null>; cwd?: string | null };
export type Requester = { request(op: string, body?: Record<string, unknown>): Promise<Answer> };
/** The provider's count of an earlier call's context: the read it came from, and the call's input tokens. */
export type Measured = { read_id: number; tokens: number };
/** `readId` is set only when the read's context is what goes to the model. */
export type Routed<M> = { messages: M[] | null; note: string; readId?: number };

/**
 * One model call: the adaptor's `toEvents`, a `rewrite` to the server, its `toMessages`; null messages if anything
 * fails. `readId` names the read the context came from, for the call's own count to be reported against later;
 * `measured` is an earlier call's count, sent with this one; `limit` the harness's own limit for this call (where
 * it compacts, or its model's window ends), in its provider's tokens.
 */
export async function call_ag<M>(server: Requester, where: Where, messages: M[], adaptor: Adaptor<M>,
	measured?: Measured | null, limit?: number | null): Promise<Routed<M>> {
	const declared = declarations(adaptor);
	if (where.cwd) where = { ...where, properties: { ...where.properties, [CWD]: where.cwd } };   // where the agent works
	const unset = Object.keys(where.properties).filter((p) => !declared.properties.includes(p)).sort();
	if (unset.length) {
		return { messages: null, note: `adaptor ${declared.name} does not declare the properties ${unset.join(", ")}` };
	}
	let events: Event[];
	try {
		events = adaptor.toEvents(messages);
	} catch (err) {
		return { messages: null, note: `could not make events: ${(err as Error).message}` };
	}
	const undeclared = [...new Set(events.map((e) => String(e.type)))].filter((t) => !declared.outputs.includes(t)).sort();
	if (undeclared.length) {
		return { messages: null, note: `adaptor ${declared.name} made events of types it does not declare (${undeclared.join(", ")})` };
	}
	const body: Record<string, unknown> = { ...where, events };
	if (measured) body.measured = measured;
	if (limit && limit > 0) body.limit = Math.floor(limit);
	const answer = await server.request("rewrite", body);
	if (answer.error) return { messages: null, note: `server: ${answer.error}` };
	const readId = typeof answer.read_id === "number" ? answer.read_id : undefined;
	if (!Array.isArray(answer.context)) return { messages: null, note: String(answer.note ?? "no context") };
	const context = answer.context as ContextEntry[];
	let note = String(answer.note ?? "");
	const unaccepted = [...new Set(context.map((e) => String(e?.type)))].filter((t) => !declared.accepts.includes(t)).sort();
	if (unaccepted.length) note += `; adaptor ${declared.name} does not accept ${unaccepted.join(", ")}`;
	try {
		const routed = adaptor.toMessages(context, messages);
		return readId === undefined ? { messages: routed, note } : { messages: routed, note, readId };
	} catch (err) {
		return { messages: null, note: `could not make messages: ${(err as Error).message}` };
	}
}

/**
 * What a harness's adaptor is: the policy-specific half of its hook, turning
 * the harness's messages into the context manager's events and the context
 * back into messages -- and saying which of each it handles. adaptor.py is
 * the same in Python.
 *
 *   export class MyAdaptor implements Adaptor<Message> {
 *     static readonly adaptorName = "my_harness";
 *     static readonly outputs = [USER_MESSAGE, AGENT_MESSAGE, TOOL_CALL, TOOL_OUTPUT, CONTEXT];
 *     static readonly accepts = [...MyAdaptor.outputs, AG];
 *     static readonly properties = [CHANNEL, CWD];
 *     ...
 *   }
 *
 * `outputs` are the event type names `toEvents` emits, and nothing else: ag
 * refuses to run a policy whose event types do not take them all, and
 * `call_ag` refuses an event of any other type. `accepts` are the context
 * entries `toMessages` can show -- event type names, and AG (the context
 * manager's own messages); `call_ag` notes any other it is given.
 * `properties` are the event properties its plugin sets, on every event and
 * read (e.g. CHANNEL): ag refuses to run a policy whose types for `outputs` do
 * not declare them all, or require one not among them, and `call_ag` refuses
 * to send any other. The declarations are static, so ag can read them without
 * making an adaptor.
 */

import type { ContextEntry, Event } from "../ag_connection/protocol.ts";

export const AG = "ag";
/** The property the plugins set: which of the harness's threads an event or a read belongs to (adaptor.py's CHANNEL). */
export const CHANNEL = "channel";
/** The property call_ag sets from the request's working directory (adaptor.py's CWD). */
export const CWD = "cwd";

export interface Adaptor<M> {
	toEvents(messages: M[]): Event[];
	toMessages(context: ContextEntry[], messages: M[]): M[];
}

/** An adaptor's class: its declarations, and a way to make one. */
export interface AdaptorClass<M> {
	readonly adaptorName: string;
	readonly outputs: readonly string[];
	readonly accepts: readonly string[];
	readonly properties?: readonly string[];
	new (): Adaptor<M>;
}

/** The declarations of `adaptor`'s class. */
export function declarations(adaptor: Adaptor<unknown>): { name: string; outputs: string[]; accepts: string[]; properties: string[] } {
	const cls = adaptor.constructor as unknown as AdaptorClass<unknown>;
	return {
		name: cls.adaptorName,
		outputs: [...(cls.outputs ?? [])],
		accepts: [...(cls.accepts ?? [])],
		properties: [...(cls.properties ?? [])],
	};
}

/**
 * An adaptor from its class's "path/to/adaptor.ts:ExportName" (the path absolute,
 * or relative to the working directory) -- how ag names one (AG_ADAPTOR).
 */
export async function loadAdaptor<M>(spec: string): Promise<Adaptor<M>> {
	const at = spec.lastIndexOf(":");
	if (at <= 0) throw new Error(`not path:Export: ${spec}`);
	const { pathToFileURL } = await import("node:url");
	const { resolve } = await import("node:path");
	const module = await import(pathToFileURL(resolve(spec.slice(0, at))).href);
	const cls = module[spec.slice(at + 1)] as AdaptorClass<M> | undefined;
	if (typeof cls !== "function" || !Array.isArray(cls.outputs) || !Array.isArray(cls.accepts)) {
		throw new Error(`${spec} is not an adaptor class (static adaptorName, outputs, accepts)`);
	}
	return new cls();
}

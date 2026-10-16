/**
 * The protocol's shapes (ag/ag_harness/server/__init__.py's), for the
 * harness side written in TypeScript: what routing sends the server, and
 * what it gets back.
 *
 *   an event   {type, id, payload, tokens?}   type: a name the harness's to_events chose
 *   the context, in order: events as they were sent, and the context manager's
 *   own messages {type: "ag", name, text}, which each harness's to_messages shows its own way
 *
 * Which type names there are is policy-specific, and lives in each harness's
 * to_events; nothing here names one.
 */

import { createHash } from "node:crypto";

export const AG = "ag";

/** An event: `text` is its readable text (words, a call's name and arguments, an output), what the policies show and count. */
export type Event = { type: string; id: string | null; payload: unknown; tokens?: number; text?: string };
export type AgMessage = { type: "ag"; name: string | null; text: string };
export type ContextEntry = { type: string; id?: string | null; payload?: unknown; name?: string | null; text?: string };

export function isAg(entry: unknown): entry is AgMessage {
	return !!entry && typeof entry === "object" && (entry as ContextEntry).type === AG
		&& typeof (entry as ContextEntry).text === "string";
}

/** JSON with every object's keys sorted: the same text for the same value, however it was built. */
export function stableStringify(value: unknown): string {
	if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "null";
	if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
	const obj = value as Record<string, unknown>;
	const keys = Object.keys(obj).filter((k) => obj[k] !== undefined).sort();
	return `{${keys.map((k) => `${JSON.stringify(k)}:${stableStringify(obj[k])}`).join(",")}}`;
}

/** A stable id from an item's content: `sha256:<hash of its JSON, keys sorted>`. */
export function contentId(item: unknown): string {
	return `sha256:${createHash("sha256").update(stableStringify(item), "utf8").digest("hex")}`;
}

export function isObject(value: unknown): value is Record<string, any> {
	return !!value && typeof value === "object" && !Array.isArray(value);
}

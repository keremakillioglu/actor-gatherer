/**
 * The context manager as opencode's hook: given the messages opencode is about
 * to send, the messages the model gets instead. setup/setup.ts registers it as
 * opencode's `experimental.chat.messages.transform`.
 *
 *   const ag = new OpencodeContextManager({ named });
 *   const messages = await ag.transform(output.messages, directory);   // null: send opencode's own
 *
 * The gatherer is opencode's session id -- on every message, since opencode's
 * hook is given no other input -- and so is the channel; a `named` gatherer
 * (setup/setup.ts takes it from the plugin's `gatherer` option or AG_GATHERER)
 * is the gatherer instead, each opencode session a channel in it.
 *
 * One model call goes through routing (ag/integrations/tools/ag_orchestrator/call_ag.ts) with
 * opencode's adaptor (adaptor/adaptor.ts, or the one given), to the context
 * manager's server, one per opencode process (ag/integrations/tools/ag_connection/ag_client.ts),
 * configured by the context manager's home (~/.ag, or AG_HOME). Its stderr goes
 * to <home>/logs/opencode_server.log.
 */

import { AgClient } from "../../../tools/ag_connection/ag_client.ts";
import { type Preamble, type Requester, answered_ag, call_ag, called } from "../../../tools/ag_orchestrator/call_ag.ts";
import type { Message } from "../adaptor/to_events.ts";
import { type Adaptor, CHANNEL } from "../../../tools/ag_orchestrator/adaptor.ts";
import { Measurements, n } from "../../../tools/ag_orchestrator/measured.ts";
import { OpencodeAdaptor } from "../adaptor/adaptor.ts";

/** opencode's own limit for a call with this model (its `limit`): the window less the output it reserves; null if unknown. */
export function opencodeLimit(model: any): number | null {
	const context = n(model?.limit?.context), output = n(model?.limit?.output);
	if (!context) return null;
	return output > 0 && output < context ? context - output : context;
}

/** An opencode assistant message's input tokens: its `info.tokens`, the cache's included. */
export function opencodeInputTokens(m: Message): number | null {
	const t = m?.info?.tokens;
	if (!t || typeof t !== "object") return null;
	return n(t.input) + n(t.cache?.read) + n(t.cache?.write) || null;
}

type Client = Requester & { stop(): void };

export class OpencodeContextManager {
	readonly server: Client;
	readonly named?: string;

	readonly adaptor: Adaptor<Message>;
	/** Each call's count, from the tokens on opencode's next assistant message, sent with the call after. */
	readonly measurements = new Measurements<Message>((m) => m?.info?.role === "assistant", opencodeInputTokens);
	/** Each session's own limit, from the model opencode last named for it (`chat.params`). */
	readonly limits = new Map<string, number>();
	/** What opencode sends besides the messages: each session's system prompt, every tool's definition. */
	readonly systems = new Map<string, string>();
	readonly tools = new Map<string, { description: string; parameters: unknown }>();
	/** The parts of each assistant message still being answered, by message id, as opencode's events report them. */
	readonly parts = new Map<string, Map<string, any>>();

	constructor(options: { named?: string; timeoutMs?: number; server?: Client; adaptor?: Adaptor<Message> } = {}) {
		this.named = options.named || undefined;
		this.server = options.server ?? new AgClient("opencode", options.timeoutMs);
		this.adaptor = options.adaptor ?? new OpencodeAdaptor();
	}

	/** Where these messages belong: the gatherer (their session's, or the named one), and the channel (their session's id); null if none says. */
	where(messages: Message[]): { gatherer: string; properties: { [CHANNEL]: string } } | null {
		const id = messages.findLast((m) => m.info?.sessionID)?.info.sessionID;
		return id ? { gatherer: this.named || id, properties: { [CHANNEL]: id } } : null;
	}

	/** The messages the model gets for this call, or null to send opencode's own. */
	async transform(messages: Message[], directory?: string): Promise<Message[] | null> {
		const where = this.where(messages);
		if (!where) return null;
		const channel = where.properties[CHANNEL];
		const routed = await call_ag(this.server, { ...where, cwd: directory }, messages, this.adaptor,
			this.measurements.take(channel, messages), this.limits.get(channel), this.preamble(channel));
		this.measurements.keep(channel, routed.messages !== null ? routed.readId : undefined, messages);
		void called(this.server, where, "opencode", routed.readId);     // recorded beside the call, never waited for
		return routed.messages as Message[] | null;
	}

	/** Keep a session's own limit, from the model opencode names for its call (`chat.params`'s input). */
	params(sessionID: string | undefined, model: any): void {
		const limit = opencodeLimit(model);
		if (sessionID && limit) this.limits.set(sessionID, limit);
	}

	/** Keep a session's system prompt (`experimental.chat.system.transform`'s output). */
	system(sessionID: string | undefined, parts: string[]): void {
		if (sessionID && parts.length) this.systems.set(sessionID, parts.join("\n\n"));
	}

	/** Keep a tool's definition (`tool.definition`'s output). */
	tool(toolID: string, definition: { description: string; parameters: unknown }): void {
		if (toolID) this.tools.set(toolID, { description: definition.description, parameters: definition.parameters });
	}

	/** What this session's calls send besides the messages, as known so far. */
	preamble(sessionID: string): Preamble {
		const tools = [...this.tools].sort(([a], [b]) => a.localeCompare(b)).map(([name, d]) => ({ name, ...d }));
		return [{ name: "system", text: this.systems.get(sessionID) || "" }, { name: "tools", text: tools.length ? JSON.stringify(tools) : "" }];
	}

	/**
	 * One of opencode's events (the plugin's `event` hook). A part of an assistant message is kept (`message.part.updated`)
	 * until the message has completed (`message.updated`, with `time.completed`): then the message -- what the model
	 * answered -- is recorded as the answer's parts (`answered_ag`) until the session's next call stores it, so a reader
	 * of the gatherer sees the turn's last reply, which no call carries until the user writes again, and a tool call
	 * while it runs. An answer that failed is not recorded. A note, or null for none.
	 */
	async event(event: any, directory?: string): Promise<string | null> {
		const props = event?.properties;
		if (event?.type === "message.part.updated" && props?.part?.messageID && props.part.id) {
			const parts = this.parts.get(props.part.messageID) ?? new Map<string, any>();
			parts.set(props.part.id, props.part);
			this.parts.set(props.part.messageID, parts);
			return null;
		}
		if (event?.type === "message.part.removed" && props?.messageID) {
			this.parts.get(props.messageID)?.delete(props.partID);
			return null;
		}
		const info = event?.type === "message.updated" ? props?.info : undefined;
		if (!info || info.role !== "assistant" || !info.time?.completed) return null;
		const parts = [...(this.parts.get(info.id)?.values() ?? [])];
		this.parts.delete(info.id);
		if (info.error || !parts.length) return null;
		const where = this.where([{ info, parts } as Message]);
		if (!where) return null;
		return answered_ag(this.server, where, [{ info, parts } as Message], this.adaptor, info.id);
	}

	/** Stop the server: it finishes what it is answering and exits. */
	stop(): void {
		this.server.stop();
	}
}

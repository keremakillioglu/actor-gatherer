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
import { type Requester, call_ag } from "../../../tools/ag_orchestrator/call_ag.ts";
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
			this.measurements.take(channel, messages), this.limits.get(channel));
		this.measurements.keep(channel, routed.messages !== null ? routed.readId : undefined, messages);
		return routed.messages as Message[] | null;
	}

	/** Keep a session's own limit, from the model opencode names for its call (`chat.params`'s input). */
	params(sessionID: string | undefined, model: any): void {
		const limit = opencodeLimit(model);
		if (sessionID && limit) this.limits.set(sessionID, limit);
	}

	/** Stop the server: it finishes what it is answering and exits. */
	stop(): void {
		this.server.stop();
	}
}

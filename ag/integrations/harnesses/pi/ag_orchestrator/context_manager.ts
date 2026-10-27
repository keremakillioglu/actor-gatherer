/**
 * The context manager as pi's hook: given pi's messages before a model call,
 * the messages the model gets instead. setup/setup.ts registers it with pi's
 * extension API.
 *
 *   const ag = new PiContextManager();
 *   const where = ag.where(sessionId, named);           // the gatherer, and the channel as a property
 *   const messages = await ag.context(event.messages, where, cwd);   // null: send pi's own
 *
 * The gatherer is pi's session id, and so is the channel; a `named` gatherer
 * (setup/setup.ts takes it from --ag-gatherer or AG_GATHERER) is the gatherer
 * instead, each pi session a channel in it.
 *
 * One model call goes through routing (ag/integrations/tools/ag_orchestrator/call_ag.ts) with pi's
 * adaptor (adaptor/adaptor.ts, or the one given), to the context manager's server,
 * one per pi process (ag/integrations/tools/ag_connection/ag_client.ts), configured by the context
 * manager's home (~/.ag, or AG_HOME). Its stderr goes to <home>/logs/pi_server.log.
 */

import { type Answer, AgClient } from "../../../tools/ag_connection/ag_client.ts";
import { type Preamble, type Requester, answered_ag, call_ag, called } from "../../../tools/ag_orchestrator/call_ag.ts";
import { type Adaptor, CHANNEL } from "../../../tools/ag_orchestrator/adaptor.ts";
import { Measurements, n } from "../../../tools/ag_orchestrator/measured.ts";
import { PiAdaptor } from "../adaptor/adaptor.ts";

/** pi's default compaction reserve (its settings' compaction.reserveTokens): pi compacts past window - reserve. */
export const PI_RESERVE_TOKENS = 16384;

/** pi's own limit for a call with this model: where it would compact, its window less the reserve; null if unknown. */
export function piLimit(model: any): number | null {
	const window = n(model?.contextWindow);
	return window > PI_RESERVE_TOKENS ? window - PI_RESERVE_TOKENS : null;
}

/** A pi assistant message's input tokens: its `usage` (pi-ai's Usage), the cache's included. */
export function piInputTokens(m: any): number | null {
	const u = m?.usage;
	if (!u || typeof u !== "object") return null;
	return n(u.input) + n(u.cacheRead) + n(u.cacheWrite) || null;
}

export type Where = { gatherer: string; properties: { [CHANNEL]: string } };
type Client = Requester & { stop(): void };

export class PiContextManager {
	readonly server: Client;
	/** Whether the last model call's context came from the context manager. */
	answering = false;

	readonly adaptor: Adaptor<any>;
	/** Each call's count, from the usage on pi's next assistant message, sent with the call after. */
	readonly measurements = new Measurements<any>((m) => m?.role === "assistant", piInputTokens);

	constructor(options: { timeoutMs?: number; server?: Client; adaptor?: Adaptor<any> } = {}) {
		this.server = options.server ?? new AgClient("pi", options.timeoutMs);
		this.adaptor = options.adaptor ?? new PiAdaptor();
	}

	/** The gatherer -- a named base gatherer with a channel per pi session, or the pi session alone -- and the channel. */
	where(sessionId: string, named?: string): Where {
		return { gatherer: named || sessionId, properties: { [CHANNEL]: sessionId } };
	}

	/** Set the gatherer up ahead of a call; the answer says its policy, pollers and paths, or the error. */
	async open(where: Where): Promise<Answer> {
		const answer = await this.server.request("open", where, 60_000);
		if (answer.error) this.answering = false;
		return answer;
	}

	/**
	 * The messages the model gets for this call, or null to send pi's own; `model` is pi's current model,
	 * `preamble` what pi sends besides the messages (its system prompt, its tools).
	 */
	async context(messages: any[], where: Where, cwd?: string, model?: any, preamble?: Preamble): Promise<any[] | null> {
		const channel = where.properties[CHANNEL];
		const routed = await call_ag(this.server, { ...where, cwd }, messages, this.adaptor,
			this.measurements.take(channel, messages), piLimit(model), preamble);
		this.measurements.keep(channel, routed.messages !== null ? routed.readId : undefined, messages);
		this.answering = routed.messages !== null;
		void called(this.server, where, "pi", routed.readId);     // recorded beside the call, never waited for
		return routed.messages;
	}

	/**
	 * pi's message once it has ended (`message_end`): an assistant message -- what the model answered -- recorded
	 * as the answer's parts (`answered_ag`) until the session's next call stores it, so a reader of the gatherer sees
	 * the turn's last reply, which no call carries until the user writes again, and a tool call while it runs.
	 * pi's other messages, and an answer that failed or was stopped, are not kept. A note, or null for none.
	 */
	async answered(message: any, where: Where, cwd?: string): Promise<string | null> {
		if (message?.role !== "assistant" || message.stopReason === "error" || message.stopReason === "aborted") return null;
		return answered_ag(this.server, where, [message], this.adaptor, message.responseId);
	}

	/** Stop the server: it finishes what it is answering and exits. */
	stop(): void {
		this.server.stop();
	}
}

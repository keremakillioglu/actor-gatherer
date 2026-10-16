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
 * One model call goes through routing (integrations/tools/ag_orchestrator/call_ag.ts) with pi's
 * adaptor (adaptor/adaptor.ts, or the one given), to the context manager's server,
 * one per pi process (integrations/tools/ag_connection/ag_client.ts), configured by the context
 * manager's home (~/.ag, or AG_HOME). Its stderr goes to <home>/logs/pi_server.log.
 */

import { type Answer, AgClient } from "../../../tools/ag_connection/ag_client.ts";
import { type Requester, call_ag } from "../../../tools/ag_orchestrator/call_ag.ts";
import { type Adaptor, CHANNEL } from "../../../tools/ag_orchestrator/adaptor.ts";
import { PiAdaptor } from "../adaptor/adaptor.ts";

export type Where = { gatherer: string; properties: { [CHANNEL]: string } };
type Client = Requester & { stop(): void };

export class PiContextManager {
	readonly server: Client;
	/** Whether the last model call's context came from the context manager. */
	answering = false;

	readonly adaptor: Adaptor<any>;

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

	/** The messages the model gets for this call, or null to send pi's own. */
	async context(messages: any[], where: Where, cwd?: string): Promise<any[] | null> {
		const routed = await call_ag(this.server, { ...where, cwd }, messages, this.adaptor);
		this.answering = routed.messages !== null;
		return routed.messages;
	}

	/** Stop the server: it finishes what it is answering and exits. */
	stop(): void {
		this.server.stop();
	}
}

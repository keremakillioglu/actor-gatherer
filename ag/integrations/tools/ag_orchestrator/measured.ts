/**
 * The provider's count of each call's context, for a harness whose hook runs in
 * process (pi, opencode): no proxy sees the answer, but the harness keeps it --
 * its assistant message carries the call's usage -- so the next call's messages
 * say what the last one cost. A `Measurements` keeps, per channel, the read the
 * last call's context came from and how many assistant messages there were
 * then; at the next call, once a newer assistant message is there, its input
 * tokens are that read's count, sent with the call (`call_ag`'s `measured`).
 *
 *   const m = new Measurements<Message>(isAssistant, inputTokens);
 *   const routed = await call_ag(server, where, messages, adaptor, m.take(channel, messages));
 *   m.keep(channel, routed.readId, messages);
 */
import type { Measured } from "./call_ag.ts";

export class Measurements<M> {
	private readonly pending = new Map<string, { readId: number; assistants: number }>();
	readonly isAssistant: (m: M) => boolean;
	readonly inputTokens: (m: M) => number | null;

	/**
	 * isAssistant: whether a message is the model's answer to a call; inputTokens: that
	 * answer's input tokens, cached ones included, or null if it has none.
	 */
	constructor(isAssistant: (m: M) => boolean, inputTokens: (m: M) => number | null) {
		this.isAssistant = isAssistant;
		this.inputTokens = inputTokens;
	}

	/** The last call's count, if its read is known and its answer is now among `messages`; null otherwise. */
	take(channel: string, messages: M[]): Measured | null {
		const kept = this.pending.get(channel);
		if (!kept) return null;
		this.pending.delete(channel);
		const answers = messages.filter(this.isAssistant);
		for (let i = answers.length - 1; i >= kept.assistants; i--) {   // the newest answer since that counts (one
			const tokens = this.inputTokens(answers[i]);                 // still being written counts nothing yet)
			if (tokens && tokens > 0) return { read_id: kept.readId, tokens };
		}
		return null;                                                     // no answer to that call: nothing to count
	}

	/** Keep the read this call's context came from (none: the harness's own messages went). */
	keep(channel: string, readId: number | undefined, messages: M[]): void {
		if (readId === undefined) this.pending.delete(channel);
		else this.pending.set(channel, { readId, assistants: messages.filter(this.isAssistant).length });
	}
}

/** A number, or 0. */
export function n(v: unknown): number {
	return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

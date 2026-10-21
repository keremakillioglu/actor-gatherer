/**
 * Setting the context manager up in opencode: the plugin opencode loads. It
 * registers the context manager as opencode's hook (context_manager.ts) and
 * adds what opencode needs besides:
 *
 *   experimental.chat.messages.transform
 *                opencode runs it before every model call and builds the request from the
 *                array it hands it: the context manager's messages are spliced into that
 *                array, and nothing opencode stores changes
 *   config       opencode's own automatic compaction and pruning of old tool outputs are
 *                switched off: condensing the history is the context manager's job
 *                (AG_OPENCODE_COMPACTION=allow leaves them as configured)
 *
 * Load it from opencode's config (opencode.json):
 *
 *   "plugin": ["file:///path/to/clone/integrations/harnesses/opencode/setup/setup.ts"]
 *   "plugin": [["file:///…/setup.ts", { "gatherer": "demo" }]]      a named gatherer (or AG_GATHERER)
 *
 * Environment: AG_PYTHON, AG_HOME, AG_GATHERER, AG_OPENCODE_TIMEOUT_MS (how long
 * a call waits for the manager, default 300000), AG_OPENCODE_COMPACTION. What
 * each call came to goes to the gatherer's server.log.
 */

import { loadAdaptor } from "../../../tools/ag_orchestrator/adaptor.ts";
import { OpencodeContextManager } from "../ag_orchestrator/context_manager.ts";
import type { Message } from "../adaptor/to_events.ts";

const TIMEOUT_MS = Number(process.env.AG_OPENCODE_TIMEOUT_MS) || undefined;

async function server(input: { directory: string }, options?: Record<string, unknown>) {
	const named = (typeof options?.gatherer === "string" && options.gatherer) || process.env.AG_GATHERER;
	// The adaptor ag names (AG_ADAPTOR, "path.ts:Export"); opencode's own without it. One that fails to
	// load turns the context manager off rather than run another than ag checked.
	let adaptor;
	if (process.env.AG_ADAPTOR) {
		try {
			adaptor = await loadAdaptor<Message>(process.env.AG_ADAPTOR);
		} catch (err) {
			console.error(`context manager off: adaptor ${process.env.AG_ADAPTOR}: ${(err as Error).message}`);
			return {};
		}
	}
	const ag = new OpencodeContextManager({ named, timeoutMs: TIMEOUT_MS, adaptor });

	return {
		config: async (cfg: { compaction?: Record<string, unknown> }) => {
			if (process.env.AG_OPENCODE_COMPACTION === "allow") return;
			cfg.compaction = { ...cfg.compaction, auto: false, prune: false };
		},

		"chat.params": async (params: { sessionID?: string; model?: unknown }) => {
			ag.params(params.sessionID, params.model); // the model's limit, for this session's calls
		},

		"experimental.chat.messages.transform": async (_input: {}, output: { messages: Message[] }) => {
			const messages = await ag.transform(output.messages, input.directory);
			if (!messages) return; // opencode sends its own
			output.messages.splice(0, output.messages.length, ...messages);
		},
	};
}

export default { id: "context-manager", server };

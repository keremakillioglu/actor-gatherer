/**
 * Setting the context manager up in pi: the extension pi loads (package.json at
 * the root of this repo names it). It registers the context manager as pi's
 * hook (context_manager.ts) and adds what pi needs besides:
 *
 *   the `context` event     before every model call: the context manager's messages, or pi's own
 *   --ag-gatherer NAME          a named base gatherer (or AG_GATHERER), each pi session a channel in it
 *   session_start           set the gatherer up; the footer shows `ag: <policy>` (`ag: off` and a
 *                           warning if it cannot)
 *   session_before_compact  pi's own compaction is cancelled while the manager answers: condensing
 *                           the history is its job. When it does not answer, pi compacts as usual
 *   session_shutdown        the server stops when pi quits
 *   /ag                     this gatherer's policy, pollers, config and database
 *
 * Environment: AG_PYTHON (default python3), AG_HOME, AG_GATHERER,
 * AG_PI_TIMEOUT_MS (how long a call waits for the manager, default 300000),
 * AG_PI_COMPACTION=allow (let pi compact anyway). What each call came to goes to
 * the gatherer's server.log.
 */

import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import { loadAdaptor } from "../../../tools/ag_orchestrator/adaptor.ts";
import { PiContextManager } from "../ag_orchestrator/context_manager.ts";

const TIMEOUT_MS = Number(process.env.AG_PI_TIMEOUT_MS) || undefined;
const STATUS = "context-manager";

export default async function (pi: ExtensionAPI) {
	// The adaptor ag names (AG_ADAPTOR, "path.ts:Export"); pi's own without it. One that fails to load
	// turns the context manager off rather than run another than ag checked.
	let failed: string | undefined;
	const adaptor = process.env.AG_ADAPTOR
		? await loadAdaptor(process.env.AG_ADAPTOR).catch((err: Error) => { failed = `adaptor ${process.env.AG_ADAPTOR}: ${err.message}`; return undefined; })
		: undefined;
	const ag = new PiContextManager({ timeoutMs: TIMEOUT_MS, adaptor });

	pi.registerFlag("ag-gatherer", {
		description: "context manager: the base gatherer to file into (default: one per pi session)",
		type: "string",
	});

	const where = (ctx: ExtensionContext) =>
		ag.where(ctx.sessionManager.getSessionId(), (pi.getFlag("ag-gatherer") as string | undefined) || process.env.AG_GATHERER);

	const open = async (ctx: ExtensionContext) => {
		const answer = failed ? { error: failed } : await ag.open(where(ctx));
		if (answer.error) {
			ctx.ui.setStatus(STATUS, "ag: off");
			ctx.ui.notify(`context manager: ${answer.error}`, "warning");
		} else {
			ctx.ui.setStatus(STATUS, `ag: ${answer.policy}`);
		}
		return answer;
	};

	pi.on("session_start", async (_event, ctx) => {
		await open(ctx);
	});

	pi.on("context", async (event, ctx) => {
		if (failed) return undefined;
		const messages = await ag.context(event.messages as any[], where(ctx), ctx.cwd, ctx.model);
		if (!messages) {
			ctx.ui.setStatus(STATUS, "ag: unchanged");
			return undefined;
		}
		return { messages: messages as typeof event.messages };
	});

	pi.on("session_before_compact", async () => {
		if (ag.answering && process.env.AG_PI_COMPACTION !== "allow") return { cancel: true };
		return undefined;
	});

	pi.on("session_shutdown", async (event) => {
		if (event.reason === "quit") ag.stop();
	});

	pi.registerCommand("ag", {
		description: "context manager: this gatherer's policy, config and database",
		handler: async (_args, ctx) => {
			const answer = await open(ctx);
			if (answer.error) return;
			ctx.ui.notify(
				[
					`gatherer     ${answer.gatherer}` +
						(answer.properties?.channel !== answer.gatherer ? ` (channel ${answer.properties?.channel})` : ""),
					`policy   ${answer.policy}`,
					`pollers  ${(answer.pollers || []).join(", ") || "-"}`,
					`config   ${answer.config}`,
					`database ${answer.database}`,
				].join("\n"),
				"info",
			);
		},
	});
}

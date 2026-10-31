// The agent's document tools -- DocWriter's own (mcp-doc-tools.ts: edit_doc, read_doc, write_doc, comment_doc,
// reply_to_comment, list_threads), run here, on this page's documents. The actor calls them through the dashboard's
// MCP server (ag_dashboard/mcp.py); the dashboard passes each call to a page with this DocWriter open, on its stream
// (bus.ts: `call`), and the page answers it at `${base}/tools/result`. Upstream's server opened a document
// through Hocuspocus to change it; here that handle opens the page's own copy (yjs-doc.ts), and the change reaches
// the dashboard and every other page as any edit does.
import { z } from 'zod';
import { DOC_TOOLS } from '$lib/server/mcp-doc-tools';
import { getYDocForTab, whenYDocReadyForTab, waitForTabSync, saveTab } from './yjs-doc';
import { base } from './base';
import { noteTabs } from './state';
import type { Bus } from './bus';

(globalThis as any).__docwriterWsServer = {
	hocuspocus: {
		async openDirectConnection(tabId: string) {
			const doc = getYDocForTab(tabId);
			await whenYDocReadyForTab(tabId);
			return {
				transact: async (cb: (doc: unknown) => void | Promise<void>) => { await cb(doc); },
				disconnect: async () => { await waitForTabSync(tabId); await saveTab(tabId); }
			};
		}
	}
};

/** The tools as MCP lists them: name, description, JSON Schema of the input. */
export const TOOLS = (DOC_TOOLS as readonly any[]).map((t) => ({
	name: t.name,
	description: t.description,
	inputSchema: z.toJSONSchema(z.object(t.inputSchema))
}));

const json = { 'Content-Type': 'application/json' };

/** One call, run as upstream's handler runs it, the tabs known as the dashboard has them now. */
async function run(name: string, args: Record<string, unknown>) {
	const tool = (DOC_TOOLS as readonly any[]).find((t) => t.name === name);
	if (!tool) return { content: [{ type: 'text', text: `No tool ${name}.` }], isError: true };
	try {
		noteTabs(await (await fetch(`${base}/api/tabs`)).json());
		return await tool.handler(args);
	} catch (e) {
		return { content: [{ type: 'text', text: `${name} failed: ${(e as Error)?.message ?? e}` }], isError: true };
	}
}

/** This page takes the actor's tool calls, one at a time, in the order they come; and tells the dashboard what the
 * tools are, for the MCP server to list. Again whenever the stream comes back. */
export function serveTools(bus: Bus): void {
	let chain: Promise<void> = Promise.resolve();
	const list = () => void fetch(`${base}/tools/list`, { method: 'POST', headers: json, body: JSON.stringify({ tools: TOOLS }) });
	bus.on('open', list);
	if (bus.isOpen()) list();
	bus.on('call', (c) => {
		chain = chain.then(async () => {
			const result = await run(c.name, c.arguments ?? {});
			await fetch(`${base}/tools/result`, { method: 'POST', headers: json, body: JSON.stringify({ id: c.id, result }) })
				.catch((e) => console.error('DocWriter: a tool result not sent:', e));
		});
	});
}

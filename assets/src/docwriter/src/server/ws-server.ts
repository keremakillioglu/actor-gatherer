// DocWriter's server/ws-server.ts: the page writes a document to its file itself (yjs-doc.ts).
import { saveTab } from '../yjs-doc';

export function flushTabMarkdownNow(tabId: string): void {
	void saveTab(tabId);
}

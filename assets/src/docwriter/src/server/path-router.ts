// DocWriter's server/path-router.ts, its open tabs the page's (state.ts).
import { isAgentScratchPath } from './document-files';
import { tabs } from '../state';

export function isScratchPath(path: string): boolean {
	if (isAgentScratchPath(path)) return true;
	return path.includes('.docwriter/agent/scratch/') || path.endsWith('.docwriter/agent/scratch');
}

export function resolveTabFromPath(path: string): string | null {
	for (const id of [...tabs.order].sort((a, b) => b.length - a.length)) {
		if (path === id || path.endsWith('/' + id)) return id;
	}
	return null;
}

export function isOpenTab(tabId: string | null | undefined): boolean {
	return !!tabId && tabs.order.includes(tabId);
}

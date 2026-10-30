// DocWriter's server/documents-store.ts: a file opened as a tab, by the dashboard (/api/tabs), not made active.
import { ask } from './sync';
import { noteTabs } from '../state';

export function openDocument(tabId: string, opts?: { activate?: boolean }): void {
	noteTabs(ask('open', { id: tabId, activate: opts?.activate !== false }));
}

// What the page knows of its DocWriter, kept as the page's requests come and go (backend.ts): which DocWriter this
// is (`config`, from the dashboard), its open tabs, its rules. DocWriter's server code the page runs (its document
// tools: tools.ts) reads them here, synchronously, as upstream reads its database.
import { base } from './base';

export interface Config {
	key: string;            // this DocWriter's: its folder and its actor
	root: string;           // the folder: the workspace
	gatherer: string;
	channel: string;        // its actor's session (its channel in the gatherer)
	harness: string;
	name: string;           // its actor's name, as the list shows it
	wake: boolean;          // whether a pause in typing wakes the agent
	error?: string;
}

export const config: Config = { key: '', root: '', gatherer: '', channel: '', harness: 'claude', name: '', wake: false };
export const tabs: { order: string[]; active: string | null } = { order: [], active: null };
export const meta: { rules: Array<{ text: string; examples?: unknown[] }>; agentSettings: Record<string, unknown> } = {
	rules: [],
	agentSettings: {}
};

export async function loadConfig(): Promise<void> {
	const res = await fetch(`${base}/dw`);
	Object.assign(config, await res.json());
}

/** A request's answer that says what the tabs are now, kept. */
export function noteTabs(v: { order?: string[]; tabs?: string[]; active?: string | null } | null | undefined): void {
	if (!v) return;
	const order = v.tabs ?? v.order;
	if (Array.isArray(order)) tabs.order = order;
	if (v.active !== undefined) tabs.active = v.active;
}

/**
 * DocWriter's per-tab Y.Doc registry (upstream src/lib/yjs-doc.ts), its documents shared through the dashboard
 * instead of DocWriter's Hocuspocus server: each tab's Y.Doc is linked (`Link`) to the dashboard's copy of it
 * (ag_dashboard/docwriter.py's `Docs`) -- joined with a POST, the dashboard's updates coming in on the page's one
 * stream (bus.ts), this page's going out as POSTs -- and the dashboard holds the documents unread. What DocWriter's server did to a document's text, the
 * page does here, with DocWriter's own code:
 *   - seeds a new document from its file (`seed`, sent to one page only);
 *   - folds a change of the file on disk into it (`external`, sent to one page only: applyExternalText);
 *   - writes it to its file, as the committed view (`serializeYDoc`), a moment after this page changed it.
 * The same exports as upstream's, so the rest of DocWriter's page is unchanged.
 */
import * as Y from 'yjs';
import { COMMENTS_MAP_NAME, SYSTEM_ORIGIN, USER_ORIGIN, type CommentsMap, seedYDoc, serializeYDoc } from '$lib/shared/ydoc-codec';
import { applyExternalText } from '$lib/shared/proposals';
import { base } from './base';
import type { Bus } from './bus';

let bus: Bus;
/** The page's stream, which the documents' changes come on: set before any document is linked (main.ts). */
export function useBus(b: Bus): void {
	bus = b;
}

const REMOTE = 'remote';            // an update from the dashboard: not sent back
const SAVE_MS = 400;                // after this page's last change, how long until the file is written
const LOST_CONNECTION_GRACE_MS = 5_000;

const b64 = (bytes: Uint8Array): string => {
	let s = '';
	for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
	return btoa(s);
};
const bytes = (s: string): Uint8Array => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

type Handler = (arg?: any) => void;

/** One tab's Y.Doc linked to the dashboard's copy: the subset of HocuspocusProvider DocWriter's page uses
 * (`synced`, `hasUnsyncedChanges`, their events, `status`). */
class Link {
	synced = false;
	connected = false;
	private out: Uint8Array[] = [];
	private sending = 0;
	private gone = false;
	private offs: Array<() => void> = [];
	private handlers = new Map<string, Set<Handler>>();
	private saveTimer: ReturnType<typeof setTimeout> | null = null;
	private readonly conn = bus.conn;
	private readonly onUpdate = (u: Uint8Array, origin: unknown) => {
		if (origin === REMOTE) return;
		this.out.push(u);
		void this.flush();
		this.saveSoon();
	};

	constructor(readonly ydoc: Y.Doc, readonly tabId: string) {
		ydoc.on('update', this.onUpdate);
		this.offs.push(
			bus.on('doc', (v) => {
				if (v.tab !== this.tabId) return;
				if (v.type === 'update') Y.applyUpdate(this.ydoc, bytes(v.update), REMOTE);
				else if (v.type === 'external') this.fold(v.text);
			}),
			bus.on('open', () => void this.join()),          // again: the dashboard forgot it with the stream that went
			bus.on('down', () => this.setConnected(false))
		);
		if (bus.isOpen()) void this.join();
	}

	get hasUnsyncedChanges(): boolean {
		return this.out.length > 0 || this.sending > 0;
	}

	on(name: string, h: Handler): void {
		if (!this.handlers.has(name)) this.handlers.set(name, new Set());
		this.handlers.get(name)!.add(h);
	}
	off(name: string, h: Handler): void {
		this.handlers.get(name)?.delete(h);
	}
	private emit(name: string, arg?: any): void {
		for (const h of [...(this.handlers.get(name) ?? [])]) h(arg);
	}

	/** The document joined at the dashboard: its copy there taken in, and what this page has that it lacks sent. */
	private async join(): Promise<void> {
		let v: any;
		try {
			const res = await fetch(`${base}/doc/join`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ tab: this.tabId, conn: this.conn }) });
			v = await res.json();
			if (!res.ok) throw new Error(v?.error ?? `HTTP ${res.status}`);
		} catch (e) {
			console.error(`DocWriter: ${this.tabId} not opened:`, e);
			if (!this.gone) setTimeout(() => { if (!this.gone && bus.isOpen()) void this.join(); }, 2000);
			return;
		}
		if (this.gone) return;
		Y.applyUpdate(this.ydoc, bytes(v.update), REMOTE);
		const mine = Y.encodeStateAsUpdate(this.ydoc, bytes(v.sv));   // what this page has that the dashboard lacks
		if (mine.length > 2) { this.out.push(mine); void this.flush(); }
		if (typeof v.seed === 'string') this.ydoc.transact(() => seedYDoc(this.ydoc, v.seed), SYSTEM_ORIGIN);
		if (typeof v.external === 'string') this.fold(v.external);
		this.setConnected(true);
		if (!this.synced) { this.synced = true; this.emit('synced'); }
	}

	/** The file changed on disk, by an actor or anyone: its text folded into the document, outside any proposal. */
	private fold(text: string): void {
		this.ydoc.transact(() => applyExternalText(this.ydoc, text), SYSTEM_ORIGIN);
	}

	private setConnected(on: boolean): void {
		if (this.connected === on) return;
		this.connected = on;
		this.emit('status', { status: on ? 'connected' : 'disconnected' });
	}

	private async flush(): Promise<void> {
		if (this.sending || !this.out.length) return;
		const update = Y.mergeUpdates(this.out.splice(0));
		this.sending++;
		this.emit('unsyncedChanges');
		try {
			const res = await fetch(`${base}/doc/update`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ tab: this.tabId, conn: this.conn, update: b64(update) }) });
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
		} catch (e) {
			this.out.unshift(update);                              // sent again with the next
			setTimeout(() => void this.flush(), 1000);
		} finally {
			this.sending--;
			this.emit('unsyncedChanges');
			if (this.out.length) void this.flush();
		}
	}

	private saveSoon(): void {
		if (this.saveTimer) clearTimeout(this.saveTimer);
		this.saveTimer = setTimeout(() => void this.save(), SAVE_MS);
	}

	/** The document written to its file as the author has it: no proposed insertions, proposed deletions kept. */
	async save(): Promise<void> {
		if (this.saveTimer) { clearTimeout(this.saveTimer); this.saveTimer = null; }
		if (!this.synced) return;
		try {
			await fetch(`${base}/doc/save`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ tab: this.tabId, conn: this.conn, text: serializeYDoc(this.ydoc) }) });
		} catch (e) {
			console.error(`DocWriter: saving ${this.tabId}:`, e);
		}
	}

	destroy(): void {
		if (this.saveTimer) void this.save();
		this.gone = true;
		this.ydoc.off('update', this.onUpdate);
		for (const off of this.offs.splice(0)) off();
		this.handlers.clear();
		void fetch(`${base}/doc/leave`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ tab: this.tabId, conn: this.conn }) }).catch(() => {});
	}
}

interface TabDoc {
	ydoc: Y.Doc;
	link: Link | null;
	readyPromise: Promise<void>;
}

const registry = new Map<string, TabDoc>();

function waitForSynced(link: Link): Promise<void> {
	return new Promise((resolve) => {
		if (link.synced) return resolve();
		const done = () => { link.off('synced', done); resolve(); };
		link.on('synced', done);
	});
}

function waitForIdle(link: Link, timeoutMs = 2_000): Promise<boolean> {
	return new Promise((resolve) => {
		const idle = () => link.synced && !link.hasUnsyncedChanges;
		if (idle()) return resolve(true);
		let finished = false;
		const finish = (ok: boolean) => {
			if (finished) return;
			finished = true;
			link.off('unsyncedChanges', check);
			link.off('synced', check);
			clearTimeout(timer);
			resolve(ok);
		};
		const check = () => { if (idle()) finish(true); };
		const timer = setTimeout(() => finish(idle()), timeoutMs);
		link.on('unsyncedChanges', check);
		link.on('synced', check);
	});
}

export const SERVER_INSTANCE_STORAGE_KEY = 'docwriter.serverInstanceId';

type SyncConnectionListener = (event: { tabId: string; connected: boolean }) => void;
const syncConnectionListeners = new Set<SyncConnectionListener>();
const lostTimers = new Map<string, ReturnType<typeof setTimeout>>();
const reportedLost = new Set<string>();

/** Be told when a tab's link has been down for longer than a normal reconnect, and when it comes back. */
export function onSyncConnectionChange(listener: SyncConnectionListener): () => void {
	syncConnectionListeners.add(listener);
	return () => syncConnectionListeners.delete(listener);
}

function trackConnection(link: Link, tabId: string): void {
	link.on('status', ({ status }: { status: string }) => {
		if (status === 'connected') {
			const timer = lostTimers.get(tabId);
			if (timer) clearTimeout(timer);
			lostTimers.delete(tabId);
			if (reportedLost.delete(tabId)) for (const l of syncConnectionListeners) l({ tabId, connected: true });
			return;
		}
		if (lostTimers.has(tabId) || reportedLost.has(tabId)) return;
		lostTimers.set(tabId, setTimeout(() => {
			lostTimers.delete(tabId);
			if (link.connected) return;
			reportedLost.add(tabId);
			for (const l of syncConnectionListeners) l({ tabId, connected: false });
		}, LOST_CONNECTION_GRACE_MS));
	});
}

function linked(ydoc: Y.Doc, tabId: string): TabDoc {
	const link = new Link(ydoc, tabId);
	trackConnection(link, tabId);
	return { ydoc, link, readyPromise: waitForSynced(link) };
}

/** Get or create the local Y.Doc, linked to the dashboard's, for `tabId`. */
export function getYDocForTab(tabId: string): Y.Doc {
	const existing = registry.get(tabId);
	if (existing) return existing.ydoc;
	const entry = linked(new Y.Doc(), tabId);
	registry.set(tabId, entry);
	return entry.ydoc;
}

/** The tab's document written to its file now, not a moment later (an accepted edit). */
export async function saveTab(tabId: string): Promise<void> {
	await registry.get(tabId)?.link?.save();
}

export function getCommentsMapForTab(tabId: string): CommentsMap {
	return getYDocForTab(tabId).getMap<unknown>(COMMENTS_MAP_NAME);
}

/** The tab's document, as the dashboard had it first. */
export function whenYDocReadyForTab(tabId: string): Promise<void> {
	getYDocForTab(tabId);
	return registry.get(tabId)!.readyPromise;
}

/** True once the dashboard has all of this page's changes to the tab. */
export function waitForTabSync(tabId: string, timeoutMs = 2_000): Promise<boolean> {
	const doc = registry.get(tabId);
	if (!doc) return Promise.resolve(false);
	if (!doc.link) return Promise.resolve(true);
	return waitForIdle(doc.link, timeoutMs);
}

/** Upstream disconnects a tab while its server accepts or rejects an edit; here the page does that itself, on its
 * own document, so there is nothing to hold off. */
export function pauseTabSync(_tabId: string): () => void {
	return () => {};
}

export async function destroyTab(tabId: string): Promise<void> {
	const doc = registry.get(tabId);
	if (!doc) return;
	doc.link?.destroy();
	doc.ydoc.destroy();
	registry.delete(tabId);
}

/** A tab's document moved to its new id after its file was renamed: the dashboard moved its copy (`/api/tabs`). */
export async function renameTab(oldId: string, newId: string): Promise<void> {
	if (oldId === newId) return;
	const existing = registry.get(oldId);
	if (!existing) return;
	const state = Y.encodeStateAsUpdate(existing.ydoc);
	existing.link?.destroy();
	existing.ydoc.destroy();
	registry.delete(oldId);
	const ydoc = new Y.Doc();
	Y.applyUpdate(ydoc, state, REMOTE);
	registry.set(newId, linked(ydoc, newId));
}

export function applyUpdateToTab(tabId: string, updateBase64: string): void {
	const doc = registry.get(tabId);
	if (!doc) return;
	Y.applyUpdate(doc.ydoc, bytes(updateBase64), USER_ORIGIN);
}

export async function resetAllYDocs(): Promise<void> {
	for (const [id] of Array.from(registry)) await destroyTab(id);
}

/** Upstream starts over when its server restarted; the dashboard keeps its documents across restarts. */
export async function reconcileServerInstance(currentId: string): Promise<void> {
	try { sessionStorage.setItem(SERVER_INSTANCE_STORAGE_KEY, currentId); } catch { /* this page only */ }
}

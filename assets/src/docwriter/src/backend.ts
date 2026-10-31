// What DocWriter's page asks its server for, answered: by the dashboard, under this DocWriter's base (most of it:
// files, tabs, settings, hooks, previews -- ag_dashboard/docwriter.py), or here, by the page itself, where
// upstream's server did its work on a document (now this page's own copy) or ran the agent:
//   POST /api/document?tab=   accept, reject, dismiss a proposal's thread (upstream's ws-server.ts, resolveTabThread
//                             and the rest), told to the gatherer as an event of the dashboard's
//   POST /api/comments        a new thread on a passage, or a reply on one (upstream's routes/api/comments)
//   POST /api/render          the agent's turn: render.ts
//   POST /api/ask-user-reply  an answer to what the actor asks: render.ts
// Every answer that says what the tabs and rules are now is kept (state.ts), for the tools to read.
import * as Y from 'yjs';
import {
	getCommentsMap, getThread, putThread, appendThreadMessage, setThreadResolved, decodeRelPosition, USER_ORIGIN
} from '$lib/shared/ydoc-codec';
import {
	committedText, proposedText, proposalThreadIds, resolveThreadMarks, setCommentMarkByAbsolutePositions,
	setCommentMarkByViewOffsets, summarizeThreadMarks, type CommentMarkResult, type ThreadOutcome
} from '$lib/shared/proposals';
import type { CommentThread } from '$lib/types';
import { getYDocForTab, whenYDocReadyForTab, saveTab } from './yjs-doc';
import { render, answerQuestion } from './render';
import { base } from './base';
import { meta, noteTabs } from './state';
import { dashboardTheme } from './actor';

const realFetch = window.fetch.bind(window);
const json = { 'Content-Type': 'application/json' };
const answer = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: json });
const fail = (status: number, message: string) => new Response(message, { status });

async function docFor(tabId: string): Promise<Y.Doc> {
	const doc = getYDocForTab(tabId);
	await whenYDocReadyForTab(tabId);
	return doc;
}

/** What the reader decided, kept in the gatherer as the dashboard's own event in the actor's channel. */
function record(type: string, payload: Record<string, unknown>): void {
	void realFetch(`${base}/record`, { method: 'POST', headers: json, body: JSON.stringify({ type, payload }) })
		.catch((e) => console.error('DocWriter: not recorded:', e));
}

/** The proposals of threads `ids`, as they stand before they are settled: what the event says was decided. */
function proposals(doc: Y.Doc, ids: string[]): Array<{ thread: string; changes: Array<{ before: string; after: string }> }> {
	const by = new Map(summarizeThreadMarks(doc).map((s) => [s.threadId, s]));
	return ids.map((id) => ({ thread: id, changes: (by.get(id)?.changes ?? []).map(({ before, after }) => ({ before, after })) }));
}

async function threadAction(tabId: string, body: any): Promise<Response> {
	const doc = await docFor(tabId);
	const map = getCommentsMap(doc);
	const settle = (ids: string[], outcome: ThreadOutcome) => {
		const decided = proposals(doc, ids);
		doc.transact(() => {
			for (const id of ids) {
				resolveThreadMarks(doc, id, outcome);
				setThreadResolved(map, id, true, outcome);
			}
		}, USER_ORIGIN);
		record('proposal_resolved', { file: tabId, outcome, proposals: decided });
		void realFetch(`${base}/kv`, { method: 'POST', headers: json,           // upstream's touchLastSeen
			body: JSON.stringify({ set: { [`last_seen:${tabId}`]: proposedText(doc) } }) });
		if (outcome === 'accepted') void saveTab(tabId);
	};
	if (body.action === 'resolve_thread') {
		if (!getThread(map, body.threadId)) return answer({ error: 'Thread not found' }, 404);
		const hadProposal = proposalThreadIds(doc).has(body.threadId);
		settle([body.threadId], body.outcome);
		return answer({ ok: true, hadProposal, yjsUpdate: null });
	}
	if (body.action === 'resolve_all') {
		const ids = [...proposalThreadIds(doc)].filter((id) => { const t = getThread(map, id); return t && !t.resolved; });
		if (ids.length) settle(ids, body.outcome);
		return answer({ ok: true, count: ids.length, yjsUpdate: null });
	}
	if (body.action === 'set_thread_resolution') {
		if (!getThread(map, body.threadId)) return answer({ ok: false, yjsUpdate: null });
		if (body.resolved) settle([body.threadId], 'dismissed');
		else doc.transact(() => setThreadResolved(map, body.threadId, false), USER_ORIGIN);
		return answer({ ok: true, yjsUpdate: null });
	}
	return fail(400, `Unknown action ${body.action}`);
}

async function comments(body: any): Promise<Response> {
	const tabId = typeof body?.tabId === 'string' ? body.tabId : '';
	if (!tabId) return fail(400, 'Invalid tab id');
	const text = typeof body.message === 'string' ? body.message.trim() : '';
	if (!text) return fail(400, 'message is required');
	const doc = await docFor(tabId);
	const now = Date.now();
	if (body.mode === 'new-thread') {
		const anchorText = typeof body.anchorText === 'string' ? body.anchorText : '';
		if (!anchorText) return fail(400, 'anchorText is required for a new thread');
		const threadId = 'thread_' + crypto.randomUUID();
		const thread: CommentThread = { id: threadId, resolved: false, createdAt: now,
			messages: [{ id: 'msg_' + crypto.randomUUID(), author: 'user', text, timestamp: now }] };
		let marked: CommentMarkResult = { ok: false, reason: 'range' };
		doc.transact(() => {
			const rs = body.relStart ? decodeRelPosition(body.relStart) : null;
			const re = body.relEnd ? decodeRelPosition(body.relEnd) : null;
			const from = rs ? Y.createAbsolutePositionFromRelativePosition(rs, doc) : null;
			const to = re ? Y.createAbsolutePositionFromRelativePosition(re, doc) : null;
			if (from && to) marked = setCommentMarkByAbsolutePositions(doc, threadId, from, to);
			if (!marked.ok && marked.reason === 'range') {
				const idx = committedText(doc).indexOf(anchorText);
				if (idx >= 0) marked = setCommentMarkByViewOffsets(doc, threadId, { kind: 'committed' }, idx, idx + anchorText.length);
			}
			if (marked.ok) putThread(getCommentsMap(doc), thread);
		}, USER_ORIGIN);
		const m = marked as CommentMarkResult;
		if (!m.ok) {
			return m.reason === 'overlap'
				? answer({ error: 'The selected passage already has a thread', overlapThreadId: (m as any).otherThreadId }, 409)
				: fail(409, 'anchorText was not found in the document');
		}
		record('comment', { file: tabId, thread: threadId, passage: anchorText, text });
		return answer({ threadId });
	}
	if (body.mode === 'reply') {
		const map = getCommentsMap(doc);
		if (!body.threadId || !getThread(map, body.threadId)) return fail(404, 'Thread not found');
		doc.transact(() => {
			appendThreadMessage(map, body.threadId, { id: 'msg_' + crypto.randomUUID(), author: 'user', text, timestamp: now });
			setThreadResolved(map, body.threadId, false);
		}, USER_ORIGIN);
		record('reply', { file: tabId, thread: body.threadId, text });
		return answer({ ok: true });
	}
	return fail(400, 'Unknown comments mode');
}

async function bodyOf(init?: RequestInit): Promise<any> {
	try { return JSON.parse(typeof init?.body === 'string' ? init.body : '{}'); } catch { return {}; }
}

/** The page's fetch, its DocWriter routes answered as the module says. */
export function install(): void {
	window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
		const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, location.href);
		const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
		const route = url.origin === location.origin && url.pathname.startsWith(`${base}/api/`) ? url.pathname.slice(base.length + 5) : null;
		if (route === 'render' && method === 'POST') return render(await bodyOf(init), init?.signal);
		if (route === 'ask-user-reply' && method === 'POST') return answerQuestion(await bodyOf(init));
		if (route === 'comments' && method === 'POST') return comments(await bodyOf(init));
		if (route === 'document' && method === 'POST' && url.searchParams.get('tab')) {
			const body = await bodyOf(init);
			if (body.action && !String(body.action).startsWith('dev_')) return threadAction(url.searchParams.get('tab')!, body);
		}
		const res = await realFetch(input, init);
		if (route === 'session' && method === 'GET' && dashboardTheme() && res.ok) {   // its theme the dashboard's, at its start
			const v = await res.clone().json().catch(() => null);
			if (v) return answer({ ...v, theme: dashboardTheme() === 'dark' ? 'dark' : 'light' });
		}
		if (route === 'tabs' || route === 'document') {           // what the tabs and rules are now
			res.clone().json().then((v) => {
				if (route === 'tabs') noteTabs(v);
				else if (v?.meta) Object.assign(meta, v.meta.rules ? { rules: v.meta.rules } : {},
					v.meta.agentSettings ? { agentSettings: v.meta.agentSettings } : {});
			}).catch(() => {});
		}
		if (route === 'document' && method === 'PUT') {
			const body = await bodyOf(init);
			if (body?.meta?.rules) meta.rules = body.meta.rules;
			if (body?.meta?.agentSettings) {
				meta.agentSettings = { ...meta.agentSettings, ...body.meta.agentSettings };
				record('doc_settings', { ...body.meta.agentSettings });
			}
		}
		return res;
	};
}

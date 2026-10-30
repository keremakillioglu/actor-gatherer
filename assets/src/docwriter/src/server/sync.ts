// What DocWriter's server code did on its own disk, asked of the dashboard -- synchronously, as that code expects
// (a synchronous request: the page waits the few milliseconds the dashboard takes). Only under this DocWriter's
// folder; the dashboard checks.
import { base } from '../base';

export function ask(op: string, args: Record<string, unknown>): any {
	const xhr = new XMLHttpRequest();
	xhr.open('POST', `${base}/fs`, false);
	xhr.setRequestHeader('Content-Type', 'application/json');
	xhr.send(JSON.stringify({ op, ...args }));
	let v: any;
	try { v = JSON.parse(xhr.responseText); } catch { v = { error: `HTTP ${xhr.status}` }; }
	if (v && v.error) {
		const err = new Error(v.error) as Error & { code?: string };
		if (v.code) err.code = v.code;
		throw err;
	}
	return v;
}

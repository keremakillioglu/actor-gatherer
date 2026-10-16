// The context manager as pi's and opencode's hook (ag/integrations/harnesses/<harness>/ag_orchestrator/context_manager.ts), with a stand-in
// server: which gatherer and channel a call belongs to, what reaches the server, what comes back, and that
// whatever fails leaves the harness's own messages. How the harness calls it (setup.ts) is not involved.
// Run: npm test.

import assert from "node:assert/strict";
import { test } from "node:test";
import { OpencodeContextManager } from "../../ag/integrations/harnesses/opencode/ag_orchestrator/context_manager.ts";
import { PiContextManager } from "../../ag/integrations/harnesses/pi/ag_orchestrator/context_manager.ts";

const server = (answer: (op: string, body: any) => any) => {
	const requests: { op: string; body: any }[] = [];
	return {
		requests,
		stopped: false,
		async request(op: string, body?: Record<string, unknown>) {
			requests.push({ op, body });
			return answer(op, body);
		},
		stop() {
			this.stopped = true;
		},
	};
};
const withNote = (op: string, body: any) =>
	op === "open" ? { policy: "aware" } : {
		context: [{ type: "ag", name: "earlier", text: "NOTE" }, ...body.events.map((e: any) => ({ type: e.type, id: e.id, payload: e.payload }))],
		note: "ok",
	};

test("pi: the gatherer, what reaches the server, and what comes back", async () => {
	const s = server(withNote);
	const ag = new PiContextManager({ server: s });
	assert.deepEqual(ag.where("p1"), { gatherer: "p1", properties: { channel: "p1" } });
	assert.deepEqual(ag.where("p1", "demo"), { gatherer: "demo", properties: { channel: "p1" } });      // named: each pi session a channel
	const messages = [{ role: "user", content: "hi", timestamp: 1 }];
	const out = await ag.context(messages, ag.where("p1", "demo"), "/w");
	assert.deepEqual(out?.map((m) => m.role), ["custom", "user"]);
	assert.equal(ag.answering, true);
	const { op, body } = s.requests[0];
	assert.deepEqual([op, body.gatherer, body.properties.channel, body.cwd, body.events.length], ["rewrite", "demo", "p1", "/w", 1]);
	assert.equal((await ag.open(ag.where("p1"))).policy, "aware");
	ag.stop();
	assert.equal(s.stopped, true);
});

test("pi: whatever fails, pi's own messages -- and it no longer counts as answering", async () => {
	const ag = new PiContextManager({ server: server(() => ({ error: "server exited (1)" })) });
	assert.equal(await ag.context([{ role: "user", content: "hi", timestamp: 1 }], ag.where("p1"), "/w"), null);
	assert.equal(ag.answering, false);
	assert.equal((await ag.open(ag.where("p1"))).error, "server exited (1)");
});

const oc = (id: string, sid = "ses_1") => ({ info: { id, sessionID: sid, role: "user" }, parts: [{ id: `${id}_t`, type: "text", text: "hi" }] });

test("opencode: the gatherer from the messages, and what comes back", async () => {
	const s = server(withNote);
	const ag = new OpencodeContextManager({ server: s });
	assert.deepEqual(ag.where([oc("m1")]), { gatherer: "ses_1", properties: { channel: "ses_1" } });
	assert.deepEqual(new OpencodeContextManager({ server: s, named: "demo" }).where([oc("m1")]), { gatherer: "demo", properties: { channel: "ses_1" } });
	const out = await ag.transform([oc("m1")], "/w");
	assert.deepEqual(out?.map((m) => m.info.role), ["user", "user"]);                  // the ag message, then opencode's
	assert.deepEqual(out?.[1], oc("m1"));
	assert.equal(s.requests[0].body.cwd, "/w");
});

test("opencode: no gatherer on the messages, or a failure: opencode's own", async () => {
	const s = server(() => ({ context: null, note: "insert failed" }));
	const ag = new OpencodeContextManager({ server: s });
	assert.equal(ag.where([]), null);
	assert.equal(await ag.transform([], "/w"), null);
	assert.equal(s.requests.length, 0);                                               // nothing to ask without a gatherer
	assert.equal(await ag.transform([oc("m1")], "/w"), null);
});

// The model's answers kept as pending (the server's `pending`) by pi's and opencode's hooks, once each has ended:
// what reaches the server, with the properties of the session's calls, and what is not kept. Run: npm test.

import assert from "node:assert/strict";
import { test } from "node:test";
import { OpencodeContextManager } from "../../ag/integrations/harnesses/opencode/ag_orchestrator/context_manager.ts";
import { PiContextManager } from "../../ag/integrations/harnesses/pi/ag_orchestrator/context_manager.ts";

const server = () => {
	const requests: { op: string; body: any }[] = [];
	return {
		requests,
		async request(op: string, body?: Record<string, unknown>) {
			requests.push({ op, body });
			return { kept: (body?.events as unknown[] | undefined)?.length ?? 0 };
		},
		stop() {},
	};
};

const reply = (stopReason = "stop") => ({
	role: "assistant", content: [{ type: "text", text: "There are 42 rows." }], stopReason, responseId: "r1", timestamp: 2,
});

test("pi: an assistant message that ended is kept, with the call's properties", async () => {
	const s = server();
	const ag = new PiContextManager({ server: s });
	assert.equal(await ag.answered(reply(), ag.where("p1", "demo"), "/w"), "1 events pending");
	const { op, body } = s.requests[0];
	assert.equal(op, "pending");
	assert.deepEqual(body.properties, { channel: "p1", cwd: "/w" });
	assert.equal(body.answer, "r1");
	assert.deepEqual(body.events.map((e: any) => [e.type, e.text]), [["agent_message", "There are 42 rows."]]);
	assert.equal("id" in body.events[0], false);                                     // not history: no id
});

test("pi: another message, or a failed answer, is not kept", async () => {
	const s = server();
	const ag = new PiContextManager({ server: s });
	assert.equal(await ag.answered({ role: "user", content: "hi", timestamp: 1 }, ag.where("p1"), "/w"), null);
	assert.equal(await ag.answered(reply("error"), ag.where("p1"), "/w"), null);
	assert.equal(await ag.answered(reply("aborted"), ag.where("p1"), "/w"), null);
	assert.equal(s.requests.length, 0);
});

const info = (completed?: number, error?: unknown) => ({
	id: "msg_2", sessionID: "ses_1", role: "assistant", time: { created: 1, ...(completed ? { completed } : {}) }, ...(error ? { error } : {}),
});
const part = { id: "prt_1", sessionID: "ses_1", messageID: "msg_2", type: "text", text: "There are 42 rows." };

test("opencode: a message's parts are kept until it completes, then the message is pending", async () => {
	const s = server();
	const ag = new OpencodeContextManager({ server: s });
	assert.equal(await ag.event({ type: "message.part.updated", properties: { part: { ...part, text: "There" } } }, "/w"), null);
	assert.equal(await ag.event({ type: "message.part.updated", properties: { part } }, "/w"), null);   // the part, as it ends
	assert.equal(await ag.event({ type: "message.updated", properties: { info: info() } }, "/w"), null);  // still answering
	assert.equal(await ag.event({ type: "message.updated", properties: { info: info(3) } }, "/w"), "1 events pending");
	const { op, body } = s.requests[0];
	assert.equal(op, "pending");
	assert.deepEqual([body.gatherer, body.properties, body.answer], ["ses_1", { channel: "ses_1", cwd: "/w" }, "msg_2"]);
	assert.deepEqual(body.events.map((e: any) => [e.type, e.text]), [["agent_message", "There are 42 rows."]]);
	assert.equal(ag.parts.size, 0);                                                  // nothing left of it
});

test("opencode: a failed answer is not kept, and its parts are let go", async () => {
	const s = server();
	const ag = new OpencodeContextManager({ server: s });
	await ag.event({ type: "message.part.updated", properties: { part } }, "/w");
	assert.equal(await ag.event({ type: "message.updated", properties: { info: info(3, { name: "APIError" }) } }, "/w"), null);
	assert.equal(await ag.event({ type: "session.idle", properties: { sessionID: "ses_1" } }, "/w"), null);
	assert.deepEqual([s.requests.length, ag.parts.size], [0, 0]);
});

// The model's answers recorded by pi's and opencode's hooks once each has ended -- each event a `reply_part`, then the
// answer's `reply_end`, inserted by the server in its lane for records (call_ag.ts's `answered_ag`, as records.py
// records them) -- and each model call's `model_call`: what reaches the server, and what is not recorded. Run: npm test.

import assert from "node:assert/strict";
import { test } from "node:test";
import { OpencodeContextManager } from "../../ag/integrations/harnesses/opencode/ag_orchestrator/context_manager.ts";
import { PiContextManager } from "../../ag/integrations/harnesses/pi/ag_orchestrator/context_manager.ts";

const server = (answer?: (op: string, body: any) => any) => {
	const requests: { op: string; body: any }[] = [];
	return {
		requests,
		async request(op: string, body?: Record<string, unknown>) {
			requests.push({ op, body });
			return answer?.(op, body) ?? { rows: (body?.events as unknown[] | undefined)?.map(() => 1) ?? [] };
		},
		stop() {},
	};
};

const reply = (stopReason = "stop") => ({
	role: "assistant", content: [{ type: "text", text: "There are 42 rows." }], stopReason, responseId: "r1", timestamp: 2,
});

test("pi: an assistant message that ended is recorded as its answer's parts, in the session's channel", async () => {
	const s = server();
	const ag = new PiContextManager({ server: s });
	assert.equal(await ag.answered(reply(), ag.where("p1", "demo"), "/w"), "1 reply parts recorded");
	const { op, body } = s.requests[0];
	assert.deepEqual([op, body.gatherer, body.properties, body.lane], ["insert", "demo", { channel: "p1" }, "records"]);
	assert.deepEqual(body.events.map((e: any) => [e.type, e.id, e.properties.answer_id]),
		[["reply_part", "r1:0", "r1"], ["reply_end", "r1:end", "r1"]]);            // each stored once, by the answer's id
	assert.deepEqual([body.events[0].payload.type, body.events[0].payload.text], ["agent_message", "There are 42 rows."]);
});

test("pi and opencode: each model call recorded, with its harness", async () => {
	const s = server(() => ({ context: [], note: "ok", read_id: 7 }));
	await new PiContextManager({ server: s }).context([{ role: "user", content: "hi", timestamp: 1 }], { gatherer: "g", properties: { channel: "p1" } }, "/w");
	await new Promise((r) => setTimeout(r, 0));
	const call = s.requests.find((r) => r.op === "insert")!;
	assert.deepEqual([call.body.properties, call.body.lane], [{ channel: "p1" }, "records"]);
	assert.deepEqual([call.body.events[0].type, call.body.events[0].payload, call.body.events[0].properties],
		["model_call", { kind: "turn", harness: "pi" }, { read_id: 7 }]);
});

test("pi: another message, or a failed answer, is not recorded", async () => {
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

test("opencode: a message's parts are kept until it completes, then the message is recorded", async () => {
	const s = server();
	const ag = new OpencodeContextManager({ server: s });
	assert.equal(await ag.event({ type: "message.part.updated", properties: { part: { ...part, text: "There" } } }, "/w"), null);
	assert.equal(await ag.event({ type: "message.part.updated", properties: { part } }, "/w"), null);   // the part, as it ends
	assert.equal(await ag.event({ type: "message.updated", properties: { info: info() } }, "/w"), null);  // still answering
	assert.equal(await ag.event({ type: "message.updated", properties: { info: info(3) } }, "/w"), "1 reply parts recorded");
	const { op, body } = s.requests[0];
	assert.deepEqual([op, body.gatherer, body.properties, body.lane], ["insert", "ses_1", { channel: "ses_1" }, "records"]);
	assert.deepEqual(body.events.map((e: any) => [e.type, e.id]), [["reply_part", "msg_2:0"], ["reply_end", "msg_2:end"]]);
	assert.deepEqual([body.events[0].payload.type, body.events[0].payload.text], ["agent_message", "There are 42 rows."]);
	assert.equal(ag.parts.size, 0);                                                  // nothing left of it
});

test("opencode: a failed answer is not recorded, and its parts are let go", async () => {
	const s = server();
	const ag = new OpencodeContextManager({ server: s });
	await ag.event({ type: "message.part.updated", properties: { part } }, "/w");
	assert.equal(await ag.event({ type: "message.updated", properties: { info: info(3, { name: "APIError" }) } }, "/w"), null);
	assert.equal(await ag.event({ type: "session.idle", properties: { sessionID: "ses_1" } }, "/w"), null);
	assert.deepEqual([s.requests.length, ag.parts.size], [0, 0]);
});

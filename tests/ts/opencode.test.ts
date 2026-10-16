// The opencode harness's policy-specific half (to_events.ts, to_messages.ts): its messages as the context manager's events, and the context back as
// opencode's messages, shaped as opencode's session/message-v2.ts makes them. Run: npm test.

import assert from "node:assert/strict";
import { test } from "node:test";
import { classify, itemId, pieces, textOf, toEvents } from "../../ag/integrations/harnesses/opencode/adaptor/to_events.ts";
import { agMessage, join, toMessages } from "../../ag/integrations/harnesses/opencode/adaptor/to_messages.ts";

const SID = "ses_1";
const user = (mid: string, text: string, ...extra: object[]) => ({
	info: { id: mid, sessionID: SID, role: "user", time: { created: 1 }, agent: "build", model: { providerID: "litellm", modelID: "m" } },
	parts: [{ id: `prt_${mid}_t`, messageID: mid, sessionID: SID, type: "text", text }, ...extra],
});
const assistant = (mid: string, ...parts: object[]) => ({
	info: { id: mid, sessionID: SID, role: "assistant", parentID: "msg_u1", time: { created: 2 }, modelID: "m",
		providerID: "litellm", mode: "build", agent: "build", cost: 0, tokens: { input: 900, output: 20 }, finish: "tool-calls" },
	parts: parts.map((p) => ({ ...p, messageID: mid, sessionID: SID })),
});
const step = (id: string) => ({ id, type: "step-start" });
const say = (id: string, text: string) => ({ id, type: "text", text });
const think = (id: string, text: string) => ({ id, type: "reasoning", text, time: { start: 1 } });
const tool = (id: string, name: string, input: object, output: string, status = "completed") => ({
	id, type: "tool", callID: `call_${id}`, tool: name,
	state: status === "completed"
		? { status, input, output, time: { start: 1, end: 2 }, title: name, metadata: {} }
		: { status, input, error: output, time: { start: 1, end: 2 }, title: name, metadata: {} },
});
const reminder = (mid: string, n: number) => ({   // what opencode's SessionReminders adds on every step
	id: `prt_rem${n}`, messageID: mid, sessionID: SID, type: "text", text: "<system-reminder>plan mode</system-reminder>", synthetic: true,
});

const READ = tool("prt_a1_t", "read", { filePath: "notes.txt" }, "The launch code is 4217.");
const TURN = [
	user("msg_u1", "read notes.txt"),
	assistant("msg_a1", step("prt_a1_s"), think("prt_a1_r", "look first"), READ, { id: "prt_a1_f", type: "step-finish" }),
	assistant("msg_a2", step("prt_a2_s"), say("prt_a2_x", "It is 4217.")),
];

test("a user message is one item; an assistant message one per part, a tool part two", () => {
	const items = pieces(TURN);
	assert.deepEqual(items.map(classify), ["user_message", "agent_reasoning", "tool_call", "tool_output", "agent_message"]);
	const [, , call, output] = items;
	assert.equal("output" in call.part.state, false);                      // the call alone
	assert.deepEqual(call.part.state.input, { filePath: "notes.txt" });
	assert.deepEqual(output.part, TURN[1].parts[2]);                       // the result: the whole part
	assert.equal(JSON.stringify(items).includes("step-start"), false);    // opencode's structure: not an item
});

test("reasoning is its own type, costs nothing, and comes back in place", () => {
	const events = toEvents(TURN);
	const reasoning = events.filter((e) => e.type === "agent_reasoning");
	assert.equal(reasoning.length, 1);
	assert.equal(reasoning[0].tokens, 0);                                   // never counted
	assert.equal(events.filter((e) => e.type !== "agent_reasoning").some((e) => "tokens" in e), false);
	const back = toMessages(events.map((e) => ({ type: e.type, id: e.id, payload: e.payload })), TURN);
	assert.deepEqual(back, TURN);                                           // reasoning part included, in its place
});

test("join gives opencode's messages back with their structure", () => {
	assert.deepEqual(join(pieces(TURN), TURN), TURN);
});

test("a part the manager left out is left out", () => {
	const items = pieces(TURN).filter((i) => i.part?.type !== "reasoning");
	assert.deepEqual(join(items, TURN)[1].parts.map((p: any) => p.type), ["step-start", "tool", "step-finish"]);
});

test("a message opencode no longer sends is rebuilt from what was stored", () => {
	const out = join(pieces(TURN), TURN.slice(2));                        // msg_u1, msg_a1 gone from opencode
	assert.deepEqual(out[0], TURN[0]);
	assert.deepEqual(out[1].parts.map((p: any) => p.id), ["prt_a1_r", "prt_a1_t"]);   // the tool part once, whole
	assert.deepEqual(out[1].parts[1], TURN[1].parts[2]);
	assert.deepEqual(out[2], TURN[2]);
});

test("a call whose result was dropped is left out when rebuilt", () => {
	const items = pieces(TURN).filter((i) => classify(i) !== "tool_output");
	assert.deepEqual(join(items, [])[1].parts.map((p: any) => p.type), ["reasoning"]);
});

test("each item's type", () => {
	const cases: [unknown, string][] = [
		[user("m", "hi"), "user_message"],
		[user("m", " "), "context"],
		[{ info: { id: "m", role: "user" }, parts: [reminder("m", 1)] }, "context"],     // only opencode's own
		[{ info: { id: "m", role: "user" }, parts: [{ id: "p", type: "compaction", auto: true }] }, "context"],
		[{ info: { id: "m", role: "user" }, parts: [{ id: "p", type: "file", mime: "image/png", url: "data:", filename: "a.png" }] }, "user_message"],
		[{ info: { role: "assistant" }, part: { type: "hologram" } }, "context"],   // nothing opencode has: carried as context,
		[{ info: { role: "robot" }, parts: [] }, "context"],
		[{}, "context"],
	];
	for (const [item, name] of cases) assert.equal(classify(item), name, JSON.stringify(item));
});

test("ids are opencode's", () => {
	assert.deepEqual(pieces(TURN).map(itemId),
		["msg:msg_u1", "prt:prt_a1_r", "prt:prt_a1_t:call", "prt:prt_a1_t:output", "prt:prt_a2_x"]);
});

test("a reminder added on every step does not make a new event", () => {
	const first = user("msg_u1", "read notes.txt", reminder("msg_u1", 1));
	const again = user("msg_u1", "read notes.txt", reminder("msg_u1", 2)); // next step: a new reminder id
	assert.equal(toEvents([first])[0].id, toEvents([again])[0].id);
});

test("toMessages: ag messages as user messages, events joined with this call's copies", () => {
	const again = [user("msg_u1", "read notes.txt", reminder("msg_u1", 2)), ...TURN.slice(1), user("msg_u2", "thanks")];
	const context = [
		{ type: "ag", name: "earlier", text: "earlier: x" },
		...toEvents(again).map((e) => ({ type: e.type, id: e.id, payload: e.payload })),
	];
	const out = toMessages(context, again);
	assert.deepEqual(out.slice(1), again);                                  // opencode's current copies, in order
	assert.equal(out[0].info.role, "user");
	assert.deepEqual(out[0].parts.map((p: any) => [p.type, p.text, p.synthetic]), [["text", "earlier: x", true]]);
	const other = agMessage("y");
	assert.notEqual(other.info.id, out[0].info.id);                         // each its own id
});

test("each event's text is what the model reads, without opencode's bookkeeping", () => {
	const failed = tool("prt_a3_t", "bash", { command: "boom" }, "exit 1", "error");
	const events = toEvents([...TURN, assistant("msg_a3", failed), user("msg_u2", "and now?", reminder("msg_u2", 1))]);
	assert.deepEqual(events.map((e) => [e.type, e.text]), [
		["user_message", "read notes.txt"],
		["agent_reasoning", undefined],
		["tool_call", 'read({"filePath":"notes.txt"})'],
		["tool_output", "The launch code is 4217."],
		["agent_message", "It is 4217."],
		["tool_call", 'bash({"command":"boom"})'],
		["tool_output", "exit 1"],
		["user_message", "and now?"],            // the synthetic reminder is not the user's
	]);
	const json = JSON.stringify(events.map((e) => e.text));
	for (const bookkeeping of ["prt_", "msg_", "ses_1", "call_prt", "tokens", "metadata"]) assert.ok(!json.includes(bookkeeping), bookkeeping);
	assert.equal(textOf({ info: { role: "user" }, parts: [{ type: "file", filename: "a.png" }] }), "[file a.png]");
});

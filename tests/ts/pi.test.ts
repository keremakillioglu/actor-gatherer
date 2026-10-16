// The pi harness's policy-specific half: its messages as the context manager's events (to_events.ts), and the
// context back as pi's messages (to_messages.ts). Run: npm test (node --test, with type stripping).

import assert from "node:assert/strict";
import { test } from "node:test";
import { classify, event, pieces, textOf, toEvents } from "../../ag/integrations/harnesses/pi/adaptor/to_events.ts";
import { agMessage, CUSTOM_TYPE, join, toMessages } from "../../ag/integrations/harnesses/pi/adaptor/to_messages.ts";

const user = (text: string, ts = 1000) => ({ role: "user", content: [{ type: "text", text }], timestamp: ts });
const assistant = (blocks: object[], ts = 2000) => ({
	role: "assistant", content: blocks, api: "openai-responses", provider: "litellm", model: "gemini-3.8-flash",
	usage: { input: 10, output: 5 }, stopReason: "toolUse", timestamp: ts,
});
const result = (id: string, text: string, ts = 3000) => ({
	role: "toolResult", toolCallId: id, toolName: "bash", content: [{ type: "text", text }], isError: false, timestamp: ts,
});
const THINK = { type: "thinking", thinking: "look first", thinkingSignature: "x".repeat(400) };
const SAY = { type: "text", text: "listing" };
const CALL = { type: "toolCall", id: "call_0", name: "bash", arguments: { command: "ls" } };
const CALL2 = { type: "toolCall", id: "call_1", name: "read", arguments: { path: "a.py" } };

test("an assistant message is a piece per block, and joins again", () => {
	const messages = [user("hi"), assistant([THINK, SAY, CALL, CALL2]), result("call_0", "a.py"), result("call_1", "x")];
	const items = pieces(messages);
	assert.equal(items.length, 7);
	assert.deepEqual(items.slice(1, 5).map((i) => i.content), [[THINK], [SAY], [CALL], [CALL2]]);
	assert.ok(items.slice(1, 5).every((i) => i.timestamp === 2000 && i.usage.input === 10));
	assert.deepEqual(join(items), messages);
});

test("two assistant messages stay two; a message between pieces keeps them apart", () => {
	const two = [assistant([SAY], 1), assistant([SAY], 2)];
	assert.deepEqual(join(pieces(two)), two);
	const [a, b] = pieces([assistant([SAY, CALL])]);
	const notice = agMessage("note", 5);
	assert.deepEqual(join([a, notice, b]), [a, notice, b]);
});

test("each item's type, by role and block", () => {
	const cases: [unknown, string][] = [
		[user("hi"), "user_message"],
		[user("  "), "context"],                                  // nothing said: opens no turn
		[{ role: "user", content: "plain" }, "user_message"],
		[{ role: "user", content: [{ type: "image", data: "..", mimeType: "image/png" }] }, "user_message"],
		[assistant([THINK]), "agent_reasoning"],
		[assistant([SAY]), "agent_message"],
		[assistant([CALL]), "tool_call"],
		[assistant([SAY, CALL]), "tool_call"],                   // unsplit, with a call
		[assistant([]), "agent_message"],
		[result("c", "out"), "tool_output"],
		[agMessage("x"), "context"],
		[{ role: "bashExecution", command: "ls", output: "a" }, "context"],
		[{ role: "compactionSummary", summary: "s", tokensBefore: 9 }, "context"],
		[{ role: "branchSummary", summary: "s", fromId: "e" }, "context"],
		[assistant([{ type: "hologram" }]), "context"],                  // nothing pi has: carried as context,
		[{ role: "robot" }, "context"],
		[{}, "context"],
		["not a message", "context"],
	];
	for (const [item, name] of cases) assert.equal(classify(item), name, JSON.stringify(item));
});

test("ids are the content's: the same after a round trip, another when said again later", () => {
	const m = user("hi");
	assert.equal(event(m).id, event(JSON.parse(JSON.stringify(m))).id);
	assert.equal(event(m).id, event({ timestamp: 1000, content: [{ text: "hi", type: "text" }], role: "user" }).id); // key order
	assert.notEqual(event(m).id, event(user("hi", 1001)).id);
	assert.match(event(m).id ?? "", /^sha256:[0-9a-f]{64}$/);
});

test("a thinking piece costs nothing; the rest is counted by the server", () => {
	assert.equal(event(assistant([THINK])).tokens, 0);
	assert.equal(event(assistant([SAY])).tokens, undefined);
});

test("toEvents: pieces, typed, in order", () => {
	const events = toEvents([user("hi"), assistant([SAY, CALL])]);
	assert.deepEqual(events.map((e) => e.type), ["user_message", "agent_message", "tool_call"]);
});

test("thinking is its own type and comes back into its message", () => {
	const messages = [user("hi"), assistant([THINK, SAY, CALL]), result("call_0", "a.py")];
	const events = toEvents(messages);
	assert.deepEqual(events.map((e) => e.type), ["user_message", "agent_reasoning", "agent_message", "tool_call", "tool_output"]);
	assert.deepEqual(toMessages(events.map((e) => ({ type: e.type, id: e.id, payload: e.payload }))), messages);
});

test("toMessages: payloads as sent, pieces joined, ag messages as hidden custom messages", () => {
	const messages = [user("hi"), assistant([SAY, CALL]), result("call_0", "a.py")];
	const events = toEvents(messages);
	const context = [
		{ type: "ag", name: "earlier", text: "# Earlier\n..." },
		...events.map((e) => ({ type: e.type, id: e.id, payload: e.payload })),
	];
	const out = toMessages(context);
	assert.deepEqual(out.slice(1), messages);
	assert.equal(out[0].role, "custom");
	assert.equal(out[0].customType, CUSTOM_TYPE);
	assert.equal(out[0].content, "# Earlier\n...");
	assert.equal(out[0].display, false);
});

test("each event's text is what the model reads, without pi's bookkeeping", () => {
	const messages = [user("hi"), assistant([THINK, SAY, CALL]), result("call_0", "a.py\nb.py"),
		{ role: "bashExecution", command: "pwd", output: "/w", exitCode: 0, timestamp: 4000 },
		{ role: "compactionSummary", summary: "earlier work", tokensBefore: 9, timestamp: 5000 }];
	const texts = toEvents(messages).map((e) => e.text);
	assert.deepEqual(texts, ["hi", undefined, "listing", 'bash({"command":"ls"})', "a.py\nb.py", "$ pwd\n/w", "earlier work"]);
	assert.equal(textOf({ role: "user", content: "plain" }), "plain");
	assert.equal(textOf({ role: "user", content: [{ type: "image", data: "x", mimeType: "image/png" }] }), "[image]");
	const json = JSON.stringify(toEvents(messages).map((e) => e.text));
	for (const bookkeeping of ["thinkingSignature", "timestamp", "usage", "call_0", "openai-responses"]) {
		assert.ok(!json.includes(bookkeeping), bookkeeping);
	}
});

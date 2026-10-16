// ag/integrations/tools/ag_orchestrator/call_ag.ts: one model call through a harness's adaptor and the server, with every way it
// can fail leaving the harness's own messages, and the adaptor held to what it declares. The adaptor and the server are
// stand-ins. Run: npm test.

import assert from "node:assert/strict";
import { test } from "node:test";
import { CHANNEL, AG, CWD } from "../../ag/integrations/tools/ag_orchestrator/adaptor.ts";
import { call_ag } from "../../ag/integrations/tools/ag_orchestrator/call_ag.ts";

type Req = { op: string; body?: Record<string, unknown> };
const server = (answer: (body: any) => any) => {
	const requests: Req[] = [];
	return { requests, request: async (op: string, body?: Record<string, unknown>) => (requests.push({ op, body }), answer(body)) };
};
class Stand {
	static readonly adaptorName = "stand";
	static readonly outputs = ["t"];
	static readonly accepts = ["t", AG];
	static readonly properties = [CHANNEL, CWD];
	toEvents(ms: string[]) {
		return ms.map((m, i) => ({ type: "t", id: String(i), payload: m }));
	}
	toMessages(context: any[]) {
		return context.map((e) => (e.type === "ag" ? `<${e.text}>` : e.payload));
	}
}
const broken = () => { throw new Error("no"); };
const adaptor = (overrides: Record<string, unknown> = {}) => Object.assign(new Stand(), overrides);
const where = { gatherer: "s", properties: { [CHANNEL]: "c" }, cwd: "/w" };

test("messages to events, to the server, and back", async () => {
	const s = server((body) => ({ context: [{ type: "ag", text: "note" }, ...body.events], note: "ok" }));
	assert.deepEqual(await call_ag(s, where, ["a", "b"], adaptor()), { messages: ["<note>", "a", "b"], note: "ok" });
	const sent = { ...where, properties: { ...where.properties, [CWD]: "/w" } };   // the working directory, as a property too
	assert.deepEqual(s.requests, [{ op: "rewrite", body: { ...sent, events: new Stand().toEvents(["a", "b"]) } }]);
});

test("every failure leaves the harness's own messages", async () => {
	const cases: [ReturnType<typeof server>, Stand, string][] = [
		[server(() => ({ error: "server exited (1)" })), adaptor(), "server: server exited (1)"],
		[server(() => ({ context: null, note: "insert failed" })), adaptor(), "insert failed"],
		[server(() => ({ context: [] })), adaptor({ toEvents: broken }), "could not make events"],
		[server(() => ({ context: [] })), adaptor({ toMessages: broken }), "could not make messages"],
	];
	for (const [s, a, why] of cases) {
		const routed = await call_ag(s, where, ["a"], a);
		assert.equal(routed.messages, null, why);
		assert.ok(routed.note.includes(why), `${routed.note} / ${why}`);
	}
});

test("an adaptor that fails on the way in sends nothing", async () => {
	const s = server(() => ({ context: [] }));
	await call_ag(s, where, ["a"], adaptor({ toEvents: broken }));
	assert.deepEqual(s.requests, []);
});

test("a property the adaptor does not declare sends nothing", async () => {
	const s = server(() => ({ context: [] }));
	const routed = await call_ag(s, { ...where, properties: { [CHANNEL]: "c", user: "u" } }, ["a"], adaptor());
	assert.equal(routed.messages, null);
	assert.ok(routed.note.includes("does not declare the properties user"), routed.note);
	assert.deepEqual(s.requests, []);
});

test("an event of a type the adaptor does not declare sends nothing", async () => {
	const s = server(() => ({ context: [] }));
	const routed = await call_ag(s, where, ["a"], adaptor({ toEvents: () => [{ type: "other", id: "1", payload: "a" }] }));
	assert.equal(routed.messages, null);
	assert.ok(routed.note.includes("does not declare (other)"), routed.note);
	assert.deepEqual(s.requests, []);
});

test("a context entry the adaptor does not accept is noted", async () => {
	const s = server(() => ({ context: [{ type: "environment_update", payload: "x" }, { type: "t", payload: "a" }], note: "ok" }));
	const routed = await call_ag(s, where, ["a"], adaptor());
	assert.deepEqual(routed.messages, ["x", "a"]);
	assert.ok(routed.note.includes("does not accept environment_update"), routed.note);
});

test("an adaptor ag names is loaded from its path, and one without declarations refused", async () => {
	const { loadAdaptor } = await import("../../ag/integrations/tools/ag_orchestrator/adaptor.ts");
	const { PiAdaptor } = await import("../../ag/integrations/harnesses/pi/adaptor/adaptor.ts");
	const { join } = await import("node:path");
	const here = new URL(".", import.meta.url).pathname;
	const loaded = await loadAdaptor(join(here, "../../ag/integrations/harnesses/pi/adaptor/adaptor.ts:PiAdaptor"));
	assert.ok(loaded instanceof PiAdaptor);
	await assert.rejects(loadAdaptor(join(here, "../../ag/integrations/tools/ag_orchestrator/adaptor.ts:declarations")),
		/not an adaptor class/);
});

test("each shipped adaptor emits only what it declares", async () => {
	const { PiAdaptor } = await import("../../ag/integrations/harnesses/pi/adaptor/adaptor.ts");
	const { OpencodeAdaptor } = await import("../../ag/integrations/harnesses/opencode/adaptor/adaptor.ts");
	const pi = [{ role: "user", content: "hi", timestamp: 1 }, { role: "assistant", content: [{ type: "text", text: "x" },
		{ type: "toolCall", id: "c", name: "read", arguments: {} }, { type: "hologram" }] },
		{ role: "toolResult", toolCallId: "c", content: [] }, { role: "robot" }, {}];
	const oc = [{ info: { id: "m", sessionID: "s", role: "user" }, parts: [{ id: "p", type: "text", text: "hi" }] },
		{ info: { id: "a", sessionID: "s", role: "assistant" }, parts: [{ id: "q", type: "text", text: "x" },
			{ id: "r", type: "hologram" }] }, { info: { role: "robot" }, parts: [] }];
	for (const [cls, messages] of [[PiAdaptor, pi], [OpencodeAdaptor, oc]] as const) {
		for (const e of new (cls as any)().toEvents(messages)) assert.ok((cls as any).outputs.includes(e.type), `${cls.name}: ${e.type}`);
	}
});

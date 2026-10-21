// The provider's count of each call's context for an in-process hook (pi, opencode): call_ag names the read and sends
// an earlier call's count with the next rewrite; Measurements finds that count on the harness's next assistant
// message; and pi's and opencode's usage read as input tokens, the cache's included. Run: npm test.

import assert from "node:assert/strict";
import { test } from "node:test";
import { CHANNEL, AG, CWD } from "../../ag/integrations/tools/ag_orchestrator/adaptor.ts";
import { call_ag } from "../../ag/integrations/tools/ag_orchestrator/call_ag.ts";
import { Measurements } from "../../ag/integrations/tools/ag_orchestrator/measured.ts";
import { piInputTokens } from "../../ag/integrations/harnesses/pi/ag_orchestrator/context_manager.ts";
import { opencodeInputTokens } from "../../ag/integrations/harnesses/opencode/ag_orchestrator/context_manager.ts";

class Stand {
	static readonly adaptorName = "stand";
	static readonly outputs = ["t"];
	static readonly accepts = ["t", AG];
	static readonly properties = [CHANNEL, CWD];
	toEvents(ms: string[]) {
		return ms.map((m, i) => ({ type: "t", id: String(i), payload: m }));
	}
	toMessages(context: any[]) {
		return context.map((e) => e.payload);
	}
}
const where = { gatherer: "s", properties: { [CHANNEL]: "c" } };

test("a rewrite's read comes back, and an earlier count goes with the next one", async () => {
	const bodies: any[] = [];
	const s = { request: async (_op: string, body?: any) => (bodies.push(body), { context: body.events, note: "", read_id: 7 }) };
	const routed = await call_ag(s, where, ["a"], new Stand());
	assert.equal(routed.readId, 7);
	assert.equal("measured" in bodies[0], false);                       // nothing to send yet
	await call_ag(s, where, ["a", "b"], new Stand(), { read_id: 7, tokens: 900 });
	assert.deepEqual(bodies[1].measured, { read_id: 7, tokens: 900 });
	const none = { request: async (_op: string, body?: any) => ({ context: null, note: "x", read_id: 8 }) };
	assert.equal((await call_ag(none, where, ["a"], new Stand())).readId, undefined);   // the harness's own went
});

type M = { role: string; t?: number };
const m = () => new Measurements<M>((x) => x.role === "assistant", (x) => x.t ?? null);

test("the count is the newest answer since the read, once there is one", () => {
	const ms = m();
	assert.equal(ms.take("c", [{ role: "user" }]), null);                // no read kept
	ms.keep("c", 3, [{ role: "user" }]);
	assert.equal(ms.take("c", [{ role: "user" }]), null);                // no answer since: nothing, and forgotten
	ms.keep("c", 4, [{ role: "user" }]);
	assert.deepEqual(ms.take("c", [{ role: "user" }, { role: "assistant", t: 120 }, { role: "assistant", t: 0 }]),
		{ read_id: 4, tokens: 120 });                                      // one still being written counts nothing yet
	ms.keep("c", 5, [{ role: "assistant", t: 1 }]);
	assert.equal(ms.take("c", [{ role: "assistant", t: 1 }]), null);     // the old answer is not this call's
	ms.keep("c", undefined, []);
	assert.equal(ms.take("c", [{ role: "assistant", t: 9 }]), null);     // the harness's own went: no read
});

test("pi's and opencode's usage, the cache's included", () => {
	assert.equal(piInputTokens({ role: "assistant", usage: { input: 10, cacheRead: 200, cacheWrite: 5, output: 3 } }), 215);
	assert.equal(piInputTokens({ role: "assistant" }), null);
	assert.equal(opencodeInputTokens({ info: { role: "assistant", tokens: { input: 7, output: 2, cache: { read: 93, write: 0 } } }, parts: [] }), 100);
	assert.equal(opencodeInputTokens({ info: { role: "assistant", tokens: { input: 0, cache: { read: 0, write: 0 } } }, parts: [] }), null);
});

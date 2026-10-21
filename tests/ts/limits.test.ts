// A harness's own limit for its calls, from an in-process hook: pi's (its model's window less its compaction
// reserve) and opencode's (its model's window less the output it reserves, as `chat.params` names the model), sent
// with each rewrite by call_ag. Run: npm test.

import assert from "node:assert/strict";
import { test } from "node:test";
import { CHANNEL, AG, CWD } from "../../ag/integrations/tools/ag_orchestrator/adaptor.ts";
import { call_ag } from "../../ag/integrations/tools/ag_orchestrator/call_ag.ts";
import { PI_RESERVE_TOKENS, piLimit } from "../../ag/integrations/harnesses/pi/ag_orchestrator/context_manager.ts";
import { OpencodeContextManager, opencodeLimit } from "../../ag/integrations/harnesses/opencode/ag_orchestrator/context_manager.ts";

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

test("pi's limit: its model's window less the compaction reserve", () => {
	assert.equal(piLimit({ contextWindow: 128000 }), 128000 - PI_RESERVE_TOKENS);
	assert.equal(piLimit(undefined), null);
	assert.equal(piLimit({ contextWindow: 8000 }), null);               // no room past the reserve: none stated
});

test("opencode's limit: its model's window less its output", () => {
	assert.equal(opencodeLimit({ limit: { context: 200000, output: 32000 } }), 168000);
	assert.equal(opencodeLimit({ limit: { context: 200000, output: 0 } }), 200000);
	assert.equal(opencodeLimit({}), null);
	const ag = new OpencodeContextManager({ server: { request: async () => ({}), stop() {} } as any });
	ag.params("ses_1", { limit: { context: 400000, output: 64000 } });
	ag.params(undefined, { limit: { context: 1, output: 0 } });              // no session: nothing kept
	assert.deepEqual([...ag.limits], [["ses_1", 336000]]);
});

test("call_ag sends the limit with the rewrite", async () => {
	const bodies: any[] = [];
	const s = { request: async (_op: string, body?: any) => (bodies.push(body), { context: body.events, note: "" }) };
	const where = { gatherer: "s", properties: { [CHANNEL]: "c" } };
	await call_ag(s, where, ["a"], new Stand(), null, 111616.7);
	await call_ag(s, where, ["a"], new Stand());
	assert.equal(bodies[0].limit, 111616);
	assert.equal("limit" in bodies[1], false);
});

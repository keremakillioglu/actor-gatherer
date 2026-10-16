/**
 * The harness side's client of the context manager's server, for plugins that
 * run in Node or Bun (ag_client.py is the same for hooks in Python): starts
 * `python -m ag.ag_harness.server` on first use, again if it has exited, sends
 * it one JSON line per request and matches each answer line to its request by id. The protocol is ag/ag_harness/server/__init__.py's; `harness` only
 * names the server's log.
 *
 * A request never rejects: it resolves with the answer, or with `{error}` when
 * the server exits, cannot start, keeps exiting (three starts in a minute), or
 * does not answer in time -- so a broken server never blocks a model call.
 *
 * Environment: AG_PYTHON (default python3), AG_HOME (default ~/.ag). How long a
 * call waits is the constructor's `timeoutMs` (default 300000 ms). The
 * server's stderr goes to <home>/logs/<harness>_server.log.
 */

import { type ChildProcess, spawn } from "node:child_process";
import { mkdirSync, openSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";

export const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", ".."); // <root>/ag/integrations/tools/ag_connection/this file
export const HOME = resolve((process.env.AG_HOME || join(homedir(), ".ag")).replace(/^~(?=$|\/)/, homedir()));
const TIMEOUT_MS = 300_000;

export type Answer = Record<string, any>;
type Pending = { resolve: (a: Answer) => void; timer: ReturnType<typeof setTimeout> };

/** The server process for one harness: started on first use, again if it has exited. */
export class AgClient {
	private child?: ChildProcess;
	private next = 1;
	private pending = new Map<number, Pending>();
	private starts: number[] = [];

	readonly harness: string;
	readonly timeoutMs: number;

	constructor(harness: string, timeoutMs: number = TIMEOUT_MS) {
		this.harness = harness;
		this.timeoutMs = timeoutMs;
	}

	get log(): string {
		return join(HOME, "logs", `${this.harness}_server.log`);
	}

	private start(): ChildProcess | undefined {
		const now = Date.now();
		this.starts = this.starts.filter((t) => now - t < 60_000);
		if (this.starts.length >= 3) return undefined; // exits at once, over and over: give up
		this.starts.push(now);
		mkdirSync(dirname(this.log), { recursive: true });
		const child = spawn(process.env.AG_PYTHON || "python3", ["-m", "ag.ag_harness.server"], {
			cwd: REPO,
			env: { ...process.env, PYTHONPATH: [REPO, process.env.PYTHONPATH].filter(Boolean).join(":") },
			stdio: ["pipe", "pipe", openSync(this.log, "a")],
		});
		createInterface({ input: child.stdout! }).on("line", (line) => {
			let answer: Answer;
			try {
				answer = JSON.parse(line);
			} catch {
				return;
			}
			const waiting = this.pending.get(answer.id);
			if (!waiting) return; // answered after its request timed out
			this.pending.delete(answer.id);
			clearTimeout(waiting.timer);
			waiting.resolve(answer);
		});
		const gone = (why: string) => {
			if (this.child === child) this.child = undefined;
			for (const [id, waiting] of this.pending) {
				clearTimeout(waiting.timer);
				waiting.resolve({ id, error: why });
			}
			this.pending.clear();
		};
		child.on("exit", (code, signal) => gone(`server exited (${signal ?? code}); see ${this.log}`));
		child.on("error", (err) => gone(`server failed to start: ${err.message}`));
		child.stdin!.on("error", () => {}); // a write after exit: the exit handler answers
		return child;
	}

	/** One request; resolves with the answer, or with `{error}` -- never rejects. */
	request(op: string, body: Answer = {}, timeoutMs = this.timeoutMs): Promise<Answer> {
		if (!this.child || this.child.exitCode !== null) this.child = this.start();
		const child = this.child;
		if (!child) return Promise.resolve({ error: "the server keeps exiting; not restarted" });
		const id = this.next++;
		return new Promise((resolve) => {
			const timer = setTimeout(() => {
				this.pending.delete(id);
				resolve({ id, error: `no answer in ${timeoutMs} ms` });
			}, timeoutMs);
			this.pending.set(id, { resolve, timer });
			child.stdin!.write(`${JSON.stringify({ id, op, ...body })}\n`);
		});
	}

	/** Close the server's stdin: it finishes what it is answering and exits. */
	stop(): void {
		this.child?.stdin?.end();
		this.child = undefined;
	}
}

// Finding the dashboard the app shows, or starting it (desktop/DESIGN.md, "The app"): the way `ag` does it. `ag` runs
// `ag dashboard --open` on the home, which serves the page on port 4200, or, if a dashboard of the same home is there
// already, opens that one (ag_dashboard/__main__.py: `_serves_this_home`, its /api/home). Plain Node, no Electron, so
// it is tested on its own (test/dashboard.test.ts).
import { spawn, spawnSync } from "node:child_process";
import { accessSync, constants, mkdirSync, openSync, readFileSync } from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";

export const DEFAULT_PORT = 4200;
export const START_WAIT = 120_000; // ms: a checkout's dashboard builds its page first (page_build.ensure)

/** The home ag uses: the one given, else AG_HOME, else ~/.ag -- made absolute as ag_dashboard/home.py makes it. */
export function homeOf(env: NodeJS.ProcessEnv, given?: string): string {
  const raw = given || env.AG_HOME || "~/.ag";
  return path.resolve(raw.replace(/^~(?=$|\/)/, os.homedir()));
}

export function urlOf(port: number): string {
  return `http://127.0.0.1:${port}/`;
}

export type Found =
  | { kind: "ours"; url: string } // a dashboard of this home
  | { kind: "none" } // nothing listens there
  | { kind: "other"; what: string }; // something else: another home's dashboard, or another program

/** What is on `port`: this home's dashboard, nothing, or something else. */
export function probe(port: number, home: string, timeoutMs = 5000): Promise<Found> {
  return new Promise((resolve) => {
    const req = http.get(`${urlOf(port)}api/home`, { timeout: timeoutMs }, (res) => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (chunk: string) => (body += chunk));
      res.on("end", () => {
        let other: unknown;
        try {
          other = (JSON.parse(body) as { home?: unknown }).home;
        } catch {
          return resolve({ kind: "other", what: "another program" });
        }
        if (res.statusCode === 200 && other === home) return resolve({ kind: "ours", url: urlOf(port) });
        resolve({
          kind: "other",
          what: typeof other === "string" ? `the dashboard of another home (${other})` : "another program",
        });
      });
    });
    req.on("timeout", () => req.destroy(new Error("timed out")));
    req.on("error", (err: NodeJS.ErrnoException) =>
      resolve(err.code === "ECONNREFUSED" ? { kind: "none" } : { kind: "other", what: `something that did not answer (${err.message})` }),
    );
  });
}

/** `ag` on the PATH of `env`, or null. */
export function findAg(env: NodeJS.ProcessEnv): string | null {
  for (const dir of (env.PATH || "").split(path.delimiter)) {
    if (!dir) continue;
    const candidate = path.join(dir, "ag");
    try {
      accessSync(candidate, constants.X_OK);
      return candidate;
    } catch {
      // not here
    }
  }
  return null;
}

/** The environment of the user's login shell -- an app opened from the Finder or the Dock gets almost none of it (no
 * PATH to `ag`, none of the API keys the actors need) -- else `fallback`. */
export function loginEnv(fallback: NodeJS.ProcessEnv, shell = process.env.SHELL || "/bin/zsh"): NodeJS.ProcessEnv {
  const mark = "__ag_desktop_env__";
  const out = spawnSync(shell, ["-ilc", `printf ${mark}; env -0; printf ${mark}`], {
    encoding: "utf8",
    timeout: 10_000,
    stdio: ["ignore", "pipe", "ignore"],
  });
  const parts = (out.stdout || "").split(mark);
  if (out.status !== 0 || parts.length < 3) return fallback;
  const env: NodeJS.ProcessEnv = {};
  for (const line of parts[1].split("\0")) {
    const eq = line.indexOf("=");
    if (eq > 0) env[line.slice(0, eq)] = line.slice(eq + 1);
  }
  return env;
}

export type Started = { pid: number; log: string; exited: Promise<number | null> };

/** `ag dashboard --no-open` on `home`, at `port`, started on its own: it runs on after the app quits, as it does after
 * the browser tab closes (desktop/DESIGN.md, "Decisions"). What it says goes to <home>/logs/dashboard/desktop.log. */
export function startDashboard(ag: string, home: string, port: number, env: NodeJS.ProcessEnv): Started {
  const logs = path.join(home, "logs", "dashboard");
  mkdirSync(logs, { recursive: true });
  const log = path.join(logs, "desktop.log");
  const fd = openSync(log, "a");
  const child = spawn(ag, ["dashboard", "--no-open", "--port", String(port)], {
    env: { ...env, AG_HOME: home },
    cwd: os.homedir(),
    detached: true,
    stdio: ["ignore", fd, fd],
  });
  const exited = new Promise<number | null>((resolve) => {
    child.on("exit", (code) => resolve(code));
    child.on("error", () => resolve(-1));
  });
  child.unref();
  return { pid: child.pid ?? -1, log, exited };
}

/** The last lines of a log, to show why a start failed. */
export function tail(file: string, lines = 12): string {
  try {
    return readFileSync(file, "utf8").trimEnd().split("\n").slice(-lines).join("\n");
  } catch {
    return "";
  }
}

/** Waits until `port` has this home's dashboard: its address; an Error if the start ended first, or took too long. */
export async function waitFor(port: number, home: string, started: Started, timeoutMs = START_WAIT): Promise<string> {
  let ended: number | null | undefined;
  void started.exited.then((code) => (ended = code));
  const until = Date.now() + timeoutMs;
  while (Date.now() < until) {
    const found = await probe(port, home, 2000);
    if (found.kind === "ours") return found.url;
    if (ended !== undefined) throw new Error(`ag dashboard stopped (exit ${ended}):\n${tail(started.log)}`);
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`ag dashboard did not answer in ${Math.round(timeoutMs / 1000)} s:\n${tail(started.log)}`);
}

/** The dashboard to show: the home's own on `port` if it runs, else one started there. `env`: what to start it with. */
export async function connect(home: string, port: number, env: () => NodeJS.ProcessEnv): Promise<string> {
  const found = await probe(port, home);
  if (found.kind === "ours") return found.url;
  if (found.kind === "other") throw new Error(`Port ${port} is taken by ${found.what}, so this home's dashboard can't start there.`);
  const startEnv = env();
  const ag = findAg(startEnv);
  if (!ag) throw new Error("Couldn't find ag on your shell's PATH. Install it with pip install 'actor-gatherer[dashboard]'.");
  return waitFor(port, home, startDashboard(ag, home, port, startEnv));
}

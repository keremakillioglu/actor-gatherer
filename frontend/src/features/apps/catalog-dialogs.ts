// The Apps page's dialogs (catalog.ts): each step that installs, updates or uninstalls an app asked first. An app from
// a folder or git URL is staged -- copied aside and checked by the server -- then shown as it is: what it may do, what
// agents get of it, and that its code runs unsandboxed; Install installs it, Cancel discards it. One dialog at a time.
import { post } from "../../core/api/client";
import type { CatalogApp } from "./catalog";
import { el, kb, markOf, said, tokens } from "./catalog-parts";

/** What a dialog tells the page when it is done: the apps changed (`note` said, `sel` shown), or read again. */
export interface Asked {
  done: (note: string, sel: string | null) => Promise<void>;
  reload: () => Promise<void>;
}
interface Staged extends CatalogApp {
  id: string;
  installed?: CatalogApp;
  changes?: {
    version: string[];
    tools_added: string[];
    tools_gone: string[];
    can_added: string[];
    own_process: boolean;
  };
}

const open = { dim: null as HTMLElement | null, staged: "", back: null as HTMLElement | null };

/** The dialog open closed (a staged app discarded): whether one was. */
export function closeDialog(): boolean {
  if (!open.dim) return false;
  if (open.staged) void post("/api/apps/discard", { id: open.staged }).catch(() => {});
  open.dim.remove();
  open.dim = null;
  open.staged = "";
  open.back?.focus?.();
  return true;
}

function dialog(label: string, ...kids: (HTMLElement | null)[]): HTMLElement {
  if (!open.dim) {
    open.back = document.activeElement as HTMLElement | null;
    open.dim = el("div", { class: "ap-dim", onclick: (ev: MouseEvent) => ev.target === open.dim && closeDialog() });
    document.body.append(open.dim);
  }
  const d = el("div", { class: "ap-dlg", role: "dialog", "aria-modal": "true", "aria-label": label }, ...kids);
  open.dim.replaceChildren(d);
  requestAnimationFrame(() => d.querySelector<HTMLElement>("input:not([type=checkbox]), .primary, .danger")?.focus());
  return d;
}
const buttons = (...b: HTMLElement[]): HTMLElement => el("div", { class: "ap-btns" }, ...b);
const cancel = (): HTMLElement =>
  el("button", { type: "button", class: "ap-btn", onclick: () => closeDialog() }, "Cancel");
const lead = (a: CatalogApp, title: string, sub: string): HTMLElement =>
  el(
    "div",
    { class: "ap-lead" },
    markOf(a, 40),
    el("div", {}, el("h2", { text: title }), el("div", { class: "ap-sub", text: sub })),
  );
const fromLine = (a: CatalogApp): string =>
  [
    a.version ? `version ${a.version}` : "",
    a.origin === "builtin" ? "comes with ag" : a.source ? `from ${a.source}` : "",
    a.commit ? `at ${a.commit.slice(0, 7)}` : "",
  ]
    .filter(Boolean)
    .join(" · ");

/** A failure said in the dialog, its button let go again. */
function failed(d: HTMLElement, text: string, go?: HTMLButtonElement): void {
  d.querySelector(".ap-busy")?.remove();
  let e = d.querySelector<HTMLElement>(".ap-derr");
  if (!e) {
    e = el("div", { class: "ap-derr", role: "alert" });
    d.querySelector(".ap-btns")?.before(e);
  }
  e.textContent = text;
  if (go) go.disabled = false;
}
function busy(d: HTMLElement, text: string, go?: HTMLButtonElement): void {
  d.querySelector(".ap-derr")?.remove();
  d.querySelector(".ap-busy")?.remove();
  d.querySelector(".ap-btns")?.before(
    el("div", { class: "ap-busy" }, el("i", { class: "spin", "aria-hidden": "true" }), text),
  );
  if (go) go.disabled = true;
}

/** "Install from a folder or git URL…": where it is asked (`source` filled in), then it is staged and shown. `go`: an
 * entry of ag's index, staged at once. */
export function fromSource(asked: Asked, source = "", go = false): void {
  const input = el("input", {
    class: "ap-field",
    value: source,
    placeholder: "~/apps/pager, or https://github.com/someone/ag-pager",
    "aria-label": "Folder or git URL",
    spellcheck: "false",
  }) as HTMLInputElement;
  const check = el("button", { type: "button", class: "ap-btn primary" }, "Check") as HTMLButtonElement;
  const d = dialog(
    "Install an app",
    el("h2", { text: "Install an app" }),
    el("p", {
      class: "ap-sub",
      text: "A folder on this computer or a git URL.",
    }),
    input,
    buttons(cancel(), check),
  );
  const stage = async (): Promise<void> => {
    const src = input.value.trim();
    if (!src) return failed(d, "Enter a folder or a git URL.", check);
    busy(d, "Checking the app…", check);
    try {
      const st = await post<Staged>("/api/apps/stage", { source: src });
      if (!open.dim) return void post("/api/apps/discard", { id: st.id }).catch(() => {}); // closed meanwhile
      if (st.installed) {
        void post("/api/apps/discard", { id: st.id }).catch(() => {});
        return failed(d, `${st.label} is already installed. Update it from its details.`, check);
      }
      confirmInstall(st, asked);
    } catch (e) {
      failed(d, `Can't install it. ${(e as Error).message}`, check);
    }
  };
  check.addEventListener("click", () => void stage());
  input.addEventListener("keydown", (ev) => ev.key === "Enter" && void stage());
  if (go && source) void stage();
}

// what it may do, and what agents get of it, as the install and update dialogs say it
function itCan(a: CatalogApp): HTMLElement[] {
  const who =
    a.access === "group"
      ? "Every agent of the group, when it next starts"
      : "Only the agents in its task, when they next start";
  return [
    el("h3", { text: "It can" }),
    el(
      "ul",
      {},
      ...said.can(a).map((c) => el("li", { text: c })),
      ...(a.schedules || []).map((s) => el("li", { text: `Runs ${s}` })),
    ),
    el("h3", { text: "Agents get" }),
    el(
      "ul",
      {},
      el("li", {}, `${said.count((a.tools || []).length, "tool")}, `, tokens(a.tokens || 0, "per agent")),
      el("li", { text: who }),
      a.needs ? el("li", { text: `Needs: ${a.needs}` }) : null,
    ),
  ];
}

function confirmInstall(st: Staged, asked: Asked): void {
  open.staged = st.id;
  const go = el("button", { type: "button", class: "ap-btn primary" }, "Install") as HTMLButtonElement;
  const d = dialog(
    `Install ${st.label}?`,
    lead(st, `Install ${st.label}?`, fromLine(st)),
    el("p", { text: said.sentence(st.description) }),
    ...itCan(st),
    el("p", { class: "ap-sub", text: "Once installed it's on in every folder." }),
    el("div", {
      class: "ap-warn",
      text: "Apps run on your computer with your permissions. Only install apps you trust.",
    }),
    buttons(cancel(), go),
  );
  go.addEventListener("click", async () => {
    busy(d, "Installing…", go);
    try {
      await post("/api/apps/install", { id: st.id });
      open.staged = "";
      closeDialog();
      await asked.done(`Installed ${st.label}. Agents get its tools when they next start.`, st.name);
    } catch (e) {
      failed(d, (e as Error).message, go);
    }
  });
}

/** An app that comes with ag, uninstalled: installed again. */
export function confirmBuiltin(a: CatalogApp, asked: Asked): void {
  const go = el("button", { type: "button", class: "ap-btn primary" }, "Install") as HTMLButtonElement;
  const d = dialog(
    `Install ${a.label}?`,
    lead(a, `Install ${a.label}?`, fromLine(a)),
    el("p", { text: said.sentence(a.description) }),
    ...itCan(a),
    a.data?.there
      ? el("p", {
          class: "ap-sub",
          text: `Its data from before is still there (${kb(a.data.bytes)}), so it starts as you left it.`,
        })
      : null,
    buttons(cancel(), go),
  );
  go.addEventListener("click", async () => {
    busy(d, "Installing…", go);
    try {
      await post("/api/apps/install", { builtin: a.name });
      closeDialog();
      await asked.done(`Installed ${a.label} again.`, a.name);
    } catch (e) {
      failed(d, (e as Error).message, go);
    }
  });
}

/** Uninstall: what follows said first; its data kept unless ticked. `broken`: a folder that couldn't load. */
export function confirmUninstall(a: CatalogApp, asked: Asked, broken = false): void {
  const per = Object.entries(a.open || {}).filter(([, n]) => n),
    n = per.reduce((x, [, k]) => x + k, 0);
  const tick = el("input", { type: "checkbox", id: "ap-del-data" }) as HTMLInputElement;
  const go = el("button", { type: "button", class: "ap-btn danger" }, "Uninstall") as HTMLButtonElement;
  const d = dialog(
    `Uninstall ${a.label}?`,
    lead(a, `Uninstall ${a.label}?`, broken ? "it couldn't load" : fromLine(a)),
    el(
      "ul",
      {},
      broken
        ? el("li", { text: "It never loaded, so nothing is open and no agent has its tools." })
        : el("li", {
            text: n
              ? `Its ${n} open window${n > 1 ? "s" : ""} close (${per.map(([g, k]) => `${g} ${k}`).join(", ")}).`
              : "Nothing is open.",
          }),
      broken ? null : el("li", { text: "Agents lose its tools when they next start. Calls before then are refused." }),
      broken ? null : el("li", { text: "What it put in your history stays." }),
      a.origin === "builtin" ? el("li", { text: "It comes with ag. Reinstall it from Available to install." }) : null,
    ),
    el(
      "label",
      { class: "ap-tick", for: "ap-del-data" },
      tick,
      "Also delete its data ",
      el("span", {
        class: "mono ap-quiet",
        text: a.data ? `${a.data.path}${a.data.there ? ` · ${kb(a.data.bytes)}` : ""}` : "",
      }),
    ),
    buttons(cancel(), go),
  );
  go.addEventListener("click", async () => {
    busy(d, "Uninstalling…", go);
    try {
      await post("/api/apps/uninstall", { name: a.name, data: tick.checked });
      closeDialog();
      await asked.done(
        `Uninstalled ${a.label}. ${tick.checked ? "Its data was deleted." : `Its data is kept in ${a.data?.path || "its folder"}.`}`,
        null,
      );
    } catch (e) {
      failed(d, (e as Error).message, go);
    }
  });
}

/** Update (an app from git with a newer commit): fetched and checked first, then only what changes is said. */
export async function stageUpdate(a: CatalogApp, asked: Asked): Promise<void> {
  const go = el("button", { type: "button", class: "ap-btn primary" }, "Update") as HTMLButtonElement;
  go.disabled = true;
  const d = dialog(`Update ${a.label}`, lead(a, `Update ${a.label}`, fromLine(a)), buttons(cancel(), go));
  busy(d, "Fetching the latest commit…", go);
  let st: Staged;
  try {
    st = await post<Staged>("/api/apps/stage", { source: a.source });
  } catch (e) {
    return failed(d, `Can't update it. ${(e as Error).message}`);
  }
  if (!open.dim) return void post("/api/apps/discard", { id: st.id }).catch(() => {});
  open.staged = st.id;
  const ch = st.changes;
  const lines = [
    ...(ch?.tools_added || []).map((t) => `New tool: ${t}`),
    ...(ch?.tools_gone || []).map((t) => `Removed tool: ${t}`),
    ...(ch?.can_added || []).map((c) => `New permission: ${c}`),
    ...(ch?.own_process ? ["Now runs its own process on this computer"] : []),
  ];
  const v = ch ? ch.version.join(" → ") : st.version || "";
  dialog(
    `Update ${a.label}?`,
    lead(st, `Update ${a.label} to ${st.version}?`, `${v}${st.commit ? ` · ${st.commit.slice(0, 7)}` : ""}`),
    el("h3", { text: "What changes" }),
    el("ul", {}, ...(lines.length ? lines : ["Only its code changes."]).map((t) => el("li", { text: t }))),
    el("p", {
      class: "ap-sub",
      text: "The app restarts and its windows reload. Agents get new tools when they next start.",
    }),
    buttons(cancel(), go),
  );
  go.disabled = false;
  const d2 = open.dim!.firstElementChild as HTMLElement;
  go.addEventListener("click", async () => {
    busy(d2, "Updating…", go);
    try {
      await post("/api/apps/install", { id: st.id, update: true });
      open.staged = "";
      closeDialog();
      await asked.done(`Updated ${a.label} to ${st.version}.`, a.name);
    } catch (e) {
      failed(d2, (e as Error).message, go);
    }
  });
}

/** An agent's asking to install, update or uninstall an app (ag_dashboard/app_requests.py), as the home lists them. */
export interface AgentRequest {
  id: string;
  actor: string;
  op: "install" | "update" | "uninstall";
  about: CatalogApp;
  args?: { data?: boolean };
}
const answered = new Set<string>();

/** The first request waiting that this page hasn't shown yet, shown -- unless a dialog is open: the next one then, once
 * it is closed (the page calls this as its home is read again). `who`: how the page names an actor. `done`: told after
 * an answer, the apps read again. */
export function askedByAgent(requests: AgentRequest[], who: (actor: string) => string, done: () => void): void {
  if (open.dim) return;
  const r = (requests || []).find((x) => !answered.has(x.id));
  if (!r) return;
  answered.add(r.id);
  const a = r.about || ({ name: "?", label: "an app", origin: "" } as CatalogApp);
  const verb = { install: "install", update: "update", uninstall: "uninstall" }[r.op] || r.op;
  const yes = el(
    "button",
    { type: "button", class: `ap-btn ${r.op === "uninstall" ? "danger" : "primary"}` },
    verb[0].toUpperCase() + verb.slice(1),
  ) as HTMLButtonElement;
  const no = el("button", { type: "button", class: "ap-btn" }, "Decline") as HTMLButtonElement;
  const title = `${who(r.actor)} asks to ${verb} ${a.label}`;
  const d = dialog(
    title,
    lead(a, title, fromLine(a)),
    el("p", { text: said.sentence(a.description || "") }),
    ...(r.op === "uninstall" ? [] : itCan(a)),
    r.op === "uninstall"
      ? el("p", {
          text: `Its windows close, and agents lose its tools when their terminal next starts.${r.args?.data ? " Its data is deleted too." : ""}`,
        })
      : el("div", {
          class: "ap-warn",
          text: "Apps run on your computer with your permissions. Only approve apps you trust.",
        }),
    buttons(no, yes),
  );
  const answer = async (approve: boolean) => {
    const doing = { install: "Installing…", update: "Updating…", uninstall: "Uninstalling…" }[r.op] || "…";
    busy(d, approve ? doing : "Declining…", approve ? yes : no);
    try {
      await post(`/api/apps/requests/${encodeURIComponent(r.id)}`, { approve });
      closeDialog();
      done();
    } catch (e) {
      failed(d, (e as Error).message, approve ? yes : no);
    }
  };
  yes.addEventListener("click", () => void answer(true));
  no.addEventListener("click", () => void answer(false));
}

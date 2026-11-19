// THE APPS PAGE (app_kit/DESIGN.md, "Apps from outside"; ag_dashboard/app_catalog.py): a screen tab's page, in place of
// its new-tab page (layout/tabs.ts's `page`). Every app installed -- each on in every group, there being no turning one
// off in a group -- with what it gives agents and costs them, where it came from and its windows open; the apps that can
// be installed (ag's index, and those that come with ag, uninstalled); the folders that couldn't load. A row clicked
// shows its details beside the list; its ⋯ opens it, updates it (one from git) or uninstalls it. Installing, updating
// and uninstalling are each asked in a dialog first (catalog-dialogs.ts). What it asks of the page around it
// (src/features/apps/apps-page.js): an app opened, and the apps installed changed.
import { get, post } from "../../core/api/client";
import { glyph } from "../../core/ui/glyphs";
import "./catalog.css";
import { closeDialog, confirmBuiltin, confirmUninstall, fromSource, stageUpdate, type Asked } from "./catalog-dialogs";
import { onTaskChoice, type OnTask } from "./catalog-on-task";
import { el, kb, markOf, meta, said, tokens, whoGets, windows } from "./catalog-parts";

export interface CatalogApp {
  name: string;
  label: string;
  version?: string;
  description: string;
  mark?: boolean;
  /** where it is: "builtin" (comes with ag), "home" (installed), "path" (AG_APPS_PATH), "index", "staged" */
  origin: string;
  kind?: string;
  source?: string;
  commit?: string;
  /** who may use its instances: "task" (the agents in its task) or "group" (every agent of the group) */
  access?: string;
  /** it can be opened with an agent of its own (its manifest's [agent] offered) */
  with_agent?: boolean;
  /** opened, it starts with an agent of its own: the reader's choice here (app_settings.py), yes until they say not */
  opens_with_agent?: boolean;
  /** what "+" on an actor or a task does with it ("join", "folder", "no": ag_dashboard/app_policy.py), as chosen; its
   * manifest's own; and those it can take (a group app: not "join") */
  on_task?: OnTask;
  on_task_own?: OnTask;
  on_task_can?: OnTask[];
  instances?: string;
  tools?: string[];
  tokens?: number;
  can?: string[];
  own_process?: boolean;
  schedules?: string[];
  open?: Record<string, number>;
  data?: { path: string; bytes: number; there: boolean };
  failed?: string | null;
  needs?: string;
}
export interface Broken {
  folder: string;
  name: string;
  error: string;
  origin: string;
}
export interface Catalog {
  installed: CatalogApp[];
  available: CatalogApp[];
  broken: Broken[];
  /** the apps the server found added, gone or changed as it read their folders again for this */
  found?: { added: string[]; gone: string[]; changed: string[] };
}
/** What the page around it gives it. */
export interface PageHooks {
  /** The app opened where things start (a new tab, in its group). */
  open: (app: CatalogApp, withAgent?: boolean) => Promise<void>;
  /** The apps installed changed: the page reads them again, closes the panels of those gone. */
  changed: () => Promise<void>;
  /** A folder shown in the computer's file manager. */
  reveal?: (folder: string) => void;
}

const page = {
  box: null as HTMLElement | null,
  hooks: null as PageHooks | null,
  got: null as Catalog | null,
  error: "",
  note: "",
  sel: null as string | null,
  q: "",
  allTools: false,
  updates: {} as Record<string, string>,
  flash: "",
};

/** The page drawn into `box` (the work area's box for a tab showing nothing), its apps read again. */
export function draw(box: HTMLElement, hooks: PageHooks): void {
  const again = page.box === box;
  Object.assign(page, { box, hooks });
  box.classList.add("ap");
  if (!again) Object.assign(page, { q: "", sel: null, note: "", allTools: false });
  render();
  void reload(true);
}

/** The apps read again (`updates`: each app from git asked whether it has a newer commit, once read). */
async function reload(updates = false): Promise<void> {
  try {
    page.got = await get<Catalog>("/api/apps/catalog"); // (the server reads the app folders again for it)
    page.error = "";
    const f = page.got.found;
    if (f && f.added.length + f.gone.length + f.changed.length) await page.hooks?.changed(); // the page's own list too
  } catch (e) {
    page.error = `Couldn't load apps: ${(e as Error).message}`;
  }
  render();
  if (updates && page.got?.installed.some((a) => a.kind === "git"))
    void get<{ updates: Record<string, string> }>("/api/apps/updates")
      .then((u) => {
        page.updates = u.updates || {};
        render();
      })
      .catch(() => {});
}

/** After an install, update or uninstall: the page around told, the apps read again, `note` said at the top. */
async function done(note: string, sel: string | null): Promise<void> {
  page.note = note;
  page.sel = sel;
  page.flash = sel || "";
  if (sel) delete page.updates[sel]; // (updated: asked again below)
  await page.hooks?.changed();
  await reload(true);
}
const asked: Asked = { done, reload: () => reload() };

function render(): void {
  const box = page.box;
  if (!box || !box.isConnected || !box.classList.contains("ap")) return;
  const main = box.querySelector<HTMLElement>(".ap-main"),
    scroll = main ? main.scrollTop : 0,
    was = document.activeElement,
    typing = was instanceof HTMLInputElement && was.classList.contains("ap-search") ? was : null;
  const sel = page.sel ? page.got?.installed.find((a) => a.name === page.sel) || null : null;
  box.replaceChildren(
    el("div", { class: "ap-page" }, el("div", { class: "ap-main" }, ...head(), ...body()), sel ? details(sel) : null),
  );
  const m = box.querySelector<HTMLElement>(".ap-main");
  if (m) m.scrollTop = scroll;
  if (typing) {
    const s = box.querySelector<HTMLInputElement>(".ap-search")!;
    s.focus();
    s.setSelectionRange(typing.selectionStart, typing.selectionEnd); // where the caret was, not at the end
  }
  page.flash = "";
}

function head(): HTMLElement[] {
  const search = el("input", {
    class: "ap-search",
    type: "search",
    placeholder: "Search apps and their tools",
    "aria-label": "Search apps",
    value: page.q,
  }) as HTMLInputElement;
  search.addEventListener("input", (ev) => {
    page.q = search.value;
    if ((ev as InputEvent).isComposing) return; // a word being composed (an input method): drawn once it is done
    render();
  });
  search.addEventListener("compositionend", () => render());
  return [
    el(
      "div",
      { class: "ap-head" },
      el("h1", { text: "Apps" }),
      search,
      el(
        "button",
        { type: "button", class: "ap-btn", onclick: () => fromSource(asked) },
        "+ Install from a folder or git URL…",
      ),
    ),
    el("p", {
      class: "ap-lede",
      text: "Installed apps are on in every folder. Agents get new tools when they next start.",
    }),
    page.note ? el("div", { class: "ap-note", role: "status" }, page.note) : null,
    page.error ? el("div", { class: "ap-error", role: "alert" }, page.error) : null,
  ].filter((x): x is HTMLElement => !!x);
}

const matches = (a: { name: string; label?: string; description?: string; tools?: string[] }): boolean =>
  !page.q ||
  [a.name, a.label, a.description, ...(a.tools || [])].join(" ").toLowerCase().includes(page.q.toLowerCase());

function body(): HTMLElement[] {
  const got = page.got;
  if (!got) return page.error ? [] : [el("p", { class: "ap-quiet", text: "Loading apps…" })];
  const inst = got.installed.filter(matches),
    av = got.available.filter(matches),
    br = got.broken.filter(matches);
  if (page.q && !inst.length && !av.length && !br.length)
    return [el("p", { class: "ap-quiet", text: `No app matches “${page.q}”.` })];
  const out: HTMLElement[] = [];
  if (inst.length || !page.q)
    out.push(
      ...section("Installed", inst.length, inst.map(installedRow), "No app is installed.", "on in every folder"),
    );
  if (av.length || !page.q)
    out.push(...section("Available to install", av.length, av.map(availableRow), "Nothing else to install yet."));
  if (br.length) out.push(...section("Couldn't load", br.length, br.map(brokenRow), ""));
  return out;
}

function section(title: string, n: number, rows: HTMLElement[], none: string, hint = ""): HTMLElement[] {
  return [
    el(
      "div",
      { class: "ap-sec" },
      el("span", { text: title }),
      el("span", { class: "n", text: String(n) }),
      hint ? el("span", { class: "hint", text: hint }) : null,
    ),
    el("div", { class: "ap-rows" }, ...(rows.length ? rows : [el("div", { class: "ap-none", text: none })])),
  ];
}

function badges(a: CatalogApp): HTMLElement[] {
  const out = [
    el("span", { class: `ap-badge ${a.origin === "home" && a.kind === "git" ? "git" : ""}`, text: said.where(a) }),
  ];
  const n = windows(a);
  if (n) out.push(el("span", { class: "ap-badge open", text: `${n} open` }));
  if (page.updates[a.name]) out.push(el("span", { class: "ap-badge upd", text: "update" }));
  if (a.failed) out.push(el("span", { class: "ap-badge bad", text: "failed to start" }));
  return out;
}

function installedRow(a: CatalogApp): HTMLElement {
  const row = el(
    "div",
    {
      class: `ap-row${page.sel === a.name ? " sel" : ""}${page.flash === a.name ? " flash" : ""}`,
      tabindex: "0",
      "data-app": a.name,
      onclick: () => select(a.name),
      onkeydown: (ev: KeyboardEvent) => {
        if (ev.target === row && (ev.key === "Enter" || ev.key === " ")) {
          ev.preventDefault();
          select(a.name);
        }
      },
    },
    markOf(a, 30),
    el(
      "div",
      { class: "ap-txt" },
      el("div", { class: "ap-t1" }, el("span", { class: "ap-name", text: a.label }), ...badges(a)),
      el("div", { class: "ap-desc", text: a.description }),
      meta([
        whoGets(a),
        said.count((a.tools || []).length, "tool"),
        tokens(a.tokens || 0, "per agent"),
        (a.schedules || []).length ? "runs on a schedule" : null,
      ]),
    ),
    moreButton(a),
  );
  return row;
}

function availableRow(a: CatalogApp): HTMLElement {
  const install = (): void =>
    a.origin === "builtin" ? confirmBuiltin(a, asked) : void fromSource(asked, a.source || "", true);
  return el(
    "div",
    { class: "ap-row", "data-app": a.name, onclick: install },
    markOf(a, 30),
    el(
      "div",
      { class: "ap-txt" },
      el(
        "div",
        { class: "ap-t1" },
        el("span", { class: "ap-name", text: a.label }),
        el("span", { class: "ap-badge", text: said.where(a) }),
      ),
      el("div", { class: "ap-desc", text: a.description }),
      meta([
        a.origin === "builtin" ? "comes with ag" : "ag's index",
        a.tools ? said.count(a.tools.length, "tool") : null,
        a.tokens ? tokens(a.tokens, "per agent") : null,
        a.needs || null,
      ]),
    ),
    el(
      "button",
      {
        type: "button",
        class: "ap-btn",
        "data-install": a.name,
        onclick: (ev: Event) => (ev.stopPropagation(), install()),
      },
      "Install",
    ),
  );
}

function brokenRow(b: Broken): HTMLElement {
  const gone: CatalogApp = {
    name: b.name,
    label: b.name,
    description: "",
    origin: b.origin,
    data: { path: b.folder, bytes: 0, there: false },
  };
  return el(
    "div",
    { class: "ap-row broken" },
    el("span", { class: "ap-mark bad", "aria-hidden": "true", text: "!" }),
    el(
      "div",
      { class: "ap-txt" },
      el("div", { class: "ap-t1" }, el("span", { class: "ap-name", text: b.name })),
      el("div", { class: "ap-desc err", text: b.error }),
      meta([el("span", { class: "mono", text: b.folder })]),
    ),
    page.hooks?.reveal
      ? el(
          "button",
          { type: "button", class: "ap-btn ghost", onclick: () => page.hooks!.reveal!(b.folder) },
          "Show folder",
        )
      : null,
    b.origin === "home"
      ? el(
          "button",
          { type: "button", class: "ap-btn ghost", onclick: () => confirmUninstall(gone, asked, true) },
          "Uninstall…",
        )
      : null,
  );
}

// its ⋯: Open (the way chosen in its details: with an agent of its own, or on its own), Details, Update (one from git
// with a newer commit), Uninstall
function moreButton(a: CatalogApp): HTMLElement {
  const b = el("button", {
    type: "button",
    class: "ap-more",
    "aria-haspopup": "menu",
    "aria-expanded": "false",
    "aria-label": `More for ${a.label}`,
    text: "⋯",
  });
  b.addEventListener("click", (ev) => {
    ev.stopPropagation();
    if (b.getAttribute("aria-expanded") === "true") return closeMenu();
    menu(b, [
      ["Open", () => open(a, !!a.opens_with_agent)],
      ["Details", () => select(a.name, true)],
      ...(page.updates[a.name] ? ([["Update…", () => void stageUpdate(a, asked)]] as [string, () => void][]) : []),
      ["Uninstall…", () => confirmUninstall(a, asked)],
    ]);
  });
  return b;
}

let menuEl: HTMLElement | null = null;
function closeMenu(): void {
  menuEl?.remove();
  menuEl = null;
  page.box?.querySelectorAll('.ap-more[aria-expanded="true"]').forEach((x) => x.setAttribute("aria-expanded", "false"));
}
function menu(anchor: HTMLElement, items: [string, () => void][]): void {
  closeMenu();
  const host = page.box!.querySelector<HTMLElement>(".ap-page")!,
    r = anchor.getBoundingClientRect(),
    hr = host.getBoundingClientRect();
  menuEl = el(
    "div",
    { class: "ap-menu", role: "menu" },
    ...items.map(([label, run]) =>
      el("button", { type: "button", role: "menuitem", class: "ap-it", onclick: () => (closeMenu(), run()) }, label),
    ),
  );
  host.append(menuEl);
  menuEl.style.top = `${r.bottom - hr.top + 4}px`;
  menuEl.style.left = `${Math.max(6, r.right - hr.left - menuEl.offsetWidth)}px`;
  anchor.setAttribute("aria-expanded", "true");
  menuEl.querySelector<HTMLElement>("button")?.focus();
}
document.addEventListener("click", (ev) => {
  if (menuEl && !menuEl.contains(ev.target as globalThis.Node)) closeMenu();
});
document.addEventListener("keydown", (ev) => {
  if (ev.key !== "Escape" || !page.box?.isConnected || !page.box.classList.contains("ap")) return;
  if (closeDialog()) return;
  if (menuEl) return closeMenu();
  if (page.sel) select(null);
});

function select(name: string | null, keep = false): void {
  page.sel = keep || page.sel !== name ? name : null;
  page.allTools = false;
  render();
}

function open(a: CatalogApp, withAgent = false): void {
  const hooks = page.hooks;
  if (!hooks) return;
  page.note = withAgent ? `Opening ${a.label} with an agent…` : `Opening ${a.label}…`;
  render();
  hooks
    .open(a, withAgent)
    .then(() => (page.note = ""))
    .catch((e: Error) => (page.note = `${a.label} couldn't be opened: ${e.message}`))
    .finally(render);
}

// HOW IT OPENS, for an app that can have an agent of its own: with one (a new actor attached to it) or on its own -- the
// way every place opens it (a group's "+ ⋯" menu, a new tab's "Or open", Open here), each listing it once. Kept by the
// server (app_settings.py), so every page reads the same; the page around told, for its menus.
function opensWith(a: CatalogApp): HTMLElement {
  const pick = (agent: boolean, label: string) =>
    el(
      "button",
      {
        type: "button",
        class: "ap-seg-b",
        "aria-pressed": String(!!a.opens_with_agent === agent),
        onclick: () => void choose(a, agent),
      },
      label,
    );
  return el(
    "div",
    { class: "ap-opens" },
    el("span", { class: "ap-opens-l", text: "Opens" }),
    el(
      "div",
      { class: "ap-seg", role: "group", "aria-label": `How ${a.label} opens` },
      pick(true, "With its own agent"),
      pick(false, "On its own"),
    ),
  );
}
async function choose(a: CatalogApp, agent: boolean): Promise<void> {
  if (!!a.opens_with_agent === agent) return;
  try {
    await post("/api/apps/settings", { app: a.name, agent });
    a.opens_with_agent = agent;
    render();
    await page.hooks?.changed();
  } catch (e) {
    page.note = `${a.label}: ${(e as Error).message}`;
    render();
  }
}

// ITS DETAILS, beside the list: what agents get, what it may do, when it works on its own, its windows, its data
function details(a: CatalogApp): HTMLElement {
  const tools = page.allTools ? a.tools || [] : (a.tools || []).slice(0, 5),
    more = (a.tools || []).length - 5;
  const art = /^[aeiou]/i.test(a.label) ? "an" : "a";
  const openNow = Object.entries(a.open || {}).filter(([, n]) => n);
  return el(
    "aside",
    { class: "ap-side", "aria-label": `${a.label}'s details` },
    el(
      "div",
      { class: "ap-dtop" },
      markOf(a, 38),
      el("div", {}, el("h2", { text: a.label }), el("div", { class: "ap-sub", text: said.from(a) })),
      el(
        "button",
        { type: "button", class: "ap-close", "aria-label": "Close details", onclick: () => select(null) },
        glyph("x", 16),
      ),
    ),
    el("p", { text: said.sentence(a.description) }),
    a.failed ? el("p", { class: "err", text: `Backend failed to start: ${a.failed}` }) : null,
    el(
      "div",
      { class: "ap-acts" },
      el(
        "button",
        { type: "button", class: "ap-btn primary", onclick: () => open(a, !!a.opens_with_agent) },
        a.instances === "one" ? `Open ${a.label}` : `Open ${art} ${a.label}`,
      ),
    ),
    a.with_agent ? opensWith(a) : null,
    onTaskChoice(a, (note) => {
      page.note = note;
      render();
      void page.hooks?.changed(); // (its "+" menus read the apps again)
    }),
    el("h3", { text: "What agents get" }),
    el(
      "div",
      { class: "ap-kv" },
      el("span", { text: "Who" }),
      el("span", { text: a.access === "group" ? "every agent of the group" : `only the agents in its task` }),
      el("span", { text: "Tools" }),
      el("span", {}, `${(a.tools || []).length}, `, tokens(a.tokens || 0, "per agent")),
    ),
    el(
      "div",
      { class: "ap-tools" },
      ...tools.map((t) => el("code", { text: t })),
      more > 0
        ? el(
            "button",
            { type: "button", onclick: () => ((page.allTools = !page.allTools), render()) },
            page.allTools ? "fewer" : `+${more}`,
          )
        : null,
    ),
    el("h3", { text: "What it can do" }),
    el("ul", {}, ...said.can(a).map((c) => el("li", { text: c }))),
    (a.schedules || []).length ? el("h3", { text: "Schedule" }) : null,
    (a.schedules || []).length
      ? el("ul", {}, ...(a.schedules || []).map((s) => el("li", { text: said.sentence(s) })))
      : null,
    el("h3", { text: "Open now" }),
    openNow.length
      ? el(
          "div",
          { class: "ap-kv" },
          ...openNow.flatMap(([g, n]) => [el("span", { text: g }), el("span", { text: `${n} open` })]),
        )
      : el("p", { class: "ap-quiet", text: "Nothing open." }),
    el("h3", { text: "Data" }),
    el(
      "div",
      { class: "mono" },
      a.data ? `${a.data.path}${a.data.there ? ` · ${kb(a.data.bytes)}` : " (none yet)"}` : "—",
    ),
    el(
      "div",
      { class: "ap-foot" },
      page.updates[a.name]
        ? el(
            "button",
            { type: "button", class: "ap-btn primary", onclick: () => void stageUpdate(a, asked) },
            "Update…",
          )
        : el("span", { class: "ap-quiet", text: said.upToDate(a) }),
      el("button", { type: "button", class: "ap-btn", onclick: () => confirmUninstall(a, asked) }, "Uninstall…"),
    ),
  );
}

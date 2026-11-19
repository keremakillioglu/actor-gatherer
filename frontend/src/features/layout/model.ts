// The work area's layout as one value (ag_dashboard/DESIGN.md, A6: "the layout slice"): its screen tabs, the tab shown,
// and what each task was left with -- what the old page kept in its panes and three browser keys, and the tabs and task
// trees kept in three more, each side copying the other (a tab learning its tasks from what was shown). Here the tab
// shown's tasks ARE what is shown: every change is a function of the layout before it (and what is asked), and the
// panes are made to match it. Pure: no DOM, no storage, no clock but `now` given.
//
// Step 1 of 4: the model and its rules, as tabs.ts and the old page's rememberTask have them, with the migration from
// the six keys. Not wired yet.
import type { Cell } from "./tab-map";
import type { Node } from "./tree";

export interface Tab {
  id: string;
  name: string;
  /** the tasks it shows, in order (the tab shown: what the work area shows) */
  tasks: string[];
  /** how its tasks' blocks are arranged (blocks.ts); null: as they come */
  screen: Node | null;
  /** the task in focus */
  focus: string | null;
  /** what its new-tab page's message box holds (a tab showing nothing) */
  draft?: string;
  /** a page of the dashboard's it shows in place of its new-tab page, holding no task: "apps" */
  page?: string;
  /** its panels as they were last laid out, for its map on the bar (tab-map.ts) */
  map?: Cell[];
}

export interface TaskTab {
  id: string;
  name: string;
  tree: Node;
}

/** What a task was left with, to open it again as it was (panes.js's rememberTask) -- and whatever else an older page
 * kept there (the widths it had: work.ts makes a first arrangement from them). */
export interface Left {
  /** its actors' panes open, by channel, in order */
  actors: string[];
  /** its apps' panels open */
  apps: { app: string; id: string }[];
  /** the actor in focus, and the app selected in it */
  focus: string | null;
  focusApp: string | null;
  /** each actor pane's view */
  views: Record<string, string>;
  /** the actor whose pane its × closed: opened out of sight if no other is open */
  shut: string | null;
  at?: number;
  [older: string]: unknown;
}

/** A task's record: what it was left with (none: never left), its panels' arrangement, and its own tabs (tasks.ts). */
export interface TaskLayout {
  left?: Left;
  tree?: Node;
  tabs?: TaskTab[];
  tab?: string;
  at: number;
}

/** The page's panes as it last showed them (panes.js's savePanes): the actor in its own pane, the others beside, the one
 * in focus, each one's size and view -- opened again at a reload once the home is known. */
export interface PanesKept {
  here: [string, string] | null;
  size?: number;
  focus?: number;
  others: { g: string; c: string; view?: string; size?: number }[];
}
/** The apps' panels the page last showed above its panes (saveAppPanes), opened again once the apps are known. */
export interface AppKept {
  app: string;
  instance: string;
  g: string;
  size?: number;
}

export interface Layout {
  tabs: Tab[];
  current: string;
  tasks: Record<string, TaskLayout>;
  panes?: PanesKept;
  apps?: AppKept[];
}

export const KEY = "ag-dashboard-layout";
export const TASKS_KEPT = 200;
let made = 0;
export const newTabId = (): string => `t${Date.now().toString(36)}${(made++).toString(36)}`;

/** A tab that holds something: tasks, a name, a draft or a page. One that holds nothing is not kept once left. */
export const holds = (t: Tab): boolean => t.tasks.length > 0 || !!t.name || !!t.draft || !!t.page;

export function empty(id = newTabId()): Layout {
  return { tabs: [{ id, name: "", tasks: [], screen: null, focus: null }], current: id, tasks: {} };
}

export const shownTab = (l: Layout): Tab => l.tabs.find((t) => t.id === l.current) ?? l.tabs[0];
/** What the work area shows: the tab shown's tasks. */
export const shown = (l: Layout): string[] => shownTab(l).tasks;

/** The tab holding `task`: its number (from 1), and whether it is the tab shown. */
export function where(l: Layout, task: string): { n: number; here: boolean } | null {
  const at = l.tabs.findIndex((t) => t.tasks.includes(task));
  return at < 0 ? null : { n: at + 1, here: l.tabs[at].id === l.current };
}

const withTab = (l: Layout, id: string, f: (t: Tab) => Tab): Layout => ({
  ...l,
  tabs: l.tabs.map((t) => (t.id === id ? f(t) : t)),
});
// the tab shown left: none of its tasks in another tab now (one left with none, dropped, unless it holds something
// else); then, once another is shown, the tab left (`left`) dropped too if it holds nothing
const leaving = (l: Layout): Layout => {
  const here = shownTab(l).tasks;
  const tabs = l.tabs
    .map((t) => (t.id === l.current ? t : { ...t, tasks: t.tasks.filter((k) => !here.includes(k)) }))
    .filter((t) => t.id === l.current || holds(t));
  return { ...l, tabs };
};
const dropping = (l: Layout, left: string): Layout => ({
  ...l,
  tabs: l.tabs.filter((t) => t.id !== left || t.id === l.current || holds(t)),
});

/** A new tab after the tab shown, shown; the one left dropped if it holds nothing. */
export function fresh(was: Layout, id = newTabId()): Layout {
  const l = leaving(was);
  const at = l.tabs.findIndex((t) => t.id === l.current);
  const tabs = [...l.tabs];
  tabs.splice(at + 1, 0, { id, name: "", tasks: [], screen: null, focus: null });
  return dropping({ ...l, tabs, current: id }, l.current);
}

/** Tab `id` shown, `focus` its task in focus (none: as it was left); the tab left dropped if it holds nothing. */
export function show(was: Layout, id: string, focus: string | null = null): Layout {
  if (id === was.current || !was.tabs.some((t) => t.id === id)) return was;
  const l = leaving(was);
  if (!l.tabs.some((t) => t.id === id)) return l; // (emptied by it)
  const shownNow = withTab(l, id, (t) => (focus ? { ...t, focus } : t));
  return dropping({ ...shownNow, current: id }, l.current);
}

/** Where a plain click in the list on `task` goes: "here" (in the tab shown: put in focus), another tab shown, or a new
 * tab -- unless the tab shown shows nothing (or, `idle`, only what the page opened on by itself; or, `fill`, its new-tab
 * page is opening something), when the task goes in it. */
export function route(
  l: Layout,
  task: string,
  opts: { idle?: boolean; fill?: boolean; id?: string } = {},
): { layout: Layout; go: "here" | "tab" | "fresh" | "in" } {
  const tab = shownTab(l);
  if (tab.tasks.includes(task)) return { layout: l, go: "here" };
  const holding = l.tabs.find((t) => t.id !== l.current && t.tasks.includes(task));
  if (holding) return { layout: show(l, holding.id, task), go: "tab" };
  if (tab.page || ((tab.tasks.length || (tab.draft && !opts.fill)) && !opts.idle))
    return { layout: fresh(l, opts.id), go: "fresh" };
  return { layout: l, go: "in" };
}

/** `route`'s layout alone (for shadow.ts). */
export const routed = (l: Layout, task: string, opts: { idle?: boolean; fill?: boolean; id?: string }): Layout =>
  route(l, task, opts).layout;

/** Task `task` opened in the tab shown: with the others (`beside`), or in their place; in focus either way. */
export function open(l: Layout, task: string, beside = false): Layout {
  return withTab(l, l.current, (t) => ({
    ...t,
    tasks: beside ? (t.tasks.includes(task) ? t.tasks : [...t.tasks, task]) : [task],
    focus: task,
    page: undefined,
  }));
}

/** A plain click on task `task` routed to the tab shown: in it already, put in focus; else shown in place of the others. */
export function pick(l: Layout, task: string): Layout {
  return shownTab(l).tasks.includes(task) ? withTab(l, l.current, (t) => ({ ...t, focus: task })) : open(l, task);
}

/** The page opening on task `task` by itself (the first actor, as the home comes): in the tab shown if it holds nothing
 * -- one left with tasks, something typed, or a page is shown as it was left (tabs.ts's start). */
export const opened = (l: Layout, task: string): Layout => (holds(shownTab(l)) ? l : open(l, task));

/** ⌥+click: the task out of every other tab (one left holding nothing, gone) -- to be the tab shown's alone once the
 * page enters it (open). */
export function take(l: Layout, task: string): Layout {
  const tabs = l.tabs
    .map((t) => (t.id === l.current ? t : { ...t, tasks: t.tasks.filter((k) => k !== task) }))
    .filter((t) => t.id === l.current || holds(t));
  return { ...l, tabs };
}

/** Tab `id` closed (not the only one): the tab shown closed, the next shown (else the one before). */
export function close(l: Layout, id: string): Layout {
  if (l.tabs.length < 2) return l;
  let out = l;
  if (id === l.current) {
    const at = l.tabs.findIndex((t) => t.id === id);
    out = { ...l, current: (l.tabs[at + 1] || l.tabs[at - 1]).id };
  }
  return { ...out, tabs: out.tabs.filter((t) => t.id !== id) };
}

/** The close key: the tab shown closed -- the only one emptied (its name, draft and page gone): a new tab again. */
export function closeShown(l: Layout): Layout {
  if (l.tabs.length > 1) return close(l, l.current);
  const tab = shownTab(l);
  if (!holds(tab)) return l;
  return withTab(l, tab.id, (t) => ({ id: t.id, name: "", tasks: [], screen: null, focus: null }));
}

/** Task `task` closed in the list: out of the tab holding it -- that tab closed if it held nothing else. */
export function closed(l: Layout, task: string): Layout {
  const tab = l.tabs.find((t) => t.tasks.includes(task));
  if (!tab) return l;
  const rest = tab.tasks.filter((k) => k !== task);
  if (!rest.length) return tab.id === l.current ? closeShown(l) : close(l, tab.id);
  return withTab(l, tab.id, (t) => ({ ...t, tasks: rest, focus: t.focus === task ? rest[0] : t.focus }));
}

/** Task `task` closed in the tab shown (its card head's ×, or moved to another tab): out of it, the tab kept. */
export function closeHere(l: Layout, task: string): Layout {
  const tab = shownTab(l);
  if (!tab.tasks.includes(task)) return l;
  const rest = tab.tasks.filter((k) => k !== task);
  return withTab(l, tab.id, (t) => ({ ...t, tasks: rest, focus: t.focus === task ? rest[0] || null : t.focus }));
}

/** Task `task` put in tab `to` (another), last -- or, none, in a new tab after the tab shown (`last`: at the end). */
export function put(l: Layout, task: string, to: string | null, last = false, id = newTabId()): Layout {
  let tabs = [...l.tabs];
  let target = to && to !== l.current ? tabs.find((t) => t.id === to) : undefined;
  if (!target) {
    target = { id, name: "", tasks: [], screen: null, focus: task };
    tabs.splice(last ? tabs.length : tabs.findIndex((t) => t.id === l.current) + 1, 0, target);
  }
  const into = target.id;
  tabs = tabs.map((t) =>
    t.id === into
      ? { ...t, tasks: [...t.tasks.filter((k) => k !== task), task], focus: t.focus || task }
      : t.id !== l.current
        ? { ...t, tasks: t.tasks.filter((k) => k !== task) }
        : t,
  );
  return { ...l, tabs };
}

/** Tab `id` (not the one shown) dropped on the work area: gone, its tasks -> to open in the tab shown. */
export function merge(l: Layout, id: string): { layout: Layout; tasks: string[] } {
  const tab = l.tabs.find((t) => t.id === id);
  if (!tab || id === l.current || !tab.tasks.length) return { layout: l, tasks: [] };
  const tabs = l.tabs.filter((t) => t.id !== id);
  const here = shownTab(l);
  return {
    layout: { ...l, tabs: tabs.map((t) => (t.id === here.id ? { ...t, tasks: [...t.tasks, ...tab.tasks] } : t)) },
    tasks: tab.tasks,
  };
}

/** `merge`'s layout alone (for shadow.ts). */
export const merged = (l: Layout, id: string): Layout => merge(l, id).layout;

/** Tab `id` put at place `at` (from 0) among the others. */
export function move(l: Layout, id: string, at: number): Layout {
  const tab = l.tabs.find((t) => t.id === id);
  if (!tab) return l;
  const order = l.tabs.filter((t) => t !== tab);
  order.splice(Math.max(0, Math.min(at, order.length)), 0, tab);
  return { ...l, tabs: order };
}

export const rename = (l: Layout, id: string, name: string): Layout => withTab(l, id, (t) => ({ ...t, name }));
/** The page's panes, and the apps' panels above them, as it shows them now (none: none beside its own pane; none). */
export const keptPanes = (l: Layout, panes: PanesKept | null): Layout => {
  const out = { ...l };
  if (panes) out.panes = panes;
  else delete out.panes;
  return out;
};
export const keptApps = (l: Layout, apps: AppKept[] | null): Layout => {
  const out = { ...l };
  if (apps && apps.length) out.apps = apps;
  else delete out.apps;
  return out;
};
/** The tab shown's arrangement, as the work area has it now. */
export const setScreen = (l: Layout, screen: Node | null): Layout => withTab(l, l.current, (t) => ({ ...t, screen }));
/** The tab shown's arrangement and the task in focus, as the page has them now. */
export const noted = (l: Layout, screen: Node | null, focus: string | null): Layout =>
  withTab(l, l.current, (t) => ({ ...t, screen, focus }));
/** Tab `id`'s map, as its panels were last laid out. */
export const mapped = (l: Layout, id: string, map: Cell[]): Layout => withTab(l, id, (t) => ({ ...t, map }));
/** The tab shown showing a page of the dashboard's in place of its new-tab page. */
export const setPage = (l: Layout, page: string): Layout => withTab(l, l.current, (t) => ({ ...t, page }));
/** What tab `id`'s new-tab page's box holds now ("": none). */
export const setDraft = (l: Layout, text: string, id = l.current): Layout =>
  withTab(l, id, (t) => {
    const rest = { ...t };
    delete rest.draft;
    return text ? { ...rest, draft: text } : rest;
  });
/** A page of the dashboard's (the Apps page): the tab showing it already, shown; else in the tab shown if it shows
 * nothing (no task, draft or page: its name aside), or in a new tab. */
export function openPage(l: Layout, page: string, id = newTabId()): Layout {
  const there = l.tabs.find((t) => t.page === page);
  if (there) return show(l, there.id);
  const tab = shownTab(l);
  const into = tab.tasks.length || tab.draft || tab.page ? fresh(l, id) : l;
  return withTab(into, into.current, (t) => ({ ...t, page }));
}

/** The task keyed `from` known as `to` now (an item joined a task, or left one): every tab, and what it was left with. */
export function rekey(l: Layout, from: string, to: string): Layout {
  if (from === to) return l;
  const swap = (k: string) => (k === from ? to : k);
  const tabs = l.tabs.map((t) => {
    const tasks = t.tasks.map(swap).filter((k, i, all) => all.indexOf(k) === i);
    return { ...t, tasks, focus: t.focus && swap(t.focus) };
  });
  const tasks = { ...l.tasks };
  if (tasks[from] && !tasks[to]) tasks[to] = tasks[from];
  delete tasks[from];
  return { ...l, tabs, tasks };
}

// task `key`'s record changed (`f`), its time now; the newest TASKS_KEPT records kept
function withTask(l: Layout, key: string, f: (t: TaskLayout) => TaskLayout, now: number): Layout {
  const tasks = { ...l.tasks, [key]: { ...f(l.tasks[key] ?? { at: now }), at: now } };
  const keys = Object.keys(tasks).sort((x, y) => tasks[y].at - tasks[x].at);
  for (const k of keys.slice(TASKS_KEPT)) delete tasks[k];
  return { ...l, tasks };
}

/** What task `key` was left with, kept. */
export const remember = (l: Layout, key: string, left: Left, now: number): Layout =>
  withTask(l, key, (t) => ({ ...t, left: { ...left, at: now } }), now);

/** Actor `c` closed from the list: out of task `key` as it was left -- not opened with it again. */
export function forgetActor(l: Layout, key: string, c: string): Layout {
  const was = l.tasks[key]?.left;
  if (!was || (!was.actors.includes(c) && was.focus !== c)) return l;
  const actors = was.actors.filter((x) => x !== c);
  const left = { ...was, actors, focus: was.focus === c ? actors[0] || null : was.focus };
  return { ...l, tasks: { ...l.tasks, [key]: { ...l.tasks[key], left } } };
}

// ---- a task's arrangement and its tabs (tasks.ts)

let tabsMade = 0;
const newTaskTabId = (): string => `k${Date.now().toString(36)}${(tabsMade++).toString(36)}`;

/** The tree of task `key`'s tab shown, as it is now. */
export const setTree = (l: Layout, key: string, tree: Node, now: number): Layout =>
  withTask(
    l,
    key,
    (t) => ({ ...t, tree, ...(t.tabs ? { tabs: t.tabs.map((x) => (x.id === t.tab ? { ...x, tree } : x)) } : {}) }),
    now,
  );
/** Task `key` shown again: its record kept among the newest. */
export const touchTask = (l: Layout, key: string, now: number): Layout =>
  l.tasks[key] ? withTask(l, key, (t) => t, now) : l;
/** Another tab of task `key`, holding `tree` -- the task's one tab so far named "Tab 1". `id`: the new tab's. */
export function addTaskTab(l: Layout, key: string, tree: Node, now: number, id = newTaskTabId()): Layout {
  return withTask(
    l,
    key,
    (t) => {
      const was = t.tree ?? tree;
      const tabs = t.tabs?.length ? t.tabs : [{ id: newTaskTabId(), name: "Tab 1", tree: was }];
      return {
        ...t,
        tree: was,
        tabs: [...tabs, { id, name: `Tab ${tabs.length + 1}`, tree }],
        tab: t.tabs?.length ? t.tab : tabs[0].id,
      };
    },
    now,
  );
}
/** Task `key`'s tab `id` shown: its tree the task's. */
export function showTaskTab(l: Layout, key: string, id: string, now: number): Layout {
  const tab = l.tasks[key]?.tabs?.find((x) => x.id === id);
  return tab ? withTask(l, key, (t) => ({ ...t, tab: id, tree: tab.tree }), now) : l;
}
/** Task `key`'s tab `id` given `tree` (the tab shown: the task's too); none, the tab closed. */
export function changeTaskTab(l: Layout, key: string, id: string, tree: Node | null): Layout {
  const t = l.tasks[key];
  if (!t?.tabs?.some((x) => x.id === id)) return l;
  if (!tree) return closeTaskTab(l, key, id);
  const tabs = t.tabs.map((x) => (x.id === id ? { ...x, tree } : x));
  return { ...l, tasks: { ...l.tasks, [key]: { ...t, tabs, ...(t.tab === id ? { tree } : {}) } } };
}
/** Task `key`'s tab `id` closed: the next shown, if it was; one tab left, the task as a task of one tab. */
export function closeTaskTab(l: Layout, key: string, id: string): Layout {
  const t = l.tasks[key];
  const at = t?.tabs ? t.tabs.findIndex((x) => x.id === id) : -1;
  if (!t?.tabs || at < 0) return l;
  const tabs = t.tabs.filter((x) => x.id !== id);
  let { tab, tree } = t;
  if (tab === id) {
    const next = tabs[at] || tabs[at - 1];
    if (next) [tab, tree] = [next.id, next.tree];
  }
  const out: TaskLayout = { ...t, tabs, tab, tree };
  if (tabs.length < 2) {
    if (tabs[0]) out.tree = tabs[0].tree;
    delete out.tabs;
    delete out.tab;
  }
  return { ...l, tasks: { ...l.tasks, [key]: out } };
}
/** Task `key`'s tab `id` named `name` (none: as it was). */
export function renameTaskTab(l: Layout, key: string, id: string, name: string): Layout {
  const t = l.tasks[key];
  if (!t?.tabs || !name.trim()) return l;
  const tabs = t.tabs.map((x) => (x.id === id ? { ...x, name: name.trim() } : x));
  return { ...l, tasks: { ...l.tasks, [key]: { ...t, tabs } } };
}

// ---- kept in this browser: one key (KEY), or, before it, the six keys of before -- read once, then dropped

/** The keys of before this file's KEY: what it holds now. */
export const OLD_KEYS = [
  "ag-dashboard-screen-tabs",
  "ag-dashboard-task-layouts-2",
  "ag-dashboard-task-trees",
  "ag-dashboard-screen",
  "ag-dashboard-panes",
  "ag-dashboard-top-apps",
];

/** The layout kept: KEY's, if readable; else made from the keys of before (migrate). */
export function load(get: (k: string) => string | null): Layout {
  const kept = read(get, KEY) as Layout | null;
  if (
    kept &&
    Array.isArray(kept.tabs) &&
    kept.tabs.length &&
    kept.tabs.every((t) => t && typeof t.id === "string" && Array.isArray(t.tasks)) &&
    typeof kept.current === "string" &&
    kept.tasks &&
    typeof kept.tasks === "object"
  )
    return {
      ...kept,
      current: kept.tabs.some((t) => t.id === kept.current) ? kept.current : kept.tabs[0].id,
    };
  return migrate(get);
}

const read = (get: (k: string) => string | null, k: string): unknown => {
  try {
    return JSON.parse(get(k) || "null");
  } catch {
    return null;
  }
};

/** The layout the six keys of before held: the screen tabs (ag-dashboard-screen-tabs, the tab shown's arrangement in
 * ag-dashboard-screen), what each task was left with (ag-dashboard-task-layouts-2) and its trees and tabs
 * (ag-dashboard-task-trees), the page's panes and the apps' panels above them (ag-dashboard-panes, -top-apps); with no
 * tabs kept, the page opens as it does on a fresh home. */
export function migrate(get: (k: string) => string | null): Layout {
  const kept = read(get, "ag-dashboard-screen-tabs") as { tabs?: Tab[]; current?: string } | null;
  const tabs = (kept?.tabs || []).filter((t) => t && typeof t.id === "string" && Array.isArray(t.tasks));
  const l: Layout = tabs.length
    ? {
        tabs: tabs.map((t) => ({
          id: t.id,
          name: t.name || "",
          tasks: t.tasks.filter((k) => typeof k === "string"),
          screen: t.screen ?? null,
          focus: t.focus ?? null,
          ...(t.draft ? { draft: t.draft } : {}),
          ...(t.page ? { page: t.page } : {}),
          ...(Array.isArray(t.map) ? { map: t.map } : {}),
        })),
        current: tabs.some((t) => t.id === kept?.current) ? (kept!.current as string) : tabs[0].id,
        tasks: {},
      }
    : empty();
  const panes = read(get, "ag-dashboard-panes") as PanesKept | null;
  if (panes && Array.isArray(panes.others)) l.panes = panes;
  const apps = read(get, "ag-dashboard-top-apps") as { apps?: AppKept[] } | null;
  if (apps && Array.isArray(apps.apps) && apps.apps.length) l.apps = apps.apps;
  const screen = read(get, "ag-dashboard-screen") as Node | null;
  const here = shownTab(l);
  if (screen && !here.screen) here.screen = screen;
  const layouts = (read(get, "ag-dashboard-task-layouts-2") || {}) as Record<string, Partial<Left>>;
  const trees = (read(get, "ag-dashboard-task-trees") || {}) as Record<
    string,
    { tree: Node; at: number; tabs?: TaskTab[]; tab?: string }
  >;
  for (const k of new Set([...Object.keys(layouts), ...Object.keys(trees)])) {
    const a = layouts[k],
      t = trees[k];
    l.tasks[k] = {
      ...(a && typeof a === "object"
        ? {
            left: {
              ...a,
              actors: Array.isArray(a.actors) ? a.actors : [],
              apps: Array.isArray(a.apps) ? a.apps : [],
              focus: (a.focus as string) ?? null,
              focusApp: (a.focusApp as string) ?? null,
              views: a.views && typeof a.views === "object" ? (a.views as Record<string, string>) : {},
              shut: (a.shut as string) ?? null,
            },
          }
        : {}),
      ...(t ? { tree: t.tree, ...(t.tabs ? { tabs: t.tabs, tab: t.tab } : {}) } : {}),
      at: Math.max(Number(a?.at) || 0, t?.at || 0),
    };
  }
  return l;
}

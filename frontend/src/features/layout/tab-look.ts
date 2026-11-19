// How a screen tab looks on the bar (tabs.ts): its name, its tasks' states (the most pressing of each one's), and its map's
// boxes, each marked by its task's state -- from the tab, its tasks now and what the page says of each.
import { cellsFor, drawnCells, type Drawn } from "./tab-map";
import type { Tab, TabsHooks } from "./tabs";

/** An item's state, as a tab marks it: `mark` one of MARKS (or "", none), `said` its word ("Waiting for you"). */
export interface State {
  mark: string;
  said: string;
}
/** The marks, the most pressing first: what waits on the reader (a question, an error, an app's notification, a turn
 * done since they looked) before what is at work (a turn, in the background). A task's mark, its items' most pressing. */
export const MARKS = ["asking", "error", "notified", "finished", "working", "background"];
/** The pages a tab can show (Tab's `page`), by the name its tab is given. */
export const PAGES: Record<string, string> = { apps: "Apps" };
const rank = (m: string): number => (MARKS.includes(m) ? MARKS.indexOf(m) : MARKS.length);
/** The most pressing of these states (none marked: the first, its word only). */
export function pressing(states: State[]): State {
  const best = states.reduce<State | null>((b, s) => (!b || rank(s.mark) < rank(b.mark) ? s : b), null);
  return best || { mark: "", said: "" };
}
/** How a tab looks on the bar: its name, whether named, its map's boxes, what its tasks say. */
export type TabLook = ReturnType<typeof tabLook>;
/** What a tab's look reads of the page (tabs.ts's TabsHooks). */
export type LookHooks = Pick<TabsHooks, "name" | "status" | "canon" | "lead" | "look">;

export function tabLook(
  t: Tab,
  tasks: string[],
  current: string,
  hooks: LookHooks,
): {
  id: string;
  page: string;
  name: string;
  given: boolean;
  on: boolean;
  map: Drawn[];
  says: string[];
} {
  const names = tasks.map((k) => hooks.name(k)).filter(Boolean);
  const said = names.length
    ? names.slice(0, 2).join(", ") + (names.length > 2 ? ` +${names.length - 2}` : "")
    : (t.page && PAGES[t.page]) || "New tab";
  // each task: its state, marked on its lead's box in the map (cellsFor gives every task a box)
  const states = new Map(tasks.map((k) => [k, pressing(hooks.status?.(k) || [])]));
  const title = (k: string): string => {
    const st = states.get(k);
    return st?.said ? `${hooks.name(k)} · ${st.said}` : hooks.name(k);
  };
  const map = drawnCells(
    cellsFor(t.map, tasks, (k) => (hooks.canon ? hooks.canon(k) : k), hooks.lead || ((k) => k)),
    (k, item) => hooks.look?.(k, item) ?? null,
    (k) => ({ mark: states.get(k)?.mark || "", title: title(k) }),
  );
  return {
    id: t.id,
    page: tasks.length ? "" : t.page || "",
    name: t.name || said,
    given: !!t.name,
    on: t.id === current,
    map,
    says: tasks.filter((k) => states.get(k)?.said).map(title),
  };
}

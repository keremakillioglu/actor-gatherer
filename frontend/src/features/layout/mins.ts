// PANES MINIMIZED (work.ts): only their message boxes, where something is above or below them -- of their task, or
// another task -- by a pane's own button, or by the bar beside them dragged past its least (place.ts's folds); panes side
// by side always together, all minimized or all whole (one minimized beside one whole would leave a blank above it):
// which are as last placed, each told as that changes; which can be.
import { leaves, mark } from "./arrange";
import { APP, isStrip, type Built } from "./build";
import { isSplit, type Node } from "./tree";

export class Mins {
  private mins = new Set<HTMLElement>(); // the panes minimized, as last placed; those that can be
  private cans = new Set<HTMLElement>();

  constructor(private readonly changed: (node: HTMLElement, on: boolean) => void) {}

  /** `built` placed: the panes minimized now, or no longer -- or able to be, or no longer -- each told (once placed), to
   * draw itself so. */
  placed(built: Built): void {
    const now = new Set([...built.minimized].map((id) => built.nodes.get(id)!)),
      can = new Set([...built.under].filter((id) => canMinId(built, id)).map((id) => built.nodes.get(id)!));
    for (const n of new Set([...now, ...this.mins, ...can, ...this.cans]))
      if (now.has(n) !== this.mins.has(n) || can.has(n) !== this.cans.has(n))
        queueMicrotask(() => this.changed(n, now.has(n)));
    this.mins = now;
    this.cans = can;
  }
  /** Whether a pane is minimized now. */
  has(node: HTMLElement): boolean {
    return this.mins.has(node);
  }
}

/** A panel's id in `built`, by its element. */
export const idOf = <N>(built: Built<N> | null, node: N): string | null =>
  [...(built?.nodes || [])].find(([, n]) => n === node)?.[0] ?? null;

/** Whether a pane can be minimized: something of its task, or another task, above or below it -- and beside it, panes
 * of tasks alone (an app there stays whole: the pane minimized would leave a blank above it). */
export function canMin<N>(built: Built<N> | null, node: N): boolean {
  const id = idOf(built, node);
  return id !== null && canMinId(built!, id);
}
const canMinId = <N>(built: Built<N>, id: string): boolean => built.under.has(id) && besides(built, id).length > 0;

// the ids of `ids` -- strips left out -- if every one is a pane of a task: not an app's, nor of no task (a terminal's)
function panesOnly<N>(built: Built<N>, ids: string[]): string[] {
  const of = ids.filter((id) => !built.strips.has(id));
  const pane = (id: string): boolean => {
    const it = built.items.get(id);
    return !!it && it.key !== null && !it.item.startsWith(APP);
  };
  return of.length && of.every(pane) ? of : [];
}

/** The panels of kid `kid` of split `key` of `built` -- one above another, in a task or among the tasks shown -- if every
 * one is a pane of a task: the panes its bar minimizes, dragged past its least (their ids in `built`). None: an app in it
 * (it stops at its least), or a panel of no task (a terminal's, kept nowhere). */
export function foldable<N>(built: Built<N> | null, key: string, kid: number): string[] {
  const s = built?.splits.get(key);
  if (!built || !s || (!s.screen && s.task === null) || s.dir !== "col" || !s.kids[kid]) return [];
  return panesOnly(built, leaves(s.kids[kid]));
}

// the panes beside pane `id` of `built`, it among them: the panels of the kid of the column it is in (a task's, or the
// tasks' own; a strip's aside) -- those its bar minimizes. None: no column it is in, or an app or a terminal's among them.
function besides<N>(built: Built<N>, id: string): string[] {
  const find = (n: Node, kid: Node | null): Node | null | undefined => {
    if (!isSplit(n)) return n.id === id ? kid : undefined;
    const col = n.dir === "col" && !isStrip(built, n);
    for (const k of n.kids) {
      const got = find(k, col ? k : kid);
      if (got !== undefined) return got;
    }
    return undefined;
  };
  const kid = built.tree ? find(built.tree, null) : null;
  return kid ? panesOnly(built, leaves(kid)) : [];
}

/** The panes minimized with pane `id` of `built` by its own button (`on`), or shown whole with it: the panes beside it --
 * and shown whole, each pane minimized beside it in a row further out too (its row whole again). */
export function together<N>(built: Built<N> | null, id: string, on: boolean): string[] {
  if (!built || !built.items.has(id)) return [];
  if (on) return besides(built, id);
  const out = new Set([id, ...besides(built, id)]);
  for (const other of built.items.keys()) if (besides(built, other).includes(id)) out.add(other);
  return [...out];
}

/** The arrangements of the tasks of panes `ids` of `built` (as kept: `tree`, by task), with those panes minimized (or
 * shown whole): by task. */
export function marked<N>(
  built: Built<N> | null,
  ids: string[],
  on: boolean,
  tree: (task: string) => Node | null,
): Map<string, Node> {
  const items = new Map<string, string[]>();
  for (const id of ids) {
    const it = built?.items.get(id);
    if (!it || it.key === null) continue;
    items.set(it.key, [...(items.get(it.key) || []), it.item]);
  }
  const out = new Map<string, Node>();
  for (const [task, of] of items) {
    const kept = tree(task);
    if (kept) out.set(task, minimized(kept, of, on));
  }
  return out;
}

/** A task's arrangement with `items` minimized (or shown whole). */
export const minimized = (tree: Node, items: string[], on: boolean): Node =>
  items.reduce((t, item) => mark(t, item, { min: on || undefined }), tree);

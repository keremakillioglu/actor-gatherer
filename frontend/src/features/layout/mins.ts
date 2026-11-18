// PANES MINIMIZED, each on its own (work.ts): only its message box, where something is above or below it -- of its task,
// or another task --
// by its own button, or by the bar beside it dragged past its least (place.ts's folds): which are as last placed, each
// told as that changes; which can be.
import { leaves, mark } from "./arrange";
import { APP, type Built } from "./build";
import type { Node } from "./tree";

export class Mins {
  private mins = new Set<HTMLElement>(); // the panes minimized, as last placed; those that can be
  private unders = new Set<HTMLElement>();

  constructor(private readonly changed: (node: HTMLElement, on: boolean) => void) {}

  /** `built` placed: the panes minimized now, or no longer -- or able to be, or no longer -- each told (once placed), to
   * draw itself so. */
  placed(built: Built): void {
    const now = new Set([...built.minimized].map((id) => built.nodes.get(id)!)),
      under = new Set([...built.under].map((id) => built.nodes.get(id)!));
    for (const n of new Set([...now, ...this.mins, ...under, ...this.unders]))
      if (now.has(n) !== this.mins.has(n) || under.has(n) !== this.unders.has(n))
        queueMicrotask(() => this.changed(n, now.has(n)));
    this.mins = now;
    this.unders = under;
  }
  /** Whether a pane is minimized now. */
  has(node: HTMLElement): boolean {
    return this.mins.has(node);
  }
}

/** A panel's id in `built`, by its element. */
export const idOf = (built: Built | null, node: HTMLElement): string | null =>
  [...(built?.nodes || [])].find(([, n]) => n === node)?.[0] ?? null;

/** Whether a pane can be minimized: something of its task, or another task, above or below it. */
export function canMin(built: Built | null, node: HTMLElement): boolean {
  const id = idOf(built, node);
  return id !== null && !!built?.under.has(id);
}

/** The panels of kid `kid` of split `key` of `built` -- one above another, in a task or among the tasks shown -- if every
 * one is a pane of a task: the panes its bar minimizes, dragged past its least (their ids in `built`). None: an app in it
 * (it stops at its least), or a panel of no task (a terminal's, kept nowhere). */
export function foldable<N>(built: Built<N> | null, key: string, kid: number): string[] {
  const s = built?.splits.get(key);
  if (!built || !s || (!s.screen && s.task === null) || s.dir !== "col" || !s.kids[kid]) return [];
  const ids = leaves(s.kids[kid]).filter((id) => !built.strips.has(id));
  const pane = (id: string): boolean => {
    const it = built.items.get(id);
    return !!it && it.key !== null && !it.item.startsWith(APP);
  };
  return ids.length && ids.every(pane) ? ids : [];
}

/** The arrangements of the tasks of the panes kid `kid` of split `key` of `built` minimizes (or shows whole), as kept
 * (`tree`, by task), with them so: by task. */
export function folded<N>(
  built: Built<N> | null,
  key: string,
  kid: number,
  on: boolean,
  tree: (task: string) => Node | null,
): Map<string, Node> {
  const items = new Map<string, string[]>();
  for (const id of foldable(built, key, kid)) {
    const it = built!.items.get(id)!;
    items.set(it.key!, [...(items.get(it.key!) || []), it.item]);
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

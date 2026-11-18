// The work area's panels PLACED where its tree (tree.ts) lays them out: each at its own spot in the one box, the bars
// between them over it. A panel is never moved in the page to go elsewhere -- a frame moved is a frame loaded again, its
// actor's view drawn anew, a Browser's page with it -- only its spot changes. Placed again as the box changes size, as
// a panel as long as what it shows does, or as the page says (place). A phone's width: none placed (the tree null), the
// page's own stylesheet lays them out.
import "./place.css";
import {
  drag,
  draggable,
  even,
  evens,
  isSplit,
  lay,
  lengths,
  type Bar,
  type Laid,
  type Node,
  type Rect,
  type Size,
} from "./tree";

export interface PlaceHooks {
  /** What the work area shows, for a box this size; null: none placed. */
  tree: (box: { w: number; h: number }) => Node | null;
  /** A panel's element, by its id. */
  node: (id: string) => HTMLElement | null;
  /** A split's sizes, its bar dragged (`done`: let go) or double-clicked: the page keeps them, and places again. */
  resized: (key: string, sizes: Size[], done: boolean) => void;
  /** How far in from each side of the box the panels go (the tabs' bar over them, the well round them). */
  inset?: () => { top: number; right: number; bottom: number; left: number };
  /** A panel as tall as what it shows though its spot is not (a pane minimized beside one that is not). */
  fitted?: (id: string) => boolean;
  /** The panels placed (again): whatever is drawn round them follows. */
  placed?: () => void;
  /** Whether kid `kid` of a split can be minimized by its bar, and under what length: dragged shorter than that (past
   * its least), minimized; dragged longer again, whole. Null: it can't (an app in it). */
  folds?: (key: string, kid: number) => number | null;
  /** Kid `kid` of a split minimized (`on`), or whole again: the page keeps it, and places again. */
  fold?: (key: string, kid: number, on: boolean) => void;
}

const SPOT = ["left", "top", "width", "height", "bottom"] as const;
type Spot = Partial<Record<(typeof SPOT)[number], string>>;
const px = (n: number): string => `${n}px`;
// each style set only when it changes: placing again what has not moved is nothing to lay out
function spot(e: HTMLElement, s: Spot): void {
  for (const k of SPOT) {
    const v = s[k] ?? "";
    if (e.style[k] !== v) e.style[k] = v;
  }
}
const attr = (e: HTMLElement, name: string, v: string): void => {
  if (e.getAttribute(name) !== v) e.setAttribute(name, v);
};
const HIT = 2; // a bar is this much wider on each side than the room it takes, to be caught
const SLACK = 24; // a kid minimized by its bar: dragged this much longer than where it was minimized, whole again

export class Placer {
  private readonly bars: HTMLElement;
  private placed = new Map<string, HTMLElement>();
  private watched = new Set<HTMLElement>();
  private laid: Laid | null = null;
  private readonly sizes = new ResizeObserver(() => this.place());

  constructor(
    private readonly work: HTMLElement,
    private readonly hooks: PlaceHooks,
  ) {
    this.bars = document.createElement("div");
    this.bars.className = "lay-bars";
    work.append(this.bars);
    this.sizes.observe(work);
  }

  place(): void {
    const box = { w: this.work.clientWidth, h: this.work.clientHeight };
    const tree = this.hooks.tree(box);
    this.work.classList.toggle("placed", !!tree);
    if (!tree) {
      this.laid = null;
      for (const e of this.placed.values()) spot(e, {});
      this.placed.clear();
      this.watch(new Set());
      this.drawBars();
      this.hooks.placed?.();
      return;
    }
    const pad = this.hooks.inset ? this.hooks.inset() : { top: 0, right: 0, bottom: 0, left: 0 };
    const top = Math.min(box.h, pad.top),
      area = {
        x: pad.left,
        y: top,
        w: Math.max(0, box.w - pad.left - pad.right),
        h: Math.max(0, box.h - top - pad.bottom),
      };
    const laid = lay(tree, area, (kid, cross) => this.natural(kid, cross));
    const now = new Map<string, HTMLElement>();
    const fitted = new Set([...laid.rects.keys()].filter((id) => laid.fitted.has(id) || !!this.hooks.fitted?.(id)));
    for (const [id, r] of laid.rects) {
      const e = this.hooks.node(id);
      if (!e) continue;
      now.set(id, e);
      // a panel as long as what it shows: as tall as it is, at the bottom of its spot
      spot(
        e,
        fitted.has(id) ? { left: px(r.x), width: px(r.w), bottom: px(box.h - r.y - r.h), height: "auto" } : this.at(r),
      );
    }
    const placing = new Set(now.values()); // (a panel under another id now -- the page's own pane, another actor -- stays)
    for (const e of this.placed.values()) if (!placing.has(e)) spot(e, {});
    this.placed = now;
    this.laid = laid;
    this.watch(new Set([...fitted].map((id) => now.get(id)).filter((e): e is HTMLElement => !!e)));
    this.drawBars();
    this.hooks.placed?.();
  }

  /** Where each panel was placed last, by its id (the work area's own coordinates). */
  rects(): Map<string, Rect> {
    return this.laid ? this.laid.rects : new Map();
  }

  private at(r: Rect): Spot {
    return { left: px(r.x), top: px(r.y), width: px(r.w), height: px(r.h) };
  }

  // How long a kid sized `fit` is: what its panels show, `w` wide -- each panel as tall as it is
  private natural(n: Node, w: number): number {
    if (!isSplit(n)) {
      const e = this.hooks.node(n.id);
      if (!e) return 0;
      spot(e, { left: e.style.left, width: px(w), bottom: e.style.bottom, height: "auto" });
      return e.offsetHeight;
    }
    if (n.dir === "col") return n.kids.reduce((sum, k) => sum + this.natural(k, w), 0) + n.bar * (n.kids.length - 1);
    const ls = lengths(n, w, 0, (k, cross) => this.natural(k, cross));
    return Math.max(0, ...n.kids.map((k, i) => this.natural(k, ls[i])));
  }

  // the panels as long as what they show: placed again as that changes (the box itself always watched)
  private watch(now: Set<HTMLElement>): void {
    for (const e of this.watched) if (!now.has(e)) this.sizes.unobserve(e);
    for (const e of now) if (!this.watched.has(e)) this.sizes.observe(e);
    this.watched = now;
  }

  // The bars between the kids of each split, each where it is laid out, a little wider to be caught -- the same element
  // for the same bar while the tree keeps its shape, so one dragged stays under the pointer
  private drawBars(): void {
    const all = this.laid ? this.laid.bars : [];
    while (this.bars.children.length > all.length) this.bars.lastElementChild!.remove();
    while (this.bars.children.length < all.length) this.bars.append(this.newBar());
    all.forEach((b, i) => {
      const e = this.bars.children[i] as HTMLElement;
      const row = b.split.dir === "row",
        still = !this.drags(b),
        min = !draggable(b.split, b.at); // (beside a kid minimized: dragged to show it whole)
      attr(e, "data-split", b.split.key);
      attr(e, "data-dir", b.split.dir);
      attr(e, "aria-orientation", row ? "vertical" : "horizontal");
      attr(
        e,
        "title",
        still
          ? ""
          : min
            ? "Drag to show the chat whole"
            : `Drag to resize${evens(b.split) ? ` · double-click: all the same ${row ? "width" : "height"}` : ""}`,
      );
      e.classList.toggle("thick", !!b.split.thick);
      e.classList.toggle("gap", !!b.split.gap);
      e.classList.toggle("still", still);
      const r = b.rect;
      spot(e, this.at(row ? { ...r, x: r.x - HIT, w: r.w + 2 * HIT } : { ...r, y: r.y - HIT, h: r.h + 2 * HIT }));
    });
  }

  private barOf(e: HTMLElement) {
    const i = Array.prototype.indexOf.call(this.bars.children, e);
    return this.laid ? this.laid.bars[i] || null : null;
  }

  // Whether a bar can be dragged: one of a split's (tree.ts's draggable), or one beside a kid minimized by being dragged
  // short (folds), the other whole -- dragged to show it whole again
  private drags(b: Bar): boolean {
    if (draggable(b.split, b.at)) return true;
    const fit = [b.at, b.at + 1].filter((k) => b.split.sizes[k]?.fit);
    return !b.split.still && fit.length === 1 && this.hooks.folds?.(b.split.key, fit[0]) != null;
  }

  // A bar dragged: the split's sizes as the pointer has moved since it was pressed, told as it moves and once let go
  // -- the frames letting the pointer by meanwhile, so it goes on over them. A kid beside it that can be minimized
  // (folds), dragged shorter than it says, minimized -- its sizes as they were before the drag kept, to show it whole
  // again so; dragged longer again, whole, as long as the pointer says. Double-clicked: its kids even.
  private newBar(): HTMLElement {
    const e = document.createElement("div");
    e.className = "lay-bar";
    e.setAttribute("role", "separator");
    e.addEventListener("pointerdown", (ev) => {
      const b = this.barOf(e);
      if (!b || ev.button !== 0 || !this.drags(b)) return;
      ev.preventDefault();
      e.setPointerCapture(ev.pointerId);
      const key = b.split.key,
        at = b.at,
        row = b.split.dir === "row",
        from = row ? ev.clientX : ev.clientY,
        a0 = b.lengths[at],
        both = a0 + b.lengths[at + 1];
      // the sizes to keep if a kid is minimized: as they were when it was last whole (here, or shown whole mid-drag)
      let whole: Size[] | null = b.split.sizes.some((z) => z.fit) ? null : b.split.sizes.map((z) => ({ ...z })),
        sizes: Size[] | null = null;
      e.classList.add("on");
      this.work.dataset.resizing = b.split.dir;
      const move = (m: PointerEvent): void => {
        const a = a0 + (row ? m.clientX : m.clientY) - from,
          want = [a, both - a];
        let now = this.barOf(e);
        if (!now || now.split.key !== key) return;
        for (const k of [0, 1]) {
          const kid = at + k,
            fit = !!now.split.sizes[kid]?.fit,
            least = this.hooks.folds?.(key, kid) ?? null;
          if (least === null || !this.hooks.fold) continue;
          if (!fit && want[k] < least) {
            if (whole && sizes) this.hooks.resized(key, whole, true); // (shown whole again, as it was)
            sizes = null;
            this.hooks.fold(key, kid, true);
            return;
          }
          if (fit && want[k] >= least + SLACK) {
            this.hooks.fold(key, kid, false);
            now = this.barOf(e);
            if (!now || now.split.key !== key || now.split.sizes.some((z) => z.fit)) return;
            whole = now.split.sizes.map((z) => ({ ...z }));
          }
        }
        if (!draggable(now.split, at)) return;
        sizes = drag(now.split, at, now.lengths, a - now.lengths[at]);
        this.hooks.resized(key, sizes, false);
      };
      const up = (): void => {
        e.removeEventListener("pointermove", move);
        e.removeEventListener("pointerup", up);
        e.removeEventListener("pointercancel", up);
        e.classList.remove("on");
        delete this.work.dataset.resizing;
        if (sizes) this.hooks.resized(key, sizes, true);
      };
      e.addEventListener("pointermove", move);
      e.addEventListener("pointerup", up);
      e.addEventListener("pointercancel", up);
    });
    e.addEventListener("dblclick", () => {
      const b = this.barOf(e);
      if (b && draggable(b.split, b.at) && evens(b.split)) this.hooks.resized(b.split.key, even(b.split), true);
    });
    return e;
  }
}

/** The work area `work` placed as `hooks` say, from now on: place() again whenever what it shows changes. */
export const placer = (work: HTMLElement, hooks: PlaceHooks): Placer => new Placer(work, hooks);

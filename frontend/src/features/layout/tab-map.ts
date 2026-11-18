// A SCREEN TAB'S MAP, before its name in the tabs' bar (tabs.ts): a small picture of the tab's panels as they are laid
// out, each a box of its own -- an actor's tinted in its avatar's hue, its face in it if it has room; an app's grey, its
// mark in it -- so a tab reads as a screen of panels, never as a web page's tab (a Browser's tabs have a page's icon).
// The tab shown's map is taken from where its panels are each time they are placed (snapshot), and kept with the tab: a
// tab not shown shows the one it was left with -- or, its tasks changed since (one taken out, one put in) or none kept,
// one box for each task, side by side (cellsFor). Each task's state is marked on its lead's box (its first actor's).
import type { Rect } from "./tree";

/** A panel on a tab's map: its item (an actor's channel, an app's "app:<id>"), its task's key ("": a panel of no task,
 * a terminal's), and where it is -- shares of the map's width and height, from its top left. */
export interface Cell {
  item: string;
  key: string;
  x: number;
  y: number;
  w: number;
  h: number;
}
/** What a panel's box shows (the page says): an app's (grey, its mark) or an actor's (its hue, its face); none: grey. */
export interface CellLook {
  app?: boolean;
  hue?: string | null;
  src?: string | null;
}
/** A box as the bar draws it: where it is, what it shows, and (its task's lead's) its task's state and words. */
export interface Drawn {
  x: number;
  y: number;
  w: number;
  h: number;
  app: boolean;
  hue: string | null;
  src: string | null;
  mark: string;
  title: string;
}

// the map's inside (place.css's .lay-map, less its frame and a hair all round), in px
const IN_W = 36,
  IN_H = 20,
  FACE = 14, // a face at most, in a box
  FACE_LEAST = 7; // a box with less room shows its hue alone
const r3 = (n: number): number => Math.round(n * 1000) / 1000;

/** The tab shown's map: its panels (`items`, by their ids in the tree) where they are placed (`rects`), as shares of the
 * box round them all. */
export function snapshot(
  rects: Map<string, Rect>,
  items: Map<string, { key: string | null; item: string }> | undefined,
): Cell[] {
  const placed = [...(items || [])].flatMap(([id, it]) => {
    const r = rects.get(id);
    return r && r.w > 0 && r.h > 0 ? [{ it, r }] : [];
  });
  if (!placed.length) return [];
  const x0 = Math.min(...placed.map((p) => p.r.x)),
    y0 = Math.min(...placed.map((p) => p.r.y));
  const w = Math.max(...placed.map((p) => p.r.x + p.r.w)) - x0 || 1,
    h = Math.max(...placed.map((p) => p.r.y + p.r.h)) - y0 || 1;
  return placed.map(({ it, r }) => ({
    item: it.item,
    key: it.key ?? "",
    x: r3((r.x - x0) / w),
    y: r3((r.y - y0) / h),
    w: r3(r.w / w),
    h: r3(r.h / h),
  }));
}

/** A tab's map now: the one kept (`kept`), its tasks' keys as they are now (`canon`), if it holds just the tab's tasks
 * (`tasks`) -- else one box for each task, side by side, its lead's (`lead`: its item). */
export function cellsFor(
  kept: Cell[] | undefined,
  tasks: string[],
  canon: (key: string) => string | null,
  lead: (task: string) => string,
): Cell[] {
  const now = (kept || []).map((c) => (c.key ? { ...c, key: canon(c.key) ?? "\u0000gone" } : c));
  const keys = new Set(now.filter((c) => c.key).map((c) => c.key));
  if (now.length && keys.size === tasks.length && tasks.every((k) => keys.has(k))) return now;
  const w = 1 / Math.max(1, tasks.length);
  return tasks.map((k, i) => ({ item: lead(k), key: k, x: r3(i * w), y: 0, w: r3(w), h: 1 }));
}

/** The boxes as the bar draws them: each its look (`look`), and its task's state (`said`) on its lead's box -- the task's
 * first actor's, top left first, else its first box. */
export function drawnCells(
  cells: Cell[],
  look: (key: string, item: string) => CellLook | null,
  said: (key: string) => { mark: string; title: string },
): Drawn[] {
  const looks = cells.map((c) => look(c.key, c.item) || {});
  const order = cells.map((_, i) => i).sort((a, b) => cells[a].y - cells[b].y || cells[a].x - cells[b].x);
  const lead = new Map<string, number>();
  for (const i of order) if (cells[i].key && !lead.has(cells[i].key) && !looks[i].app) lead.set(cells[i].key, i);
  for (const i of order) if (cells[i].key && !lead.has(cells[i].key)) lead.set(cells[i].key, i);
  return cells.map((c, i) => {
    const s = lead.get(c.key) === i ? said(c.key) : { mark: "", title: "" };
    return {
      x: c.x,
      y: c.y,
      w: c.w,
      h: c.h,
      app: !!looks[i].app,
      hue: looks[i].hue || null,
      src: looks[i].src || null,
      mark: s.mark,
      title: s.title,
    };
  });
}

// a box's corners in the map, in whole px (its inside's): as drawMap draws it
function corners(c: { x: number; y: number; w: number; h: number }): number[] {
  return [c.x * IN_W, c.y * IN_H, (c.x + c.w) * IN_W, (c.y + c.h) * IN_H].map(Math.round);
}
/** Whether two maps look the same: the same panels, each box on the same pixels. */
export function sameMap(a: Cell[], b: Cell[]): boolean {
  const look = (m: Cell[]): string => JSON.stringify(m.map((c) => [c.item, c.key, ...corners(c)]));
  return look(a) === look(b);
}

/** The map drawn: each box where it is, a hair apart from the next; its face (or mark) in it if there is room; its
 * task's state marked at its corner (`mark` draws it). */
export function drawMap(cells: Drawn[], mark: (m: string) => HTMLElement): HTMLElement {
  const map = document.createElement("span");
  map.className = "lay-map";
  for (const c of cells) {
    const [x0, y0, x1, y1] = corners(c);
    const x = 1 + x0,
      y = 1 + y0,
      w = Math.max(2, x1 - x0 - 1),
      h = Math.max(2, y1 - y0 - 1);
    const box = document.createElement("span");
    box.className = c.app ? "lay-mcell app" : "lay-mcell";
    Object.assign(box.style, { left: `${x}px`, top: `${y}px`, width: `${w}px`, height: `${h}px` });
    if (c.hue) box.style.setProperty("--hue", c.hue);
    const size = Math.min(FACE, Math.min(w, h) - 2);
    if (c.src && size >= FACE_LEAST) {
      const img = document.createElement("img");
      Object.assign(img, { src: c.src, alt: "", draggable: false });
      img.style.width = img.style.height = `${size}px`;
      box.append(img);
    }
    if (c.title) box.title = c.title;
    if (c.mark) box.append(mark(c.mark));
    map.append(box);
  }
  return map;
}

/** A page's mark in its tab's map (tabs.ts's `page`): the Apps page's, four squares, one a "+". */
export function pageMark(): SVGSVGElement {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("class", "lay-page");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML =
    '<rect x="2" y="2" width="5" height="5" rx="1.2"/><rect x="9" y="2" width="5" height="5" rx="1.2"/>' +
    '<rect x="2" y="9" width="5" height="5" rx="1.2"/><path d="M11.5 9v5M9 11.5h5"/>';
  return svg;
}

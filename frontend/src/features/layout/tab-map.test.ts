// A screen tab's map (tab-map.ts): the tab shown's panels as shares of the box round them; a map kept drawn while it
// holds just the tab's tasks (by their keys now), else a box per task; each task's state on its lead's box.
import { describe, expect, it } from "vitest";
import { cellsFor, drawMap, drawnCells, sameMap, snapshot, type Cell } from "./tab-map";

const cell = (item: string, key: string, x: number, y: number, w: number, h: number): Cell => ({
  item,
  key,
  x,
  y,
  w,
  h,
});

describe("a screen tab's map", () => {
  it("the panels placed, as shares of the box round them -- a terminal's (no task) too, a panel of no size not", () => {
    const rects = new Map([
      ["l", { x: 12, y: 52, w: 300, h: 400 }],
      ["r", { x: 318, y: 52, w: 300, h: 400 }],
      ["t", { x: 12, y: 0, w: 0, h: 0 }],
      ["strip", { x: 12, y: 40, w: 606, h: 12 }], // (a card's head: not a panel)
    ]);
    const items = new Map([
      ["l", { key: "a", item: "a1" }],
      ["r", { key: null, item: "shell" }],
      ["t", { key: "a", item: "app:x" }],
    ]);
    expect(snapshot(rects, items)).toEqual([cell("a1", "a", 0, 0, 0.495, 1), cell("shell", "", 0.505, 0, 0.495, 1)]);
    expect(snapshot(rects, undefined)).toEqual([]);
  });

  it("a map kept, drawn while it holds just the tab's tasks (by their keys now); else a box per task, its lead's", () => {
    const kept = [cell("a1", "a", 0, 0, 0.5, 1), cell("b1", "b", 0.5, 0, 0.5, 1)];
    const lead = (k: string): string => `${k}*`;
    expect(cellsFor(kept, ["a", "b"], (k) => k, lead)).toEqual(kept);
    expect(cellsFor(kept, ["t1", "b"], (k) => (k === "a" ? "t1" : k), lead).map((c) => c.key)).toEqual(["t1", "b"]);
    // one taken out, one put in, one gone: a box per task
    expect(cellsFor(kept, ["a"], (k) => k, lead)).toEqual([cell("a*", "a", 0, 0, 1, 1)]);
    expect(cellsFor(kept, ["a", "b", "c"], (k) => k, lead).map((c) => [c.item, c.x, c.w])).toEqual([
      ["a*", 0, 0.333],
      ["b*", 0.333, 0.333],
      ["c*", 0.667, 0.333],
    ]);
    expect(cellsFor(kept, ["a", "b"], (k) => (k === "b" ? null : k), lead)).toHaveLength(2);
    expect(cellsFor(undefined, [], (k) => k, lead)).toEqual([]);
  });

  it("a task's state on its lead's box: its first actor's, top left first -- else its first box", () => {
    const cells = [
      cell("app:n", "a", 0, 0, 1, 0.3), // its app, above
      cell("a2", "a", 0.5, 0.3, 0.5, 0.7),
      cell("a1", "a", 0, 0.3, 0.5, 0.7),
      cell("app:m", "b", 0, 0, 1, 1), // apps alone
    ];
    const drawn = drawnCells(
      cells,
      (_k, item) => (item.startsWith("app:") ? { app: true } : { hue: "#22a55a" }),
      (k) => ({ mark: k === "a" ? "working" : "error", title: k.toUpperCase() }),
    );
    expect(drawn.map((d) => `${d.app ? "app" : d.hue}:${d.mark}:${d.title}`)).toEqual([
      "app::",
      "#22a55a::",
      "#22a55a:working:A",
      "app:error:B",
    ]);
  });

  it("a face shown in a box with room for it; a box a hair apart from the next, never less than 2px", () => {
    const d = (x: number, w: number, h = 1) => ({
      x,
      y: 0,
      w,
      h,
      app: false,
      hue: "#000",
      src: "/avatars/z.svg",
      mark: "",
      title: "",
    });
    const map = drawMap([d(0, 0.5), d(0.5, 0.2), d(0.7, 0.3, 0.01)], () => document.createElement("i"));
    const boxes = [...map.children] as HTMLElement[];
    expect(boxes.map((b) => [b.style.left, b.style.width, b.style.height])).toEqual([
      ["1px", "17px", "19px"],
      ["19px", "6px", "19px"],
      ["26px", "10px", "2px"],
    ]);
    expect(boxes.map((b) => b.querySelector("img")?.style.width ?? null)).toEqual(["14px", null, null]);
  });

  it("two maps the same while each box is on the same pixels (a bar dragged a little), its panels the same", () => {
    const a = [cell("a1", "a", 0, 0, 0.5, 1), cell("b1", "b", 0.5, 0, 0.5, 1)];
    expect(sameMap(a, [cell("a1", "a", 0, 0, 0.505, 1), cell("b1", "b", 0.505, 0, 0.495, 1)])).toBe(true);
    expect(sameMap(a, [cell("a1", "a", 0, 0, 0.6, 1), cell("b1", "b", 0.6, 0, 0.4, 1)])).toBe(false);
    expect(sameMap(a, [cell("a1", "a", 0, 0, 0.5, 1), cell("c1", "b", 0.5, 0, 0.5, 1)])).toBe(false);
    expect(sameMap([], [])).toBe(true);
  });
});

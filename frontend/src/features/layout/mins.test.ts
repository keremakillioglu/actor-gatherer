// Panes minimized by the bar beside them dragged past their least (mins.ts's foldable): a task's panes one above or below
// something of it, every panel of that kid a pane -- not an app's, nor one of the blocks' own arrangement.
import { describe, expect, it } from "vitest";
import { leaves, leafNodes } from "./arrange";
import { build, firstTree, type Shown } from "./build";
import { foldable, minimized } from "./mins";
import type { Node } from "./tree";

const at = (key: string | null, item: string): Shown<string> => ({
  key,
  item,
  node: item,
  app: item.startsWith("app:"),
});
const T = "g\u0000t1",
  U = "g\u0000t2";
const opts = { top: null, h: 900 };
const items = (built: ReturnType<typeof build<string>>, ids: string[]) => ids.map((id) => built.items.get(id)!.item);
const key = (built: ReturnType<typeof build<string>>, task: string | null, dir: string) =>
  [...built.splits.values()].find((s) => s.task === task && s.dir === dir && !s.screen)!.key;

describe("the panes a bar minimizes, dragged past their least", () => {
  it("is the panes under their task's app, side by side or alone -- never the app's row above them", () => {
    const shown = [at(T, "app:b"), at(T, "c1"), at(T, "c2")];
    const built = build(shown, {}, () => null, opts);
    const col = key(built, T, "col");
    expect(items(built, foldable(built, col, 1))).toEqual(["c1", "c2"]);
    expect(foldable(built, col, 0)).toEqual([]);
    expect(foldable(built, key(built, T, "row"), 0)).toEqual([]); // (side by side: a bar between widths)
  });

  it("is either of two panes one above the other", () => {
    const tree: Node = { key: "", dir: "col", bar: 1, kids: [{ id: "c1" }, { id: "c2" }], sizes: [{}, {}] };
    const built = build([at(T, "c1"), at(T, "c2")], { [T]: tree }, () => null, opts);
    const col = key(built, T, "col");
    expect(items(built, foldable(built, col, 0))).toEqual(["c1"]);
    expect(items(built, foldable(built, col, 1))).toEqual(["c2"]);
  });

  it("is none where an app is among them", () => {
    const tree: Node = {
      key: "",
      dir: "col",
      bar: 1,
      kids: [{ id: "app:b" }, { key: "", dir: "row", bar: 1, kids: [{ id: "c1" }, { id: "app:n" }], sizes: [{}, {}] }],
      sizes: [{ top: true }, {}],
    };
    const built = build([at(T, "app:b"), at(T, "c1"), at(T, "app:n")], { [T]: tree }, () => null, opts);
    expect(foldable(built, key(built, T, "col"), 1)).toEqual([]);
  });

  it("between two tasks one above the other, is a task of panes alone -- not one with an app, nor a terminal's", () => {
    const screen: Node = {
      key: "",
      dir: "col",
      bar: 1,
      kids: [{ id: T }, { id: U }, { id: "\u0002t" }],
      sizes: [{}, {}, {}],
    };
    const shown = [at(T, "app:b"), at(T, "c1"), at(U, "c2"), at(null, "t")];
    const built = build(shown, {}, () => null, { ...opts, screen, strip: (b) => b });
    const col = [...built.splits.values()].find((s) => s.screen)!.key;
    expect(foldable(built, col, 0)).toEqual([]); // Notepad above Claude's pane, under their strip
    expect(items(built, foldable(built, col, 1))).toEqual(["c2"]);
    expect(foldable(built, col, 2)).toEqual([]); // (a terminal's: kept nowhere)
    const trees = { [T]: firstTree(shown.slice(0, 2), null)!, [U]: minimized({ id: "c2" }, ["c2"], true) };
    const min = build(shown, trees, () => null, { ...opts, screen, strip: (b) => b });
    const s = [...min.splits.values()].find((x) => x.screen)!;
    expect(s.sizes.map((z) => !!z.fit)).toEqual([false, true, false]); // as long as its message box
    expect([...min.minimized].map((id) => min.items.get(id)!.item)).toEqual(["c2"]);
    expect(
      [...min.under].map((id) => min.items.get(id)!.item).sort(), // each task's: above or below another
    ).toEqual(["app:b", "c1", "c2"]); // (a terminal's, of no task: never minimized)
    const side = build(shown.slice(0, 3), trees, () => null, {
      ...opts,
      screen: { key: "", dir: "row", bar: 1, kids: [{ id: T }, { id: U }], sizes: [{}, {}] },
    });
    expect(side.minimized.size).toBe(0); // side by side: shown whole
  });

  it("minimized, is as long as what it shows -- its sizes kept to show it whole again", () => {
    const tree = firstTree([at(T, "app:b"), at(T, "c1"), at(T, "c2")], null)!;
    const folded = minimized(tree, ["c1", "c2"], true);
    expect(leafNodes(folded).map((l) => [l.id, !!l.min])).toEqual([
      ["app:b", false],
      ["c1", true],
      ["c2", true],
    ]);
    const built = build([at(T, "app:b"), at(T, "c1"), at(T, "c2")], { [T]: folded }, () => null, opts);
    expect(built.splits.get(key(built, T, "col"))!.sizes[1]).toEqual({ fit: true });
    expect(minimized(folded, ["c1", "c2"], false)).toEqual(tree);
    expect(leaves(folded)).toEqual(leaves(tree));
  });
});

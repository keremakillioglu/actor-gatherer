// The apps' panels' kit (app_kit/js/kit.js, served to each panel at /_ag/lib/kit.js), loaded as a panel loads it.
import { readFileSync } from "node:fs";
import path from "node:path";
import { beforeAll, describe, expect, it } from "vitest";
import { ago } from "../../core/format";

type Kit = {
  el: (tag: string, attrs?: Record<string, unknown>, ...kids: unknown[]) => HTMLElement;
  patch: (box: Element, kids: Node[] | DocumentFragment) => void;
  ago: (t: number | null) => string;
};
let kit: Kit;

beforeAll(() => {
  new Function(readFileSync(path.resolve(import.meta.dirname, "../../../../app_kit/js/kit.js"), "utf8"))();
  kit = (window as unknown as { agKit: Kit }).agKit;
});

describe("agKit.patch", () => {
  const msg = (ts: string, text: string) => kit.el("div", { class: "msg", "data-ts": ts }, text);

  it("keeps each child the same as before, adding, changing and taking out only what differs", () => {
    const log = document.createElement("div");
    kit.patch(log, [msg("1", "a"), msg("2", "b"), msg("3", "c")]);
    const [one, two, three] = [...log.children];
    kit.patch(log, [msg("1", "a"), msg("2", "b, edited"), msg("4", "d")]);
    expect([...log.children].map((n) => n.textContent)).toEqual(["a", "b, edited", "d"]);
    expect(log.children[0]).toBe(one); // the same: kept, not drawn anew
    expect(log.children[1]).not.toBe(two);
    expect(three.isConnected).toBe(false);
  });

  it("keeps a selection in a message while another arrives", () => {
    const log = document.body.appendChild(document.createElement("div"));
    kit.patch(log, [msg("1", "hello there"), msg("2", "b")]);
    const words = log.children[0].firstChild!;
    getSelection()!.setBaseAndExtent(words, 0, words, 5);
    const frag = document.createDocumentFragment();
    frag.append(msg("1", "hello there"), msg("2", "b"), msg("3", "new"));
    kit.patch(log, frag);
    expect(log.children).toHaveLength(3);
    expect(getSelection()!.toString()).toBe("hello");
    log.remove();
  });
});

describe("agKit.ago", () => {
  it("says how long ago as the dashboard does", () => {
    const now = Date.now() / 1000;
    for (const t of [null, now - 5, now - 200, now - 7300, now - 90000]) expect(kit.ago(t)).toBe(ago(t));
  });
});

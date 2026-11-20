// The page's count-up times, set where they are (clocks.ts).
import { describe, expect, it, vi } from "vitest";
import { tick } from "./clocks";

describe("the page's clocks", () => {
  it("sets each count-up time where it is", () => {
    vi.useFakeTimers();
    vi.setSystemTime(1_000_000 * 1000);
    const box = document.createElement("div");
    box.innerHTML = `<span data-ago="999880">x</span><span data-lasting="999875">x</span><span data-since="999955">x</span>`;
    tick(box);
    expect([...box.children].map((n) => n.textContent)).toEqual(["2m ago", "2m 05s", "45s"]);
    const words = box.firstChild!.firstChild;
    tick(box); // the same words: the text left as it is, not set again
    expect(box.firstChild!.firstChild).toBe(words);
    vi.useRealTimers();
  });
});

import { afterEach, describe, expect, it, vi } from "vitest";
import * as M from "./model";
import { shadow } from "./shadow";

const page = (current: string, shown: string[], tabs: { id: string; tasks: string[] }[]) => ({ current, shown, tabs });

describe("the layout model run beside the page", () => {
  afterEach(() => {
    vi.useRealTimers();
    shadow.mismatches.length = 0;
  });

  it("takes the page's first tab on a home with none kept, and agrees with the page as changes are told", () => {
    shadow.start(() => null);
    shadow.begin([{ id: "s1", name: "", tasks: [] }], "s1");
    shadow.tell("auto", M.opened, "g\u0000c1");
    shadow.tell("route", M.routed, "g\u0000c2", { id: "s2" });
    shadow.tell("enter", M.open, "g\u0000c2");
    shadow.check(
      page(
        "s2",
        ["g\u0000c2"],
        [
          { id: "s1", tasks: ["g\u0000c1"] },
          { id: "s2", tasks: [] },
        ],
      ),
    );
    expect(shadow.mismatches).toEqual([]);
  });

  it("reports a difference with the changes told since, then takes the page's state", () => {
    shadow.tell("enter", M.open, "g\u0000c9");
    shadow.check(
      page(
        "s2",
        ["g\u0000c3"],
        [
          { id: "s1", tasks: ["g\u0000c1"] },
          { id: "s2", tasks: [] },
        ],
      ),
    );
    expect(shadow.mismatches.map((m) => [m.what, m.since])).toEqual([["tasks shown", ['enter("g\\u0000c9")']]]);
    shadow.check(
      page(
        "s2",
        ["g\u0000c3"],
        [
          { id: "s1", tasks: ["g\u0000c1"] },
          { id: "s2", tasks: [] },
        ],
      ),
    );
    expect(shadow.mismatches.length).toBe(1);
  });

  it("checks once the page is quiet, not while a tab is shown; flush checks what waits", () => {
    vi.useFakeTimers();
    let busy = true;
    const now = () =>
      busy
        ? null
        : page(
            "s2",
            ["g\u0000c4"],
            [
              { id: "s1", tasks: ["g\u0000c1"] },
              { id: "s2", tasks: [] },
            ],
          );
    shadow.later(now);
    vi.advanceTimersByTime(1000);
    expect(shadow.mismatches).toEqual([]); // still busy
    busy = false;
    vi.advanceTimersByTime(1000);
    expect(shadow.mismatches.map((m) => m.what)).toEqual(["tasks shown"]);
    shadow.tell("enter", M.open, "g\u0000c5");
    shadow.later(() =>
      page(
        "s2",
        ["g\u0000c5"],
        [
          { id: "s1", tasks: ["g\u0000c1"] },
          { id: "s2", tasks: [] },
        ],
      ),
    );
    expect(shadow.flush().length).toBe(1);
  });

  it("reads the model's keys as they are now: a task an item joined, the items of a task gone", () => {
    shadow.keysWith((k) => (k === "g\u0000c5" ? ["g\u0000t1"] : k === "g\u0000t1" ? ["g\u0000c5", "g\u0000a"] : [k]));
    shadow.check(
      page(
        "s2",
        ["g\u0000t1"],
        [
          { id: "s1", tasks: ["g\u0000c1"] },
          { id: "s2", tasks: [] },
        ],
      ),
    );
    expect(shadow.mismatches).toEqual([]);
  });
});

describe("the model's rules the page tells it by", () => {
  it("opens what the page opens by itself only in a tab holding nothing; closes a task here, the tab kept", () => {
    const l = M.empty("e");
    expect(M.shown(M.opened(l, "g\u0000c1"))).toEqual(["g\u0000c1"]);
    expect(M.shown(M.opened(M.setDraft(l, "x"), "g\u0000c1"))).toEqual([]);
    const two = M.open(M.open(l, "g\u0000c1"), "g\u0000c2", true);
    const out = M.closeHere(two, "g\u0000c2");
    expect([M.shown(out), M.shownTab(out).focus, out.tabs.length]).toEqual([["g\u0000c1"], "g\u0000c1", 1]);
    expect(M.shownTab(M.pick(two, "g\u0000c1")).focus).toBe("g\u0000c1");
  });
});

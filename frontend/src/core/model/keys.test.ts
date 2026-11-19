import { describe, expect, it } from "vitest";
import { appInstance, appItem, isApp, isShell, isTask, key, parse, taskId, taskNumber } from "./keys";

describe("item keys", () => {
  it("are a group and an id, back and forth", () => {
    for (const [g, id] of [
      ["g", "c1"],
      ["my.group", "app:abc"],
      ["g", "t12"],
      ["self:c9", "c9"],
    ]) {
      expect(parse(key(g, id))).toEqual({ group: g, id });
    }
  });

  it("read a key with no id as its group's", () => {
    expect(parse("g")).toEqual({ group: "g", id: "" });
    expect(parse(null)).toEqual({ group: "", id: "" });
  });

  it("keep an id holding the separator whole", () => {
    expect(parse(key("g", "a\u0000b"))).toEqual({ group: "g", id: "a\u0000b" });
  });

  it("tell a task, an app and a shell from an actor's channel", () => {
    expect([isTask("t3"), isTask("t"), isTask("tx3"), isTask("c-t3"), isTask(undefined)]).toEqual([
      true,
      false,
      false,
      false,
      false,
    ]);
    expect([taskNumber("t12"), taskNumber("c1"), taskId(4)]).toEqual([12, null, "t4"]);
    expect([isApp("app:x"), appInstance("app:x"), appInstance("c1"), appItem("y")]).toEqual([true, "x", null, "app:y"]);
    expect([isShell("shell:0a"), isShell("c1"), isShell(3)]).toEqual([true, false, false]);
  });
});

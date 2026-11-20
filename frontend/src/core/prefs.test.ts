// What the page keeps in this browser (prefs.ts): read back as kept, and nothing thrown where storage is off.
import { afterEach, describe, expect, it, vi } from "vitest";
import * as prefs from "./prefs";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("prefs", () => {
  it("reads back what it kept", () => {
    prefs.keep("k-list", ["a", "b"]);
    prefs.setFlag("k-flag", true);
    prefs.setText("k-text", "dark");
    expect([prefs.list("k-list"), prefs.flag("k-flag"), prefs.text("k-text")]).toEqual([["a", "b"], true, "dark"]);
    prefs.setFlag("k-flag", false);
    expect([prefs.flag("k-flag", true), prefs.flag("k-none"), prefs.flag("k-none", true)]).toEqual([
      false,
      false,
      true,
    ]);
    prefs.drop("k-text");
    expect(prefs.text("k-text")).toBeNull();
    localStorage.setItem("k-bad", "{not json");
    expect([prefs.json("k-bad"), prefs.list("k-text"), prefs.list("k-flag")]).toEqual([null, null, null]);
  });

  it("throws nothing where storage is off", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("off");
      },
      setItem: () => {
        throw new Error("off");
      },
      removeItem: () => {
        throw new Error("off");
      },
    });
    prefs.keep("k", [1]);
    prefs.drop("k");
    expect([prefs.text("k"), prefs.json("k"), prefs.flag("k", true)]).toEqual([null, null, true]);
  });
});

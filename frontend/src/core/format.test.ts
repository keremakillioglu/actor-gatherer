// Times, counts and words as the page says them.
import { afterEach, describe, expect, it, vi } from "vitest";
import { ago, compact, firstLine, full, lasting, plural, span, spell, usd } from "./format";

afterEach(() => vi.useRealTimers());

describe("format", () => {
  it("counts", () => {
    expect([full(1204.4), full(null), plural(1, "message"), plural(3, "turn"), plural(1500, "line")]).toEqual([
      "1,204",
      "–",
      "1 message",
      "3 turns",
      "1,500 lines",
    ]);
  });

  it("cuts a text to its first line", () => {
    expect([firstLine("a\nb"), firstLine("abcdef", 3), firstLine(null), firstLine(undefined, 2)]).toEqual([
      "a",
      "abc…",
      "",
      "",
    ]);
  });

  it("says how long ago, and how long", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(1_000_000_000);
    const now = 1_000_000;
    expect([ago(now - 44.6), ago(now - 150), ago(now - 7200), ago(now - 3 * 86400), ago(0), ago(now + 5)]).toEqual([
      "45s ago",
      "3m ago",
      "2h ago",
      "3d ago",
      "never",
      "0s ago",
    ]);
    expect([spell(45.9), spell(125), spell(4320), spell(-1), lasting(now - 61)]).toEqual([
      "45s",
      "2m 05s",
      "1h 12m",
      "0s",
      "1m 01s",
    ]);
  });

  it("says counts short, dollars to the cent, and how long from one time to another", () => {
    expect([null, 950, 1234, 34_000, 150_000, 1_500_000, 12_000_000].map(compact)).toEqual([
      "–",
      "950",
      "1.2K",
      "34K",
      "150K",
      "1.5M",
      "12M",
    ]);
    expect([undefined, 0.004, 1.2, 0].map(usd)).toEqual(["–", "<$0.01", "$1.20", "$0.00"]);
    expect([span(null, 5), span(100, 145), span(100, 250), span(100, 4420)]).toEqual(["–", "45s", "2.5m", "1.2h"]);
  });
});

// The page's streams over one socket (stream.ts): opened once the server says hello, their events to their listeners,
// closed, tried again after they end and once a socket that went is back, and each its own EventSource where the
// socket never worked.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Mux, RETRY_MS, Stream } from "./stream";

class FakeSocket {
  static all: FakeSocket[] = [];
  sent: unknown[] = [];
  onmessage: ((m: { data: unknown }) => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(readonly url: string) {
    FakeSocket.all.push(this);
  }
  send(text: string) {
    this.sent.push(JSON.parse(text));
  }
  say(sid: string, name: string, data = "") {
    this.onmessage!({ data: `${sid}\n${name}\n${data}` });
  }
  hello() {
    this.say("0", "hello");
  }
  gone() {
    this.onclose!();
  }
}

class FakeEventSource {
  static all: FakeEventSource[] = [];
  readyState = 0;
  closed = false;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  listeners = new Map<string, ((ev: MessageEvent) => void)[]>();
  constructor(readonly url: string) {
    FakeEventSource.all.push(this);
  }
  addEventListener(name: string, f: (ev: MessageEvent) => void) {
    this.listeners.set(name, [...(this.listeners.get(name) || []), f]);
  }
  close() {
    this.closed = true;
  }
  emit(name: string, data: string) {
    const ev = new MessageEvent(name, { data });
    if (name === "message") this.onmessage?.(ev);
    for (const f of this.listeners.get(name) || []) f(ev);
  }
}

const sock = () => FakeSocket.all[FakeSocket.all.length - 1];

beforeEach(() => {
  FakeSocket.all = [];
  FakeEventSource.all = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("streams over one socket", () => {
  it("opens each once the server says hello, and hands its events to its listeners", () => {
    const mux = new Mux("ws://h/api/ws");
    const a = new Stream("/api/stream?gatherer=g", mux),
      b = new Stream("/api/terminal?session_id=s", mux);
    expect(FakeSocket.all).toHaveLength(1); // one socket for both
    expect(sock().sent).toEqual([]); // not before hello
    expect(a.readyState).toBe(Stream.CONNECTING);
    sock().hello();
    expect(sock().sent).toEqual([
      { open: "1", url: "/api/stream?gatherer=g" },
      { open: "2", url: "/api/terminal?session_id=s" },
    ]);
    const seen: string[] = [];
    a.onopen = () => seen.push("open");
    a.addEventListener("home", (ev) => seen.push(`home ${(ev as MessageEvent).data}`));
    b.addEventListener("out", (ev) => seen.push(`out ${(ev as MessageEvent).data}`));
    sock().say("1", "!open");
    sock().say("1", "home", '{"a":\n1}');
    sock().say("2", "out", "x");
    expect(seen).toEqual(["open", 'home {"a":\n1}', "out x"]);
    expect(a.readyState).toBe(Stream.OPEN);
    expect([Stream.CONNECTING, Stream.OPEN, Stream.CLOSED]).toEqual([0, 1, 2]); // as EventSource's, which the page compares with
  });

  it("lets one go when it is closed, and hears no more of it", () => {
    const mux = new Mux("ws://h/api/ws");
    const a = new Stream("/api/stream", mux);
    sock().hello();
    const seen: string[] = [];
    a.addEventListener("home", () => seen.push("home"));
    a.close();
    expect(sock().sent).toEqual([{ open: "1", url: "/api/stream" }, { close: "1" }]);
    sock().say("1", "home", "{}");
    expect(seen).toEqual([]);
    expect(a.readyState).toBe(Stream.CLOSED);
    const b = new Stream("/api/stream", mux); // opened at once on the socket already there
    expect(b.id).toBe("2");
    expect(FakeSocket.all).toHaveLength(1);
  });

  it("opens one that ended again after a while, as an EventSource does", () => {
    const mux = new Mux("ws://h/api/ws");
    const a = new Stream("/api/edit/stream?path=p", mux);
    sock().hello();
    const errors: number[] = [];
    a.onerror = () => errors.push(a.readyState);
    sock().say("1", "!end");
    expect(errors).toEqual([Stream.CONNECTING]);
    vi.advanceTimersByTime(RETRY_MS - 1);
    expect(sock().sent).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(sock().sent[1]).toEqual({ open: "2", url: "/api/edit/stream?path=p" });
  });

  it("does not try again one that was refused", () => {
    const mux = new Mux("ws://h/api/ws");
    const a = new Stream("/api/nope", mux);
    sock().hello();
    const errors: number[] = [];
    a.addEventListener("error", () => errors.push(a.readyState));
    sock().say("1", "!fail", "404");
    expect(errors).toEqual([Stream.CLOSED]);
    vi.advanceTimersByTime(RETRY_MS * 3);
    expect(sock().sent).toHaveLength(1);
  });

  it("opens every stream again once a socket that went is back", () => {
    const mux = new Mux("ws://h/api/ws");
    const a = new Stream("/api/stream", mux),
      b = new Stream("/api/terminal?session_id=s", mux);
    sock().hello();
    const states: number[] = [];
    a.onerror = () => states.push(a.readyState);
    sock().gone(); // the server restarting
    expect(states).toEqual([Stream.CONNECTING]);
    b.close(); // closed while it is away: not opened again
    vi.advanceTimersByTime(250);
    expect(FakeSocket.all).toHaveLength(2);
    sock().gone(); // still away: tried again, later
    vi.advanceTimersByTime(499);
    expect(FakeSocket.all).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(FakeSocket.all).toHaveLength(3);
    sock().hello();
    expect(sock().sent).toEqual([{ open: "3", url: "/api/stream" }]);
    expect(FakeEventSource.all).toEqual([]); // it worked once: never given up for EventSources
  });

  it("keeps to one socket when a stream is opened while a socket that went is tried again", () => {
    const mux = new Mux("ws://h/api/ws");
    const a = new Stream("/api/stream", mux);
    sock().hello();
    sock().gone();
    const b = new Stream("/api/agent?id=x", mux); // opened before the socket is tried again: waits for it
    expect(FakeSocket.all).toHaveLength(1);
    vi.advanceTimersByTime(250);
    expect(FakeSocket.all).toHaveLength(2);
    sock().hello();
    expect(sock().sent).toEqual([
      { open: "2", url: "/api/stream" },
      { open: "3", url: "/api/agent?id=x" },
    ]);
    const seen: string[] = [];
    b.addEventListener("agent", (ev) => seen.push((ev as MessageEvent).data));
    sock().say("3", "agent", "x");
    expect(seen).toEqual(["x"]); // heard on the one socket there is
    expect(a.readyState).toBe(Stream.CONNECTING);
  });

  it("opens each as its own EventSource where the socket never worked", () => {
    const mux = new Mux("ws://h/api/ws");
    const a = new Stream("/api/stream", mux);
    const seen: string[] = [];
    a.addEventListener("home", (ev) => seen.push(`home ${(ev as MessageEvent).data}`));
    a.onopen = () => seen.push("open");
    a.onmessage = (ev) => seen.push(`message ${(ev as MessageEvent).data}`);
    sock().gone(); // refused, or no WebSockets on this dashboard
    expect(FakeEventSource.all.map((e) => e.url)).toEqual(["/api/stream"]);
    const own = FakeEventSource.all[0];
    own.readyState = 1;
    own.onopen!();
    own.emit("home", "{}");
    own.emit("message", "m");
    a.addEventListener("agent", (ev) => seen.push(`agent ${(ev as MessageEvent).data}`)); // listened to later
    own.emit("agent", "{}");
    expect(seen).toEqual(["open", "home {}", "message m", "agent {}"]);
    expect(a.readyState).toBe(Stream.OPEN);
    const b = new Stream("/api/terminal?session_id=s", mux); // later ones too, with no socket tried
    expect(FakeEventSource.all.map((e) => e.url)).toEqual(["/api/stream", "/api/terminal?session_id=s"]);
    expect(FakeSocket.all).toHaveLength(1);
    a.close();
    b.close();
    expect(FakeEventSource.all.every((e) => e.closed)).toBe(true);
  });

  it("goes on to the other listeners when a handler throws", () => {
    const mux = new Mux("ws://h/api/ws");
    const a = new Stream("/api/stream", mux);
    sock().hello();
    const seen: string[] = [];
    a.onopen = () => {
      throw new Error("a handler's");
    };
    a.addEventListener("open", () => seen.push("open"));
    const thrown: unknown[] = [];
    const queued = vi.spyOn(globalThis, "queueMicrotask").mockImplementation((f) => {
      try {
        f();
      } catch (err) {
        thrown.push(err);
      }
    });
    sock().say("1", "!open");
    queued.mockRestore();
    expect(seen).toEqual(["open"]);
    expect(String(thrown[0])).toContain("a handler's");
  });
});

// The page's streams, each as an EventSource would be, but all of a page's over one WebSocket (ag_dashboard/api/ws.py
// says why and how): a browser keeps at most six connections to the dashboard open, for all its tabs together, and an
// EventSource holds one for as long as it is open -- two tabs, or one with a terminal, an Editor and a Preview, held
// them all, and every other request waited for one to close. A WebSocket is not one of the six.
//
// `stream(url)` is what `new EventSource(url)` was: the same events (`addEventListener(name)`, `onopen`, `onerror`,
// `onmessage`), `readyState`, `close()`, and tried again as an EventSource is -- after a stream ends, and once the
// socket is back after it went (the server restarted). A page whose socket never worked (a dashboard without WebSockets)
// opens each stream as an EventSource after all.

const CONNECTING = 0,
  OPEN = 1,
  CLOSED = 2;
/** How long after a stream ends it is opened again, as an EventSource waits. */
export const RETRY_MS = 3000;
/** The longest wait between tries of a socket that went. */
const MAX_WAIT_MS = 3000;

type Handler = ((ev: Event) => void) | null;

/** One stream, as an EventSource. */
export class Stream extends EventTarget {
  static readonly CONNECTING = CONNECTING;
  static readonly OPEN = OPEN;
  static readonly CLOSED = CLOSED;
  readonly CONNECTING = CONNECTING;
  readonly OPEN = OPEN;
  readonly CLOSED = CLOSED;
  readyState = CONNECTING;
  onopen: Handler = null;
  onerror: Handler = null;
  onmessage: Handler = null;
  /** Its name on the socket, this time it is open there ("" while it is not). */
  id = "";
  private own: EventSource | null = null; // opened by itself: the socket never worked
  private names = new Set<string>(); // the events listened to, passed on from `own`
  private retry: ReturnType<typeof setTimeout> | null = null;

  constructor(
    readonly url: string,
    private readonly mux: Mux,
  ) {
    super();
    mux.open(this);
  }

  addEventListener(
    type: string,
    listener: EventListenerOrEventListenerObject | null,
    options?: boolean | AddEventListenerOptions,
  ) {
    super.addEventListener(type, listener, options);
    if (this.own && !this.names.has(type)) this.pass(this.own, type);
    this.names.add(type);
  }

  close() {
    if (this.readyState === CLOSED) return;
    this.readyState = CLOSED;
    if (this.retry) clearTimeout(this.retry);
    this.retry = null;
    if (this.own) this.own.close();
    this.own = null;
    this.mux.close(this);
  }

  /** What happened to it, said to its listeners (and its `on...` handler first). */
  private say(ev: Event) {
    const handler =
      ev.type === "open"
        ? this.onopen
        : ev.type === "error"
          ? this.onerror
          : ev.type === "message"
            ? this.onmessage
            : null;
    try {
      if (handler) handler.call(this, ev);
    } catch (err) {
      queueMicrotask(() => {
        throw err; // said as the page's error, as an EventSource's handler's would be, not stopping the socket's others
      });
    }
    this.dispatchEvent(ev);
  }

  // What the socket says of it (Mux).
  opened() {
    if (this.readyState === CLOSED) return;
    this.readyState = OPEN;
    this.say(new Event("open"));
  }
  event(name: string, data: string) {
    if (this.readyState !== CLOSED) this.say(new MessageEvent(name, { data }));
  }
  /** It ended, or the socket went: tried again, the one by itself in a moment, the other once the socket is back. */
  ended(again: boolean) {
    if (this.readyState === CLOSED) return;
    this.readyState = CONNECTING;
    this.id = "";
    this.say(new Event("error"));
    if (again && this.readyState === CONNECTING && !this.retry)
      this.retry = setTimeout(() => {
        this.retry = null;
        if (this.readyState === CONNECTING) this.mux.open(this);
      }, RETRY_MS);
  }
  /** Refused, or not a stream: not tried again, as an EventSource given an error. */
  failed() {
    if (this.readyState === CLOSED) return;
    this.readyState = CLOSED;
    this.id = "";
    this.mux.close(this);
    this.say(new Event("error"));
  }
  /** The socket never worked: opened as an EventSource of its own, its events passed on. */
  alone() {
    if (this.readyState === CLOSED || this.own) return;
    const own = (this.own = new EventSource(this.url));
    own.onopen = () => {
      if (this.own !== own) return;
      this.readyState = OPEN;
      this.say(new Event("open"));
    };
    own.onerror = () => {
      if (this.own !== own) return;
      this.readyState = own.readyState;
      this.say(new Event("error"));
    };
    own.onmessage = (ev) => {
      if (this.own === own) this.say(new MessageEvent("message", { data: ev.data }));
    };
    for (const name of this.names) this.pass(own, name);
  }
  private pass(own: EventSource, name: string) {
    if (name === "open" || name === "error" || name === "message") return; // said by its handlers above
    own.addEventListener(name, (ev) => {
      if (this.own === own) this.say(new MessageEvent(name, { data: (ev as MessageEvent).data }));
    });
  }
}

/** A page's one socket, and the streams on it. */
export class Mux {
  private ws: WebSocket | null = null;
  private ready = false; // the server said hello: streams can be opened
  private worked = false; // it did once: when it goes, it is tried again, not given up for EventSources
  private alone = false; // it never worked: every stream its own EventSource
  private tries = 0;
  private again: ReturnType<typeof setTimeout> | null = null; // the socket tried again after it went, in a while
  private next = 1;
  private streams = new Map<string, Stream>(); // by id, those open on the socket (or to be once it is ready)
  private waiting = new Set<Stream>(); // to be opened once it is ready

  constructor(private readonly url: string) {}

  open(s: Stream) {
    if (this.alone) return s.alone();
    if (this.ready) this.send(s);
    else {
      this.waiting.add(s);
      if (!this.ws && !this.again) this.connect(); // (while it is tried again in a while, opened with the others then)
    }
  }

  close(s: Stream) {
    this.waiting.delete(s);
    if (!s.id) return;
    this.streams.delete(s.id);
    if (this.ready && this.ws) this.ws.send(JSON.stringify({ close: s.id }));
    s.id = "";
  }

  private send(s: Stream) {
    s.id = String(this.next++);
    this.streams.set(s.id, s);
    this.ws!.send(JSON.stringify({ open: s.id, url: s.url }));
  }

  private connect() {
    if (this.ws) return; // one socket a page: a second, opened beside it, would take the first one's streams' events
    const ws = (this.ws = new WebSocket(this.url));
    ws.onmessage = (m) => {
      if (this.ws !== ws || typeof m.data !== "string") return;
      const text = m.data,
        a = text.indexOf("\n"),
        b = text.indexOf("\n", a + 1);
      if (a < 0 || b < 0) return;
      const sid = text.slice(0, a),
        name = text.slice(a + 1, b),
        data = text.slice(b + 1);
      if (sid === "0" && name === "hello") {
        this.ready = this.worked = true;
        this.tries = 0;
        const waiting = [...this.waiting];
        this.waiting.clear();
        for (const s of waiting) this.send(s);
        return;
      }
      const s = this.streams.get(sid);
      if (!s) return; // closed here meanwhile
      if (name === "!open") s.opened();
      else if (name === "!end") {
        this.streams.delete(sid);
        s.ended(true);
      } else if (name === "!fail") {
        this.streams.delete(sid);
        s.failed();
      } else s.event(name, data);
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      this.ready = false;
      const open = [...this.streams.values()];
      this.streams.clear();
      if (!this.worked) {
        // never worked here (no WebSockets on this dashboard): each stream by itself, as before
        this.alone = true;
        const all = [...this.waiting, ...open];
        this.waiting.clear();
        for (const s of all) s.alone();
        return;
      }
      for (const s of open) {
        s.ended(false);
        this.waiting.add(s); // opened again once it is back
      }
      this.again = setTimeout(
        () => {
          this.again = null;
          this.connect();
        },
        Math.min(MAX_WAIT_MS, 250 * 2 ** this.tries++),
      );
    };
  }
}

let shared: Mux | null = null;

/** A stream of the dashboard's at `url` (a path of it), on this page's socket: as `new EventSource(url)`. */
export function stream(url: string): Stream {
  if (!shared) shared = new Mux(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/ws`);
  return new Stream(url, shared);
}

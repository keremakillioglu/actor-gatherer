// The types of app_kit's SDK (app.js, served at /_ag/app.js): what an app's panel calls of the dashboard around it, as
// app.js's header describes it (app_kit/DESIGN.md, "Panels"). For a panel written in TypeScript (DocWriter's ag.ts), and
// for one in plain JS checked with `// @ts-check`: `/** @type {import("/path/to/app_kit/js/app").AgApi} */`.
// frontend/tsconfig.json includes it, so `pnpm typecheck` checks it.

/** What the panel shows: its app, and the instance of it. */
export interface AgInfo {
  app: string;
  label: string;
  gatherer: string;
  instance: string;
  title: string;
  folder: string | null;
}

/** One of the instance's events, as stored (ag's event shape, with its row). */
export interface AgEvent {
  row_id: number;
  type: string;
  channel?: string | null;
  payload: Record<string, unknown>;
  [more: string]: unknown;
}

/** An event the panel inserts: its own types, or `ag.context(...)` for agents to see. */
export interface AgNewEvent {
  type: string;
  payload: Record<string, unknown>;
}

/** A tool's result, as MCP has it. */
export interface AgToolResult {
  content: { type: string; text?: string; [more: string]: unknown }[];
  isError?: boolean;
}

/** Who called a tool the panel answers. */
export interface AgCaller {
  channel?: string;
  gatherer?: string;
  [more: string]: unknown;
}

/** An attached agent as the page has it. */
export interface AgAgentState {
  status?: string;
  turn_over?: boolean;
  asking?: {
    call: string;
    harness?: string;
    questions?: { question: string; options?: { label: string }[] }[];
  } | null;
  failing?: { text?: string } | null;
  stopped?: { kind: string } | null;
  session?: { session_id?: string; terminal?: boolean } | null;
  name?: string | null;
}

/** The actors as the dashboard lists them (capability `actors`). */
export interface AgActors {
  gatherers: {
    name: string;
    agents: {
      channel: string;
      name?: { text?: string } | string | null;
      avatar?: string;
      avatar_hue?: string;
      cwd?: string;
      status?: [string, string];
      [more: string]: unknown;
    }[];
  }[];
  home_dir: string;
  cwd: string;
  [more: string]: unknown;
}

/** The dashboard's theme: its mode, and its colours (also set on the panel's :root). */
export interface AgTheme {
  mode: "light" | "dark";
  vars: Record<string, string>;
}

/** A link to something in this app the user clicked (`ag://<app>/<path>#<part>`). */
export interface AgLink {
  href: string;
  path: string;
  part: string;
  values: Record<string, string>;
  form: string;
}

/** A notification to the user (capability `notify`). */
export interface AgNotice {
  title: string;
  text?: string;
  key?: string;
  show?: ("ag" | "system")[];
  where?: string;
}

/** The SDK, once connected: `await AgApp.connect()`. */
export interface AgApi {
  readonly app: string;
  readonly label: string;
  readonly gatherer: string;
  readonly instance: string;
  readonly title: string;
  readonly folder: string | null;
  events: {
    read(q: {
      types: string[];
      after?: number;
      channel?: string;
      limit?: number;
    }): Promise<AgEvent[]>;
    /** Each event of `types` as it is stored (after `after`): the function returned stops it. */
    subscribe(
      types: string[],
      onRow: (row: AgEvent) => void,
      opts?: { after?: number },
    ): () => void;
    insert(events: AgNewEvent[], opts?: { channel?: string }): Promise<unknown>;
  };
  context(stream: string, author: string, text: string): AgNewEvent;
  tools: {
    handle(
      name: string,
      fn: (
        args: Record<string, unknown>,
        caller: AgCaller,
      ) => string | AgToolResult | Promise<string | AgToolResult>,
    ): void;
    call(name: string, args?: Record<string, unknown>): Promise<AgToolResult>;
  };
  native: {
    readonly available: boolean;
    show(el: HTMLElement, target: string): void;
    hide(): void;
    release(): Promise<unknown>;
  };
  spelling: {
    readonly available: boolean;
    check(
      word: string,
    ): Promise<{ misspelled: boolean; suggestions: string[] } | null>;
    learn(word: string): Promise<unknown>;
  };
  agents: {
    readonly attached: string[];
    onChange(cb: (attached: string[]) => void): void;
    attach(channel: string): Promise<unknown>;
    detach(channel: string): Promise<unknown>;
    state(channel: string): AgAgentState | null;
    onState(cb: (states: Record<string, AgAgentState>) => void): void;
    send(channel: string, text: string): Promise<unknown>;
    answer(channel: string, call: string, choice: unknown): Promise<unknown>;
    interrupt(channel: string): Promise<unknown>;
    transcript(
      channel: string,
      opts?: { after?: number },
    ): Promise<{
      items?: { row_id: number; type: string; parts: unknown[] }[];
    }>;
    focus(channel: string): Promise<unknown>;
  };
  intents: {
    open(kind: string, data?: Record<string, unknown>): Promise<unknown>;
    on(kind: string, cb: (data: Record<string, unknown>) => void): void;
  };
  selection: {
    readonly current: { gatherer: string; channel: string } | null;
    on(
      cb: (selection: { gatherer: string; channel: string } | null) => void,
    ): void;
  };
  actors: {
    readonly current: AgActors | null;
    on(cb: (actors: AgActors | null) => void): void;
    send(channel: string, text: string): Promise<{ channel: string }>;
    answer(channel: string, call: string, choice: unknown): Promise<unknown>;
    start(o: {
      harness?: string;
      folder?: string;
      text?: string;
    }): Promise<{ channel: string }>;
    show(channel: string): Promise<unknown>;
  };
  theme: {
    readonly current: AgTheme | null;
    on(cb: (theme: AgTheme) => void): void;
  };
  notices: {
    send(n: AgNotice): Promise<string>;
    clear(idOrKey: string): Promise<unknown>;
    onOpen(cb: (where: string, id: string) => void): void;
  };
  links: {
    onOpen(cb: (link: AgLink) => void): void;
    href(path: string, part?: string): string;
    open(href: string): Promise<unknown>;
  };
  /** What the app's backend tells its panels. */
  onMessage(cb: (message: unknown) => void): void;
  /** The app's backend's own routes, on its own origin. */
  api(path: string, init?: RequestInit): Promise<Response>;
  close(): Promise<unknown>;
}

/** `window.AgApp`, which /_ag/app.js sets. */
export interface AgAppGlobal {
  connect(): Promise<AgApi>;
}

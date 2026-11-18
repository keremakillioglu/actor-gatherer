// ------------------------------------------------------------------ the Terminal view
// The session in its harness's own UI: its interactive process, run by the dashboard in a
// pseudo-terminal (sessions.py's `terminal`), drawn by xterm.js. The terminal keeps one node across
// the tab's draws (moved, never made again), so what it shows, its scroll and its focus stay. Showing a
// session in the view opens its terminal, once each time the session is chosen: one that exits or fails
// to open is not opened again until asked (a button). Once open it has the session -- the Chat view's
// message box types into it -- until it is closed (the list's close button) or exits. A message sent while
// none is open opens it too (unless the home's config says `[dashboard] chat = "headless"`), the message its first.
// The terminal's colors: the page's terminal colors, and a 16-color palette for each theme made from them.
const XTERM_ANSI = {
  dark: { black: "#3a3935", red: "#ff6b80", green: "#4eba65", yellow: "#e8b600", blue: "#7cb7ff", magenta: "#e58fb6", cyan: "#4fc1c9", white: "#c3c2b7",
    brightBlack: "#8f8c84", brightRed: "#ff8fa0", brightGreen: "#7fd492", brightYellow: "#f2cc3a", brightBlue: "#a6cdff", brightMagenta: "#f0a8c8",
    brightCyan: "#7fd8de", brightWhite: "#ecebe7", selectionBackground: "rgba(124,183,255,.28)" },
  light: { black: "#2b2a27", red: "#cf3a50", green: "#2f9a4c", yellow: "#a87700", blue: "#2468c8", magenta: "#b8437a", cyan: "#13858d", white: "#a09d95",
    brightBlack: "#6f6c65", brightRed: "#a5293d", brightGreen: "#1b6b34", brightYellow: "#8a6200", brightBlue: "#1a4f9c", brightMagenta: "#8f2f5d",
    brightCyan: "#0e6870", brightWhite: "#55544f", selectionBackground: "rgba(36,104,200,.20)" },
};
function xtermTheme() {
  const css = getComputedStyle(document.documentElement), v = (n) => css.getPropertyValue(n).trim();
  const ink = v("--term-ink");
  return { ...XTERM_ANSI[css.colorScheme === "dark" ? "dark" : "light"], background: v("--term-bg"), foreground: ink, cursor: ink, cursorAccent: v("--term-bg") };
}
window.addEventListener("ag-theme", () => { if (term.xterm) term.xterm.options.theme = xtermTheme(); });
// The screen a session's terminal runs in, as its harness says (harness_kit's `fullscreen`): its full screen, which
// scrolls by sending each wheel tick to the harness, which redraws (Claude Code's); or its classic one, inline,
// printed into xterm's own scrollback and scrolled here (codex's).
const fullscreenFor = (info) => (harnessInfo(info.harness || (info.session && info.session.harness)) || {}).fullscreen !== false;
// A mouse report for the pointer moving with no button held (SGR: ESC [ < b;x;y M, motion bit 32, button 3):
// with any-motion tracking on, every move over the terminal is one, and each would share the one-at-a-time
// input with the wheel. Claude Code is given clicks, drags and the wheel, not the bare moves.
const BARE_MOVE = /\x1b\[<(\d+);\d+;\d+M/g;
const dropBareMoves = (d) => d.includes("\x1b[<") ? d.replace(BARE_MOVE, (m, b) => ((b & 32) && (b & 3) === 3 ? "" : m)) : d;
const term = { sid: null, xterm: null, fit: null, host: null, es: null, opened: false, exited: null, unsent: "", sending: false, error: "", tried: false };
// A link in the terminal clicked (one a program marks as a link, as Claude Code does its addresses): in a Browser of the
// actor's task, as a link in a message (07-panes.js, linkClicked); else as xterm would, the address asked about first.
const TERM_LINKS = {
  activate(ev, uri) {
    if (linkClicked(uri, ev)) return;
    if (!confirm(`Do you want to navigate to ${uri}?\n\nWARNING: This link could potentially be dangerous`)) return;
    const w = window.open();
    if (w) { try { w.opener = null; } catch (e) { /* as it is */ } w.location.href = uri; }
  },
};
function termFor(sid) {
  if (term.sid === sid && term.xterm) return term;
  termDrop();
  const xterm = new Terminal({ cursorBlink: true, fontSize: 13, scrollback: 5000, allowProposedApi: false, linkHandler: TERM_LINKS,
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace', theme: xtermTheme() });
  const fit = new FitAddon.FitAddon();
  xterm.loadAddon(fit);
  const host = el("div", { class: "xterm-host", id: "xterm-host", "data-refocus": "1" });
  host.agFocus = () => xterm.focus();
  Object.assign(term, { sid, xterm, fit, host, opened: false, exited: null, error: "", tried: false });
  // to the session by its id now, not the one it opened under: a codex session is renamed to its thread
  xterm.onData((d) => { d = dropBareMoves(d); if (d && term.xterm === xterm) termType(term.sid, d); });
  xterm.onResize(({ cols, rows }) => {
    if (term.xterm === xterm && termRunning(term.sid)) post("/api/terminal/resize", { session_id: term.sid, cols, rows }).catch(() => {});
  });
  new ResizeObserver(() => { if (host.isConnected && host.clientWidth) { try { fit.fit(); } catch (e) { /* not shown yet */ } } }).observe(host);
  return term;
}
// Drawn with WebGL where the browser has it: far faster than the DOM when the whole screen is redrawn, as
// full screen does on every scroll. Without it, or once its context is lost, the DOM draws.
function termWebgl(t) {
  if (!window.WebglAddon) return;
  try {
    const gl = new WebglAddon.WebglAddon();
    gl.onContextLoss(() => gl.dispose());
    t.xterm.loadAddon(gl);
  } catch (e) { /* no WebGL here: the DOM draws */ }
}
function termDrop() {
  if (term.es) term.es.close();
  if (term.xterm) term.xterm.dispose();
  Object.assign(term, { sid: null, xterm: null, fit: null, host: null, es: null, opened: false, exited: null, unsent: "", tried: false });
}
const termRunning = (sid) => {
  if (isShell(sid)) return term.sid === sid && term.exited === null;
  const info = selectedInfo(); return !!(info && info.channel === sid && info.session && info.session.terminal);
};
// What is typed, to the process, in order: one request at a time (two at once could arrive swapped), and
// what is typed while one is on its way goes together in the next -- fast typing is a few requests, not a queue.
function termType(sid, data) {
  if (!termRunning(sid)) return;
  term.unsent += data;
  if (!term.sending) termSend();
}
async function termSend() {
  term.sending = true;
  while (term.unsent && term.sid) {                  // each batch to the terminal shown when it goes
    const data = term.unsent, sid = term.sid;
    term.unsent = "";
    try { await post("/api/terminal/input", { session_id: sid, data }); } catch (err) { /* the terminal is gone: its end shows */ }
  }
  term.sending = false;
}
// What the process prints: everything kept at first (a page that comes back sees the screen), then as it comes.
function termListen(sid) {
  if (term.es || SNAPSHOT) return;
  const es = window.agNext.stream(`/api/terminal?session_id=${encodeURIComponent(sid)}`);
  term.es = es;
  if (term.opened)                                   // one opened elsewhere (a message sent): at the size drawn here
    post("/api/terminal/resize", { session_id: sid, cols: term.xterm.cols, rows: term.xterm.rows }).catch(() => {});
  const mine = () => term.es === es && term.sid === sid;
  es.addEventListener("out", (ev) => {
    if (!mine()) return;
    const got = JSON.parse(ev.data);
    if (got.reset) term.xterm.reset();
    term.xterm.write(Uint8Array.from(atob(got.data), (c) => c.charCodeAt(0)));
  });
  const ended = (ev) => {
    if (!mine()) return;
    es.close(); term.es = null;
    if (isShell(sid)) { term.exited = ev.type === "exit" ? JSON.parse(ev.data).code : -1; return shownGone(sid); }
    if (ev.type === "exit") { term.exited = JSON.parse(ev.data).code; term.xterm.write("\r\n\x1b[2m[the session's process ended]\x1b[0m\r\n"); }
    else if (term.exited === null) term.exited = -1;  // gone before it was listened to: ended all the same
    refresh();
  };
  es.addEventListener("exit", ended);
  es.addEventListener("none", ended);
}
async function termOpen(info) {
  const t = termFor(info.channel), xterm = t.xterm;
  t.tried = true;
  const dims = (t.fit && t.fit.proposeDimensions()) || { cols: 120, rows: 32 };
  t.error = ""; t.exited = null;
  try {
    await post("/api/terminal", { ...(info.session ? { session_id: info.session.session_id } : { gatherer: state.selected[0], channel: info.channel }),
      cols: dims.cols, rows: dims.rows, fullscreen: fullscreenFor(info) });
    t.xterm.reset();
    // listened to at once, not once the list says it runs: one that ends straight away (its harness refusing to
    // start) shows what it printed and its end, with "Open again", rather than "Opening the terminal…" for good
    if (term.xterm === xterm) termListen(info.channel);
  } catch (err) { t.error = err.message; }
  await refresh();
  if (termRunning(info.channel) && (t.xterm.cols !== dims.cols || t.xterm.rows !== dims.rows))   // fitted again meanwhile
    post("/api/terminal/resize", { session_id: info.channel, cols: t.xterm.cols, rows: t.xterm.rows }).catch(() => {});
  t.xterm.focus();
}
if (!SNAPSHOT && window.Terminal && window.FitAddon) addChatView({
  id: "terminal", name: "Terminal", feed: "none", frame: "xterm-frame", icon: ICONS.terminal,
  description: "The harness's own interface, in a terminal: what it would show and ask in one outside, its keys included.",
  render: (ctx) => {
    const { info, held } = ctx;
    if (state.home && state.home.terminals === false)
      return el("div", { class: "xterm-cover" }, el("div", { class: "desc", text: "A terminal needs a Unix pseudo-terminal, which the dashboard's system does not have." }));
    const t = termFor(info.channel), running = !!(info.session && info.session.terminal);
    if (running) { termListen(info.channel); t.tried = true; }   // seen open: once it ends (closed), not opened again here
    const open = !running && !held && !t.tried && hasChat(info);
    if (open) t.tried = true;
    requestAnimationFrame(() => {                      // drawn into the page: opened there once, then fitted to it
      if (!t.host.isConnected) return;
      if (!t.opened) { t.xterm.open(t.host); t.opened = true; termWebgl(t); }
      try { t.fit.fit(); } catch (e) { /* not shown */ }
      if (open) termOpen(info);                        // the session's terminal, at the size it was just fitted to
    });
    const cover = running ? null : el("div", { class: "xterm-cover" },
      el("div", { class: "desc", text: held || (!hasChat(info) ? "This session cannot be opened from the dashboard."
        : t.exited !== null ? "The session's process ended." : t.error ? "The terminal did not open." : "Opening the terminal…") }),
      held || !hasChat(info) || (!t.error && t.exited === null) ? null
        : el("button", { type: "button", class: "primary", onclick: () => termOpen(info) }, "Open again"),
      t.error ? el("div", { class: "err", text: t.error }) : null);
    return [t.host, cover].filter(Boolean);
  },
  composer: () => [],
});


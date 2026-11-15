// ------------------------------------------------------------------ the top row, as the actors' panes see it
// Above the panes, the apps' panels (07-panes.js's top row): whether it shows any (topShown), and each pane's chat
// minimized under what is above it. A pane's frame asks this page (window.agTop).
const topShown = () => PANE ? !!(window.parent.agTop && window.parent.agTop.shown())
  : !!(panes.apps && panes.apps.some((p) => !p.held));
// Drawn with the main view: the work area placed again if what it shows changed (another actor shown in this page's own
// pane: 07-panes.js's placeIfShown).
function topMount() {
  if (PANE || SNAPSHOT) return;
  placeIfShown();
}
// A panel opened or closed in the top row: each pane's frame told (its head put in its Chat bar, or not).
let topWas = null;
function topChanged() {
  if (PANE || SNAPSHOT) return;
  placeWork();
  markSeen();                                        // an app's panel shown: its notifications seen
  const now = topShown();
  for (const p of panes.others) p.call("toprow", now);
  if (now === topWas) { keepingPlace(renderMain); drawn.main = mainSignature(); return; }
  topWas = now;
  minRedraw();
}
// A pane's frame asks: what is above, and its own chat minimized, or able to be
const paneNode = (win) => { const p = paneOf(win); return p ? p.node : null; };
if (!PANE && !SNAPSHOT) window.agTop = Object.freeze({ shown: () => topShown(),
  min: (win) => !!workPlacer && !!paneNode(win) && workPlacer.isMin(paneNode(win)),
  canMin: (win) => !!workPlacer && !!paneNode(win) && workPlacer.canMin(paneNode(win)),
  setMin: (on, win) => { if (workPlacer && paneNode(win)) workPlacer.setMin(paneNode(win), on); } });
// A PANE MINIMIZED, each on its own (features/layout/work.ts): only its message box, right of it the conversation's last two
// lines -- the actor's avatar, small and still, on its own (18-mini-history.js) -- and its ×; what is above or below it the
// rest. Offered where something of its task is above or below it; kept in its task's arrangement (the tab shown), so it is
// minimized again there; moved where nothing is, shown whole.
const MIN_TIP = "Minimize the chat: only its message box and its last lines, under what is above it";
const chatMin = () => !SNAPSHOT && (PANE ? !!(window.parent.agTop && window.parent.agTop.min(window))
  : !!workPlacer && workPlacer.isMin(panes.here.node));
const canMinimize = () => !SNAPSHOT && !chatMin() && (PANE ? !!(window.parent.agTop && window.parent.agTop.canMin(window))
  : !!workPlacer && workPlacer.canMin(panes.here.node));
function setChatMin(on) {
  if (PANE) { if (window.parent.agTop) window.parent.agTop.setMin(on, window); return; }
  if (workPlacer) workPlacer.setMin(panes.here.node, on);   // drawn so as it is placed (minChanged, 07-panes.js)
}
// This page's pane minimized or shown again: its counts are the latest turn's, from the files' feed (chatFeed) -- then, shown
// again, its view's own feed.
async function minRedraw() {
  if (chatMin() && state.files && state.files.turn !== null) { state.files.turn = null; state.files.sel = null; }
  topMount();
  await loadChat();
  keepingPlace(renderMain);
  drawn.main = mainSignature();
  if (!chatMin()) chatToEnd();
}
// The view a minimized pane draws in place of its own (chatCard): no conversation, the message box, and miniFoot.
const MINI_VIEW = { id: "mini", name: "Chat", feed: "files", mini: true, background: false, queued: false, greets: true,
  render: () => [], footer: (ctx) => miniFoot(ctx) };
// the way back, at a minimized terminal's left (an actor's has none: its lines, or its avatar, pressed, are)
const miniBack = () => el("button", { type: "button", class: "mini-back", title: "Show the terminal again", "aria-label": "Show the terminal again",
  onclick: () => setChatMin(false) }, strokeIcon(ICONS.restore, 14));
// its pane's × (its head, hidden while minimized, has it: 21-start.js), at its far right
const miniClose = () => {
  const x = document.getElementById("pane-close");
  return el("button", { type: "button", class: "mini-x", title: x.title, "aria-label": x.title, onclick: () => x.click() }, "×");
};
// right of the box, the conversation's last two lines (18-mini-history.js), hovered: the whole of it -- pressed, the chat
// shown again; none shown (no turn yet, or a pane too narrow for them: 07-top.css), the actor's avatar alone does that
const miniFoot = (ctx) => [miniHistory(ctx), miniMe(ctx.info), miniClose()];
// The actor's avatar, small and still -- a mark at its corner while it asks the reader or stopped on an error -- on its line
// of the history (18-mini-history.js's meIcon), or alone right of the box (miniFoot); no avatar, the way back's icon.
const ME_MARKS = { asking: ["ask", "?"], error: ["err", "!"], failed: ["err", "!"] };
const meMark = (m) => m ? el("span", { class: "mk " + m[0], text: m[1] }) : null;
function miniMe(info) {
  const src = bareAvatar(info), [st, word] = statusOf(info);
  return el("button", { type: "button", class: "mini-me", title: `${word}. Show the chat`, "aria-label": `${word}. Show the chat`,
    onclick: () => setChatMin(false) },
    src ? el("img", { src, alt: "", draggable: "false" }) : strokeIcon(ICONS.restore, 14), meMark(ME_MARKS[st]));
}
// A shell's pane, minimized: what it is, and the way back.
function shellMini(id) {
  const sh = shellOf(id);
  return el("section", { class: "chat mini shell", "aria-label": "Terminal", "data-for": signature([id, "mini"]) }, miniBack(),
    el("span", { class: "mini-sh" }, strokeIcon(ICONS.terminal, 13), el("span", { text: sh ? `Terminal · ${shellPath(sh)}` : "Terminal" })),
    miniClose());
}
// In a frame: as tall as its minimized pane -- the row under the top row as tall as its tallest -- else as its pane is laid out.
let miniFit = null;
function fitMini() {
  const f = PANE && window.frameElement;
  if (!f) return;
  const card = document.querySelector("#main > .chat.mini");
  if (miniFit && miniFit.card === card) return;
  if (miniFit) miniFit.obs.disconnect();
  miniFit = null;
  if (!card) { f.style.height = ""; return; }
  const obs = new ResizeObserver(() => { f.style.height = `${Math.ceil(card.getBoundingClientRect().height)}px`; });
  obs.observe(card);
  miniFit = { card, obs };
}

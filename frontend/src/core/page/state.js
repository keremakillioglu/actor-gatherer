"use strict";
const SNAPSHOT = window.AG_SNAPSHOT ?? null;            // a snapshot's data (index.html), or none
// In a pane: the page again, in a frame of the page around it (panes, below), showing one actor -- the URL's
// (?pane=1&gatherer=G&channel=C&view=V) -- with no list or header of its own. PANE is the page around it:
// it streams for the frame, and keeps which actor and view it shows.
const PANE_URL = new URLSearchParams(location.search);
const PANE = (() => {
  if (SNAPSHOT || !PANE_URL.has("pane") || window.parent === window) return null;
  try { return window.parent.agPanes || null; } catch (e) { return null; }
})();
if (PANE) document.documentElement.classList.add("pane-mode");
// The server pushes each change (/api/stream); this is only how often the "ago" texts are redrawn.
const AGO_MS = 30000;
// What the page calls each kind the data names (data.py's group names stay as they are).
const LABELS = { "ag's sections": "Summarized history", "Recent history": "Recent raw history", "Other agents' requests": "Other actors' requests" };
const label = (group) => LABELS[group] || group;
const PREAMBLE = "Harness preamble", NOT_COUNTED = "Not counted by ag";
// the provider's count beyond ag's, shown only when the gap is more than this: smaller is tokenizer noise
const NOT_COUNTED_MIN = 50000;
const uncounted = (n) => n > NOT_COUNTED_MIN ? n : 0;
const GROUP_ORDER = [PREAMBLE, "Recent history", "ag's sections", "Kept from before the cut", "File-change notices", "Other agents' requests", "Stream messages", NOT_COUNTED];
let state = { home: null, selected: null, agent: null, readId: null, context: null, paused: false, stream: null,
  tx: null,             // the transcript feed's events, loaded as they come: {key, items, pending, first_row, last_row, earlier}
  details: !!SNAPSHOT,  // the details panel open beside the chat: at first in a snapshot, which has no conversation
  chat: null,           // the history feed's messages: {key, items (stored, append-only), pending, last_row}
  adding: null,         // the form open in the agent list: {gatherer: ""} a new gatherer's, {gatherer: G} a new session's in G
  renaming: null };     // the actor being named in the list: {g, c, value (as typed so far), was (its name before)}; a
                        // task or an app: c its item, kind, auto (features/list/list.js's startItemRename); the gatherer: c null
if (PANE) state.selected = [PANE_URL.get("gatherer") || "", PANE_URL.get("channel") || ""];
// The actors open side by side (panes, below): this page's own view (`here`, its actor state.selected), the
// first, and the others (`others`), each the page in a frame; `focus` the one a click in the list shows its
// actor in. `home` and `actors`: the stream's last home and each other pane's last agent, as sent (JSON), for
// a frame that is not ready when they come. `checked`: the panes kept in this browser opened again.
const MAX_PANES = 4;
const panes = { here: null, others: [], focus: null, home: null, actors: new Map(), checked: false, top: null };

export {
  AGO_MS, GROUP_ORDER, MAX_PANES, NOT_COUNTED, PANE, PANE_URL, PREAMBLE, SNAPSHOT, label, panes, state,
  uncounted,
};

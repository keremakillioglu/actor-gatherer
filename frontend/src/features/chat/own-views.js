import { SNAPSHOT } from "../../core/page/state.js";
import {
  ago, clock, compact, el, full, get, harnessBadge, harnessLogo, harnessName, itemType, svgEl,
} from "../../core/page/helpers.js";
import { statusOf } from "../list/seen.js";
import {
  askingNote, backgroundNote, columns, contextCard, contextItem, errorNote, sizeCard, typeChips,
} from "./chat.js";
import { firstLine, foldedOutput, markdown, notesSwitch, plural, transcriptBlocks } from "../transcript/transcript.js";
import { addChatView } from "./views.js";
import { actorLogo } from "../apps/app-actors.js";

// ------------------------------------------------------------------ the reader's own views
// What a view gets to draw with -- and, for one in a file of its own, how it adds itself.
// (set as the page starts, below: what every view is drawn with is there by then)
let agDashboard = null;
// The reader's own views: each file in <home>/dashboard/views/, loaded once the page is up. One that
// does not load, or throws, is reported and left out.
async function loadOwnViews() {
  if (SNAPSHOT) return;
  let names;
  try { names = await get("/api/views"); } catch (err) { return; }
  for (const name of names) {
    await new Promise((done) => {
      const tag = document.createElement("script");
      tag.src = `/views/${encodeURIComponent(name)}`;
      tag.onload = done;
      tag.onerror = () => { console.error(`chat view ${name}: not loaded`); done(); };
      document.head.append(tag);
    });
  }
}
// What this module did as the page's script ran, in that order: page.js runs it once every module is loaded.
export function start() {
  agDashboard = window.agDashboard = Object.freeze({
    chatView: addChatView,
    el, svgEl, markdown, clock, ago, full, compact, plural, firstLine,
    contextItem, columns, typeChips, itemType, transcriptBlocks, foldedOutput, notesSwitch, sizeCard, contextCard,
    statusOf, harnessName, harnessLogo, harnessBadge, actorLogo, backgroundNote, askingNote, errorNote,
  });
}

export { agDashboard, loadOwnViews };

import { el } from "./helpers.js";

// ------------------------------------------------------------------ code, coloured
// The page's own highlighter, its shell reader and how it lays a command out, a command's output in its terminal's
// colours, and a fenced block in a message: src/core/ui/highlight/ (ag_dashboard/DESIGN.md, A5), reached through
// src/bridge.ts's window.agNext.ui. Each function is declared here, so the sections before this one can call it.
function langOfPath(...a) { return window.agNext.ui.langOfPath(...a); }
function guessWeb(...a) { return window.agNext.ui.guessWeb(...a); }
function hlLines(...a) { return window.agNext.ui.hlLines(...a); }
function hlPart(...a) { return window.agNext.ui.hlPart(...a); }
const shellSpan = (text) => { const s = el("span", { class: "sh-t" }); s.innerHTML = hlLines(text, "shell").join("\n"); return s; };

function tildePath(...a) { return window.agNext.ui.tildePath(...a); }
function shellHtml(...a) { return window.agNext.ui.shellHtml(...a); }
function ansiHtml(...a) { return window.agNext.ui.ansiHtml(...a); }
function outputHtml(...a) { return window.agNext.ui.outputHtml(...a); }
// What this module did as the page's script ran, in that order: page.js runs it once every module is loaded.
export function start() {
  // a code block's Copy (codeFence's, callView's): the command as written (data-copy), else the block's own text; its
  // Fold and Show all
  document.addEventListener("click", (ev) => window.agNext.ui.codeClick(ev));
}

export { ansiHtml, guessWeb, hlLines, hlPart, langOfPath, outputHtml, shellHtml, shellSpan, tildePath };

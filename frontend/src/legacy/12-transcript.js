// ------------------------------------------------------------------ the Transcript view
// The conversation as a terminal running the harness shows it: what was asked, what the agent said
// (markdown), each tool call with its result under it, its thinking folded away. The data has made
// every harness's events the same parts (data.parts), each call with its shape (SHAPES says how each is shown).
const NOTES_KEY = "ag-dashboard-transcript-notes";
let showNotes = (() => { try { return localStorage.getItem(NOTES_KEY) === "1"; } catch (e) { return false; } })();
const RESULT_LINES = 4;                            // a result's lines shown before "+N lines"
// Text escaped for HTML, and markdown as the page draws a message (a harness's reply block in it as a card, `unplanned`
// its words less the block's tags): src/core/ui/html.ts and md.ts (ag_dashboard/DESIGN.md, A5), reached through
// src/bridge.ts's window.agNext.ui.
function escapeHtml(t) { return window.agNext.ui.escapeHtml(t); }
// Where each harness keeps its memory of a directory (harness_kit's `memory_folder`): [the folder's pattern, harness].
const memoryFolders = () => Object.entries((state.home && state.home.harness_info) || {})
  .filter(([, h]) => h.memory_folder).map(([n, h]) => [new RegExp(`${h.memory_folder}$`), n]);
function unplanned(...a) { return window.agNext.ui.unplanned(...a); }
function markdown(...a) { return window.agNext.ui.markdown(...a); }
const firstLine = (t, n = 160) => { const l = String(t ?? "").split("\n")[0]; return l.length > n ? l.slice(0, n) + "…" : l; };
// a tool's output as lines, less the terminal's escape codes (colors, line clears) it may have printed
const lines = (t) => (t ? String(t).replace(/\x1b\[[0-9;?]*[ -\/]*[@-~]/g, "").replace(/\n+$/, "").split("\n") : []);
const plural = (n, w) => `${full(n)} ${w}${n === 1 ? "" : "s"}`;
const str = (v) => typeof v === "string" ? v : v === undefined || v === null ? "" : JSON.stringify(v);
const shortPath = (p) => { const s = str(p); const cwd = (state.txCwd || "").replace(/\/$/, ""); return cwd && s.startsWith(cwd + "/") ? s.slice(cwd.length + 1) : s; };
// A result folded to its first lines; the rest one click away. `id` keeps it open across redraws.
function foldedOutput(text, id, cls = "") {
  const all = lines(text);
  if (!all.length) return el("pre", { class: cls, text: "(no output)" });
  if (all.length <= RESULT_LINES + 1) return el("pre", { class: cls, text: all.join("\n") });
  return el("details", { id }, el("summary", {}, el("pre", { class: cls, text: all.slice(0, RESULT_LINES).join("\n") }),
    el("span", { class: "more", text: `… +${plural(all.length - RESULT_LINES, "line")} (click to expand)` })),
    el("pre", { class: cls, text: all.slice(RESULT_LINES).join("\n") }));
}
// A change as lines taken out and put in, what both share at either end left as context.
function diffLines(before, after) {
  const a = lines(before), b = lines(after);
  let s = 0; while (s < a.length && s < b.length && a[s] === b[s]) s++;
  let e = 0; while (e < a.length - s && e < b.length - s && a[a.length - 1 - e] === b[b.length - 1 - e]) e++;
  const box = el("div", { class: "diff" });
  const keep = (l) => box.append(el("div", { class: "ctx", text: "  " + l }));
  a.slice(Math.max(0, s - 2), s).forEach(keep);
  for (const l of a.slice(s, a.length - e)) box.append(el("div", { class: "del", text: "- " + l }));
  for (const l of b.slice(s, b.length - e)) box.append(el("div", { class: "add", text: "+ " + l }));
  a.slice(a.length - e, a.length - e + 2).forEach(keep);
  return { box, added: b.length - s - e, removed: a.length - s - e };
}
// A patch (codex's apply_patch, a unified diff) colored by its lines' marks.
function patchView(text) {
  const box = el("div", { class: "diff" });
  for (const l of lines(text)) box.append(el("div", { class: l.startsWith("+") && !l.startsWith("+++") ? "add"
    : l.startsWith("-") && !l.startsWith("---") ? "del" : l.startsWith("@@") || l.startsWith("***") ? "hunk" : "ctx", text: l }));
  return box;
}
function todoView(todos) {
  const box = el("div", { class: "todo" });
  for (const t of Array.isArray(todos) ? todos : []) {
    const st = t.status || "";
    const done = st === "completed", doing = st === "in_progress";
    box.append(el("div", { class: done ? "done" : doing ? "doing" : "", text: `${done ? "☒" : "☐"} ${t.content || t.step || t.activeForm || str(t)}` }));
  }
  return box;
}
// How a call is shown, by its shape (harness_kit's Shape: the harness's rules read each tool's input into it, data.py's
// `view`): the argument beside its title, a note on the right, and (optionally) what goes under it instead of its
// plain result. The title is its harness's (`view.title`), as is any argument a shape's own does not give (`view.arg`).
// A call no rules read (pi's, opencode's): its name and inputs.
const found = (unit) => (text, id) => { const n = lines(text).length; return el("details", { id }, el("summary", { text: `${unit === "line" ? "Read" : "Found"} ${plural(n, unit)}` }), el("pre", { text })); };
const SHAPES = {
  shell: (v) => ({ arg: firstLine(str(v.command), 200), note: v.description, doing: v.description }),
  script: (v) => ({ arg: firstLine(str(v.code).trim(), 200) }),       // a script that calls no tool (one that does: its calls)
  read: (v) => ({ arg: shortPath(v.path) + (v.offset ? ` (from line ${v.offset})` : ""), result: found("line") }),
  write: (v) => ({ arg: shortPath(v.path), quiet: true,
    body: (id) => { const l = lines(v.content); return el("details", { id: id + "-w" }, el("summary", { text: `Wrote ${plural(l.length, "line")}` }), diffLines("", str(v.content)).box); } }),
  edit: (v) => { const ds = (v.edits || []).map((e) => diffLines(str(e.old), str(e.new)));
    const added = ds.reduce((n, d) => n + d.added, 0), removed = ds.reduce((n, d) => n + d.removed, 0);
    return { arg: shortPath(v.path), quiet: true,
      body: () => el("div", {}, el("div", { text: `${plural(added, "addition")}, ${plural(removed, "removal")}${v.all ? " (all)" : ""}` }), ...ds.map((d) => d.box)) }; },
  patch: (v) => ({ arg: (str(v.patch).match(/\*\*\* (?:Update|Add|Delete) File: (.+)/) || [, ""])[1], body: () => patchView(str(v.patch)), quiet: true }),
  search: (v) => ({ arg: `pattern: "${str(v.pattern)}"${v.path ? `, path: "${shortPath(v.path)}"` : ""}${v.glob ? `, glob: "${v.glob}"` : ""}`,
    result: (text, id) => { const n = lines(text).length; return el("details", { id }, el("summary", { text: `Found ${plural(n, v.finds === "files" ? "file" : "line")}` }), el("pre", { text })); } }),
  web: (v) => ({ arg: v.url ? str(v.url) : `"${str(v.query)}"` }),
  agent: () => ({}),
  todo: (v) => ({ body: () => todoView(v.items), quiet: true }),
  skill: (v) => ({ arg: str(v.name) }),
  ask: () => ({}),
};
function summary(call) {
  const inner = (call.calls || []).filter((c) => c.input !== null && c.input !== undefined);
  if (inner.length) {                    // a script (codex's code mode), shown as the calls it makes
    const first = summary(inner[0]), more = call.calls.length - 1;
    return more ? { ...first, arg: `${first.arg || ""}${first.arg ? " " : ""}+ ${plural(more, "more call")}`, body: undefined, quiet: false } : first;
  }
  const v = call.view || {}, shaped = SHAPES[v.shape];
  if (shaped) { try { const s = shaped(v); return { ...s, title: v.title || call.name, arg: v.arg ?? s.arg }; } catch (e) { /* shown as any other */ } }
  const input = call.input && typeof call.input === "object" ? call.input : { input: call.input };
  const args = v.arg ?? (typeof call.input === "string" ? call.input : Object.entries(input).map(([k, v]) => `${k}: ${firstLine(str(v), 60)}`).join(", "));
  return { title: v.title || String(call.name || "tool").replace(/^mcp__([^_]+(?:_[^_]+)*)__/, "$1 · "), arg: firstLine(str(args), 200) };
}
// One tool call and, under it, its result: running while there is none and the agent is.
function callBlock(call, result, id, running) {
  const s = summary(call);
  const glyph = result ? (result.error ? "dot-err" : "dot-ok") : running ? "dot-run" : "dot-ok";
  const head = el("div", { class: "head" }, el("b", { text: s.title }), s.arg !== undefined && s.arg !== "" ? el("span", { class: "arg", text: `(${s.arg})` }) : null,
    s.note ? el("span", { class: "note", text: s.note }) : null);
  const blk = el("div", { class: "blk" }, el("span", { class: "g " + glyph, text: "●" }), head);
  const under = [];
  if (s.body) under.push(s.body(id));
  if (result && result.error) under.push(foldedOutput(result.text, id + "-r", "err"));
  else if (result && s.result) under.push(s.result(result.text, id + "-r"));
  else if (result && !s.quiet) under.push(foldedOutput(result.text, id + "-r"));
  else if (!result && !running) under.push(el("pre", { text: "(no result recorded)" }));
  else if (!result) under.push(el("pre", { text: "Running…" }));
  for (const u of under) blk.append(el("div", { class: "res" }, el("span", { class: "g", text: "⎿" }), u));
  return blk;
}
// A tool call as one line, in the agent's words: its description where it gave one (Bash does), else
// its title and argument ("Read y.py").
const callLine = (call) => { const s = summary(call); return firstLine(s.doing || (s.arg ? `${s.title} ${s.arg}` : s.title), 160); };
const RUN_SHOWN = 5;                                 // a stretch's last calls listed; the earlier ones behind "+N more"

// A stretch of tool calls between two messages, as Claude Code shows it: each call one line saying
// what it is for, its dot green, red when it failed, blinking while it runs; the call itself and its
// output folded under the line. Thinking in the stretch is a folded line of its own.
function runBlock(run, results, running) {
  const line = ({ part, id }) => {
    if (part.kind !== "call") return el("div", { class: "blk think-blk" }, el("span", { class: "g think", text: "✻" }),
      el("details", { id }, el("summary", { text: "Thinking…" }), el("div", { class: "body", text: part.text })));
    const result = part.id ? results.get(part.id) : null;
    const glyph = result ? (result.error ? "dot-err" : "dot-ok") : running && run.last ? "dot-run" : "dot-ok";
    return el("div", { class: "blk call-line" }, el("span", { class: "g " + glyph, text: "●" }),
      el("details", { id: id + "-l" }, el("summary", { class: result && result.error ? "bad" : "" }, callLine(part)),
        el("div", { class: "calls" }, callBlock(part, result, id, running && run.last))));
  };
  const lines = run.map(line);
  if (lines.length <= RUN_SHOWN + 1) return lines;
  const earlier = lines.slice(0, lines.length - RUN_SHOWN);
  return [el("div", { class: "blk more" }, el("span", { class: "g", text: " " }),
    el("details", { id: `${run[0].id}-more` }, el("summary", { text: `+${earlier.length} more` }), ...earlier)),
    ...lines.slice(-RUN_SHOWN)];
}

// Blocks already drawn, by their id, with what they were drawn from (`sig`): handed back as the same nodes
// while that is unchanged, so a redraw builds only what is new and patch() keeps the rest in place. One
// per view, emptied when the actor changes; a block not asked for in a draw is forgotten.
function blockCache() {
  let owner = null, now = new Map(), before = new Map();
  return {
    begin(key) { if (key !== owner) { owner = key; before = new Map(); } else before = now; now = new Map(); },
    get(k, sig, make) {
      const had = before.get(k);
      const v = had && had.sig === sig ? had.v : make();
      now.set(k, { sig, v });
      return v;
    },
  };
}
// The transcript's blocks, in order: messages as they are; each stretch of tool calls between two
// of them folded into one line (runBlock), each result drawn with its call wherever it was stored.
function transcriptBlocks(items, running, cache = null) {
  const keep = (k, sig, make) => cache ? cache.get(k, sig, make) : make();
  const results = new Map();
  for (const it of items) for (const p of it.parts) if (p.kind === "result" && p.id) results.set(p.id, p);
  const calls = new Set(items.flatMap((it) => it.parts.filter((p) => p.kind === "call" && p.id).map((p) => p.id)));
  const out = [];
  let notes = [], run = [];
  const flushNotes = () => {
    if (!notes.length) return;
    const id = `tx-n-${notes[0].id}`, these = notes;
    out.push(keep(id, these.map((n) => n.id + ":" + n.text.length).join(","), () => el("div", { class: "blk notes" }, el("span", { class: "g", text: "※" }),
      el("details", { id }, el("summary", { text: these.length === 1 ? `${these[0].name}: ${firstLine(these[0].text, 120)}` : `${these.length} notes: ${[...new Set(these.map((n) => n.name))].join(", ")}` }),
        ...these.map((n) => el("pre", { text: `${n.name}\n${n.text}` }))))));
    notes = [];
  };
  const flushRun = (last = false) => {
    if (!run.length) return;
    if (run.some((x) => x.part.kind === "call")) {
      run.last = last;
      const these = run;                             // the same calls with the same results: the same lines
      const sig = these.map(({ part }) => { const r = part.id && results.get(part.id); return `${part.kind}${r ? (r.error ? "!" : "+") + r.text.length : "-"}`; }).join(",")
        + (running && last ? ",running" : "");
      out.push(...keep(`${these[0].id}-run`, sig, () => runBlock(these, results, running)));
    } else for (const { part, id } of run) out.push(keep(id, part.text.length, () => el("div", { class: "blk think-blk" }, el("span", { class: "g think", text: "✻" }),
      el("details", { id }, el("summary", { text: "Thinking…" }), el("div", { class: "body", text: part.text })))));
    run = [];
  };
  items.forEach((it, n) => {
    const base = it.row_id !== null ? `r${it.row_id}` : `p${n}`;
    it.parts.forEach((p, j) => {
      const id = `tx-${base}-${j}`;
      const isNote = p.kind === "note" || (p.kind === "text" && p.role === "system");
      if (isNote) { if (showNotes) notes.push({ id, name: p.name || "system", text: p.text }); return; }
      if (p.kind === "call" || (p.kind === "thinking" && p.text.trim())) { flushNotes(); run.push({ part: p, id }); return; }
      if (p.kind === "thinking" || (p.kind === "result" && p.id && calls.has(p.id))) return;   // encrypted; or drawn with its call
      flushRun(); flushNotes();
      const sig = `${p.kind}${p.role}${p.error ? "!" : ""}:${p.text}`;
      if (p.kind === "text" && p.role === "user") out.push(keep(id, sig, () => el("div", { class: "user" }, el("span", { class: "g", text: "❯" }), el("div", { class: "body", text: p.text }))));
      else if (p.kind === "text") out.push(keep(id, sig, () => el("div", { class: "blk" }, el("span", { class: "g text", text: "●" }), markdown(p.text))));
      else if (p.kind === "result")                    // its call is not loaded: shown alone
        out.push(keep(id, sig, () => el("div", { class: "blk" }, el("span", { class: "g", text: " " }), el("div", { class: "res" }, el("span", { class: "g", text: "⎿" }), foldedOutput(p.text, id, p.error ? "err" : "")))));
    });
  });
  flushRun(true);
  flushNotes();
  return out;
}
// The switch for the harness's system messages and ag's notes, between a transcript's messages.
function notesSwitch() {
  const box = el("input", { type: "checkbox" });
  box.checked = showNotes;
  box.addEventListener("change", () => {
    showNotes = box.checked;
    try { localStorage.setItem(NOTES_KEY, showNotes ? "1" : "0"); } catch (e) { /* this page only */ }
    keepingPlace(renderMain);
  });
  return el("label", { title: "The harness's system messages and ag's notices" }, box, "Show system and ag notes");
}

// ------------------------------------------------------------------ moves between groups
// In the home's one database (state.home.merged: `ag home merge`'s), what is dragged in the list may be dropped into
// another group -- actors, each with its task (which moves whole), or a folder with all in it -- once the reader says
// so (the Notes design "Groups: design", section 2): a dialog says who moves, from which group to which, how many
// others each has, and how many of those moving are working now, which rebuild their context at their next call. Then
// the server moves them (/api/groups, groups.py), and a pane showing one of them follows it. An app of a task or a
// folder that moves goes with it, its actors keeping it -- one with many instances (Browser, DocWriter, Editor). An
// app's own agent (one it started: 19-app-actors.js's appRole) and its window go together, as a task does (withOwn):
// so a group's only one of its app (Notes, Slack, Paper news) goes too when its own agent does -- into a group with one
// of its own, it closes, and its agent works with that one -- and otherwise stays with its group, a drag that would
// take it staying in its group, as every drag did before.
const moveAsk = { dialog: null, busy: false };
const WORKING = new Set(["Running", "Waiting for you", "Background"]);     // groupOf's: working now

// Whether what is dragged (listDrag) may go into group `g` from another -- a group, not the list's head (GFS) --
// asked first (askMove)
function canCross(g) {
  const d = listDrag;
  if (!d || d.g === g.name || !state.home.merged || d.gs || g.alone || !state.home.gatherers.some((x) => x.name === g.name)) return false;
  const from = state.home.gatherers.find((x) => x.name === d.g);
  if (!from) return false;
  if (d.folder !== null) return folderCanMove(from, d.folder);
  const items = withOwn(from, d.cs);
  return items.length > 0 && items.every((c) => isAppItem(c) ? appCanMove(from.name, c, items) : !!actorOf(from, c) && !isCoordinator(actorOf(from, c)));
}
// What dragging `cs` (items of group `g`) takes (groups.py's `actors`): each one's task, which moves whole, and an app's
// own agent with its window, the window with its agents, as they are one task
function withOwn(g, cs) {
  let out = withTasks(g, cs);
  for (;;) {
    const more = new Set(out);
    for (const a of g.agents) {
      const r = appRole({ session: { role: a.role } });
      if (!r) continue;
      if (more.has(appItem(r.key))) more.add(a.channel);
      else if (more.has(a.channel) && appInfo(g.name, r.key)) more.add(appItem(r.key));
    }
    const grown = withTasks(g, [...more]);
    if (grown.length === out.length) return out;
    out = grown;
  }
}
// whether the app item `k` (APP_ITEM + its id) of group `gname` may go to another group with `items`: one with many
// instances, or a group's only one of its app with its own agent among them (groups.py's `apps`) -- else it stays
const appCanMove = (gname, k, items = []) => ((o) => !!o && (o.app.instances === "many" || ownAgentIn(gname, o.id, items)))(
  appInfo(gname, String(k).slice(APP_ITEM.length)));
const ownAgentIn = (gname, id, items) => ((g) => !!g && g.agents.some((a) => items.includes(a.channel)
  && ((r) => !!r && r.key === id)(appRole({ session: { role: a.role } }))))(state.home.gatherers.find((x) => x.name === gname));
// whether folder `id` of group `g` may go: it is there, and every app in it, or in its actors' tasks, may go too
function folderCanMove(g, id) {
  if (!folderById(g.name, id)) return false;
  const filed = gathererApps(g.name).filter((o) => ((f) => f !== null && within(g.name, f, id))(appFolder(g.name, o.id)));
  const items = withOwn(g, [...actorsWithin(g, id).map((a) => a.channel), ...filed.map((o) => appItem(o.id))]);
  return items.every((c) => !isAppItem(c) || appCanMove(g.name, c, items));
}
// the apps a move takes (the server's plan: [{id, app, title, joins?}]), said: "The app Browser goes with it." -- and
// one that closes for the group `to`'s own of its app (`joins`): "Its Paper news closes: it works with the lab group's."
function appsLine(apps, many, to = null) {
  if (!apps || !apps.length) return null;
  const label = (x) => ((a) => (a && a.label) || x.app)(window.agNext && window.agNext.apps.named(x.app));
  const named = (x) => label(x) + (x.title && x.title !== label(x) ? ` (${x.title})` : "");
  const going = apps.filter((x) => !x.joins), joining = apps.filter((x) => x.joins);
  const list = going.map(named), out = [];
  if (list.length) out.push(`The ${list.length === 1 ? "app" : "apps"} ${list.length === 1 ? list[0] : `${list.slice(0, -1).join(", ")} and ${list[list.length - 1]}`} `
    + `${list.length === 1 ? "goes" : "go"} with ${many ? "them" : "it"}.`);
  for (const x of joining) out.push(`${many ? "Their" : "Its"} ${named(x)} closes, as the ${to ? titleOf(to) : "other"} group has its own: `
    + `${many ? "they" : "it"} will work with that one.`);
  return out.join(" ");
}
const mvCount = (n, one, many = one + "s") => `${n} ${n === 1 ? one : many}`;
// the coordinator agents of `from` over folder `fid` or a folder in it: they go where it goes (groups.py's `_crews`)
const crewsWithin = (from, fid) => from.agents.filter((a) => isCoordinator(a) && String(a.over || "").startsWith("folder:")
  && within(from.name, +a.over.slice("folder:".length), fid));
const crewsSaid = (crews, made) => !crews.length ? null : crews.length === 1
  ? `Its coordinator agent ${made ? "becomes the new group's" : "goes with it"}.`
  : `The ${crews.length} coordinator agents over it and its folders go with it${made ? ", the one over it the new group's" : ""}.`;

// What is dragged (`d`, listDrag's), dropped into folder `id` of group `g` (null: its top): the dialog, then the move --
// into that folder's group, as the default rule has it (an actor on its own: it joins; kept on its own there only from
// Manage groups)
async function askMove(d, g, id) {
  const from = state.home.gatherers.find((x) => x.name === d.g);
  if (!from) return;
  const body = { gatherer: d.g, to: g.name, ...(d.folder !== null ? { folder: d.folder } : { channels: withOwn(from, d.cs) }) };
  const title = `Move to the ${titleOf(g)} group?`;
  mvOpen("Move to another group");
  mvDraw({ title, note: "Working out who moves…" });
  let plan;
  try { plan = await post("/api/groups", { ...body, do: "plan" }); } catch (err) { mvDraw({ title, note: `Can't move: ${err.message}` }); return; }
  const crews = d.folder !== null ? crewsWithin(from, d.folder) : [];
  const said = crewsSaid(crews, false);
  const shown = { title: from.alone ? `Join the ${titleOf(g)} group?` : title, lines: [...moveLines(from, g, plan), ...(said ? [said] : [])],
    names: moveNames(from, plan.actors.filter((c) => !crews.some((a) => a.channel === c))), goLabel: from.alone ? "Join" : "Move" };
  const go = mvGo(shown, "Moving…", "Not moved", async () => {
    const got = await post("/api/groups", { ...body, do: "move", into: id });
    return { to: g.name, actors: plan.actors, apps: (got.moved && got.moved.apps) || [], joined: (got.moved && got.moved.joined) || {},
      said: `Moved to the ${titleOf(g)} group` };
  }, d.g);
  mvDraw({ ...shown, go });
}
// A folder dropped outside every group (`d`, listDrag's): the dialog, then the folder made a group of its own (groups.py's
// `split`) -- the server's, named after it
function askSplit(d) {
  const from = state.home.gatherers.find((x) => x.name === d.g), f = from && folderById(d.g, d.folder);
  if (f) askOwn(from, f, false);
}
// Folder `f` of group `g` given a group of its own (groups.py's `own`), where it is (`here`: its line's button) -- or,
// dropped outside every group, at the list's top (`split`): the dialog, then the group, named after it
function askOwn(g, f, here = true) {
  const inside = withTasks(g, actorsWithin(g, f.id).map((a) => a.channel)).filter((c) => !isAppItem(c));
  const going = [...new Set([...withTasks(g, actorsWithin(g, f.id).map((a) => a.channel)).filter(isAppItem)
    .map((c) => c.slice(APP_ITEM.length)), ...gathererApps(g.name).filter((o) => ((x) => x !== null && within(g.name, x, f.id))(appFolder(g.name, o.id))).map((o) => o.id)])]
    .map((i) => appInfo(g.name, i)).filter(Boolean).map((o) => ({ id: o.id, app: o.app.name, title: o.name || o.title }));
  const actors = g.agents.filter((a) => inside.includes(a.channel)), n = actors.length;
  const others = g.agents.filter((a) => !isCoordinator(a) && !inside.includes(a.channel)).length;
  const lines = [(here ? `${f.name} becomes a group of its own where it is, named after it, with the settings of ${titleOf(g)}.`
    : `The folder ${f.name} becomes a group of its own, ${f.name}, and what is in it goes to the new group's top.`)
    + (n ? ` ${n === 1 ? "Its actor leaves" : `Its ${n} actors leave`} the ${titleOf(g)} group (${mvCount(others, "other")}) for it.`
      : here ? " No actor is in it yet: those started there will share context with each other only." : ` It leaves the ${titleOf(g)} group.`)];
  if (n) lines.push(`${n === 1 ? "It" : "They"} will no longer share context with the actors of ${titleOf(g)}`
    + `${n === 1 ? "" : ", only with each other"}.`, rebuildLine(g, actors));
  const appsSaid = appsLine(going, n > 1), crewSaid = crewsSaid(crewsWithin(g, f.id), true);
  if (appsSaid) lines.push(appsSaid);
  if (crewSaid) lines.push(crewSaid);
  const shown = { title: here ? `Give ${f.name} a group of its own?` : `Make ${f.name} a group of its own?`, lines,
    names: moveNames(g, inside), goLabel: "Make a group" };
  mvOpen("A folder made a group of its own");
  const go = mvGo(shown, "Making the group…", "Not made", async () => {
    const got = await post("/api/groups", { gatherer: g.name, do: here ? "own" : "split", folder: f.id });
    const made = here ? got.own : got.split;
    return { to: made.group, actors: made.actors, apps: made.apps || [], said: `${f.name} is a group of its own` };
  }, g.name);
  mvDraw({ ...shown, go });
}
// ---- a group dropped into another (groups.py's `merge`): made a folder of it, named after it, everything in it
// Whether the group dragged (listDrag's `gs`: one) may go into group `g`: in the home's one database, neither on its own,
// and not into itself
function canMerge(g, id = null) {
  const d = listDrag;
  if (!d || !d.gs || d.gs.length !== 1 || !state.home.merged || g.name === GF || g.alone || d.gs[0] === g.name) return false;
  const from = state.home.gatherers.find((x) => x.name === d.gs[0]), p = from && placeOf(from.name);
  return !!from && !from.alone && state.home.gatherers.some((x) => x.name === g.name) && !insideOf(g.name, from.name)
    && !(p && p.in === g.name && p.folder === id);
}
// The group `name` dropped into folder `id` of group `g` (null: its top): the dialog, then the merge, as the default rule
// has it -- a folder of `g` takes `g`'s group (kept a group of its own there: Manage groups, `ag groups merge --keep`).
// `back`: a group inside `g`'s folder, made part of `g` again (Manage groups' switch)
async function askMerge(name, g, id, back = false) {
  const from = state.home.gatherers.find((x) => x.name === name);
  if (!from) return;
  const title = back ? `Make ${titleOf(from)} part of ${titleOf(g)} again?` : `Merge ${titleOf(from)} into ${titleOf(g)}?`;
  mvOpen("A group merged into another");
  mvDraw({ title, note: "Working out what moves…" });
  let plan;
  try { plan = await post("/api/groups", { gatherer: name, to: g.name, into: id, do: "merge_plan" }); } catch (err) {
    mvDraw({ title, note: `Can't merge: ${err.message}` });
    return;
  }
  const actors = from.agents.filter((a) => !isCoordinator(a)), n = actors.length;
  const others = g.agents.filter((a) => !isCoordinator(a)).length, inside = id === null ? null : folderById(g.name, id);
  const lines = [`${titleOf(from)} becomes a folder of ${titleOf(g)}, named ${plan.folder}${inside ? `, in ${inside.name}` : ""}, `
    + "with everything in it. The group itself is then gone from the list."];
  if (n) lines.push(`Its ${mvCount(n, "actor")} and the ${mvCount(others, "actor")} of ${titleOf(g)} will share context with each other.`,
    rebuildLine(from, actors));
  const apps = appsLine(plan.apps.filter((x) => x.app !== "notes"), true, g);
  if (apps) lines.push(apps);
  if (plan.apps.some((x) => x.app === "notes")) lines.push(`Its notes go under a page named ${titleOf(from)} in the notes of ${titleOf(g)}.`);
  if (groupCrew(from)) lines.push("Its coordinator agent becomes the one over the new folder.");
  const shown = { title, lines, names: moveNames(from, actors.map((a) => a.channel)), goLabel: "Merge" };
  const go = mvGo(shown, "Merging…", "Not merged", async () => {
    const got = await post("/api/groups", { gatherer: name, to: g.name, into: id, do: "merge" });
    const m = got.merged;
    if (collapsed.delete(g.name)) {                  // the group it went into open, and the folder it became
      try { localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...collapsed])); } catch (e) { /* kept for this page only */ }
    }
    showFolder(g.name, id, true);
    showFolder(g.name, m.folder, true);
    return { to: g.name, actors: m.actors, apps: m.apps || [], joined: m.joined || {}, said: `${titleOf(from)} is a folder of ${titleOf(g)} now` };
  }, name);
  mvDraw({ ...shown, go });
}
// The dialog, made once, opened
function mvOpen(label) {
  if (!moveAsk.dialog) {
    moveAsk.dialog = el("dialog", { class: "br-dialog mv-dialog" });
    moveAsk.dialog.addEventListener("click", (ev) => { if (ev.target === moveAsk.dialog && !moveAsk.busy) moveAsk.dialog.close(); });
    moveAsk.dialog.addEventListener("cancel", (ev) => { if (moveAsk.busy) ev.preventDefault(); });
    document.body.append(moveAsk.dialog);
  }
  moveAsk.dialog.setAttribute("aria-label", label);
  moveAsk.busy = false;
  if (!moveAsk.dialog.open) moveAsk.dialog.showModal();
}
// What its button does: `act()` (-> {to, actors, said}), the dialog busy meanwhile; then the home read again, the panes
// that show an actor moved following it (from group `from`)
function mvGo(shown, doing, failed, act, from) {
  const go = async () => {
    moveAsk.busy = true;
    mvDraw({ ...shown, note: doing });
    let got;
    try { got = await act(); } catch (err) {
      moveAsk.busy = false;
      mvDraw({ ...shown, note: `${failed}: ${err.message}`, go });
      return;
    }
    moveAsk.busy = false;
    moveAsk.dialog.close();
    await loadHome();
    await followMoved(from, got.to, got.actors, got.apps || [], got.joined || {});
    renderAgents();
    setLive(got.said);
  };
  return go;
}
// The dialog drawn: its title, `lines`, the actors `names`, `note`, then Cancel and `goLabel` (`go`; none: not yet)
function mvDraw({ title, lines = [], names = null, note = "", go = null, goLabel = "" }) {
  const box = moveAsk.dialog, busy = moveAsk.busy ? { disabled: "" } : {};
  const form = el("form", { class: "newform", method: "dialog" },
    el("div", { class: "br-title" }, el("h3", { text: title }),
      el("button", { type: "button", class: "x", "aria-label": "Close", ...busy, onclick: () => box.close() }, "×")),
    ...lines.map((t) => el("p", { class: "mv-line", text: t })),
    names,
    note ? el("p", { class: "mv-note", role: "status", text: note }) : null,
    el("div", { class: "row" }, el("button", { type: "button", ...busy, onclick: () => box.close() }, "Cancel"),
      go ? el("button", { type: "submit", class: "primary", ...busy }, goLabel) : null));
  form.addEventListener("submit", (ev) => { ev.preventDefault(); if (go && !moveAsk.busy) go(); });
  box.replaceChildren(form);
  const submit = box.querySelector("button[type=submit]");
  if (submit && !moveAsk.busy) submit.focus();
}
// What the dialog says of a move (`plan`) from group `from` into `g`: the page's own counts, as the list has them
function moveLines(from, g, plan) {
  const moving = new Set(plan.actors), actors = from.agents.filter((a) => moving.has(a.channel));
  const others = (x) => x.agents.filter((a) => !isCoordinator(a) && !moving.has(a.channel)).length;
  const f = plan.folder !== undefined && plan.folder !== null ? folderById(from.name, plan.folder) : null;
  const n = actors.length, one = !f && n === 1;
  const what = f ? (n ? `The folder ${f.name} and its ${mvCount(n, "actor")}` : `The folder ${f.name}`) : one ? actorTitle(actors[0]) : `${n} actors`;
  const out = [`${what} ${one ? "moves" : "move"} from the ${titleOf(from)} group (${mvCount(others(from), "other")}) `
    + `to the ${titleOf(g)} group (${mvCount(others(g), "other")}).`];
  if (!n) return out;
  out.push(`${one ? "It" : "They"} will share context with the actors of ${titleOf(g)}, and no longer with those of ${titleOf(from)}.`);
  out.push(rebuildLine(from, actors));
  const apps = appsLine(plan.apps, !one, g);
  if (apps) out.push(apps);
  return out;
}
// how many of `actors` (of group `from`) rebuild their context at their next call, working now
function rebuildLine(from, actors) {
  const working = actors.filter((a) => WORKING.has(groupOf(from, a))).length, one = actors.length === 1;
  return working ? `${mvCount(working, "of them is", "of them are")} working now, and ${working === 1 ? "rebuilds its" : "rebuild their"} `
    + "context at the next call; the others when they next run." : `${one ? "It rebuilds its" : "Each rebuilds its"} context when it next runs.`;
}
// the actors that move (by their channels), by name, when more than one
function moveNames(from, channels) {
  const moving = from.agents.filter((a) => channels.includes(a.channel));
  if (moving.length < 2) return null;
  const shown = moving.slice(0, 6);
  return el("ul", { class: "mv-names" }, ...shown.map((a) => el("li", { text: actorTitle(a) })),
    moving.length > shown.length ? el("li", { class: "more", text: `and ${moving.length - shown.length} more` }) : null);
}
// After a move: a pane showing an actor that moved shows it in its new group, and an app's that moved (`apps`, their
// ids) is opened again there -- its panel was opened for its old group -- and one closed for the new group's own one
// (`joined`, {its id: that one's}) shows that one
async function followMoved(from, to, moved, apps = [], joined = {}) {
  const gone = new Set(moved);
  for (const p of actorPanes()) if (p.g === from && gone.has(p.c)) { p.g = to; p.call("select", to, p.c, p.view); }
  savePanes(); connect();
  if (apps.length || Object.keys(joined).length) {
    await Promise.all([readApps(from, true), readApps(to, true)]);
    for (const p of panes.apps.filter((q) => apps.includes(q.instance.id) && q.instance.gatherer === from)) swapAppPane(p, { ...p.instance, gatherer: to });
    for (const p of panes.apps.filter((q) => q.instance.id in joined && q.instance.gatherer === from)) {
      const there = appInfo(to, joined[p.instance.id]);
      if (there && panes.apps.some((q) => q.instance.id === there.id)) closeAppPane(p);   // shown already
      else if (there) swapAppPane(p, there.inst);
    }
  }
  if (state.selected && state.selected[0] === from && gone.has(state.selected[1])) await select(to, state.selected[1]);
}

// ---- outside every group: a folder dropped there is made a group of its own (askSplit), an actor is on its own (askAlone)
// Whether what is dragged may go outside every group: in the home's one database, from a group, a folder whose apps
// may go with it (folderCanMove), or one actor -- not the coordinator agent, and not one of a task with other actors (a
// task moves whole) -- with the apps of its task, and its window if it is an app's own agent, that may go (withOwn)
function canOutside() {
  const d = listDrag;
  if (!d || !state.home.merged) return false;
  if (d.gs) return d.gs.length === 1 && !!placeOf(d.gs[0]);   // a group inside a folder: back at the top, its own group kept
  const from = state.home.gatherers.find((x) => x.name === d.g);
  if (!from) return false;
  if (from.alone) return d.folder === null && !!placeOf(from.name);   // on its own in a folder: back at the top
  if (d.folder !== null) return folderCanMove(from, d.folder);
  const items = withOwn(from, d.cs || []), actors = items.filter((c) => !isAppItem(c));
  const a = actors.length === 1 ? actorOf(from, actors[0]) : null;
  return !!a && !isCoordinator(a) && items.every((c) => !isAppItem(c) || appCanMove(from.name, c, items));
}
// The place shown, while what is dragged may go there (startDrag's), saying what it does
function showOutside() {
  const can = canOutside();
  document.body.classList.toggle("drag-out", can);
  if (can) for (const n of document.querySelectorAll(".outside-drop")) {   // the list's, and Manage groups' when it is open
    n.textContent = listDrag.folder !== null || listDrag.gs ? "Outside every group: a group of its own" : "Outside every group: on its own";
  }
}
// The place to drop it, over the list's head: shown while such a drag goes on (body.drag-out)
function outsideDrop() {
  if (SNAPSHOT || !state.home.merged) return null;
  const n = el("div", { class: "outside-drop", text: "Outside every group: a group of its own" });   // (Manage groups has one too)
  n.addEventListener("dragenter", (ev) => { if (canOutside()) { ev.preventDefault(); n.classList.add("drop-on"); } });
  n.addEventListener("dragover", (ev) => { if (canOutside()) { ev.preventDefault(); ev.dataTransfer.dropEffect = "move"; } });
  n.addEventListener("dragleave", (ev) => { if (!n.contains(ev.relatedTarget)) n.classList.remove("drop-on"); });
  n.addEventListener("drop", (ev) => {
    if (!canOutside()) return;
    ev.preventDefault();
    ev.stopPropagation();                            // the list's head it is over: not dropped there too
    const d = listDrag;
    d.later = false;
    endDrag();
    if (d.gs) placeGroup(d.gs[0], "", null);        // nothing anyone shares changes: no question
    else if (d.folder !== null) askSplit(d);
    else if (isAloneName(d.g)) placeGroup(d.g, "", null);
    else askAlone(d);
  });
  return n;
}

// ---- an actor on its own from its start (groups.py's `start_alone`): the list head's "+" beside its folder button. Its box
// (07-panes.js's railNewBox, `alone`) asks the directory it works in -- the latest active actor's to start with -- and the
// harness: one that names its session only at its first call (codex's thread) is not offered, as its record could not be
// in before that call. It runs under a group of the home's (ag runs every session in one): the shown actor's, else the
// latest active -- and shares with no one. Only on the home's one database, as every group of one: none with a database
// per gatherer, as no drop outside every group (outsideDrop).
// its pop-up's key, and what `state.starting` names while it starts: no group's (a name holds no ":", a group of one's
// ends in an id)
const ALONE_NEW = "self:new";
const aloneHarnesses = () => startable().filter((h) => !(harnessInfo(h) || {}).picks_id);
const everyActor = () => ({ agents: state.home.gatherers.flatMap((g) => g.agents) });
function aloneUnder() {
  const real = state.home.gatherers.filter((g) => !g.alone);
  const shown = state.selected && real.find((g) => g.name === state.selected[0]);
  return shown || [...real].sort((x, y) => (y.last || 0) - (x.last || 0))[0] || null;
}
// why a harness that runs here is not in the box, if one is
function aloneCant() {
  const cant = startable().filter((h) => !aloneHarnesses().includes(h));
  return cant.length ? el("div", { class: "note", text: `${cant.map(harnessName).join(" and ")} `
    + (cant.length === 1 ? "names its session" : "name their sessions") + " only at the first call: start it in a group, then drag it out." }) : null;
}
function aloneNew() {
  if (SNAPSHOT || PANE || !state.home.merged) return null;
  const hs = aloneHarnesses(), g = aloneUnder();
  const why = !g ? "Make a group first: an actor on its own runs under one"
    : !hs.length ? (startable().length ? `${startable().map(harnessName).join(" and ")}: started in a group only` : noHarness()) : "";
  const busy = state.starting && state.starting.gatherer === ALONE_NEW;
  return el("button", { class: "alone-new" + (busy ? " busy" : ""), type: "button", "data-pop": ALONE_NEW,
    ...(why || state.starting ? { disabled: "" } : {}), title: why || "New actor on its own: it shares context with no group",
    "aria-label": "New actor on its own", "aria-haspopup": "dialog", "aria-expanded": String(rowPop.key === ALONE_NEW),
    onclick: (ev) => {
      if (rowPop.key === ALONE_NEW) return closePop();
      openPop(ALONE_NEW, ev.currentTarget, railNewBox(g, hs, hs[0], startCwd(everyActor()), "", true));
    } },
    el("span", { class: "plus", "aria-hidden": "true", text: "+" }), strokeIcon(ICONS.agent, 15));
}

// ---- an actor on its own: a group of one (groups.py's `alone`, `self:<channel>`), listed as its row alone (no head: its
// title says what it is);
// it has no coordinator agent. Dragged into a group, it is asked first, as any move between groups (askMove).
const ALONE_SAYS = "On its own: it shares context with no other actor, and no other actor with it. Drag it into a group to bring it back.";
const aloneActor = (g) => g.agents.find((x) => !isCoordinator(x));
function aloneBox(g) {
  const a = aloneActor(g);
  return el("div", { class: "gatherer alone", title: ALONE_SAYS },
    ...(a ? rowsOf(g, a, groupOf(g, a)) : []), ...appRowsIn(g, null));   // its task, with its apps; its apps in none
}
function railAlone(g) {
  const a = aloneActor(g);
  return el("section", { class: "r-gatherer r-alone", "aria-label": "On its own", title: ALONE_SAYS },
    ...(a ? railRowsOf(g, a) : []), ...railAppsIn(g, null));
}
// Once closed (groupOf's Closed; saved too, Saved), an actor on its own leaves the top of the list, as a group's closed
// actors go into its closed line: every such one is in a line at the list's end -- "▸ N closed", and "▸ N saved" --
// opened again from there as any closed actor is (a message starts it, and it is back at
// the top). Open or not kept in this browser (foldOpen, by ALONE_KEY); folded, those open in a pane in view under it. Never
// hidden as a group is (isHidden): closed, it is in its line. The rail likewise (railAloneShut), its lines shown as its
// foot says for its boxes' saved and closed lines (railShow), "▸ N closed" (the rest in its title: the rail is narrow).
const ALONE_KEY = "\u0000alone";
function aloneShut(g) {
  const a = g.alone && aloneActor(g);
  return !!a && ["Saved", "Closed"].includes(groupOf(g, a));
}
// [Saved | Closed, those of `gs` (each aloneShut) in it, the latest first], each with any
function aloneFolds(gs) {
  const latest = (x, y) => (aloneActor(y).last || 0) - (aloneActor(x).last || 0);
  return ["Saved", "Closed"].map((name) => [name, gs.filter((g) => groupOf(g, aloneActor(g)) === name).sort(latest)])
    .filter(([, list]) => list.length);
}
const aloneSays = (name, n) => `${n} ${name.toLowerCase()}`;
const aloneInPane = (list) => list.filter((g) => inPane(g, aloneActor(g)));
function aloneShutRows(gs) {
  const out = [];
  for (const [name, list] of aloneFolds(gs)) {
    const shown = foldOpen[name].has(ALONE_KEY);
    out.push(el("button", { class: "agent-group fold-line", type: "button", "aria-expanded": shown ? "true" : "false",
      "data-key": `${ALONE_KEY}/${name}`, onclick: () => toggleFold(name, ALONE_KEY),
      title: `${shown ? "Hide" : "Show"} the ${name === "Saved" ? "saved " : ""}actors on their own that are closed` },
    `${shown ? "▾" : "▸"} `, aloneSays(name, list.length)));
    if (shown) out.push(...list.flatMap((g) => rowsOf(g, aloneActor(g), name)));
    else out.push(...aloneInPane(list).map((g) => agentRow(g, aloneActor(g), name)));
  }
  return out.length ? [el("div", { class: "gatherer alone shut" }, ...out)] : [];
}
function railAloneShut(gs) {
  const out = [];
  for (const [name, list] of aloneFolds(gs)) {
    const what = name.toLowerCase(), unfolded = foldOpen[name].has(ALONE_KEY);
    const peek = () => aloneInPane(list).map((g) => railActor(g, aloneActor(g)));
    if (!railShow[what]) { out.push(...peek()); continue; }   // its line not shown: those open in a pane, in view
    out.push(el("button", { class: "r-fold", type: "button", "aria-expanded": unfolded ? "true" : "false",
      title: `${aloneSays(name, list.length)}: ${unfolded ? "hide" : "show"} ${list.length === 1 ? "it" : "them"}`,   // its words: too wide here
      onclick: () => toggleFold(name, ALONE_KEY) }, `${unfolded ? "▾" : "▸"} ${list.length} ${what}`));
    out.push(...(unfolded ? list.flatMap((g) => railRowsOf(g, aloneActor(g))) : peek()));
  }
  return out.length ? [el("section", { class: "r-gatherer r-alone shut", "aria-label": "Closed, on their own" }, ...out)] : [];
}
// One actor (`d`, listDrag's) dropped outside every group: the dialog, then it on its own, with its task's apps and
// its own window if it is an app's agent (withOwn)
function askAlone(d, here = false) {
  const from = state.home.gatherers.find((x) => x.name === d.g), items = from ? withOwn(from, d.cs || []) : [];
  const c = items.find((k) => !isAppItem(k)), a = c && actorOf(from, c);
  if (!a) return;
  const name = actorTitle(a), others = from.agents.filter((x) => !isCoordinator(x) && x.channel !== c).length;
  const going = items.filter(isAppItem).map((k) => appInfo(d.g, k.slice(APP_ITEM.length))).filter(Boolean)
    .map((o) => ({ id: o.id, app: o.app.name, title: o.name || o.title }));
  const f = here ? folderById(d.g, folderOf(d.g, a)) : null, where = f ? f.name : `the top of ${titleOf(from)}`;
  const lines = [`${name} leaves the ${titleOf(from)} group (${mvCount(others, "other")}) and works on its own`
    + (here ? `, staying in ${where}` : "") + ": it will share context with no other actor, and no other actor with it.",
  appsLine(going, false), here ? `It has no coordinator agent. Manage groups brings it back into ${titleOf(from)}.`
    : "It has no coordinator agent. Drag it into a group to bring it back.",
  rebuildLine(from, [a])].filter(Boolean);
  const shown = { title: here ? "Put it on its own?" : "Take it out of every group?", lines, goLabel: here ? "On its own" : "Take it out" };
  mvOpen("An actor on its own");
  const go = mvGo(shown, "Taking it out…", "Not taken out", async () => {
    const got = await post("/api/groups", { gatherer: d.g, do: "alone", channel: c, ...(here ? { here: true } : {}) });
    return { to: got.alone.group, actors: got.alone.actors, apps: got.alone.apps || [], said: `${name} is on its own` };
  }, d.g);
  mvDraw({ ...shown, go });
}

// ---- groups inside another group's folder (groups.py's `place`, `own`, `above`; home.places: {group: {in, folder}}),
// the Notes design "Groups: folders, defaults and Manage groups": a folder takes its parent's group or has its own, an
// actor has its folder's group or is on its own. The list says nothing of groups: a group of its own inside another's
// folder is drawn there (boxRows' placedRows), its row set in as a folder's line is; an actor on its own there, as any
// actor. Who shares with whom is set in Manage groups alone (below): its own group (askOwn), back in the group around it
// (askAbove, askJoin), on its own where it is (askAloneHere). A drag follows the default rule -- what is dropped into a
// folder takes its group, after the question (askMerge, askMove) -- and one within the group it is in just moves
// (placeGroup), as a folder does.
const placesOf = () => (state.home && state.home.places) || {};
const isAloneName = (name) => String(name || "").startsWith("self:");
// where the group `name` is drawn: {in, folder} -- a folder of a group drawn (null: its top), that folder gone: its top --
// or null, at the list's top: placed nowhere, in a group hidden or gone, or in a ring of groups each inside the next
function placeOf(name) {
  const p = placesOf()[name];
  if (!p || !p.in || !state.home.merged) return null;
  const seen = new Set([name]);
  for (let at = p.in; at; at = (placesOf()[at] || {}).in) {
    if (seen.has(at)) return null;
    seen.add(at);
  }
  const outer = state.home.gatherers.find((x) => x.name === p.in);
  if (!outer || outer.alone || isHidden(outer) || isCrewHome(outer)) return null;
  return { in: p.in, folder: p.folder !== null && p.folder !== undefined && folderById(p.in, p.folder) ? p.folder : null };
}
// whether group `name` is `outer`, or drawn inside it, at any depth
function insideOf(name, outer) {
  for (let at = name, n = 0; at && n < 64; at = (placeOf(at) || {}).in, n++) if (at === outer) return true;
  return false;
}
const nestedIn = (g) => ((p) => p ? state.home.gatherers.find((x) => x.name === p.in) || null : null)(placeOf(g.name));
// the groups drawn in folder `id` of group `gname` (null: its top): groups, by their titles, then actors on their own
const placedIn = (gname, id) => state.home.gatherers.filter((x) => !isHidden(x) && !isCrewHome(x)
  && ((p) => !!p && p.in === gname && p.folder === id)(placeOf(x.name)))
  .sort((x, y) => (x.alone ? 1 : 0) - (y.alone ? 1 : 0) || byName(titleOf(x), titleOf(y)));
const placedRows = (g, id) => placedIn(g.name, id).map((x) => x.alone ? aloneBox(x) : gathererBox(x));
// the group `gname` open, and its folder `id` with the folders it is in
function openWhere(gname, id) {
  if (collapsed.delete(gname)) {
    try { localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...collapsed])); } catch (e) { /* kept for this page only */ }
  }
  for (let f = id; f !== null && f !== undefined; f = (folderById(gname, f) || {}).parent ?? null) showFolder(gname, f, true);
}
// The group `name` put in folder `id` of group `to` ("": at the list's top), keeping its own group: nothing anyone shares
// changes, so no question -- moved within the group it is in, or an actor on its own taken back to the top
async function placeGroup(name, to, id) {
  try { await post("/api/groups", { gatherer: name, to, into: id, do: "place" }); } catch (err) { setLive(`Not moved: ${err.message}`); return; }
  if (to) openWhere(to, id);
  await loadHome();
  renderAgents();
}
// A nested group's way back: made part of the group it is in again, a folder of it where it is (the merge's dialog)
function askAbove(g) {
  const p = placeOf(g.name), outer = nestedIn(g);
  if (outer) askMerge(g.name, outer, p.folder, true);
}
// An actor on its own in a folder, back in that folder's group (the move's dialog, without "Stay on its own")
function askJoin(x) {
  const p = placeOf(x.name), g = nestedIn(x), a = aloneActor(x);
  if (g && a) askMove({ g: x.name, cs: [a.channel], folder: null }, g, p.folder);
}
// An actor of group `g` on its own, staying in its folder
const askAloneHere = (g, a) => askAlone({ g: g.name, cs: [a.channel] }, true);

// ---- MANAGE GROUPS: who shares context with whom, at a glance, and the switches (the Notes design's section 4) -- each
// row that starts a group of its own (a group, an actor on its own: `defines`) on a highlighted background: a
// dialog from the list's head (manageButton) -- each group, at its place, its folders and open actors under it (closed
// ones counted), a folder's switch "<the group it is in> | Own group", an actor's "<the group it is in> | On its own" -- the
// group by its name, the folder that starts it (mgIn). A switch asks
// first, as in the list (askOwn, askAbove, askAloneHere, askJoin), then the dialog is drawn again from the new home
// (renderAgents calls drawManage while it is open). The CLI's `ag groups` has the same. A group's or folder's row folds
// what is under it (mgFolded, kept in this browser). Rows are dragged and dropped as the list's are, by its own
// dragRow, dragFolder and dropOn -- the same rules, the same questions -- and its "Outside every group" area is over the
// panel's top line while one is dragged.
const manage = { dialog: null };
const MANAGE_LABEL = "Manage groups: who shares context with whom";
function manageButton() {
  if (SNAPSHOT || !state.home.merged) return null;
  return el("button", { class: "manage-groups", type: "button", title: MANAGE_LABEL, "aria-label": MANAGE_LABEL, onclick: openManage },
    strokeIcon(ICONS.group, 15));
}
function openManage() {
  if (!manage.dialog) {
    manage.dialog = el("dialog", { class: "br-dialog mg-dialog", "aria-label": "Manage groups" });
    manage.dialog.addEventListener("click", (ev) => { if (ev.target === manage.dialog) manage.dialog.close(); });
    document.body.append(manage.dialog);
  }
  drawManage();
  if (!manage.dialog.open) manage.dialog.showModal();
}
// a switch of its options (two, or one: a group at the top, or an actor on its own there, has no group around it to
// take): `now` the one pressed; the other asks (`ask`), or, `why`, it can't be had and says why. An option is its text,
// or [text, what it means on hover]
function mgSwitch(label, options, now, ask, why = "") {
  const pick = ([text, tip], on) => el("button", { type: "button", class: "mg-opt" + (on ? " on" : ""), "aria-pressed": on ? "true" : "false",
    ...(on || why ? { disabled: "" } : {}), ...(why && !on ? { title: why } : tip ? { title: tip } : {}), onclick: () => { if (!on) ask(); } }, text);
  return el("span", { class: "mg-switch", role: "group", "aria-label": label },
    ...options.map((o, i) => pick(Array.isArray(o) ? o : [o, ""], now === i)));
}
// the option of taking group `g`, the one a row sits in: by its name, the folder that starts it
const mgIn = (g) => [titleOf(g), `${titleOf(g)}'s group: shares context with its actors`];
// What the panel has folded: "g:<group>", "f:<group>:<folder id>", "alone" (those on their own at the top)
const MG_FOLDED_KEY = "ag-dashboard-manage-groups-folded";
const mgFolded = new Set((() => { try { return JSON.parse(localStorage.getItem(MG_FOLDED_KEY) || "[]"); } catch (e) { return []; } })());
// `key` folded or opened (`open`; flipped, left out), and the panel drawn so
function mgToggle(key, open) {
  const fold = open === undefined ? !mgFolded.has(key) : !open;
  if (fold === mgFolded.has(key)) return;
  if (fold) mgFolded.add(key); else mgFolded.delete(key);
  try { localStorage.setItem(MG_FOLDED_KEY, JSON.stringify([...mgFolded])); } catch (e) { /* kept for this page only */ }
  drawManage();
}
// a row's name, its caret first -- turned down while open, folding what is under it, and its name so too -- or, nothing
// under it, the caret's room, so names line up
function mgName(key, name, has, ...rest) {
  const open = !mgFolded.has(key);
  const caret = has ? el("button", { type: "button", class: "mg-fold", "aria-expanded": open ? "true" : "false",
    "aria-label": `${open ? "Fold" : "Open"} ${name}`, onclick: (ev) => { ev.stopPropagation(); mgToggle(key); } },
    el("span", { class: "caret", "aria-hidden": "true", text: "▶" })) : el("span", { class: "mg-fold", "aria-hidden": "true" });
  return el("span", { class: "mg-name" + (has ? " foldable" : ""), ...(has ? { onclick: () => mgToggle(key) } : {}) }, caret, ...rest);
}
function mgActor(g, a, depth) {
  const lone = g.alone, inTask = !lone && withOwn(g, [a.channel]).filter((c) => !isAppItem(c)).length > 1;
  const around = lone ? nestedIn(g) : g;   // the group it sits in: none for one on its own at the list's top
  const why = isCoordinator(a) ? "The coordinator agent stays with its group" : inTask ? "It works in a task with others: a task moves whole" : "";
  return dragRow(el("div", { class: "mg-row actor" + (lone ? " defines" : ""), "data-key": `${g.name}/${a.channel}`,
    style: `--depth: ${depth}`,   // on its own: a group of one
    ...(lone ? { title: `On its own: a group of one, sharing context with no other actor${around ? "" : ". Drag it into a folder to join that folder's group"}` } : {}) },
    mgName("", "", false, plainFace(a), el("span", { text: actorTitle(a) || a.channel.slice(0, 8) })),
    mgSwitch(`${actorTitle(a)}: its group`, around ? [mgIn(around), "On its own"] : ["On its own"], lone && around ? 1 : 0,
      () => (lone ? askJoin(g) : askAloneHere(g, a)), why)), g, a);
}
// group `g`'s folder `id` (null: its top), at `depth`: its folders, each with its switch and what is in it; the groups and
// actors on their own put there; its open actors (the closed counted)
function mgBox(g, id, depth) {
  const out = [];
  for (const f of kidFolders(g.name, id)) {
    const key = `f:${g.name}:${f.id}`, kids = mgBox(g, f.id, depth + 1);
    const row = el("div", { class: "mg-row folder", "data-key": `${g.name}/folder:${f.id}`, style: `--depth: ${depth}` },
      mgName(key, f.name, kids.length > 0, strokeIcon(ICONS.folder, 14), el("span", { text: f.name })),
      mgSwitch(`${f.name}: its group`, [mgIn(g), "Own group"], 0, () => askOwn(g, f)));
    out.push(dropOn(dragFolder(row, g, f), g, f.id, () => mgToggle(key, true)));   // held over: opened
    if (!mgFolded.has(key)) out.push(...kids);
  }
  for (const x of placedIn(g.name, id)) out.push(...(x.alone ? x.agents.map((a) => mgActor(x, a, depth)) : mgGroup(x, depth)));
  const mine = g.agents.filter((a) => folderOf(g.name, a) === id && !isCoordinator(a));
  const shut = mine.filter((a) => ["Saved", "Closed"].includes(groupOf(g, a)));
  out.push(...mine.filter((a) => !shut.includes(a)).map((a) => mgActor(g, a, depth)));
  if (shut.length) out.push(el("div", { class: "mg-row shut", style: `--depth: ${depth}`, text: `${plural(shut.length, "closed actor")} here too` }));
  return out;
}
// a group: its line, a folder's as the list has it -- placed in a folder, its switch; at the top, its own group, the only
// option -- then what is in it
function mgGroup(g, depth) {
  const outer = nestedIn(g), n = g.agents.filter((a) => !isCoordinator(a)).length, key = `g:${g.name}`, kids = mgBox(g, null, depth + 1);
  const row = el("div", { class: "mg-row group defines", "data-key": g.name, style: `--depth: ${depth}`,   // a group starts here
    title: `${titleOf(g)} starts a group: its actors share context with each other${outer ? `, not with ${titleOf(outer)}'s` : ""}` },
    mgName(key, titleOf(g), kids.length > 0, strokeIcon(ICONS.folder, 14), el("b", { text: titleOf(g) }), el("span", { class: "mg-n", text: plural(n, "actor") })),
    outer ? mgSwitch(`${titleOf(g)}: its group`, [mgIn(outer), "Own group"], 1, () => askAbove(g))
      : mgSwitch(`${titleOf(g)}: its group (at the top, its own)`, ["Own group"], 0, () => {}));
  if (!SNAPSHOT) {                                   // dragged as the list's group row is: into a folder of another group
    row.draggable = true;
    row.addEventListener("dragstart", (ev) => startDrag(ev, GFS, { gs: [g.name] }));
    row.addEventListener("dragend", endDrag);
  }
  return [dropOn(row, g, null, () => mgToggle(key, true)), ...(mgFolded.has(key) ? [] : kids)];
}
function drawManage() {
  if (!manage.dialog) return;
  const shown = state.home.gatherers.filter((g) => !isHidden(g) && !isCrewHome(g) && !placeOf(g.name));
  const lone = shown.filter((g) => g.alone), scrolled = (manage.dialog.querySelector(".mg-tree") || {}).scrollTop || 0;
  const loneRows = lone.flatMap((x) => x.agents.map((a) => mgActor(x, a, 1)));
  manage.dialog.replaceChildren(el("div", { class: "newform mg-form" },
    el("div", { class: "br-title" }, el("h3", { text: "Manage groups" }),
      el("button", { type: "button", class: "x", "aria-label": "Close", onclick: () => manage.dialog.close() }, "×")),
    el("div", { class: "mg-top" },
      el("p", { class: "mg-say", text: "Actors share context within their group only. Each switch names the group a folder or actor "
        + "sits in: it takes that group, or has its own. Drag rows as in the list. Each change asks first." }), outsideDrop()),
    el("div", { class: "mg-tree" }, ...shown.filter((g) => !g.alone).sort((x, y) => byName(titleOf(x), titleOf(y))).flatMap((g) => mgGroup(g, 0)),
      ...(lone.length ? [el("div", { class: "mg-row group", style: "--depth: 0" }, mgName("alone", "those on their own", true, strokeIcon(ICONS.alone, 14),
        el("b", { text: "On their own, at the list's top" })))] : []),
      ...(mgFolded.has("alone") ? [] : loneRows))));
  const tree = manage.dialog.querySelector(".mg-tree");
  if (tree) tree.scrollTop = scrolled;               // where it was, drawn again
}

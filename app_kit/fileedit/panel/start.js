// The panel, started (the last of its scripts: an app's own parts given to edAdd before it): connected to the dashboard
// around it (app_kit's SDK), told the actors as its list has them (ag.actors, kept in `state.home`), the theme (each
// change also an "ag-theme" event, as the dashboard's page sent one), and what the page asks of it -- open-file (a file
// shown, at a line), a link to a file clicked: edShowFile, the one way a file is opened from outside -- then drawn
// (edMount) on its folder.
(async () => {
  const ag = agApp = await AgApp.connect();
  window.editor = ag;                                // the browser tests drive it as the page would
  const takeActors = (got) => {
    if (!got) return;
    state.home = { ...state.home, gatherers: got.gatherers || [], home_dir: got.home_dir || "", cwd: got.cwd || "",
      harnesses: got.harnesses || [] };
    if (got.home_dir) ed.home = ed.home || got.home_dir;
    if (ed.host) { ed.treeSig = ""; edTree(); edHead(); edBranches(); if (ed.s) { edConflicts(ed.s); edAgentMarks(ed.s); } }
  };
  takeActors(ag.actors.current);
  ag.actors.on(takeActors);
  ag.theme.on(() => window.dispatchEvent(new Event("ag-theme")));
  ag.selection.on((sel) => { state.selected = sel ? [sel.gatherer, sel.channel] : null; });
  ag.intents.on("open-file", (d) => { if (d && d.path) edShowFile(String(d.path), Number(d.line) || 0); });
  // a link to a file clicked in Chat (the app's [[links]], `ag://<app>/file/<its absolute path>#L<line>`): shown, at
  // its line -- the path absolute, whether or not the link keeps its first "/"
  ag.links.onOpen((l) => {
    const p = String((l && l.values && l.values.path) || "");
    const line = /^L?(\d+)$/i.exec(String((l && l.part) || ""));
    if (p) edShowFile(p.startsWith("/") ? p : `/${p}`, line ? Number(line[1]) : 0);
  });
  ag.onMessage((m) => {                              // its backend's: the mode set (here or elsewhere), a file to show
    if (m && m.mode) { ed.mode = m.mode; edHead(); }
    if (m && m.show && m.show.path) edShowFile(String(m.show.path), Number(m.show.line) || 0);   // an agent's <app>_open
    for (const f of edAdded.message) f(m);
  });
  get("/api/mode").then((got) => { ed.mode = got.mode; edHead(); }).catch(() => {});
  edMount();
  document.body.dataset.ready = "1";
})();

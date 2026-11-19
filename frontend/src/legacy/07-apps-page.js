// THE APPS PAGE (features/apps/catalog.ts): what a tab showing nothing shows in place of its new-tab page when it is the
// Apps page's (layout/tabs.ts's `page`) -- opened from the settings panel's "Manage apps", under Groups (openAppsPage),
// and from a new tab's "Apps…". What that page asks of this one: an app opened where things start (07-new-tab.js's start place: in its group,
// in a tab of its own, as from a group's menu), and -- the apps installed having changed -- them read again: the panels
// of those gone closed, the list drawn again (an uninstalled app's rows go with it: appOf finds no app for them).
function openAppsPage() {
  if (PANE || SNAPSHOT || !workPlacer) return;
  setAbout(false);
  void workPlacer.tabs.openPage("apps");
}
if (!SNAPSHOT && !PANE) {
  document.getElementById("apps-cfg").hidden = false;
  document.getElementById("manage-apps").addEventListener("click", openAppsPage);
}
function drawAppsPage(box) {
  box.classList.remove("nt");
  window.agNext.appsPage.draw(box, { open: appsPageOpen, changed: appsChanged });
}
// An app opened from the page: the way the reader chose there (`withAgent`), as a group's "+ ⋯" menu opens it
// (07-panes.js's opensWithAgent) -- on its own when no harness here can give an agent its tools.
async function appsPageOpen(a, withAgent = false) {
  const app = window.agNext.apps.named(a.name);
  if (!app) throw new Error("it isn't loaded yet. Reload the page.");
  const p = startPlace(), g = p && !p.alone ? ntGroup(p) : realGroups()[0];
  if (!g) throw new Error("make a group first");
  const cwd = startCwd(g) || state.home.cwd || null, folder = p && !p.alone ? p.folder : null;
  const tooled = startable().filter((h) => (harnessInfo(h) || {}).mcp);   // can give an agent its tools
  if (withAgent && app.agent && app.agent.offered && tooled.length) {   // with an agent of its own: started with it
    const kept = keptValue(START_HARNESS_KEY);
    aimStart(g.name, folder);
    return startWithApp(g.name, cwd, app.name, tooled.includes(kept) ? kept : tooled[0]);
  }
  return openAppTab(g.name, app.name, cwd);
}
async function appsChanged() {
  await window.agNext.apps.load();
  for (const p of panes.apps.filter((q) => !window.agNext.apps.named(q.app.name))) {   // its app uninstalled: gone,
    panes.apps.splice(panes.apps.indexOf(p), 1);                                       // even one held for an agent
    unselectApp(p.instance.id);
    p.panel.destroy();
    p.node.remove();
  }
  appsOnlyLeft(); saveAppPanes(); topChanged(); renderAgents();
}

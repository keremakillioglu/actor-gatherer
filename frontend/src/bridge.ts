// Between the old page (page.js's modules, plain JS) and the new code, while views move from one to the other
// (ag_dashboard/DESIGN.md, A4-A6). Set up before the old page starts, as `window.agNext`: what it hands the new code
// (the stream's home) and calls of it (ag's settings; the renderers it draws with, `ui`; Chat's turns, `chat`). The old
// page hands back `window.agLegacy`: what the new code calls of it. Each side goes once nothing calls it.
import { useDashboard } from "./core/store";
import { stream } from "./core/api/stream";
import type { Home } from "./core/api/types";
import {
  ansiHtml,
  codeClick,
  guessWeb,
  hlLines,
  hlPart,
  langOfPath,
  outputHtml,
  shellHtml,
  tildePath,
} from "./core/ui/highlight";
import { escapeHtml } from "./core/ui/html";
import { markdown, unplanned } from "./core/ui/md";
import { draw as drawAppsPage } from "./features/apps/catalog";
import { askedByAgent } from "./features/apps/catalog-dialogs";
import * as apps from "./features/apps/host";
import { FILE_FORM, fileHref, filePath, isAppHref, joinPath, matchPath, parseHref } from "./features/apps/links";
import { drawTurns } from "./features/chat/mount";
import { cidsOf } from "./features/chat/view";
import { work } from "./features/layout/work";
import { useTurns } from "./features/chat/store";
import { useSettings } from "./features/settings/store";

/** What the old page gives the new code (src/features/settings/panel.js). */
export interface AgLegacy {
  /** The dashboard's panel opened or closed. */
  setAbout: (open: boolean) => void;
  /** The page is a snapshot (its data inside it), or a pane's frame inside the page: neither has ag's settings. */
  snapshot: boolean;
  pane: boolean;
}

const agNext = Object.freeze({
  /** A stream of the dashboard's, as `new EventSource(url)`, on the page's one WebSocket (core/api/stream.ts). */
  stream,
  /** The stream's home, as the old page takes it (features/list/seen.js's takeHome). */
  home: (home: Home) => useDashboard.getState().setHome(home),
  settings: Object.freeze({
    load: () => useSettings.getState().load(),
    fileOpen: () => useSettings.getState().file.open,
    closeFile: () => useSettings.getState().closeFile(),
  }),
  /** The renderers the old page draws with (src/core/page/code.js's and features/transcript/transcript.js's functions call these). */
  ui: Object.freeze({
    escapeHtml,
    langOfPath,
    guessWeb,
    hlLines,
    hlPart,
    tildePath,
    shellHtml,
    ansiHtml,
    outputHtml,
    codeClick,
    markdown,
    unplanned,
  }),
  /** Chat's turns (src/features/chat/files-view.js's filesRender): drawn from the feed it hands over, into the actor's own
   * node, which it puts in its view; what they call of the page, its host (features/chat/types.ts). The setting "Chat's
   * earlier turns" picked (features/page/data.js): every turn as it has them, the clicks against it dropped. */
  chat: Object.freeze({ draw: drawTurns, clearFlips: () => useTurns.getState().clearFlips(), cidsOf }),
  /** The apps (features/apps/host.ts): those found, an instance opened, and an app's pane -- its head, its frame and the
   * bridge to its panel -- which the old page keeps in the top row, above the panes (src/features/layout/panes.js's addAppPane). */
  apps: Object.freeze({
    load: apps.load,
    found: apps.found,
    named: apps.named,
    open: apps.open,
    instanceOf: apps.instanceOf,
    attachedTo: apps.attachedTo,
    start: apps.start,
    handler: apps.handler,
    handlers: apps.handlers,
    /** Links to things in apps, `ag://<app>/<path>` (features/apps/links.ts): read, and matched to an app's forms; and
     * a file's path an agent writes, read and made a link of an app's FILE_FORM. */
    links: Object.freeze({
      parse: parseHref,
      match: matchPath,
      isApp: isAppHref,
      file: filePath,
      join: joinPath,
      fileHref,
      FILE_FORM,
    }),
    pane: (app: apps.AppInfo, instance: apps.Instance, hooks: apps.PaneHooks) => new apps.AppPane(app, instance, hooks),
  }),
  /** The Apps page (features/apps/catalog.ts), drawn in a tab's box when the tab is its (src/features/apps/apps-page.js). */
  appsPage: Object.freeze({ draw: drawAppsPage, askedByAgent }),
  /** The work area's layout (features/layout/): the panels the old page shows (src/features/layout/panes.js's shownPanels), each
   * task's as the reader arranges them, placed; a panel moved by its head or its menu. */
  layout: Object.freeze({ work }),
});

declare global {
  interface Window {
    agNext: typeof agNext;
    agLegacy?: AgLegacy;
  }
}

window.agNext = agNext;

# The ag desktop app: design

Status: design agreed (2026-11-04). Steps 1 to 4 built: the app shows the home's dashboard; its Browsers' tabs are
native pages ag drives over the app's link; what the dashboard draws over the screen elsewhere, Pick and Area, and the
user's own input there work on them; and so do find, downloads, sites' permission asks and page dialogs. Step 5
(signing and shipping) is next.
A throwaway prototype (an Electron shell around a test dashboard, kept outside the repo) tried each risky part on
2026-11-04; what it showed is below.

**Since the Browser became an app (2026-11-07, app_kit/DESIGN.md step 8):** the Browser's code is
`ag_apps/browser/` (`core.py` was `ag_dashboard/browser.py`, `video.py` was `browser_video.py`), its view a panel in
an iframe on its own origin above its actor. What below names those files means them there. Three things work
differently, and generally -- for any app that asks the `native_view` capability, not the Browser alone:
- **Where a page goes:** the page no longer marks its panes for the preload to scan. The app's panel reports where its
  screen is (app_kit's `ag.native.show`), the page offsets that by the panel's frame, checks the dashboard's own
  overlays over it, and hands the list to the preload (`agApp.place`); a still picture goes back through the page to
  the panel, which says once it is drawn (`agApp.onStill`, `agApp.stillDrawn`).
- **The link** (`/api/desktop`) is the app host's (ag_dashboard/api/apps.py, `desktop.py`'s token): it hands it to each
  such app, every message tagged with its app ("app"). The desktop app keeps each app's pages apart -- made, seen,
  driven and placed for that app alone -- each app in a profile of its own; the Browser's is `persist:browsers`, as
  before, so its logins stay. A message naming no app is the Browser's.
- **Hiding a page:** closing its panel, not switching the actor's view; clicking its actor opens the panel again.

The app is the dashboard in a window of its own, with one difference: a Browser's page is a real, native Chromium
page inside the Browser pane, not a streamed picture of a hidden Chrome tab.

**Otherwise the app works exactly as the dashboard does now** (decided 2026-11-04). It shows the same page, from the
same server, with the same views, panels, settings and keys. Nothing else gets an app-only version, and `ag` and
`ag dashboard` stay as they are. Everything below is about the Browser, or about running the dashboard in a window.

## Why

- **The Browser is a picture today.** ag's own Chrome runs headless and the dashboard streams its tab as video (or
  JPEG frames). A click shows 20–40 ms later; scrolling costs CPU; text can go soft while frames catch up.
- **A lot of code exists only because the page is a picture.** `browser.py` and `browser_video.py` (about 4,900
  lines) include the capture extension and its windows, UI_JS (pointer shape, tooltips, drop-down lists, date and color
  pickers, the right-click menu, Cmd+F), the clipboard bridge and the key-beep fix. A native page does all of these
  itself.
- **A web page can't hold one.** The dashboard is a page in your browser, and a page can only show another site in an
  iframe: most sites refuse that (Google Docs, Figma, GitHub), logins break in it, and the dashboard's scripts can't
  reach into it for the agent. Only a native app can put a real page inside its window.

## What the prototype showed

| Tried | Result |
|---|---|
| A native page (Electron `WebContentsView`) kept over the Browser pane | Works: placed from the pane's position, moved with it (tab strip, resize), hidden when another view shows |
| ag's Browser code driving it, unchanged | Works: snapshot, type, select, click; new tabs; through a relay that played the browser's part |
| A sign-in popup ("Continue with Google" on Figma) | Broke at first: the prototype opened popups as new tabs, which cut `window.opener`, so the result never reached the page that asked. Fixed by opening them as real popups (shown in the pane as tabs); checked with a test popup that reports back and closes itself |
| Google sign-in with a debugging port open (Electron `--remote-debugging-port`; CEF too) | Refused: "This browser or app may not be secure" |
| Google sign-in with the browser's name faked (Chrome, then Google Chrome, hints included) | Refused |
| Google sign-in with **no debugging port**, the app's **honest name** (`… Electron/45.0.0`) and ag's connection attached the whole time | **Passed** (reached Google's 2-step prompt). The user's own `~/workspace/mini-browser` (plain Electron, no port) passes too |
| Dashboard HTML over the native page | Hidden: a native view is drawn above the page's HTML |

So Google refuses a browser it can see is remote-controlled through an open port, or one claiming to be what it isn't,
not Electron as such, and not ag's agent being connected.

## Rules the app keeps

1. **No debugging port, ever.** No `--remote-debugging-port`, no `--inspect`. ag reaches each page through Electron's
   in-app connection to it (`webContents.debugger`), as it reaches its own Chrome through a private pipe today.
2. **No faked name.** The app tells sites what it is.
3. **Popups open as real popups,** `window.opener` kept, and are shown in the pane as tabs of the Browser's.

## How it fits together

```
the ag app (Electron)                                     the dashboard server (Python, as today)
┌──────────────────────────────────────────┐              ┌─────────────────────────────────┐
│ window                                   │              │                                 │
│  ├─ the dashboard page (as served) ◀─────┼── HTTP, WS ──┤ api/  (unchanged for the page)  │
│  └─ Browser tabs: native views,          │              │                                 │
│     each kept over its pane              │              │ browser.py: Browsers, the tools │
│ main process                             │              │   └─ AppCdp (new): the app link │
│  ├─ places views where the page says     │              │                                 │
│  └─ the app link: the views' CDP ────────┼── one WS ───▶│                                 │
└──────────────────────────────────────────┘              └─────────────────────────────────┘
                                                                   ▲ the agent's tools (MCP), as today
```

### The app

- Electron, a pinned version, in `desktop/` (TypeScript: the main process and a preload), built with the repo's pnpm.
- **Starting:** it finds the home's running dashboard the way `ag` does (`_serves_this_home`: its `/api/home`), and if
  none is running, starts `ag dashboard --no-open` detached, so actors outlive the app as they outlive a browser tab
  today. It needs ag installed, as `ag` does; bundling Python comes later, if at all. So relaunching the app never
  restarts the dashboard: `ag dashboard restart` does (ag_dashboard/restart.py), and the app's link reconnects by itself.
- **The window** loads the page the server serves, not a copy of it, so a dashboard update needs no app update.
- **In the app, a Browser is always a native page** (decided 2026-11-04). There is no setting for it, and the app
  never shows a streamed Browser.
- **Browsers pause when the app quits** (decided 2026-11-04). A page runs inside the app, so quitting closes it;
  nothing moves to another browser. Each tab's address is kept (in `dashboard.db`, as today), so the tabs reopen at
  those pages when the app starts again, as ag's own Chrome's do today after it stops. Logins are in the app's
  profile, so they last; what a page held only in memory (a half-filled form, where it was scrolled, a sign-in kept
  only until the browser closes) does not. Closing the window is not quitting: like other Mac apps, it stays open in
  the Dock until Cmd+Q.

### Which Browsers live in the app

- **A home's Browsers live in the app once the app has run on that home.** The app's link marks the home when it first
  connects (the file `<home>/dashboard/desktop-browsers`). Deleting it undoes that; a switch for it in Settings is not
  built yet. Homes that never use the app keep today's Browser: ag's own
  Chrome, streamed (or your own Chrome, with `browser_profile = "mine"`).
- **While the app is open,** the same Browser opened in an ordinary browser (another tab, another computer) streams
  from the app's page.
- **While the app is closed,** a Browser of that home is paused: the agent's tools answer that it is paused until the
  ag app is open again and to ask the user to open it, and the pane in an ordinary browser says the same.

### The app link

The prototype's relay, made permanent and turned around: the app opens no port of its own.

- The app opens one WebSocket to the server, `/api/desktop` (in `api/browser.py`: only the Browser's own code names
  it, the dashboard's rule 3), its first message a token in the home (`<home>/dashboard/desktop-token`, mode 0600,
  made by whichever side needs it first). A web page can't read it, and its socket would say where it is (Origin),
  which the app's never does: either is refused.
- The app tells ag of its pages as they come, change and go, unasked: ag asks a Chrome for that only in some modes, and
  a popup ag isn't told of is one it opens again itself, its opener lost.
- Over it go Chrome DevTools Protocol messages, exactly as Chrome's own connection carries them. The app plays the
  browser's part: `Target.*` over its views (create, attach, close, info, the target events), each session one view's
  `webContents.debugger`. The prototype's version of this is about 100 lines.
- In `browser.py`, a third kind of Chrome connection, `AppCdp` (a `Cdp` like `WsCdp`, but the app connects to the
  server rather than the other way round), used for a home the app has marked, and only while the app is connected.
  Target ids are Chrome's real ones: ag compares a main frame's id with its tab's.
- What `browser.py` does today only because its Chrome has no window becomes per mode. In app mode: no screencast to
  the app's own page, no page size override, no UI_JS, no file-chooser interception, no WebAuthn test mode. The
  prototype's relay answered these without passing them on; the real version doesn't send them.

### A tab in its pane

- The preload tells the page it is in the app (`window.agApp`). The page then reports, for each Browser pane it
  shows, where the pane is and which tab it shows, by target id (the Browser's state gains each tab's target id). The
  prototype matched by address, which breaks with two tabs on the same page.
- The app puts that view there and hides the rest, and follows each report: resizing, splits, the Editor opening
  above, switching views or actors.
- A hidden page is laid out at its pane's size (or, for a tab no pane has shown yet, the size ag asks for in
  `Target.createTarget`: its view's) by DevTools emulation (`Emulation.setDeviceMetricsOverride` on its own
  connection), taken off when it is shown. A hidden page has no size of its own until it has been shown: a tab the
  agent opened while its pane showed something else would be laid out at 0 x 0 for the agent's tools, and Chrome would
  leave a screenshot's clip scale (ag's are at 1/dpr) on it, drawing it at half size when shown. Emulation lays the
  page out without drawing it: nothing hidden costs more than before. Keeping hidden pages drawn outside the window
  would do it too, at a few percent of a core for each animating page.
- In the app, the Browser view takes only the stream's state, not its frames.
- The same Browser opened in an ordinary browser (another tab, another computer) keeps streaming: the server
  screencasts from the app's view. To be checked: a hidden view may draw too rarely for that.

### What the dashboard draws over the page

A native view is drawn above the page's HTML, so anything the dashboard draws over the pane is hidden behind it.

- **Menus and popovers that overlap the pane** (the activity list, Settings, hover cards, dialogs): the preload sees
  something of the dashboard's at points of the pane (`elementFromPoint`), and the app swaps the view for a still
  picture of it (`capturePage`, shown in the pane's own image) until the overlay closes. A page hidden when its pane
  is covered (a tab switched to under a menu) has nothing drawn to capture, or only an old drawing: its picture is
  Chrome's own (`Page.captureScreenshot`, which draws the page for it). A page that leaves its pane drops its picture,
  so a tab switched back to under the overlay gets its own, not the other tab's.
- **The agent's cues** (its outline, about to act, acting, done or not; its pointer and the ripple of a click; the key
  cap; the scroll arrow): drawn in the page itself by `CUES_JS` (browser.py), which ag adds to each page in a world of
  its own, as UI_JS is in its own Chrome, told what to draw as the Browser's state changes (`_draw_cues`). Its marks are
  in a closed shadow root under one `<ag-cues>` element that never takes the pointer: a page's scripts can see that
  element, not into it. (The plan was Chrome's `Overlay` domain for the outline; one script for all of it is simpler,
  and the outline's fade and the pointer's glide match the dashboard's.)
- **Pick:** Chrome's own inspector (`Overlay.setInspectMode`, then `inspectNodeRequested`): the element under the
  pointer outlined, the page given no input, a click picks. **Area:** a layer of `CUES_JS`'s, for that moment only,
  that takes the drag. The dashboard's Pick and Area buttons ask for either (`/browser/w/<key>/mode`); the state says
  which is on. After a pick the dashboard's message box has the keys again.

### Your input

- Your clicks, keys, scrolling and typing go straight into the view; none of it passes through the server.
- **What you did, for the agent** ("clicked button Pay", "typed into Email", never what was typed): `CUES_JS` reports
  clicks and typing, as `log` does from the dashboard's input today. The agent's own clicks reach it too: ag leaves
  out what comes while its action is under way (they arrive before its tool answers). In the app, ag finds the element
  at a point as a click does, passing through what the pointer passes through (its marks among them).
- **Holding your input while the agent acts** (its `expect` checks): ag tells the app (`App.hold`, a message of its own
  on the link, no answer); a transparent view over the page for that moment takes clicks, and its keys are held with
  `before-input-event`. Neither touches the agent's input, which goes to the page another way: Electron's keyboard hook
  never sees it, and a view over the page doesn't stop it (both checked).
- **Esc stops the agent, or ends a Pick or Area:** ag tells the app when the user's Esc on a page is ag's
  (`App.esc`); the app's keyboard hook takes it then and tells ag (`App.escape`).

### What Electron leaves to the app

| | In the app (built in step 4 unless said) |
|---|---|
| Right-click menu | Back, Forward, Reload, cut/copy/paste, copy link, Find in Page… |
| Find (Cmd+F) | A Cmd+F the page doesn't take itself (`CUES_JS`; Google Docs has its own) opens the dashboard's find bar, which finds with Chrome's own find in the page (`App.find`: `findInPage`), "n of m" as today |
| Downloads | Into the home's downloads folder (`<home>/dashboard/downloads`, named as Chrome names a second one), told to ag as Chrome tells it (`Browser.downloadWillBegin`, `downloadProgress`), so the dashboard lists them as today. Its notice sits over the page's still picture, and goes after 8 s |
| Site permissions (camera, notifications, …) | Asked by the app's own dialog over the window, once per site, kept (`<home>/desktop/permissions.json`); what Chrome grants unasked, granted; anything else refused. Full screen is refused for now |
| Page dialogs (alert, confirm, prompt) | Electron's own can't be closed when ag answers them, and it has no prompt. So `page-preload.cts` hands the page's to the app, which tells ag as Chrome would (`Page.javascriptDialogOpening`); the dashboard's dialog card (over the page's still picture) or the agent's `dialog` tool answers. The page is held still meanwhile, so whatever else ag asks of it is refused at once. "Leave site?": left, unasked (the agent's navigations would wait on no one) |
| File choosers | Native, nothing to build |
| Passkeys, Touch ID | Step 5: `app.configureWebAuthn` (Electron 44–45), in a signed app only |
| Protected video (Netflix, …) | None: it needs a Widevine license from Google |

The dashboard's dialog card took the pane's input handling until now (its prompt's text went to the page, its OK click
was lost): it is shielded as the pane's other panels are, in a browser tab too.

### Logins

The app keeps its own profile, in the home (`<home>/desktop/`), separate from your Chrome and from ag's own
Chrome. You sign in once per site, and it's kept. The Settings import from your Chrome can copy logins into it, but not
Google's: Google drops copied sign-ins (tested 2026-11-03).

## Running it

From `desktop/`, after `pnpm install` (which also downloads Electron's app):

    pnpm start                          # the app, on AG_HOME (else ~/.ag), its dashboard on port 4200
    pnpm start -- --home DIR --port N   # another home, or port
    pnpm test                           # unit tests (CI runs these, with the types)
    AG_PYTHON=<a Python with ag's dashboard packages> pnpm e2e   # the app end to end, with real dashboards

The app's own files (its window's place; later the Browsers' profile) are in `<home>/desktop/`. A dashboard it starts
writes to `<home>/logs/dashboard/desktop.log`.

On a Mac, `pnpm start` runs the app as **AGUI** (`scripts/bundle.mjs`). macOS takes an app's name in the Dock, Cmd+Tab
and the menu bar, and its icon, from the bundle it runs from, which for `electron .` is Electron's own. So the script
makes `out/AGUI.app` the first time and again after Electron, the icon or the script changes:
- Electron's app, cloned so it takes almost no disk, with AGUI's name, its own bundle id (`io.github.ucbepic.agui`) and
  `icon.icns`;
- its code a link to this folder, so it always runs this checkout's `dist/`;
- signed ad hoc, for this Mac only.

You can keep `out/AGUI.app` in the Dock. Opened from there, it runs `dist/` as last built. The icons are drawn by
`assets/src/logo.py`. This is not the shipped app (step 5).

## Steps

1. **The app:** the window, finding or starting the dashboard, a development run. The Browser still streams.
2. **App mode:** the app link, `AppCdp`, views placed by target id, popups, the tools unchanged. Tests: `browser.py`
   against a fake app link (unit); the app itself through Playwright's Electron runner (end to end). Playwright opens a
   debugging port to drive Electron: tests only, never in the app we ship.
3. **Over the page:** the covered-pane picture, the agent's cues, Pick and Area, your actions told to the agent, the
   input hold, Esc.
4. **Electron's gaps:** find, downloads, permissions, dialogs.
5. **Shipping:** a signed, notarized macOS app (an Apple Developer ID), updates, passkeys. Linux and Windows after.

## Decisions

Made (2026-11-04):
- **The app is the dashboard as it is now,** but for the Browser: no app-only versions of anything else.
- **Native only in the app:** no streamed Browser and no Browser setting there.
- **Browsers pause when the app quits:** their pages close, and reopen at the same pages when the app starts again.
- **The app shows the home's running dashboard, else starts one,** and quitting the app leaves that server and the
  actors running, as closing the dashboard's browser tab does today. This follows from the app being the dashboard as
  it is now.
- **Mac first, unsigned builds first.** Signing, for anyone else to run it, comes with step 5.

## Risks

- **Google can change its check.** What passes today is no port and an honest name; sign-in can't be tested
  automatically (it needs a real account), so it is checked by hand at each Electron update.
- **Electron updates.** A new major every 8 weeks and security releases between them: bumping a dependency, not
  maintaining a fork, but it has to be done.
- **Two kinds of home.** Homes the app has marked keep their Browsers in the app; the rest keep ag's own Chrome. A
  Browser never moves between them, but both kinds have to keep working, so both are tested.

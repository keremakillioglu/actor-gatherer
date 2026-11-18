// Links to things in apps (app_kit/DESIGN.md, "5d. Links"): an agent's `[words](ag://<app>/<path>)`, drawn as Chat draws
// a message (core/ui/md.ts) with its app's mark, and opened by a click in the app's panel above the actor (07-panes.js's
// openAppLink), which is handed the link (the SDK's ag.links.onOpen). The test app is Notepad (tests/apps/notepad/),
// whose [[links]] take `note/<n>`. Its instance is left open, as apps.spec.ts leaves it; its panel closed.
import fs from "node:fs";
import path from "node:path";
import type { Page } from "@playwright/test";
import { closePanel, expect, test } from "./test";
import { CLAUDE, GATHERER, openActor } from "./home";
import { editorPane, editorPanel, project } from "./editor-home";

const CLAUDE_CHANNEL = "5f0c2a2e-8d1b-4c7e-9a3f-1b2c3d4e5f60";
const beside = process.platform === "darwin" ? "Meta" : "Control";
const notepad = (page: Page) => page.locator("#top-row > .app-pane[data-app=notepad]");
const notepadFrame = (page: Page) => page.frames().find((f) => /^http:\/\/notepad\.localhost:\d+\//.test(f.url()))!;

/** A message's words in the actor's pane, drawn as Chat draws them (core/ui/md.ts): its link. */
async function says(page: Page, id: string, md: string) {
  await page.locator("#pane-here").evaluate(
    (here, [id, text]) => {
      const ag = (window as unknown as { agNext: { ui: { markdown: (t: string) => HTMLElement } } }).agNext;
      const box = ag.ui.markdown(text);
      box.id = id;
      Object.assign(box.style, { position: "absolute", left: "40px", top: "60px", zIndex: "50" });
      here.append(box);
    },
    [id, md],
  );
  return page.locator(`#${id} a`);
}

test("a link to something in an app opens its panel above the actor, handed the link", async ({ page }) => {
  await openActor(page, CLAUDE);
  const link = await says(page, "said-1", "Kept as [note 3](ag://notepad/note/3#line%202).");
  await expect(link).toHaveClass(/ag-link/);
  await expect(link).toHaveAttribute("data-app", "notepad");
  expect(await link.evaluate((a) => getComputedStyle(a, "::before").backgroundImage)).toContain(
    "/apps/mark/notepad.svg",
  );
  await link.click();
  await expect(notepad(page)).toHaveCount(1);
  const panel = notepad(page).frameLocator("iframe");
  await expect(panel.locator("#intent")).toHaveText('link note/<n> {"n":"3"} line 2');
  await expect(panel.locator("#agents")).toHaveText("none"); // a click attaches no agent
  await expect(page.locator("#pane-here")).toBeVisible(); // the actor still below it
  // another app's link, opened by the panel (ag.links.open), as a click on it would: here, its own
  await notepadFrame(page).evaluate(() =>
    (window as unknown as { notes: { links: { open: (h: string) => Promise<unknown> } } }).notes.links.open(
      "ag://notepad/note/7",
    ),
  );
  await expect(panel.locator("#intent")).toHaveText('link note/<n> {"n":"7"}');
  await closePanel(page, notepad(page));
  await expect(notepad(page)).toHaveCount(0);
});

test("a link to an app is never the browser's to open, whatever key is held", async ({ page }) => {
  await openActor(page, CLAUDE);
  const link = await says(page, "said-2", "See [note 4](ag://notepad/note/4).");
  const pages = page.context().pages().length;
  await link.click({ modifiers: [beside] });
  await expect(notepad(page).frameLocator("iframe").locator("#intent")).toHaveText('link note/<n> {"n":"4"}');
  expect(page.context().pages().length).toBe(pages);
  await closePanel(page, notepad(page));
});

test("a link to no place an app lists, or to no app, opens nothing and says why", async ({ page }) => {
  await openActor(page, CLAUDE);
  await (await says(page, "said-3", "[x](ag://notepad/nothing/3)")).click();
  await expect(page.locator(".pane-note")).toHaveText("Notepad: no such place to open (nothing/3)");
  await (await says(page, "said-4", "[y](ag://nowhere/a)")).click();
  await expect(page.locator(".pane-note").last()).toHaveText("No app called nowhere here, to open ag://nowhere/a");
  await expect(notepad(page)).toHaveCount(0);
  expect(page.url()).not.toContain("ag:");
});

test("a link to a file opens it in the agent's own Editor, at its line", async ({ page }) => {
  const { repo } = project();
  const other = path.join(repo, "notes.txt");
  fs.writeFileSync(other, "one\ntwo\nthree\n");
  // an Editor of the actor's, on the project (the test home's actors have no folder to open one on)
  const opened = await page.request.post("/api/apps/open", {
    data: { app: "editor", gatherer: GATHERER, folder: repo, channel: CLAUDE_CHANNEL },
  });
  const editor = ((await opened.json()) as { id: string }).id;
  await openActor(page, CLAUDE);
  // its absolute path after file/, as the Editor's [[links]] say
  await (await says(page, "said-5", `See [line 2](ag://editor/file${other}#L2).`)).click();
  const shown = editorPane(page).filter({ visible: true });
  await expect(shown).toHaveCount(1);
  await expect(editorPane(page)).toHaveCount(1); // and no other, out of sight
  expect(new URL((await shown.locator("iframe").getAttribute("src")) || "").searchParams.get("instance")).toBe(editor);
  await expect(editorPanel(page).locator(".ed-head .ed-path")).toContainText("notes.txt");
  await expect(editorPanel(page).locator(".cm-activeLine")).toHaveText("two");
  await page.request.post("/api/apps/close", { data: { gatherer: GATHERER, instance: editor } });
});

// Links clicked in an actor's pane (features/layout/panes.js, openLink): opened in a Browser of the actor's task, by the open-url
// intent its panel takes -- a new Browser put in the task of an actor that has none, else a new tab of the Browser it
// has. The Browser's panel is the real one; the host's answers and its backend's are the routes here (the test home has
// no Chrome to run one).
import type { Page } from "@playwright/test";
import { expect, streamsAsRequests, test } from "./test";
import { CLAUDE, GATHERER, openActor } from "./home";

const KEY = "0123456789abcdef";
const LINK = "https://example.com/docs";
const beside = process.platform === "darwin" ? "Meta" : "Control";
const browserPane = (page: Page) => page.locator("#top-row > .app-pane[data-app=browser]");

/** The host as the test sets it: the Claude Code actor attached to Browser KEY (the two one task) once `attached`
 * says so; POST /api/apps/open answered with that Browser and recorded; the Browser's backend answering {}, the links
 * it is asked to open recorded. */
async function host(page: Page, attached: () => boolean) {
  const seen = { channel: "", opened: [] as Record<string, unknown>[], links: [] as string[] };
  const task = () => ({ tasks: [{ id: 99, name: "" }], tasked: { [seen.channel]: 99, [`app:${KEY}`]: 99 } });
  await page.route("**/api/home", async (route) => {
    const home = await (await route.fetch()).json();
    seen.channel = home.gatherers
      .find((g: { name: string }) => g.name === GATHERER)
      .agents.find((a: { harness: string }) => a.harness === "claude").channel;
    if (attached()) home.tasks = { ...(home.tasks || {}), [GATHERER]: task() };
    await route.fulfill({ json: home });
  });
  await page.route("**/api/apps?gatherer=*", async (route) => {
    const got = await (await route.fetch()).json();
    if (attached()) {
      got.instances.push({ id: KEY, app: "browser", gatherer: GATHERER, folder: "/work", title: "work", data: {} });
      got.attached[KEY] = [seen.channel];
      got.tasks = task();
    }
    await route.fulfill({ json: got });
  });
  await page.route("**/api/apps/open", async (route) => {
    seen.opened.push(route.request().postDataJSON());
    await route.fulfill({
      json: { id: KEY, app: "browser", gatherer: GATHERER, folder: "/work", title: "work", data: {} },
    });
  });
  await streamsAsRequests(page);
  await page.route("**/api/stream*", (route) => route.abort());
  await page.route(`**/api/w/*/${KEY}/**`, (route) => route.fulfill({ json: {} }));
  await page.route(`**/api/w/*/${KEY}/open`, (route) => {
    seen.links.push(route.request().postDataJSON().url);
    return route.fulfill({ json: { done: LINK } });
  });
  await page
    .context()
    .route("https://example.com/**", (route) => route.fulfill({ contentType: "text/html", body: "" }));
  return seen;
}

/** A link in the actor's pane, where a message's is -- as messages draw them (core/ui/md.ts): a tab of its own. */
async function addLink(page: Page) {
  await page.locator("#pane-here").evaluate((pane, href) => {
    const a = Object.assign(document.createElement("a"), {
      id: "a-link",
      href,
      target: "_blank",
      rel: "noopener noreferrer",
    });
    a.textContent = "the docs";
    Object.assign(a.style, { position: "absolute", left: "40px", top: "60px", zIndex: "50" });
    pane.append(a);
  }, LINK);
  return page.locator("#a-link");
}

test("a link of an actor with no Browser opens a new one in its task, at the link", async ({ page }) => {
  let opened = false;
  const seen = await host(page, () => opened);
  await page.route("**/api/apps/open", async (route) => {
    seen.opened.push(route.request().postDataJSON());
    opened = true; // the server puts the two in one task, the actor attached
    await route.fulfill({
      json: { id: KEY, app: "browser", gatherer: GATHERER, folder: "/work", title: "work", data: {} },
    });
  });
  await openActor(page, CLAUDE);
  await (await addLink(page)).click();
  await expect(browserPane(page)).toHaveCount(1);
  await expect.poll(() => seen.links).toEqual([LINK]); // told its panel, which asked its backend to open it
  expect(seen.opened).toEqual([expect.objectContaining({ app: "browser", gatherer: GATHERER, channel: seen.channel })]);
  await expect(page).toHaveURL(/127\.0\.0\.1/); // still the dashboard, no tab of its own
});

test("a link of an actor with a Browser opens in a new tab of it, no other Browser made", async ({ page }) => {
  const seen = await host(page, () => true);
  await openActor(page, CLAUDE);
  await page.mouse.move(0, 0);
  const link = await addLink(page);
  await link.click();
  await expect(browserPane(page)).toHaveCount(1);
  await expect.poll(() => seen.links).toEqual([LINK]);
  await link.click(); // again: another tab of the same Browser
  await expect.poll(() => seen.links).toEqual([LINK, LINK]);
  expect(seen.opened).toEqual([]);
  await expect(browserPane(page)).toHaveCount(1);
});

test("a link clicked with a key held is left to the browser, as before", async ({ page }) => {
  const seen = await host(page, () => false);
  await openActor(page, CLAUDE);
  const link = await addLink(page);
  // the click as it reaches the link, after the page's own handling: whether the page took it, then put away here --
  // what the browser does with it (a tab of its own) varies (headless Chromium on Linux opens none)
  await link.evaluate((a) =>
    a.addEventListener("click", (ev) => {
      a.dataset.taken = String(ev.defaultPrevented);
      ev.preventDefault();
    }),
  );
  for (const key of [beside, "Shift", "Alt"] as const) {
    await link.evaluate((a) => delete a.dataset.taken);
    await link.click({ modifiers: [key] });
    await expect(link).toHaveAttribute("data-taken", "false");
  }
  expect(seen.opened).toEqual([]);
  await expect(browserPane(page)).toHaveCount(0);
});

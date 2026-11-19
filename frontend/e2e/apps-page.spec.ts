// THE APPS PAGE (features/apps/catalog.ts): a screen tab of its own -- opened from the settings panel's Apps, or a new
// tab's "Apps…" -- listing every app installed (each on in every folder), what it gives agents and costs them, the apps
// to install and those that couldn't load; a row's details beside the list; installing from a folder or git URL (staged,
// checked, then asked with what it may do), updating an app from git and uninstalling one, each asked first. The
// server's side (api/app_catalog.py) is the test's own here: the run's home is shared, and installing would change it.
import type { Page, Route } from "@playwright/test";
import { expect, test } from "./test";
import { open } from "./home";

type App = Record<string, unknown> & { name: string; label: string; origin: string };
const tool = (n: number, app: string) => Array.from({ length: n }, (_, i) => `${app}_t${i}`);
const BROWSER: App = {
  name: "browser",
  label: "Browser",
  version: "1",
  description: "a browser you and an agent use together",
  origin: "builtin",
  kind: "builtin",
  access: "task",
  with_agent: true,
  instances: "many",
  on_task: "join",
  on_task_own: "join",
  on_task_can: ["join", "folder", "no"],
  tools: tool(19, "browser"),
  tokens: 8873,
  can: ["a native web view over its panel, in the desktop app"],
  schedules: [],
  open: { demo: 3, other: 1 },
  data: { path: "~/.ag/apps/browser/data", bytes: 393216, there: true },
};
const STANDUP: App = {
  name: "standup",
  label: "Standup",
  version: "0.4.1",
  description: "collects what each actor did today",
  origin: "home",
  kind: "git",
  source: "https://github.com/someone/ag-standup",
  commit: "9c1e04a11",
  access: "group",
  on_task: "no",
  on_task_own: "no",
  on_task_can: ["folder", "no"],
  tools: ["standup_today"],
  tokens: 820,
  can: [],
  schedules: ["at 18:00"],
  open: {},
  data: { path: "~/.ag/apps/standup/data", bytes: 0, there: false },
};
const NEWS: App = {
  name: "paper_news",
  label: "Paper news",
  version: "1",
  description: "each weekday's new arXiv papers",
  origin: "builtin",
  kind: "builtin",
  tools: tool(4, "paper_news"),
  tokens: 1535,
  can: [],
  needs: "",
  data: { path: "~/.ag/apps/paper_news/data", bytes: 7340032, there: true },
};
const PAGER = {
  name: "pager",
  label: "Pager",
  version: "0.2.0",
  description: "pages you when an actor needs you",
  origin: "staged",
  kind: "folder",
  source: "/work/pager",
  commit: "",
  access: "group",
  tools: ["pager_page"],
  tokens: 110,
  can: ["sending you notifications"],
  own_process: true,
  schedules: [],
  id: "a".repeat(32),
};

// The catalog as the test changes it, and each request the page makes of it, kept.
async function appsHome(page: Page) {
  const state = { installed: [BROWSER, STANDUP], available: [NEWS] as App[], asked: [] as [string, unknown][] };
  const answer = (path: string, fn: (body: Record<string, unknown>) => unknown) =>
    page.route(`**/api/apps/${path}`, async (route: Route) => {
      const body = (route.request().postDataJSON() as Record<string, unknown>) || {};
      state.asked.push([path, body]);
      await route.fulfill({ json: fn(body) });
    });
  await page.route("**/api/apps/catalog", (route) =>
    route.fulfill({
      json: {
        installed: state.installed,
        available: state.available,
        broken: [
          { folder: "/h/apps/kanban", name: "kanban", error: "app.toml: panels: not a key here", origin: "home" },
        ],
      },
    }),
  );
  await page.route("**/api/apps/updates", (route) => route.fulfill({ json: { updates: { standup: "e7d2b13" } } }));
  await answer("stage", (b) =>
    b.source === STANDUP.source
      ? {
          ...STANDUP,
          version: "0.5.0",
          id: "b".repeat(32),
          installed: STANDUP,
          changes: {
            version: ["0.4.1", "0.5.0"],
            tools_added: ["standup_post"],
            tools_gone: [],
            can_added: [],
            own_process: false,
          },
        }
      : PAGER,
  );
  await answer("discard", () => ({}));
  await answer("install", (b) => {
    if (b.builtin) {
      state.available = state.available.filter((a) => a.name !== b.builtin);
      state.installed = [...state.installed, NEWS];
    } else if (b.id === PAGER.id) state.installed = [...state.installed, { ...PAGER, origin: "home" }];
    return { name: b.builtin || "pager" };
  });
  await answer("on_task", (b) => {
    const a = state.installed.find((x) => x.name === b.name)!;
    a.on_task = b.on_task;
    return { name: b.name, on_task: b.on_task };
  });
  await answer("uninstall", (b) => {
    state.installed = state.installed.filter((a) => a.name !== b.name);
    return { name: b.name, how: "builtin" };
  });
  return state;
}

const appsPage = (page: Page) => page.locator(".work > .lay-empty.ap:not([hidden])");
const appRow = (page: Page, name: string) => appsPage(page).locator(`.ap-row[data-app="${name}"]`);
const dialog = (page: Page) => page.getByRole("dialog");
const tabNames = (page: Page) => page.locator(".lay-tabs:visible .lay-tab .lay-name");

async function fromSettings(page: Page) {
  await page.locator("#about-btn").click();
  await page.locator("#manage-apps").click();
  await expect(appsPage(page)).toBeVisible();
}

test("the settings panel's Apps opens the Apps page in a tab of its own: every app, what agents get, its details", async ({
  page,
}) => {
  await appsHome(page);
  await open(page);
  await fromSettings(page);
  await expect(page.locator("#about")).toBeHidden(); // the panel closed
  await expect(page.locator(".lay-tabs:visible .lay-tab[aria-selected=true] .lay-name")).toHaveText("Apps");
  await expect(page.locator(".lay-tabs:visible .lay-tab[aria-selected=true] .lay-page")).toHaveCount(1); // its mark
  const browser = appRow(page, "browser");
  await expect(browser).toContainText("The agents in its task");
  await expect(browser).toContainText("19 tools");
  await expect(browser.locator(".ap-big")).toHaveText("≈8.9k tokens per agent"); // a large cost, marked
  await expect(browser.locator(".ap-badge.open")).toHaveText("4 open");
  await expect(appRow(page, "standup")).toContainText("1 tool");
  await expect(appRow(page, "standup").locator(".ap-badge.upd")).toHaveText("update"); // a newer commit
  await expect(appsPage(page).locator(".ap-row.broken")).toContainText("app.toml: panels: not a key here");
  await browser.click();
  const side = appsPage(page).locator(".ap-side");
  await expect(side.locator("h2")).toHaveText("Browser");
  await expect(side).toContainText("only the agents in its task");
  await expect(side.getByRole("button", { name: "With an agent" })).toBeVisible(); // alone, or with an agent
  await expect(side).toContainText("A native web view over its panel, in the desktop app");
  await expect(side.locator(".ap-kv").last()).toContainText("demo3 open");
  await expect(side.locator(".ap-tools code")).toHaveCount(5);
  await side.getByRole("button", { name: "+14" }).click();
  await expect(side.locator(".ap-tools code")).toHaveCount(19);
  await page.keyboard.press("Escape");
  await expect(side).toHaveCount(0);
  await appsPage(page).getByLabel("Search apps").fill("standup_today"); // its tools are searched too
  await expect(appsPage(page).locator(".ap-row")).toHaveCount(1);
});

test("an app's details choose what + on an actor or a task does with it: its own marked, a choice kept at once", async ({
  page,
}) => {
  const state = await appsHome(page);
  await open(page);
  await fromSettings(page);
  await appRow(page, "browser").click();
  const side = appsPage(page).locator(".ap-side");
  const choice = side.getByRole("radiogroup");
  await expect(choice.getByRole("radio")).toHaveCount(3);
  await expect(choice.locator(".ap-opt", { hasText: "Joins the task" })).toContainText("default");
  await expect(choice.getByRole("radio", { name: /Joins the task/ })).toBeChecked();
  await choice.getByText("Opens at the agent's directory").click();
  await expect
    .poll(() => state.asked.filter(([p]) => p === "on_task"))
    .toEqual([["on_task", { name: "browser", on_task: "folder" }]]);
  await expect(choice.getByRole("radio", { name: /Opens at the agent's directory/ })).toBeChecked();
  await appRow(page, "standup").click(); // an app every agent of the group may use: never in a task
  await expect(side.getByRole("radiogroup").getByRole("radio")).toHaveCount(2);
  await expect(side.getByRole("radiogroup")).not.toContainText("Joins the task");
});

test("a new tab's Apps… opens the page in that tab, and opening it again shows that tab, not a second", async ({
  page,
}) => {
  await appsHome(page);
  await open(page);
  await page.locator(".lay-tab-add:visible").click();
  const names = await tabNames(page).allTextContents();
  await page.locator(".work > .lay-empty.nt .nt-app.manage").click();
  await expect(appsPage(page)).toBeVisible();
  await expect(tabNames(page)).toHaveText([...names.slice(0, -1), "Apps"]); // the new tab became it
  await page.locator(".lay-tab-add:visible").click();
  await fromSettings(page);
  await expect(tabNames(page).filter({ hasText: /^Apps$/ })).toHaveCount(1);
});

test("installing from a folder: checked, then asked with what it may do; Cancel discards it", async ({ page }) => {
  const state = await appsHome(page);
  await open(page);
  await fromSettings(page);
  await appsPage(page).getByRole("button", { name: "+ Install from a folder or git URL…" }).click();
  await dialog(page).getByLabel("Folder or git URL").fill("/work/pager");
  await dialog(page).getByRole("button", { name: "Check" }).click();
  await expect(dialog(page).locator("h2")).toHaveText("Install Pager?");
  await expect(dialog(page)).toContainText("Run its own process on this computer");
  await expect(dialog(page)).toContainText("Sending you notifications");
  await expect(dialog(page)).toContainText("1 tool, ≈100 tokens per agent");
  await expect(dialog(page)).toContainText("Every agent of the group, when it next starts");
  await expect(dialog(page).locator(".ap-warn")).toContainText("Only install apps you trust");
  await dialog(page).getByRole("button", { name: "Cancel" }).click();
  await expect(dialog(page)).toHaveCount(0);
  expect(state.asked.map(([p]) => p)).toEqual(["stage", "discard"]); // staged, then discarded
  await appsPage(page).getByRole("button", { name: "+ Install from a folder or git URL…" }).click();
  await dialog(page).getByLabel("Folder or git URL").fill("/work/pager");
  await dialog(page).getByLabel("Folder or git URL").press("Enter");
  await dialog(page).getByRole("button", { name: "Install" }).click();
  await expect(dialog(page)).toHaveCount(0);
  expect(state.asked.at(-1)).toEqual(["install", { id: PAGER.id }]);
  await expect(appsPage(page).locator(".ap-note")).toContainText("Installed Pager. Agents get its tools");
  await expect(appRow(page, "pager")).toHaveClass(/sel/); // shown, its details beside the list
});

test("an app that comes with ag uninstalled -- its windows said, its data kept unless ticked -- and installed again", async ({
  page,
}) => {
  const state = await appsHome(page);
  await open(page);
  await fromSettings(page);
  await appRow(page, "browser").locator(".ap-more").click();
  await page.getByRole("menuitem", { name: "Uninstall…" }).click();
  await expect(dialog(page)).toContainText("Its 4 open windows close (demo 3, other 1).");
  await expect(dialog(page)).toContainText("Reinstall it from Available to install");
  await dialog(page)
    .getByLabel(/Also delete its data/)
    .check();
  await dialog(page).getByRole("button", { name: "Uninstall" }).click();
  await expect(dialog(page)).toHaveCount(0);
  expect(state.asked.at(-1)).toEqual(["uninstall", { name: "browser", data: true }]);
  await expect(appsPage(page).locator(".ap-note")).toContainText("Uninstalled Browser. Its data was deleted.");
  await expect(appRow(page, "browser")).toHaveCount(0);
  await appsPage(page).locator('.ap-row[data-app="paper_news"] .ap-btn').click(); // uninstalled before: no warning

  await expect(dialog(page).locator(".ap-warn")).toHaveCount(0);
  await expect(dialog(page)).toContainText("Its data from before is still there (7.0 MB)");
  await dialog(page).getByRole("button", { name: "Install" }).click();
  expect(state.asked.at(-1)).toEqual(["install", { builtin: "paper_news" }]);
  await expect(appRow(page, "paper_news")).toBeVisible();
});

test("an app from git with a newer commit: Update says only what changes, then updates it in place", async ({
  page,
}) => {
  const state = await appsHome(page);
  await open(page);
  await fromSettings(page);
  await appRow(page, "standup").locator(".ap-more").click();
  await page.getByRole("menuitem", { name: "Update…" }).click();
  await expect(dialog(page).locator("h2")).toHaveText("Update Standup to 0.5.0?");
  await expect(dialog(page)).toContainText("New tool: standup_post");
  await dialog(page).getByRole("button", { name: "Update" }).click();
  await expect(dialog(page)).toHaveCount(0);
  expect(state.asked.at(-1)).toEqual(["install", { id: "b".repeat(32), update: true }]);
});

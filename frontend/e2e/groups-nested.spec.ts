// Groups inside another group's folder, and the two settings (the Notes design "Groups: folders, defaults and Manage
// groups"; 05-group-moves.js's placeOf, askOwn, askAbove, askAloneHere, askJoin; groups.py's `place`, `own`, `above`):
// a folder takes its parent's group or has its own, an actor has its folder's group or is on its own. A group placed in
// a folder is drawn there, with the mark of a group; an actor on its own there, with the mark of one. Each switch asks
// first; a group dropped into a folder asks Merge or Keep its own group.
import type { Page } from "@playwright/test";
import { expect, streamsAsRequests, test } from "./test";
import { CLAUDE, CODEX, GATHERER, open } from "./home";

const LAB = "lab";
const LAB_ACTOR = "Lab notes";
const ALONE_ACTOR = "Reads alone";
const WORK = 51; // demo's folder
const ALONE = "self:a1000000-0000-4000-8000-0000000000a2";

type Agent = { channel: string; harness?: string; [k: string]: unknown };
type Group = { name: string; agents: Agent[]; [k: string]: unknown };

// The home on its one database: demo, with a folder Work holding its Claude actor; lab, of one actor; an actor on its
// own. `places`: where lab and the actor on its own are placed, as the server says.
async function home(page: Page, places: Record<string, { in: string; folder: number | null }>) {
  await page.route("**/api/home", async (route) => {
    const home = await (await route.fetch()).json();
    const demo = home.gatherers.find((x: Group) => x.name === GATHERER) as Group;
    const codex = demo.agents.find((a) => a.harness === "codex")!;
    const claude = demo.agents.find((a) => a.harness !== "codex")!;
    const one = (channel: string, said: string) => ({
      ...codex,
      channel,
      session: null,
      status: "idle",
      last_user_message: said,
      name: null,
    });
    home.gatherers.push({ ...demo, name: LAB, agents: [one("1ab00000-0000-4000-8000-0000000000a1", LAB_ACTOR)] });
    home.gatherers.push({ ...demo, name: ALONE, alone: true, agents: [one(ALONE.slice(5), ALONE_ACTOR)] });
    home.folders = {
      ...home.folders,
      [GATHERER]: {
        folders: [{ id: WORK, parent: null, name: "Work", closed: null }],
        filed: { [claude.channel]: WORK },
      },
    };
    home.places = places;
    home.merged = true;
    await route.fulfill({ json: home });
  });
  await streamsAsRequests(page);
  await page.route("**/api/stream*", (route) => route.abort());
}

const groupRow = (page: Page, name: string) => page.locator("#agents .gatherer-row", { hasText: name });
const workLine = (page: Page) => page.locator("#agents .folder-line", { hasText: "Work" });
const demoBox = (page: Page) =>
  page.locator("#agents > .gatherer", { has: page.locator(":scope > .gatherer-row", { hasText: GATHERER }) });

async function answering(page: Page, json: (body: Record<string, unknown>) => Record<string, unknown>) {
  const asked: Record<string, unknown>[] = [];
  await page.route("**/api/groups", async (route) => {
    const body = route.request().postDataJSON();
    asked.push(body);
    await route.fulfill({ json: json(body) });
  });
  return asked;
}

test("a group and an actor on its own placed in a folder are drawn there, marked, and nowhere else", async ({
  page,
}) => {
  await home(page, { [LAB]: { in: GATHERER, folder: WORK }, [ALONE]: { in: GATHERER, folder: WORK } });
  await open(page);
  await workLine(page).locator(".fname").click(); // folded at first: opened, to show what is in it
  const work = demoBox(page).locator(".f-kids").first();
  const lab = work.locator(".gatherer.nested .gatherer-row", { hasText: LAB });
  await expect(lab).toBeVisible();
  await expect(lab.locator(".g-mark")).toHaveAttribute(
    "title",
    `A group of its own inside ${GATHERER}: its actors share context with each other, not with ${GATHERER}'s`,
  );
  await expect(work.locator("button.agent", { hasText: LAB_ACTOR })).toBeVisible();
  await expect(work.locator("button.agent", { hasText: ALONE_ACTOR }).locator(".alone-mark")).toBeVisible();
  await expect(work.locator("button.agent", { hasText: CLAUDE })).toBeVisible(); // demo's own, beside them
  await expect(page.locator("#agents > .gatherer > .gatherer-row", { hasText: LAB })).toHaveCount(0); // not at the top too
  await expect(page.locator("#agents > .gatherer.alone")).toHaveCount(0);
  await expect(page.locator("#agents button.agent", { hasText: ALONE_ACTOR })).toHaveCount(1);
});

test("a folder given a group of its own where it is, asked first", async ({ page }) => {
  await home(page, {});
  const asked = await answering(page, () => ({
    own: { group: "Work", actors: [], apps: [], from: GATHERER, in: GATHERER, folder: null },
  }));
  await open(page);
  await workLine(page).hover();
  await workLine(page).locator(".f-acts .act.own").click();
  const dialog = page.locator("dialog.mv-dialog");
  await expect(dialog.locator("h3")).toHaveText("Give Work a group of its own?");
  await expect(dialog.locator(".mv-line").first()).toContainText(
    `Work becomes a group of its own where it is, named after it, with the settings of ${GATHERER}.`,
  );
  await expect(dialog.locator(".mv-line").first()).toContainText(
    `Its actor leaves the ${GATHERER} group (1 other) for it.`,
  );
  await dialog.getByRole("button", { name: "Make a group" }).click();
  await expect(dialog).toBeHidden();
  expect(asked).toEqual([{ gatherer: GATHERER, do: "own", folder: WORK }]);
});

test("a nested group back in the group around it: the merge's question, without Keep", async ({ page }) => {
  await home(page, { [LAB]: { in: GATHERER, folder: WORK } });
  const asked = await answering(page, (body) =>
    body.do === "merge_plan"
      ? { from: LAB, to: GATHERER, into: WORK, folder: LAB, actors: 1, before: {}, apps: [] }
      : {
          merged: { group: GATHERER, folder: 60, name: LAB, actors: [], apps: [], joined: {}, from: LAB },
          folders: {},
          tasks: {},
        },
  );
  await open(page);
  await workLine(page).locator(".fname").click(); // folded at first: opened, to show what is in it
  await groupRow(page, LAB).hover();
  await groupRow(page, LAB).locator(".act.above").click();
  const dialog = page.locator("dialog.mv-dialog");
  await expect(dialog.locator("h3")).toHaveText(`Make ${LAB} part of ${GATHERER} again?`);
  await expect(dialog.getByRole("button", { name: "Keep its own group" })).toHaveCount(0);
  await dialog.getByRole("button", { name: "Merge" }).click();
  await expect(dialog).toBeHidden();
  expect(asked.at(-1)).toEqual({ gatherer: LAB, to: GATHERER, into: WORK, do: "merge" });
});

test("a group dropped on another's folder: Keep its own group puts it there, a group inside it", async ({ page }) => {
  await home(page, {});
  const asked = await answering(page, (body) =>
    body.do === "merge_plan"
      ? { from: LAB, to: GATHERER, into: WORK, folder: LAB, actors: 1, before: {}, apps: [] }
      : { placed: { group: LAB, in: GATHERER, folder: WORK }, places: {}, gatherer_folders: {} },
  );
  await open(page);
  await groupRow(page, LAB).dragTo(workLine(page));
  const dialog = page.locator("dialog.mv-dialog");
  await expect(dialog.locator("h3")).toHaveText(`Merge ${LAB} into ${GATHERER}?`);
  await expect(dialog.locator(".mv-line").last()).toHaveText(
    "Or keep it a group of its own, inside Work: no actor starts or stops sharing context.",
  );
  await dialog.getByRole("button", { name: "Keep its own group" }).click();
  await expect(dialog).toBeHidden();
  expect(asked.at(-1)).toEqual({ gatherer: LAB, to: GATHERER, into: WORK, do: "place" });
});

test("an actor put on its own stays in its folder, and joins its folder's group again from its row", async ({
  page,
}) => {
  await home(page, { [ALONE]: { in: GATHERER, folder: WORK } });
  const asked = await answering(page, (body) =>
    body.do === "plan"
      ? { actors: [ALONE.slice(5)], from: ALONE, to: GATHERER, before: {}, after: {} }
      : {
          alone: { group: "x", actors: [], apps: [] },
          moved: { actors: [], apps: [], joined: {} },
          folders: {},
          tasks: {},
        },
  );
  await open(page);
  await workLine(page).locator(".fname").click(); // folded at first: opened, to show what is in it
  const dialog = page.locator("dialog.mv-dialog");
  const claude = page.locator("#agents button.agent", { hasText: CLAUDE });
  await claude.hover();
  await claude.locator(".group-btn").click();
  await expect(dialog.locator("h3")).toHaveText("Put it on its own?");
  await expect(dialog.locator(".mv-line").first()).toContainText("staying in Work");
  await dialog.getByRole("button", { name: "On its own" }).click();
  await expect(dialog).toBeHidden();
  expect(asked.at(-1)).toEqual({ gatherer: GATHERER, do: "alone", channel: expect.any(String), here: true });

  const lone = page.locator("#agents button.agent", { hasText: ALONE_ACTOR });
  await lone.hover();
  await lone.locator(".group-btn").click();
  await expect(dialog.locator("h3")).toHaveText(`Join the ${GATHERER} group?`);
  await expect(dialog.getByRole("button", { name: "Stay on its own" })).toHaveCount(0); // asked to join: no staying
  await dialog.getByRole("button", { name: "Join" }).click();
  await expect(dialog).toBeHidden();
  expect(asked.at(-1)).toEqual({ gatherer: ALONE, to: GATHERER, channels: [ALONE.slice(5)], do: "move", into: WORK });
  await expect(page.locator("#agents button.agent", { hasText: CODEX }).locator(".group-btn")).toHaveCount(1); // demo's own
});

test("Manage groups shows each group's folders and actors with their switches, each asking as the list does", async ({
  page,
}) => {
  await home(page, { [LAB]: { in: GATHERER, folder: WORK }, [ALONE]: { in: GATHERER, folder: WORK } });
  await answering(page, (body) =>
    body.do === "plan" ? { actors: [ALONE.slice(5)], from: ALONE, to: GATHERER, before: {}, after: {} } : {},
  );
  await open(page);
  await page.locator("#agents .aside-head .manage-groups").click();
  const panel = page.locator("dialog.mg-dialog");
  await expect(panel.locator("h3")).toHaveText("Manage groups");
  const row = (text: string) => panel.locator(".mg-row", { hasText: text });
  await expect(row(GATHERER).first().locator(".mg-note")).toHaveText("a group"); // at the top: a group, no switch
  await expect(row("Work").locator(".mg-opt.on")).toHaveText("Parent's group");
  await expect(row(LAB).first().locator(".mg-opt.on")).toHaveText("Own group"); // inside Work: its own
  await expect(row(ALONE_ACTOR).locator(".mg-opt.on")).toHaveText("On its own");
  await expect(row(CLAUDE).locator(".mg-opt.on")).toHaveText("Folder's group");
  await expect(row(LAB_ACTOR).locator(".mg-opt.on")).toHaveText("Folder's group");
  await row("Work").getByRole("button", { name: "Own group" }).click();
  const dialog = page.locator("dialog.mv-dialog");
  await expect(dialog.locator("h3")).toHaveText("Give Work a group of its own?"); // the list's own question, over it
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(panel).toBeVisible();
  await row(ALONE_ACTOR).getByRole("button", { name: "Folder's group" }).click();
  await expect(dialog.locator("h3")).toHaveText(`Join the ${GATHERER} group?`);
});

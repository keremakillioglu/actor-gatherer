// Tables in the Notes app (ag_apps/notes/): made from the / menu or pasted from a spreadsheet, typed in cell by cell
// (Tab, Enter and the arrows from cell to cell), their rows and columns added, moved, deleted and widened from their
// handles and + bars, their cells picked by a drag (copied as tab-separated rows, emptied), and changed by an agent
// while the user types in another cell. Agents read and write a table as markdown (tests/test_app_notes_tables.py).
import type { FrameLocator, Page } from "@playwright/test";
import { expect, test } from "./test";
import { open } from "./home";
import { binPage, call, newPage, openNotes } from "./notes-home";

const read = async (page: Page, instance: string, title: string) =>
  (await call(page, instance, "read", { page: title })).text;
const table = (panel: FrameLocator) => panel.locator(".blk[data-type=table]").first();
const cell = (panel: FrameLocator, r: number, c: number) =>
  table(panel).locator("tbody tr").nth(r).locator("td, th").nth(c).locator(".cell");
/** The table's cells' words, row by row. */
const grid = (panel: FrameLocator) =>
  table(panel)
    .locator("tbody tr")
    .evaluateAll((trs) => trs.map((tr) => [...tr.querySelectorAll(".cell")].map((c) => c.textContent || "")));
const TRIPS = "| City | Flight | Hotel |\n| --- | --- | --- |\n| Lisbon | Booked | Ask |\n| Porto | Ask | Done |";

test("/table makes a table, typed in cell by cell, that agents read as markdown", async ({ page }) => {
  await open(page);
  const { panel, instance } = await openNotes(page);
  await newPage(page, panel, "Tables");
  const kb = page.keyboard;
  await kb.type("/tab");
  await expect(panel.locator(".pop .it.on")).toContainText("Table");
  await kb.press("Enter");
  await expect(table(panel).locator("tbody tr")).toHaveCount(3);
  await expect(table(panel).locator("tbody tr").first().locator("th")).toHaveCount(3); // its header row
  await expect(cell(panel, 0, 0)).toBeFocused();
  for (const w of ["City", "Flight", "Hotel", "Lisbon", "Booked"]) {
    await kb.type(w);
    await kb.press("Tab");
  }
  await kb.press("Shift+Tab");
  await kb.press("ControlOrMeta+b");
  await kb.type("!");
  await kb.press("Enter"); // the cell below
  await kb.type("Porto");
  await expect(cell(panel, 2, 1)).toBeFocused();
  await kb.press("Tab");
  await kb.press("Tab"); // past the last cell: a new row
  await expect(table(panel).locator("tbody tr")).toHaveCount(4);
  await expect(cell(panel, 3, 0)).toBeFocused();
  await kb.type("Faro");
  await kb.press("ArrowUp"); // the cell above, then past the table's top: the title
  await kb.press("ArrowUp");
  await kb.press("ArrowUp");
  await kb.press("ArrowUp");
  await expect(panel.locator("#title")).toBeFocused();
  await kb.press("ArrowDown"); // back into its first cell
  await expect(cell(panel, 0, 0)).toBeFocused();
  await expect
    .poll(() => grid(panel))
    .toEqual([
      ["City", "Flight", "Hotel"],
      ["Lisbon", "Booked!", ""],
      ["", "Porto", ""],
      ["Faro", "", ""],
    ]);
  await expect
    .poll(() => read(page, instance, "Tables"))
    .toContain(
      "] | City | Flight | Hotel |\n| --- | --- | --- |\n| Lisbon | Booked**!** |  |\n|  | Porto |  |\n| Faro |  |  |",
    );
  // ⌘Z takes back the typing in one cell, then the row Tab added
  await cell(panel, 3, 0).click();
  await kb.press("ControlOrMeta+z");
  await expect.poll(() => grid(panel).then((g) => g[3])).toEqual(["", "", ""]);
  await panel.locator("#title").click();
  await kb.press("ControlOrMeta+z");
  await expect(table(panel).locator("tbody tr")).toHaveCount(3);
  await binPage(panel, "Tables");
});

test("rows and columns are added, moved, deleted and widened from the table's handles", async ({ page }) => {
  await open(page);
  const { panel, instance } = await openNotes(page);
  await call(page, instance, "add", { title: "Trips", markdown: TRIPS });
  await panel.locator(".pg-row", { hasText: "Trips" }).click();
  await expect(table(panel).locator("tbody tr")).toHaveCount(3);

  await cell(panel, 1, 1).hover();
  await table(panel).locator(".tbl-add-col").click();
  await expect(table(panel).locator("tbody tr").first().locator("th")).toHaveCount(4);
  await cell(panel, 1, 1).hover();
  await table(panel).locator(".tbl-add-row").click();
  await expect(table(panel).locator("tbody tr")).toHaveCount(4);
  await expect(cell(panel, 3, 0)).toBeFocused(); // the new row's first cell, to type in

  // a column's menu: deleted; sorted
  await cell(panel, 0, 3).hover();
  await table(panel).locator(".tbl-ch").click();
  await panel.locator(".pop .it", { hasText: "Delete column" }).click();
  await expect(table(panel).locator("tbody tr").first().locator("th")).toHaveCount(3);
  await cell(panel, 1, 0).hover();
  await table(panel).locator(".tbl-ch").click();
  await panel.locator(".pop .it", { hasText: "Sort Z → A" }).click();
  await expect.poll(() => grid(panel).then((g) => g.map((r) => r[0]))).toEqual(["City", "Porto", "Lisbon", ""]);
  // a row's menu: one inserted above; the empty one deleted
  await cell(panel, 1, 0).hover();
  await table(panel).locator(".tbl-rh").click();
  await panel.locator(".pop .it", { hasText: "Insert above" }).click();
  await expect.poll(() => grid(panel).then((g) => g.map((r) => r[0]))).toEqual(["City", "", "Porto", "Lisbon", ""]);
  await cell(panel, 4, 0).hover();
  await table(panel).locator(".tbl-rh").click();
  await panel.locator(".pop .it", { hasText: "Delete row" }).click();
  await expect(table(panel).locator("tbody tr")).toHaveCount(4);

  // a row dragged by its handle: Lisbon moved above the empty row
  await cell(panel, 3, 0).hover();
  const handle = (await table(panel).locator(".tbl-rh").boundingBox())!;
  const target = (await cell(panel, 1, 0).boundingBox())!;
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
  await page.mouse.down();
  await page.mouse.move(handle.x + 4, target.y + 6, { steps: 6 });
  await expect(table(panel).locator(".tbl-drop")).toHaveCount(1);
  await page.mouse.up();
  await expect.poll(() => grid(panel).then((g) => g.map((r) => r[0]))).toEqual(["City", "Lisbon", "", "Porto"]);

  // a column's edge dragged: its width kept; double-clicked: an equal share again
  const col = table(panel).locator("colgroup col").first();
  const was = parseFloat((await col.getAttribute("style"))!.replace(/[^\d.]/g, ""));
  const edge = (await table(panel).locator(".tbl-rs").first().boundingBox())!;
  await page.mouse.move(edge.x + 3, edge.y + 20);
  await page.mouse.down();
  await page.mouse.move(edge.x + 63, edge.y + 20, { steps: 5 });
  await page.mouse.up();
  await expect.poll(async () => parseFloat((await col.getAttribute("style"))!.replace(/[^\d.]/g, ""))).toBe(was + 60);
  await page.mouse.dblclick(edge.x + 63, edge.y + 20);
  await expect.poll(async () => parseFloat((await col.getAttribute("style"))!.replace(/[^\d.]/g, ""))).toBe(was);

  // the table's own menu: no header row, a header column
  await cell(panel, 1, 1).hover();
  await table(panel).locator(".gut .grip").click();
  await panel.locator(".pop .it", { hasText: "Header row" }).click();
  await expect(table(panel).locator("th")).toHaveCount(0);
  await cell(panel, 1, 1).hover();
  await table(panel).locator(".gut .grip").click();
  await panel.locator(".pop .it", { hasText: "Header column" }).click();
  await expect(table(panel).locator("th")).toHaveCount(4);
  await expect
    .poll(() => read(page, instance, "Trips"))
    .toContain(
      "| City | Flight | Hotel |\n| --- | --- | --- |\n| Lisbon | Booked | Ask |\n|  |  |  |\n| Porto | Ask | Done |",
    );
  await binPage(panel, "Trips");
});

test("an agent changes a table while the user types in another of its cells: both kept", async ({ page }) => {
  await open(page);
  const { panel, instance } = await openNotes(page);
  await call(page, instance, "add", { title: "Shared", markdown: TRIPS });
  await panel.locator(".pg-row", { hasText: "Shared" }).click();
  const id = /\[([a-z0-9]{8})\] \| City/.exec(await read(page, instance, "Shared"))![1];
  await cell(panel, 1, 2).click();
  await page.keyboard.press("End");
  await page.keyboard.type(" first");
  await call(page, instance, "change", {
    page: "Shared",
    block: id,
    markdown: "| City | Flight | Hotel |\n| --- | --- | --- |\n| Lisbon | Booked | Ask |\n| Porto | Booked | Done |",
  });
  await expect(cell(panel, 2, 1)).toHaveText("Booked"); // the agent's cell
  await expect(cell(panel, 1, 2)).toHaveText("Ask first"); // the user's, as typed
  await expect(cell(panel, 1, 2)).toBeFocused();
  await page.keyboard.type("!");
  await panel.locator("#title").click();
  await expect
    .poll(() => read(page, instance, "Shared"))
    .toContain("| Lisbon | Booked | Ask first! |\n| Porto | Booked | Done |");
  await binPage(panel, "Shared");
});

test("cells picked by a drag are copied and emptied; a spreadsheet's cells pasted make a table, or fill one", async ({
  page,
}) => {
  await open(page);
  const { panel, instance } = await openNotes(page);
  await call(page, instance, "add", { title: "Cells", markdown: TRIPS });
  await panel.locator(".pg-row", { hasText: "Cells" }).click();
  const a = (await cell(panel, 1, 0).boundingBox())!;
  const z = (await cell(panel, 2, 1).boundingBox())!;
  await page.mouse.move(a.x + 10, a.y + 10);
  await page.mouse.down();
  await page.mouse.move(z.x + 10, z.y + 10, { steps: 6 });
  await page.mouse.up();
  await expect(table(panel).locator(".cp")).toHaveCount(4);
  const [text, ours] = await panel.locator("body").evaluate(() => {
    const dt = new DataTransfer();
    document.dispatchEvent(new ClipboardEvent("copy", { clipboardData: dt, bubbles: true, cancelable: true }));
    return [dt.getData("text/plain"), dt.getData("application/x-ag-notes-blocks")];
  });
  expect(text).toBe("Lisbon\tBooked\nPorto\tAsk");
  expect(JSON.parse(ours)[0].type).toBe("table");
  await page.keyboard.press("Backspace");
  await expect
    .poll(() => grid(panel))
    .toEqual([
      ["City", "Flight", "Hotel"],
      ["", "", "Ask"],
      ["", "", "Done"],
    ]);
  await page.keyboard.press("Escape");
  await expect(table(panel).locator(".cp")).toHaveCount(0);

  const paste = (t: string) =>
    panel.locator("body").evaluate((_, t) => {
      const dt = new DataTransfer();
      dt.setData("text/plain", t);
      document.activeElement!.dispatchEvent(
        new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }),
      );
    }, t);
  // into a cell: the cells from there, a row and a column added
  await cell(panel, 2, 2).click();
  await paste("x\ty\nz\tw\n");
  await expect
    .poll(() => grid(panel))
    .toEqual([
      ["City", "Flight", "Hotel", ""],
      ["", "", "Ask", ""],
      ["", "", "x", "y"],
      ["", "", "z", "w"],
    ]);
  // into a line: a table
  await panel.locator("#below").click();
  await paste("Name\tScore\nAda\t3\nLin\t10\n");
  await expect(panel.locator(".blk[data-type=table]")).toHaveCount(2);
  await expect
    .poll(() => read(page, instance, "Cells"))
    .toContain("| Name | Score |\n| --- | --- |\n| Ada | 3 |\n| Lin | 10 |");
  await binPage(panel, "Cells");
});

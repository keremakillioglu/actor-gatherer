// The Editor's keys in a file's text (ag_apps/editor/panel/editor.js, edMarkupKeys): ⌘B and ⌘I, bold and italic in a
// Markdown or LaTeX file's own markup, put on and taken off -- in the file, and in the box an actor's proposed lines are
// edited in -- and in any other file, left as they were.
import fs from "node:fs";
import path from "node:path";
import { expect, test } from "./test";
import { editorPanel, endEditor, project, startEditor } from "./editor-home";

test("⌘B and ⌘I make a Markdown or LaTeX file's selection bold and italic, and pressed again take it off", async ({
  page,
  request,
}) => {
  const { repo, plot } = project();
  const md = path.join(repo, "notes.md"),
    tex = path.join(repo, "paper.tex");
  fs.writeFileSync(md, "Some words here\nand more words\n");
  fs.writeFileSync(tex, "\\section{A}\nSome words here\nand \\emph{more} words\n\\textbf{a} or \\textbf{b}\n");
  const { sid, src } = await startEditor(page, repo);
  const panel = editorPanel(page);
  const frame = () => page.frames().find((f) => /^http:\/\/editor\.localhost:\d+\//.test(f.url()))!;
  const text = () => frame().evaluate("ed.s.view.state.doc.toString()") as Promise<string>;
  const line = (n: number) => frame().evaluate(`ed.s.view.state.doc.line(${n}).text`) as Promise<string>;
  const picked = () =>
    frame().evaluate("ed.s.view.state.selection.ranges.map(r => ed.s.view.state.sliceDoc(r.from, r.to))");
  // the selection: `word` on line `n` (with a space each side, if `spaced`), or nothing, the cursor at the line's end
  const pick = (n: number, word: string, spaced = false) =>
    frame().evaluate(
      `(([n, w, sp]) => { const v = ed.s.view, l = v.state.doc.line(n), at = w ? l.text.indexOf(w) : l.length;
        v.dispatch({ selection: { anchor: l.from + at - (sp ? 1 : 0), head: l.from + at + w.length + (sp ? 1 : 0) } });
      })(${JSON.stringify([n, word, spaced])})`,
    );
  const keys = async (...k: string[]) => {
    for (const key of k) await page.keyboard.press(`ControlOrMeta+${key}`);
  };
  const open = async (file: string) => {
    await panel
      .locator(".ed-row", { hasText: path.basename(file) })
      .first()
      .click();
    await expect(panel.locator(".ed-head .ed-path")).toContainText(path.basename(file));
    await panel.locator(".cm-line").first().click(); // the keys in the file
  };

  // Markdown: **…** and *…*
  await open(md);
  await pick(2, "more");
  await keys("b");
  expect(await line(2)).toBe("and **more** words");
  await keys("z"); // undone as typing is (the file's first change: the test's clock stands still, so Yjs's undo
  await expect.poll(() => line(2)).toBe("and more words"); // takes every change after it as one with it)
  await pick(1, "words", true); // its spaces left outside the markup
  await keys("b");
  expect(await line(1)).toBe("Some **words** here");
  expect(await picked()).toEqual(["words"]); // still selected: pressed again, taken off
  await keys("b");
  expect(await line(1)).toBe("Some words here");
  await keys("i");
  expect(await line(1)).toBe("Some *words* here");
  await keys("b"); // bold too, then italic off: bold left
  expect(await line(1)).toBe("Some ***words*** here");
  await keys("i");
  expect(await line(1)).toBe("Some **words** here");
  await pick(1, "**words**"); // the markup itself selected: taken off too
  await keys("b");
  expect(await line(1)).toBe("Some words here");
  await pick(1, ""); // nothing selected: the empty markup, the cursor in it
  await keys("b");
  await page.keyboard.type("bold");
  expect(await line(1)).toBe("Some words here**bold**");
  await pick(1, ""); // pressed again on the empty markup: taken out
  await keys("i", "i");
  expect(await line(1)).toBe("Some words here**bold**");
  await frame().evaluate(
    // several selections, each wrapped
    `(v => { const S = ed.s.A.EditorSelection, d = v.state.doc, a = d.line(1), b = d.line(2);
      const at = (l) => l.from + l.text.indexOf("words");
      v.dispatch({ selection: S.create([S.range(at(a), at(a) + 5), S.range(at(b), at(b) + 5)]) }); })(ed.s.view)`,
  );
  await keys("i");
  expect(await text()).toBe("Some *words* here**bold**\nand more *words*\n");
  expect(await picked()).toEqual(["words", "words"]);
  await expect.poll(() => fs.readFileSync(md, "utf8")).toBe("Some *words* here**bold**\nand more *words*\n"); // saved

  // LaTeX: \textbf{…} and \textit{…}
  await open(tex);
  await pick(2, "words");
  await keys("b");
  expect(await line(2)).toBe("Some \\textbf{words} here");
  expect(await picked()).toEqual(["words"]);
  await keys("b");
  expect(await line(2)).toBe("Some words here");
  await keys("i");
  expect(await line(2)).toBe("Some \\textit{words} here");
  await pick(2, "\\textit{words}"); // the markup itself selected
  await keys("i");
  expect(await line(2)).toBe("Some words here");
  await pick(3, "more"); // \emph is italic too
  await keys("i");
  expect(await line(3)).toBe("and more words");
  await pick(3, ""); // nothing selected
  await keys("b");
  await page.keyboard.type("x");
  expect(await line(3)).toBe("and more words\\textbf{x}");
  await pick(2, ""); // pressed again on the empty markup: taken out
  await keys("i", "i");
  expect(await line(2)).toBe("Some words here");
  await pick(4, "\\textbf{a} or \\textbf{b}"); // two, not one: its ends not one markup's, so wrapped
  await keys("b");
  expect(await line(4)).toBe("\\textbf{\\textbf{a} or \\textbf{b}}");
  await expect.poll(() => fs.readFileSync(tex, "utf8").split("\n")[2]).toBe("and more words\\textbf{x}"); // saved

  // any other file: its text left alone, ⌘I still CodeMirror's (the syntax around the selection)
  await open(plot);
  const before = await text();
  await pick(1, "drawing");
  await keys("b", "i");
  expect(await text()).toBe(before);
  expect(await picked()).toEqual(["'drawing'"]);

  // an actor's proposed lines, edited in their box (Review): the same keys there
  await open(md);
  await panel.locator(".ed-mode-pick select").selectOption("review");
  const called = await request.post(`/mcp/${sid}`, {
    data: {
      jsonrpc: "2.0",
      id: 1,
      method: "tools/call",
      params: {
        name: "editor_edit",
        arguments: { path: md, old_string: "and more *words*", new_string: "and more *words*, proposed" },
      },
    },
  });
  expect((await called.json()).result.content[0].text).toContain("Proposed");
  const box = panel.locator(".ed-cf", { hasText: "proposes to change these lines" });
  await box.getByRole("button", { name: "Edit", exact: true }).click();
  await expect(panel.locator(".ed-cf.editing .cm-content")).toBeFocused();
  const inBox = "[...ed.s.boxes.values()][0].view";
  await frame().evaluate(
    `(v => { const at = v.state.doc.toString().indexOf("proposed"); v.dispatch({ selection: { anchor: at, head: at + 8 } }); })(${inBox})`,
  );
  await keys("b");
  expect(await frame().evaluate(`${inBox}.state.doc.toString()`)).toBe("and more *words*, **proposed**\n");
  await endEditor(page, request, sid, src);
});

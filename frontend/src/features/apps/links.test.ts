// Links to things in apps, `ag://<app>/<path>` (app_kit/links.py has the same rules: tests/test_app_kit.py LinksTest).
import { describe, expect, it } from "vitest";
import { FILE_FORM, fileHref, filePath, isAppHref, joinPath, matchPath, parseHref } from "./links";

const FORMS = [{ form: "note/<id>" }, { form: "file/<path...>" }, { form: "bad/<a>/<a>" }];

describe("a link to something in an app", () => {
  it("is read: its app, path, part and instance", () => {
    expect(parseHref(" ag://notes/note/a1b2?instance=i9#l%203 ")).toEqual({
      href: "ag://notes/note/a1b2?instance=i9#l%203",
      app: "notes",
      path: "note/a1b2",
      part: "l 3",
      instance: "i9",
    });
    expect(parseHref("ag://notes")?.path).toBe("");
    for (const no of ["https://x.org/a", "ag:notes/x", "ag://Notes/x", "ag://9x/y", "page:abc123", "", null])
      expect(parseHref(no)).toBeNull();
    expect(isAppHref("AG://x")).toBe(true);
    expect(isAppHref("https://x")).toBe(false);
  });

  it("matches one of its app's forms, its values decoded", () => {
    expect(matchPath(FORMS, "note/a%20b")).toEqual({ form: "note/<id>", values: { id: "a b" } });
    expect(matchPath(FORMS, "note/a1/b2")).toBeNull(); // <id> is one segment
    expect(matchPath(FORMS, "note/")).toBeNull();
    expect(matchPath(FORMS, "file//Users/x/a%20b.py")).toEqual({
      form: "file/<path...>",
      values: { path: "/Users/x/a b.py" },
    });
    expect(matchPath(FORMS, "note/%E0%A4%A")).toBeNull(); // not decodable
    expect(matchPath(FORMS, "bad/1/2")).toBeNull(); // a form no manifest could have
    expect(matchPath(undefined, "note/x")).toBeNull();
  });

  it("reads a file's path as agents write one: absolute, relative, file://, at a line", () => {
    expect(filePath("/work/plan.md")).toEqual({ path: "/work/plan.md", line: 0 });
    expect(filePath("src/parser.py#L12")).toEqual({ path: "src/parser.py", line: 12 });
    expect(filePath("src/parser.py#L12-L20")).toEqual({ path: "src/parser.py", line: 12 });
    expect(filePath("/work/plan.md:7")).toEqual({ path: "/work/plan.md", line: 7 });
    expect(filePath("/work/plan.md:7:3")).toEqual({ path: "/work/plan.md", line: 7 });
    expect(filePath("./a%20b.txt")).toEqual({ path: "./a b.txt", line: 0 });
    expect(filePath("file:///work/a%20b.md#L2")).toEqual({ path: "/work/a b.md", line: 2 });
    expect(filePath("file://localhost/work/a.md")).toEqual({ path: "/work/a.md", line: 0 });
    for (const no of [
      "https://x.org/a",
      "ag://notes/page/x",
      "mailto:a@b.org",
      "//x.org/a",
      "#top",
      "?q=1",
      "~/a.md",
      "",
      null,
      "C:\\x\\a.txt",
      "file://host/a.md",
    ])
      expect(filePath(no)).toBeNull();
  });

  it("joins a relative path to a folder, and makes the link of an app's file form", () => {
    expect(joinPath("/work/app", "src/a.py")).toBe("/work/app/src/a.py");
    expect(joinPath("/work/app", "./src/../b.py")).toBe("/work/app/b.py");
    expect(joinPath("/work/app", "../../../x")).toBe("/x");
    expect(joinPath("/work/app", "/etc/hosts")).toBe("/etc/hosts");
    const href = fileHref("editor", "/work/a b/#1.md", 4);
    expect(href).toBe("ag://editor/file/work/a%20b/%231.md#L4");
    expect(matchPath([{ form: FILE_FORM }], parseHref(href)!.path)).toEqual({
      form: FILE_FORM,
      values: { path: "work/a b/#1.md" },
    });
    expect(fileHref("editor", "/work/a.md")).toBe("ag://editor/file/work/a.md");
  });
});

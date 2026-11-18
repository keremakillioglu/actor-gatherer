// Links to things in apps, `ag://<app>/<path>` (app_kit/links.py has the same rules: tests/test_app_kit.py LinksTest).
import { describe, expect, it } from "vitest";
import { isAppHref, matchPath, parseHref } from "./links";

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
});

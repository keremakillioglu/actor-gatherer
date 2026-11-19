// Each of the dashboard's colours a panel's stylesheets read is one the host gives it (theme-vars.ts): one left out
// falls back to the panel's light value, and stays light in the dark theme.
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { THEME_VARS } from "./theme-vars";

const ROOT = path.resolve(import.meta.dirname, "../../../..");
const read = (f: string) => readFileSync(path.join(ROOT, f), "utf8");
const names = (css: string, re: RegExp) => new Set([...css.matchAll(re)].map((m) => m[1]));
const list = (dir: string) => {
  try {
    return readdirSync(path.join(ROOT, dir));
  } catch {
    return [];
  }
};

describe("the theme's colours given to the apps' panels", () => {
  it("include every one of the dashboard's a panel reads and does not set itself", () => {
    const dashboard = names(read("frontend/src/core/page/base.css"), /(--[\w-]+)\s*:/g);
    const panels = [...list("ag_apps").map((app) => `ag_apps/${app}/panel`), "app_kit/fileedit/panel"];
    const missing: string[] = [];
    let sheets = 0;
    for (const dir of panels) {
      // a panel's stylesheets, loaded together: what one sets, the others read
      const css = list(dir)
        .filter((f) => f.endsWith(".css"))
        .map((f) => read(`${dir}/${f}`))
        .join("\n");
      if (!css) continue;
      sheets++;
      const own = names(css, /(--[\w-]+)\s*:/g);
      for (const v of names(css, /var\((--[\w-]+)/g))
        if (dashboard.has(v) && !own.has(v) && !THEME_VARS.includes(v)) missing.push(`${dir}: ${v}`);
    }
    expect(sheets).toBeGreaterThan(3);
    expect(missing).toEqual([]);
  });
});

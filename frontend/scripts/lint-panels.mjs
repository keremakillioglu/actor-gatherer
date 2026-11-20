// Lint for the apps' panels (ag_apps/*/panel/, app_kit/js/, app_kit/fileedit/panel/): plain browser scripts outside
// this build, each panel's loaded in order by its index.html. ESLint looks only under its config's folder, so this lints
// them from the repository's root with a config of its own. Scripts a page loads share one scope (app_kit.fileedit's
// with the Files and LaTeX apps' own): each is given, as globals, what the others on its pages declare -- so a name
// declared on none of them is still caught.
import js from "@eslint/js";
import { ESLint, Linter } from "eslint";
import globals from "globals";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(import.meta.dirname, "../..");
const PANELS = ["ag_apps/*/panel/*.js", "app_kit/js/*.js", "app_kit/fileedit/panel/*.js"];
// what the shared libraries a panel loads before its own scripts put on window (app_kit/js/, ag_dashboard/vendor/)
const LIBS = { AgApp: "readonly", agKit: "readonly", marked: "readonly", DOMPurify: "readonly" };

/** A served script's file: the SDK, the kit, app_kit.fileedit's, or the panel's own; null for a vendored library. */
function fileOf(app, src) {
  if (src === "/_ag/app.js") return "app_kit/js/app.js";
  if (src === "/_ag/lib/kit.js") return "app_kit/js/kit.js";
  const shared = src.match(/^\/_ag\/lib\/fileedit\/(.+\.js)$/);
  if (shared) return `app_kit/fileedit/panel/${shared[1]}`;
  if (src.startsWith("/") || /^https?:/.test(src)) return null;
  return `ag_apps/${app}/panel/${src}`;
}

/** Each panel's page: its scripts, in the order it loads them. */
function pages() {
  const out = [];
  for (const app of fs.readdirSync(path.join(ROOT, "ag_apps"))) {
    const html = path.join(ROOT, "ag_apps", app, "panel", "index.html");
    if (!fs.existsSync(html)) continue;
    const srcs = [...fs.readFileSync(html, "utf8").matchAll(/<script[^>]*\bsrc="([^"]+)"/g)].map((m) => m[1]);
    out.push(srcs.map((s) => fileOf(app, s)).filter((f) => f && fs.existsSync(path.join(ROOT, f))));
  }
  return out;
}

const linter = new Linter({ configType: "flat" });
/** The names `file` declares in the scope its page's scripts share. */
function declared(file) {
  const names = [];
  const scan = {
    rules: {
      names: {
        create: (ctx) => ({
          "Program:exit": (node) => names.push(...ctx.sourceCode.getScope(node).variables.map((v) => v.name)),
        }),
      },
    },
  };
  linter.verify(fs.readFileSync(path.join(ROOT, file), "utf8"), [
    {
      languageOptions: { ecmaVersion: "latest", sourceType: "script" },
      plugins: { scan },
      rules: { "scan/names": "error" },
    },
  ]);
  return names;
}

const shared = new Map(); // a file: what the other scripts on its pages declare
for (const page of pages())
  for (const file of page) {
    const got = shared.get(file) || {};
    for (const other of page) if (other !== file) for (const n of declared(other)) got[n] = "writable";
    shared.set(file, got);
  }

const eslint = new ESLint({
  cwd: ROOT,
  overrideConfigFile: true,
  overrideConfig: [
    { ignores: ["**/vendor/**", "**/assets/**", "**/node_modules/**"] },
    {
      files: PANELS,
      ...js.configs.recommended,
      languageOptions: { ecmaVersion: "latest", sourceType: "script", globals: { ...globals.browser, ...LIBS } },
    },
    {
      files: PANELS,
      rules: {
        // a catch that only goes on, keys left out of a copy (`_x`), a value only some calls pass on
        "no-unused-vars": [
          "error",
          {
            vars: "local",
            caughtErrors: "none",
            ignoreRestSiblings: true,
            varsIgnorePattern: "^_",
            argsIgnorePattern: "^_",
          },
        ],
      },
    },
    ...[...shared].map(([file, names]) => ({ files: [file], languageOptions: { globals: names } })),
  ],
});
const results = await eslint.lintFiles(PANELS);
const out = (await eslint.loadFormatter("stylish")).format(results);
if (out) console.log(out);
process.exitCode = results.some((r) => r.errorCount) ? 1 : 0;

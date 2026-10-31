// Builds DocWriter's page into ag_dashboard/vendor/docwriter/ (vite.config.mjs), puts pdf.js's viewer beside it
// (pdfjs/, from fetch.mjs), and writes the licenses of what is in it: LICENSE (DocWriter's, and every package
// bundled), pdfjs/LICENSE (pdf.js's). Run: npm ci && npm run build (here, in assets/src/docwriter).
import fs from "node:fs";
import path from "node:path";
import { build } from "vite";
import config, { OUT } from "./vite.config.mjs";
import { UPSTREAM } from "./fetch.mjs";

const here = import.meta.dirname;
const bundled = new Set();
await build({ ...config, configFile: false, plugins: [...config.plugins, {
  name: "licenses",
  generateBundle(_, chunks) {                       // the packages whose code is in the bundle
    for (const chunk of Object.values(chunks)) {
      for (const raw of Object.keys(chunk.modules || {})) {
        const id = raw.replace(/^\0/, "").split("?")[0];       // a plugin's virtual module names its file so
        const at = id.lastIndexOf("node_modules/");
        if (at < 0) continue;
        const parts = id.slice(at + "node_modules/".length).split("/");
        bundled.add(id.slice(0, at) + "node_modules/" + (parts[0].startsWith("@") ? parts.slice(0, 2) : parts.slice(0, 1)).join("/"));
      }
    }
  },
}] });

fs.cpSync(path.join(here, "pdfjs"), path.join(OUT, "pdfjs"), { recursive: true, filter: (p) => !p.endsWith(".version") });
fs.copyFileSync(path.join(here, "upstream", "static", "docwriter-mark.svg"), path.join(OUT, "docwriter-mark.svg"));

// DocWriter's system prompt, the actor's instructions (ag_dashboard/docwriter.py's `instructions`): upstream's
// buildSystemPrompt template, its interpolations filled in as they read for an actor -- the rules come with each
// message instead (render.ts) -- and any other one stops the build.
const src = (p) => fs.readFileSync(path.join(here, "upstream", "src", p), "utf8");
const route = src("routes/api/render/+server.ts");
const replyNote = src("lib/server/mcp-doc-tools.ts").match(/REPLY_BEFORE_EDIT_PROMPT_NOTE =\s*\n?\s*"([^"]+)"/);
if (!replyNote) throw new Error("instructions: REPLY_BEFORE_EDIT_PROMPT_NOTE not found");
const FILLS = {
  rulesBlock: "(My rules arrive in <session_state> with my messages: the latest list there is the one in force. None until then.)",
  AGENT_SCRATCH_DIR: ".docwriter/agent/scratch",
  REPLY_BEFORE_EDIT_PROMPT_NOTE: replyNote[1],
};
let at = route.indexOf("return `", route.indexOf("function buildSystemPrompt"));
if (at < 0) throw new Error("instructions: buildSystemPrompt's template not found");
let prompt = "";
for (at += "return `".length; route[at] !== "`"; at++) {
  if (at >= route.length) throw new Error("instructions: buildSystemPrompt's template not closed");
  if (route[at] === "\\") { at++; prompt += route[at] === "n" ? "\n" : route[at]; continue; }
  if (route[at] === "$" && route[at + 1] === "{") {
    const end = route.indexOf("}", at);
    const name = route.slice(at + 2, end).trim();
    if (!(name in FILLS)) throw new Error(`instructions: no filling for \${${name}}`);
    prompt += FILLS[name];
    at = end;
    continue;
  }
  prompt += route[at];
}
fs.writeFileSync(path.join(OUT, "instructions.md"), prompt.trim() + "\n");
const licenseOf = (dir, fallback) => {
  const file = fs.readdirSync(dir).find((n) => /^(licen[cs]e|copying)/i.test(n));
  return file ? fs.readFileSync(path.join(dir, file), "utf8").trim() : `License: ${fallback}`;
};
const notices = [`DocWriter (github.com/docwriter-org/docwriter at ${UPSTREAM}) (MIT)\n\n${licenseOf(path.join(here, "upstream"), "MIT")}\n`];
for (const dir of [...bundled].sort()) {
  if (!fs.existsSync(path.join(dir, "package.json"))) continue;
  const pkg = JSON.parse(fs.readFileSync(path.join(dir, "package.json"), "utf8"));
  notices.push(`${pkg.name} ${pkg.version} (${pkg.license})\n\n${licenseOf(dir, pkg.license)}\n`);
}
fs.writeFileSync(path.join(OUT, "LICENSE"), notices.join("\n" + "-".repeat(72) + "\n\n"));
let size = 0;
for (const f of fs.readdirSync(OUT, { recursive: true })) {
  const s = fs.statSync(path.join(OUT, f));
  if (s.isFile()) size += s.size;
}
console.log(`vendor/docwriter: ${(size / 1024 / 1024).toFixed(1)} MB, ${bundled.size} packages`);

// Bundles entry.mjs into ag_dashboard/vendor/editor.js, and the licenses of every package in it into
// editor.LICENSE beside it. Run: npm ci && npm run build (here, in assets/src/editor).
import * as esbuild from "esbuild";
import fs from "node:fs";
import path from "node:path";

const vendor = path.resolve(import.meta.dirname, "../../../ag_dashboard/vendor");
const built = await esbuild.build({
  entryPoints: [path.join(import.meta.dirname, "entry.mjs")], bundle: true, minify: true, format: "iife",
  target: "es2020", outfile: path.join(vendor, "editor.js"), metafile: true, legalComments: "none",
  banner: { js: "/* The dashboard's editor: CodeMirror 6 and Yjs, bundled by assets/src/editor/build.mjs. Licenses: editor.LICENSE */" },
});

const packages = new Set();
for (const file of Object.keys(built.metafile.inputs)) {
  const at = file.lastIndexOf("node_modules/");
  if (at < 0) continue;
  const parts = file.slice(at + "node_modules/".length).split("/");
  packages.add(file.slice(0, at) + "node_modules/" + (parts[0].startsWith("@") ? parts.slice(0, 2) : parts.slice(0, 1)).join("/"));
}
const notices = [...packages].sort().map((dir) => {
  const pkg = JSON.parse(fs.readFileSync(path.join(dir, "package.json"), "utf8"));
  const file = fs.readdirSync(dir).find((n) => /^(licen[cs]e|copying)/i.test(n));
  const text = file ? fs.readFileSync(path.join(dir, file), "utf8").trim() : `License: ${pkg.license}`;
  return `${pkg.name} ${pkg.version} (${pkg.license})\n\n${text}\n`;
});
fs.writeFileSync(path.join(vendor, "editor.LICENSE"), notices.join("\n" + "-".repeat(72) + "\n\n"));
const size = fs.statSync(path.join(vendor, "editor.js")).size;
console.log(`editor.js: ${(size / 1024).toFixed(0)} KB, ${packages.size} packages`);

// Fetches what build.mjs builds from, into this folder (both ignored by git):
//   upstream/  DocWriter's source (github.com/docwriter-org/docwriter, MIT) at PIN: its Svelte page is built from it
//   pdfjs/     pdf.js's prebuilt viewer at PDFJS (Apache-2.0), the files DocWriter's own setup takes from it
//              (scripts/setup-pdfjs.mjs there), its zip checked against PDFJS_SHA256
// Run: npm run fetch (npm run build runs it first). Moving PIN is how DocWriter is updated: build, and check
// the files src/ stands in for (vite.config.mjs) still have the shape src/ expects.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const here = import.meta.dirname;
const REPO = "https://github.com/docwriter-org/docwriter.git";
export const PIN = "449f41cbe74d2bf5fd89f478b7e67951ce77746f";
const PDFJS = "4.0.379";
const PDFJS_SHA256 = "11e5e00cf620e73f4b0b832d662b37d6a0cd25b3d0c817acfffec8516bc922dc";
const VIEWER_PATCH = 2;     // what is changed in its viewer.html, below: a new one, extracted again
const PDFJS_URL = `https://github.com/mozilla/pdf.js/releases/download/v${PDFJS}/pdfjs-${PDFJS}-dist.zip`;
// What of pdf.js's zip is kept: as DocWriter keeps it
const PDFJS_FILES = ["LICENSE", "build/pdf.mjs", "build/pdf.sandbox.mjs", "build/pdf.worker.mjs", "web/locale/locale.json",
  "web/viewer.css", "web/viewer.html", "web/viewer.mjs", "web/cmaps/*", "web/images/*", "web/locale/en-US/*",
  "web/standard_fonts/*"];

function git(...args) {
  return execFileSync("git", args, { encoding: "utf8", stdio: ["ignore", "pipe", "inherit"] }).trim();
}

const upstream = path.join(here, "upstream");
let have = null;
try {
  have = execFileSync("git", ["-C", upstream, "rev-parse", "HEAD"], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim();
} catch { /* none yet */ }
if (have !== PIN) {
  fs.rmSync(upstream, { recursive: true, force: true });
  git("init", "-q", upstream);
  git("-C", upstream, "fetch", "-q", "--depth", "1", REPO, PIN);
  git("-C", upstream, "-c", "advice.detachedHead=false", "checkout", "-q", "FETCH_HEAD");
  console.log(`upstream: DocWriter at ${PIN.slice(0, 7)}`);
}
// What SvelteKit's sync would write, which upstream's tsconfig.json extends: the compiler options the page is
// built with (TypeScript stripped by esbuild, its imports kept as written)
const kit = path.join(upstream, ".svelte-kit", "tsconfig.json");
fs.mkdirSync(path.dirname(kit), { recursive: true });
fs.writeFileSync(kit, JSON.stringify({ compilerOptions: {
  target: "esnext", module: "esnext", moduleResolution: "bundler", lib: ["esnext", "DOM", "DOM.Iterable"],
  verbatimModuleSyntax: true, isolatedModules: true, strict: true } }, null, 2) + "\n");

const pdfjs = path.join(here, "pdfjs");
const marker = path.join(pdfjs, ".version");
if (!fs.existsSync(marker) || fs.readFileSync(marker, "utf8").trim() !== `${PDFJS} ${VIEWER_PATCH}`) {
  const zip = path.join(here, ".cache", `pdfjs-${PDFJS}-dist.zip`);
  if (!fs.existsSync(zip)) {
    fs.mkdirSync(path.dirname(zip), { recursive: true });
    const res = await fetch(PDFJS_URL);
    if (!res.ok) throw new Error(`pdf.js: ${PDFJS_URL}: HTTP ${res.status}`);
    fs.writeFileSync(zip, Buffer.from(await res.arrayBuffer()));
  }
  const sum = createHash("sha256").update(fs.readFileSync(zip)).digest("hex");
  if (sum !== PDFJS_SHA256) {
    fs.rmSync(zip);
    throw new Error(`pdf.js: ${zip} is not the release (sha256 ${sum})`);
  }
  fs.rmSync(pdfjs, { recursive: true, force: true });
  fs.mkdirSync(pdfjs, { recursive: true });
  execFileSync("unzip", ["-q", zip, ...PDFJS_FILES, "-d", pdfjs], { stdio: "inherit" });
  // DocWriter's theme for the viewer, after the viewer's own stylesheet
  fs.copyFileSync(path.join(upstream, "assets", "pdfjs", "docwriter-theme.css"), path.join(pdfjs, "web", "docwriter-theme.css"));
  const viewer = path.join(pdfjs, "web", "viewer.html");
  const html = fs.readFileSync(viewer, "utf8");
  const css = '<link rel="stylesheet" href="viewer.css">';
  if (!html.includes(css)) throw new Error("pdf.js: viewer.html has no viewer.css link to put the theme after");
  // ... and DocWriter's theme taken from the preview page around it before the viewer's first paint -- not its own
  // light grey until the preview page themes it, once it has loaded
  const early = `<script>
      try {
        var from = parent.document.documentElement, to = document.documentElement;
        for (var i = 0; i < from.style.length; i++) {
          var k = from.style[i];
          if (k.indexOf("--") === 0) to.style.setProperty(k, from.style.getPropertyValue(k));
        }
        var theme = new URL(parent.location.href).searchParams.get("theme");
        if (theme) to.setAttribute("data-docwriter-theme", theme);
      } catch (e) {}
    </script>`;
  fs.writeFileSync(viewer, html.replace(css, `${css}\n    <link rel="stylesheet" href="docwriter-theme.css">\n    ${early}`));
  fs.writeFileSync(marker, `${PDFJS} ${VIEWER_PATCH}\n`);
  console.log(`pdfjs: pdf.js ${PDFJS}`);
}

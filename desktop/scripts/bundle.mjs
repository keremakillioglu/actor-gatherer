// `pnpm start`'s app, on a Mac, as AGUI (desktop/DESIGN.md, "Running it"): macOS names an app -- in the Dock, Cmd+Tab
// and the menu bar -- and draws its icon from the bundle it runs from, which for `electron .` is Electron's own. So this
// makes out/AGUI.app: Electron's app (cloned, nearly no disk), named AGUI with its own id and icon (icon.icns, drawn by
// assets/src/logo.py), its code this folder (Contents/Resources/app, a link to it, so it runs this checkout's dist/ as
// built: a pull wants only `pnpm start` again), signed for this Mac alone (ad hoc). Made again when Electron, the icon,
// this folder or this script changes. Then it runs the app, its arguments passed on (--home DIR, --port N), as
// Electron's own command does. Elsewhere, `electron .` as it was.
import { execFileSync, spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { copyFileSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(import.meta.url);
const DESKTOP = path.resolve(path.dirname(HERE), "..");
const NAME = "AGUI";
const ID = "io.github.ucbepic.agui"; // its own, not Electron's: macOS keeps an app's Dock place and permissions by it
const electron = createRequire(import.meta.url)("electron"); // its executable, <Electron.app>/Contents/MacOS/Electron
const OUT = path.join(DESKTOP, "out", `${NAME}.app`);
const STAMP = path.join(DESKTOP, "out", `${NAME}.stamp`); // beside the bundle: a file in it would break its signature

/** What the bundle is made from: when it changes, the bundle is made again. */
function stamp() {
  const h = createHash("sha256");
  for (const f of [HERE, path.join(DESKTOP, "icon.icns"), path.join(path.dirname(electron), "..", "Info.plist")])
    h.update(readFileSync(f));
  return h.update(DESKTOP).digest("hex");
}

function made(want) {
  try {
    return readFileSync(STAMP, "utf8") === want;
  } catch {
    return false;
  }
}

function make(want) {
  const from = path.resolve(path.dirname(electron), "..", ".."); // Electron.app
  rmSync(OUT, { recursive: true, force: true });
  mkdirSync(path.dirname(OUT), { recursive: true });
  try {
    execFileSync("cp", ["-cR", from, OUT]); // a clone (APFS): its 250 MB shared with Electron's
  } catch {
    rmSync(OUT, { recursive: true, force: true });
    execFileSync("cp", ["-R", from, OUT]);
  }
  const contents = path.join(OUT, "Contents");
  const plist = path.join(contents, "Info.plist");
  for (const [key, value] of [["CFBundleName", NAME], ["CFBundleDisplayName", NAME], ["CFBundleIdentifier", ID],
    ["CFBundleIconFile", "agui.icns"]])
    execFileSync("plutil", ["-replace", key, "-string", value, plist]);
  copyFileSync(path.join(DESKTOP, "icon.icns"), path.join(contents, "Resources", "agui.icns"));
  rmSync(path.join(contents, "Resources", "default_app.asar"), { force: true }); // (Electron's "drop an app here" page)
  symlinkSync(DESKTOP, path.join(contents, "Resources", "app"));
  execFileSync("codesign", ["--force", "--deep", "--sign", "-", OUT], { stdio: "ignore" }); // Electron's own signature
  // covered its name: re-signed for this Mac, as an app built here (Apple silicon runs nothing unsigned)
  writeFileSync(STAMP, want);
}

/** `cmd` run with the terminal's input and output, its exit this script's, Ctrl-C and a stop passed on to it. */
function run(cmd, args) {
  const child = spawn(cmd, args, { stdio: "inherit" });
  for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => child.kill(sig));
  child.on("exit", (code, sig) => process.exit(code ?? (sig ? 1 : 0)));
}

const args = process.argv.slice(2);
if (process.platform !== "darwin") {
  run(electron, [DESKTOP, ...args]);
} else {
  const want = stamp();
  if (!made(want)) make(want);
  run(path.join(OUT, "Contents", "MacOS", "Electron"), args);
}

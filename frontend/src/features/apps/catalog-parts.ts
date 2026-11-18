// The Apps page's parts (catalog.ts, catalog-dialogs.ts): elements made, an app's mark, sizes and token counts in
// words, and what the page says of an app (`said`).
import type { CatalogApp } from "./catalog";

type Child = string | globalThis.Node | null | undefined | false;
type Attrs = Record<string, string | boolean | ((ev: never) => unknown) | undefined>;

/** An element: its attributes (`text` its text, `on...` a listener, `true` an empty attribute), then its children. */
export function el(tag: string, attrs: Attrs = {}, ...kids: Child[]): HTMLElement {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === false) continue;
    if (k === "text") n.textContent = String(v);
    else if (k === "value") (n as HTMLInputElement).value = String(v);
    else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v as EventListener);
    else n.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of kids) if (c !== null && c !== undefined && c !== false) n.append(c);
  return n;
}

const HUES = ["#2a78d6", "#1baf7a", "#6250d6", "#c4502d", "#c98500", "#d55181", "#0a7489"];

/** An app's mark: its own (its manifest's `mark`, served by the dashboard), else its initial on a colour of its own. */
export function markOf(a: CatalogApp, size: number): HTMLElement {
  if (a.mark && a.origin !== "index" && a.origin !== "staged")
    return el("img", {
      class: "ap-mark",
      src: `/apps/mark/${encodeURIComponent(a.name)}.svg`,
      alt: "",
      width: String(size),
      height: String(size),
      draggable: "false",
    });
  let h = 0;
  for (const c of a.name) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  const m = el("span", {
    class: "ap-mark letter",
    "aria-hidden": "true",
    text: (a.label || a.name).slice(0, 1).toUpperCase(),
  });
  m.style.cssText = `--mark:${HUES[h % HUES.length]};width:${size}px;height:${size}px;font-size:${Math.round(size * 0.45)}px`;
  return m;
}

/** The Apps page's mark: four squares, one a "+". */
export function gridMark(size = 16): SVGSVGElement {
  const ns = "http://www.w3.org/2000/svg",
    svg = document.createElementNS(ns, "svg");
  for (const [k, v] of Object.entries({
    viewBox: "0 0 16 16",
    width: size,
    height: size,
    fill: "none",
    stroke: "currentColor",
    "stroke-width": 1.5,
    "stroke-linecap": "round",
    "aria-hidden": "true",
  }))
    svg.setAttribute(k, String(v));
  for (const [x, y] of [
    [2, 2],
    [9, 2],
    [2, 9],
  ]) {
    const r = document.createElementNS(ns, "rect");
    for (const [k, v] of Object.entries({ x, y, width: 5, height: 5, rx: 1.2 })) r.setAttribute(k, String(v));
    svg.append(r);
  }
  const p = document.createElementNS(ns, "path");
  p.setAttribute("d", "M11.5 9v5M9 11.5h5");
  svg.append(p);
  return svg;
}

/** A size in words: "384 KB", "7.0 MB". */
export function kb(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

const BIG = 5000; // tokens an agent carries for an app's tools, past which it is said in the warning colour
/** About how many tokens, said: "≈8.9k tokens each", in the warning colour past BIG. */
export function tokens(n: number, tail: string): HTMLElement {
  const said = n >= 1000 ? `≈${(n / 1000).toFixed(1)}k` : `≈${Math.max(50, Math.round(n / 50) * 50)}`;
  return el("span", { class: n > BIG ? "ap-big" : "", text: `${said} tokens ${tail}` });
}

// a git source as its badge says it: github.com/…/repo, else its last two parts
function short(url: string): string {
  const s = url
    .replace(/^[a-z]+:\/\//, "")
    .replace(/\.git\/?$/, "")
    .replace(/\/+$/, "");
  const host = /^(github\.com|gitlab\.com|codeberg\.org|bitbucket\.org)\/[^/]+\/(.+)$/.exec(s);
  if (host) return `${host[1]}/…/${host[2]}`;
  const parts = s.split("/").filter(Boolean);
  return parts.length > 2 ? `…/${parts.slice(-2).join("/")}` : s;
}
const first = (t: string): string => (t ? t[0].toUpperCase() + t.slice(1) : t);

/** What the page says of an app. */
export const said = {
  /** A count and its word: "1 tool", "19 tools". */
  count(n: number, word: string): string {
    return `${n} ${word}${n === 1 ? "" : "s"}`;
  },
  /** Where it came from, as its badge says it. */
  where(a: CatalogApp): string {
    if (a.origin === "builtin") return "Built in";
    if (a.origin === "path") return "AG_APPS_PATH";
    if (a.kind === "git" || a.origin === "index") return short(a.source || "");
    return "From a folder";
  },
  /** Its version and where it came from, under its name. */
  from(a: CatalogApp): string {
    const v = a.version ? `version ${a.version} · ` : "";
    if (a.origin === "builtin") return `${v}built in, comes with ag`;
    if (a.origin === "path") return `${v}in AG_APPS_PATH`;
    return `${v}from ${a.source || "a folder"}`;
  },
  /** A phrase as a sentence. */
  sentence(t: string): string {
    const s = first((t || "").trim());
    return s && !/[.!?]$/.test(s) ? `${s}.` : s;
  },
  /** What it may do, each in words, and where its backend runs. */
  can(a: CatalogApp): string[] {
    return [
      ...(a.own_process ? ["Run its own process on this computer"] : []),
      ...(a.can || []).map(first),
      ...(a.own_process ? [] : ["It runs in the dashboard's process"]),
    ];
  },
  /** How it is kept up to date. */
  upToDate(a: CatalogApp): string {
    if (a.origin === "builtin") return "Comes with ag: updated with it.";
    if (a.origin === "path") return "In AG_APPS_PATH: updated there.";
    if (a.kind === "git") return `Up to date${a.commit ? ` (${a.commit.slice(0, 7)})` : ""}.`;
    return "From a folder: install it again to update it.";
  },
};

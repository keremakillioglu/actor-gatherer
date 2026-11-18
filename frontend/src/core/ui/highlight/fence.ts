// A fenced block in a message: coloured when it names a language the highlighter knows (```python), as written
// otherwise -- most unnamed ones are diagrams and output -- with a button copying it. Each line a row of its own (cf-l),
// so Chat can wrap it in the box rather than scroll it sideways, what a line wraps onto indented under where it begins
// (--in, its own indent). Each row but the last ends in its line break: a copy of what is selected keeps the empty lines.
// A block of more than CODE_FOLDS lines can be folded to its first six rows (Fold; codeFolded keeps it so).
import { hlLines } from "./highlight";
import { hlLang } from "./languages";

const CODE_FOLDS = 8;
/** The blocks folded by a click, by their texts (codeKey). */
export const codeFolded = new Set<string>();
const codeKey = (t: string) => {
  let h = 0x811c9dc5;
  for (let i = 0; i < t.length; i++) h = Math.imul(h ^ t.charCodeAt(i), 0x01000193);
  return (h >>> 0).toString(36) + "-" + t.length;
};
const indentOf = (l: string) => {
  let n = 0;
  for (const c of l) {
    if (c === " ") n++;
    else if (c === "\t") n += 4 - (n % 4);
    else break;
  }
  return Math.min(n, 24);
};

/** A code box's parts: its key (data-fold), a long block's, which can be folded; what is inside it, as HTML. */
export interface Fence {
  fold: string | null;
  inner: string;
}

export function fence(text: unknown, lang?: string | null): Fence {
  const s = String(text ?? "");
  const raw = s.split("\n"),
    ls = hlLines(s, hlLang(String(lang || "").split(/\s/)[0]));
  const rows = ls
    .map(
      (h, i) => `<span class="cf-l" style="--in:${indentOf(raw[i] || "")}">${h}${i < ls.length - 1 ? "\n" : ""}</span>`,
    )
    .join("");
  const long = ls.length > CODE_FOLDS;
  return {
    fold: long ? codeKey(s) : null,
    inner:
      `<pre><code>${rows}</code></pre>` +
      (long
        ? `<button type="button" class="code-more" title="Show all lines">Show all ${ls.length} lines</button>`
        : "") +
      `<div class="code-tools">${long ? `<button type="button" class="code-fold" aria-expanded="true" title="Fold to the first lines">Fold</button>` : ""}` +
      `<button type="button" class="code-copy" title="Copy code">Copy</button></div>`,
  };
}

/** The block as HTML: what marked draws for a fenced block in markdown (md.ts). */
export function codeFence(text: unknown, lang?: string | null): string {
  const f = fence(text, lang);
  return `<div class="code-box"${f.fold ? ` data-fold="${f.fold}"` : ""}>${f.inner}</div>\n`;
}

/** A block folded to its first rows, or shown whole (`on` false). */
export function foldCode(box: Element, on: boolean) {
  box.classList.toggle("folded", on);
  const b = box.querySelector<HTMLElement>(".code-fold");
  if (b) {
    b.textContent = on ? "Unfold" : "Fold";
    b.title = on ? "Show all lines" : "Fold to the first lines";
    b.setAttribute("aria-expanded", String(!on));
  }
}

/** The blocks in `root` folded by a click before, folded again (a message drawn again). */
export function foldKept(root: ParentNode) {
  if (codeFolded.size)
    for (const b of root.querySelectorAll<HTMLElement>(".code-box[data-fold]"))
      if (codeFolded.has(b.dataset.fold!)) foldCode(b, true);
}

/**
 * A click on a code block's buttons, for the page's document to listen with (one listener for every block, however
 * drawn): Fold, Show all; and Copy (codeFence's, the files view's callView's), copying the command as written
 * (data-copy), else the block's own text.
 */
export async function codeClick(ev: Event) {
  const target = ev.target as HTMLElement;
  const f = target.closest && target.closest(".code-fold, .code-more");
  if (f) {
    const box = f.closest<HTMLElement>(".code-box")!,
      on = !box.classList.contains("folded");
    if (on) codeFolded.add(box.dataset.fold!);
    else codeFolded.delete(box.dataset.fold!);
    foldCode(box, on);
    return;
  }
  const b = target.closest && target.closest<HTMLElement>(".code-copy");
  if (!b) return;
  const code = (b.closest(".code-box") || b.parentElement!).querySelector("code");
  try {
    await navigator.clipboard.writeText(b.dataset.copy ?? code?.textContent ?? "");
    b.textContent = "Copied";
  } catch {
    b.textContent = "Not copied";
  }
  setTimeout(() => {
    b.textContent = "Copy";
  }, 1500);
}

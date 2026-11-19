// What the turn list shows of the old page's own drawing, until it moves too (types.ts's ChatHost): the actor's stage,
// kept on the page across renders while it shows the same, so its animations run on; and a node the old page builds,
// drawn as React's own.
import { createElement, useLayoutEffect, type ReactNode, type RefObject } from "react";

/** Whether the node on the page shows what `next` does: by their data-sig, else by their markup -- the old page's
 * patch() rule for the nodes it kept from one draw to the next (features/page/main-view.js). */
function same(cur: Node, next: Node): boolean {
  if (cur instanceof HTMLElement && next instanceof HTMLElement && ("sig" in cur.dataset || "sig" in next.dataset))
    return cur.dataset.sig === next.dataset.sig && cur.tagName === next.tagName;
  return cur.isEqualNode(next);
}

/**
 * The old page's stage (`make`: core/page/helpers.js's atWork, atRest, greeting) first in `box`, before React's own nodes in it
 * (`after`, the first of them, if any): made again at each render, as each of the old page's draws made it -- its moments
 * counted on from the last -- and the node on the page kept while it shows the same, so its animations run on. The stage
 * may have put a node of its own in its place since (its next moment, on its own clock): what is first in `box` is
 * compared, not what was put there.
 */
export function useStage(
  box: RefObject<HTMLElement | null>,
  make: () => Node | null,
  after?: RefObject<Element | null>,
): void {
  useLayoutEffect(() => {
    const b = box.current;
    if (!b) return;
    const first = b.firstChild;
    const cur = first && first !== (after?.current ?? null) ? first : null;
    const next = make();
    if (cur && next && same(cur, next)) return;
    if (cur && next) b.replaceChild(next, cur);
    else if (cur) cur.remove();
    else if (next) b.insertBefore(next, b.firstChild);
  });
}

const PROP: Record<string, string> = { class: "className", for: "htmlFor", tabindex: "tabIndex" };
const EMPTY = new Set(["img", "br", "hr", "input", "wbr"]);
const camel = (k: string) => (k.startsWith("--") ? k : k.replace(/-([a-z])/g, (_, c: string) => c.toUpperCase()));
const styleOf = (s: string) =>
  Object.fromEntries(
    s
      .split(";")
      .map((d) => d.split(/:(.*)/s))
      .filter(([k, v]) => k.trim() && v !== undefined)
      .map(([k, v]) => [camel(k.trim()), v.trim()]),
  );

/**
 * A node the old page builds -- nothing listening on it, nothing changing it after it is built: a call opened, a call's
 * line, a face, a Browser's message -- drawn as React's own: the same element, attributes and contents, its contents set
 * again only when they change. A text as it is; none, nothing.
 */
export function Html({ node }: { node: Node | string | null }): ReactNode {
  if (node === null) return null;
  if (typeof node === "string") return node;
  if (!(node instanceof Element)) return node.textContent;
  const props: Record<string, unknown> = {};
  for (const a of node.attributes) props[PROP[a.name] ?? a.name] = a.name === "style" ? styleOf(a.value) : a.value;
  const tag = node.tagName.toLowerCase();
  if (!EMPTY.has(tag)) props.dangerouslySetInnerHTML = { __html: node.innerHTML };
  return createElement(tag, props);
}

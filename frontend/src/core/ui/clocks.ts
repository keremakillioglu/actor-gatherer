// The times on the page that count up, set where they are every second, nothing redrawn: `data-since` (from that time
// to now, as span() says it), `data-ago` (how long ago, ago()), `data-lasting` (a clock counting up, lasting()). Any
// view puts one in (Chat's "Working… for 2m 05s", the list's and the history's "3m ago"); the page starts the ticker.
import { ago, lasting, span } from "../format";

let ticker: ReturnType<typeof setInterval> | null = null;

/** `n`'s words set to `text`, if they aren't already: setting a text, even to what it was, lays the page out again
 * ("3m ago" is so for a minute, and the page idle laid out every second). */
const set = (n: HTMLElement, text: string) => {
  if (n.textContent !== text) n.textContent = text;
};

/** Every count-up time on the page set, now. */
export function tick(root: ParentNode = document): void {
  const now = Date.now() / 1000;
  for (const n of root.querySelectorAll<HTMLElement>("[data-since]")) set(n, span(+n.dataset.since!, now));
  for (const n of root.querySelectorAll<HTMLElement>("[data-ago]")) set(n, ago(+n.dataset.ago!));
  for (const n of root.querySelectorAll<HTMLElement>("[data-lasting]")) set(n, lasting(+n.dataset.lasting!));
}

/** The ticker started, once a page. */
export function startClocks(): void {
  ticker ??= setInterval(() => tick(), 1000);
}

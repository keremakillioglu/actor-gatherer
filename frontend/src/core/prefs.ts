// What the page keeps in this browser (localStorage): the reader's choices -- a view's look, what is folded, where a
// split was left. A read or a write can throw (storage off, a private window, full): then nothing is kept, and the
// page goes on as if nothing were, for this page only.

/** The text kept under `key`, or null. */
export function text(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

/** `value` kept under `key`: whether it was. */
export function setText(key: string, value: string): boolean {
  try {
    localStorage.setItem(key, value);
    return true;
  } catch {
    return false; // this page only
  }
}

/** What is kept under `key`, read as JSON; null for none, or for what isn't JSON. */
export function json(key: string): unknown {
  const t = text(key);
  if (t === null) return null;
  try {
    return JSON.parse(t);
  } catch {
    return null;
  }
}

/** `value` kept under `key`, as JSON: whether it was. */
export function keep(key: string, value: unknown): boolean {
  return setText(key, JSON.stringify(value));
}

/** The list kept under `key`, or null for none (or what isn't one). */
export function list(key: string): unknown[] | null {
  const v = json(key);
  return Array.isArray(v) ? v : null;
}

/** A flag kept as "1" or "0"; `otherwise` if neither is. */
export function flag(key: string, otherwise = false): boolean {
  const t = text(key);
  return t === "1" ? true : t === "0" ? false : otherwise;
}

/** A flag kept, as "1" or "0". */
export function setFlag(key: string, on: boolean): void {
  setText(key, on ? "1" : "0");
}

/** Nothing kept under `key` any more. */
export function drop(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    /* this page only */
  }
}

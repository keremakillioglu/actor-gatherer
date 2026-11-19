// Times, counts and words as the page says them: the same as the old page's helpers (src/core/page/helpers.js's full,
// ago, spell, lasting; features/transcript/transcript.js's plural, firstLine), which stay there for the old page until it goes. Times are
// the server's, in seconds.

/** A whole number with its thousands marked ("1,204"); a dash for none. */
export const full = (v: number | null | undefined): string =>
  v === null || v === undefined ? "–" : Math.round(v).toLocaleString();

/** `n` and its word, plural unless one ("3 messages", "1 message"). */
export const plural = (n: number, w: string): string => `${full(n)} ${w}${n === 1 ? "" : "s"}`;

/** A text's first line, cut to `n` characters with "…" after. */
export const firstLine = (t: unknown, n = 160): string => {
  const l = String(t ?? "").split("\n")[0];
  return l.length > n ? l.slice(0, n) + "…" : l;
};

/** How long ago `t` was: "45s ago", "3m ago", "2h ago", "4d ago"; "never" for none. */
export const ago = (t: number | null | undefined): string => {
  if (!t) return "never";
  const s = Math.max(0, Date.now() / 1000 - t);
  return s < 60
    ? `${Math.round(s)}s ago`
    : s < 3600
      ? `${Math.round(s / 60)}m ago`
      : s < 86400
        ? `${Math.round(s / 3600)}h ago`
        : `${Math.round(s / 86400)}d ago`;
};

/** `s` seconds as a clock counting up: "45s", "2m 05s", "1h 12m". */
export const spell = (s: number): string => {
  s = Math.max(0, Math.floor(s));
  const pad = (n: number) => String(n).padStart(2, "0");
  return s < 60
    ? `${s}s`
    : s < 3600
      ? `${Math.floor(s / 60)}m ${pad(s % 60)}s`
      : `${Math.floor(s / 3600)}h ${pad(Math.floor(s / 60) % 60)}m`;
};

/** How long since `t`, as a clock counting up (spell). */
export const lasting = (t: number): string => spell(Date.now() / 1000 - t);

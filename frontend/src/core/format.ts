// Times, counts, sizes and words as the page says them, for every view (the old page's modules import them too). Times
// are the server's, in seconds.

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

/** A count made short: "950", "1.2K", "34K", "1.5M", "12M"; a dash for none. */
export const compact = (v: number | null | undefined): string =>
  v === null || v === undefined
    ? "–"
    : v >= 1e6
      ? (v / 1e6).toFixed(v >= 1e7 ? 0 : 1).replace(/\.0$/, "") + "M"
      : v >= 1e3
        ? (v / 1e3).toFixed(v >= 1e5 ? 0 : 1).replace(/\.0$/, "") + "K"
        : String(Math.round(v));

/** Dollars: "$1.20", "<$0.01" for less than a cent; a dash for none. */
export const usd = (v: number | null | undefined): string =>
  v === null || v === undefined ? "–" : v > 0 && v < 0.01 ? "<$0.01" : "$" + v.toFixed(2);

/** The time `t` on a chart's axis: its day too, over `days`; its seconds, if `seconds`. */
export const axisTime = (t: number, days?: boolean, seconds?: boolean): string =>
  new Date(t * 1000).toLocaleString(
    [],
    days
      ? { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }
      : seconds
        ? { hour: "2-digit", minute: "2-digit", second: "2-digit" }
        : { hour: "2-digit", minute: "2-digit" },
  );

/** The time `t` on the clock (to the second), or its day and minute `withDate`; a dash for none. */
export const clock = (t: number | null | undefined, withDate?: boolean): string =>
  t
    ? new Date(t * 1000).toLocaleString(
        [],
        withDate
          ? { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }
          : { hour: "2-digit", minute: "2-digit", second: "2-digit" },
      )
    : "–";

/** How long from `a` to `b`: "45s", "2.5m", "1.2h"; a dash without both. */
export const span = (a: number | null | undefined, b: number | null | undefined): string => {
  if (!a || !b) return "–";
  const s = Math.max(0, b - a);
  return s < 60 ? `${s.toFixed(0)}s` : s < 3600 ? `${(s / 60).toFixed(1)}m` : `${(s / 3600).toFixed(1)}h`;
};

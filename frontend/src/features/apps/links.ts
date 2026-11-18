// Links to things in apps, `ag://<app>/<path>[?instance=<id>][#<part>]` (app_kit/links.py, the same rules): an agent
// writes one in a reply as markdown -- `[the To dos page](ag://notes/page/k3p9x2wq)` -- and the page opens it in the app
// (src/legacy/07-panes.js, openAppLink): the panel shown, and handed the link (the SDK's `ag.links.onOpen`). An app
// takes only paths of the forms its manifest lists ([[links]]): words, `<name>` for one segment, a last `<name...>` for
// the rest -- the values handed to its panel decoded.

export interface LinkForm {
  form: string;
  about?: string;
}
/** An `ag://` link read: the app it names, its path (%-encoded, as written), its #part (decoded), the instance named. */
export interface AppHref {
  href: string;
  app: string;
  path: string;
  part: string;
  instance: string;
}
/** A path of one of an app's forms: the form, and its values. */
export interface LinkMatch {
  form: string;
  values: Record<string, string>;
}

const HREF = /^ag:\/\/([a-z][a-z0-9_]{0,23})(?:\/([^?#]*))?(?:\?([^#]*))?(?:#([\s\S]*))?$/;
const WORD = /^[A-Za-z0-9._~-]+$/;
const VALUE = /^<([a-z][a-z0-9_]{0,31})(\.\.\.)?>$/;

const decode = (s: string): string | null => {
  try {
    return decodeURIComponent(s);
  } catch {
    return null;
  }
};

/** An `ag://` link, read; null if `href` isn't one. */
export function parseHref(href: string | null | undefined): AppHref | null {
  const text = String(href ?? "").trim();
  const m = HREF.exec(text);
  if (!m) return null;
  const instance = new URLSearchParams(m[3] || "").get("instance") || "";
  return { href: text, app: m[1], path: m[2] || "", part: decode(m[4] || "") ?? "", instance };
}

/** Whether `href` is a link to something in an app (an `ag:` one, read or not): never a web page's. */
export const isAppHref = (href: string | null | undefined): boolean => /^ag:/i.test(String(href ?? "").trim());

const compiled = new Map<string, { re: RegExp; names: string[] } | null>();
function compile(form: string): { re: RegExp; names: string[] } | null {
  if (compiled.has(form)) return compiled.get(form)!;
  const parts = form.split("/"),
    names: string[] = [],
    out: string[] = [];
  let ok = parts.every((s) => s !== "");
  parts.forEach((s, i) => {
    const v = VALUE.exec(s);
    if (v) {
      ok &&= !names.includes(v[1]) && (!v[2] || i === parts.length - 1);
      names.push(v[1]);
      out.push(v[2] ? "([\\s\\S]+)" : "([^/]+)");
    } else if (WORD.test(s)) out.push(s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    else ok = false;
  });
  const got = ok ? { re: new RegExp(`^${out.join("/")}$`), names } : null;
  compiled.set(form, got);
  return got;
}

/** The first of `forms` a path (%-encoded, as in a link) is of, and its values decoded; null: none. */
export function matchPath(forms: LinkForm[] | undefined, path: string): LinkMatch | null {
  for (const f of forms || []) {
    const c = compile(f.form);
    const m = c && c.re.exec(path);
    if (!c || !m) continue;
    const values: Record<string, string> = {};
    const ok = c.names.every((n, i) => {
      const v = decode(m[i + 1]);
      if (!v || v.includes("\u0000")) return false;
      values[n] = v;
      return true;
    });
    if (ok) return { form: f.form, values };
  }
  return null;
}

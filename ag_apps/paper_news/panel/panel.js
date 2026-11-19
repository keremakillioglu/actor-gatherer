/* The Paper news panel: the days the app kept in a sidebar -- each weekday's listing of the user's categories -- and the day
open, on "For you": the papers the app's agent picked as related to the user's research, strongest first, each with
why; "All papers" has the whole listing, narrowed by category, kind and words. Every paper takes the user's word on it
(Relevant / Not for me), which the agent's summary of their interests is rewritten from every 20 of. "Your interests"
is where the user tells the app what they work on, and reads and edits the summary the agent judges by. "Saved" lists
the papers they starred; Enter in the find box searches every day kept. The backend tells the panel when anything
changes; a notification of a day opens it.

A link to a web page (a paper's arXiv page, PDF or HTML, a day's listing on arXiv) opens in the dashboard's Browser app,
not in a browser outside it (`openPage`).

Keys: j / k the next or previous paper, s save it, o open its arXiv page, Enter its abstract in full, / the find box. */
(async function () {
  "use strict";
  const ag = await AgApp.connect();
  const $ = (id) => document.getElementById(id);
  const PAGE = 150;                                         // papers drawn at a time
  const SVG = {
    gear: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3"><circle cx="8" cy="8" r="2.2"/><path d="M8 1.8v1.6M8 12.6v1.6M14.2 8h-1.6M3.4 8H1.8M12.4 3.6l-1.1 1.1M4.7 11.3l-1.1 1.1M12.4 12.4l-1.1-1.1M4.7 4.7L3.6 3.6" stroke-linecap="round"/></svg>',
    fetch: '<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M13 8a5 5 0 1 1-1.5-3.6M13 2.5v3h-3"/></svg>',
    side: '<svg width="16" height="16" viewBox="0 0 16 16"><rect x="1.8" y="2.5" width="12.4" height="11" rx="2" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M6 2.8v10.4" stroke="currentColor" stroke-width="1.3"/></svg>',
    star: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"><path d="M8 1.9l1.9 3.9 4.2.6-3 3 .7 4.2L8 11.6l-3.8 2 .7-4.2-3-3 4.2-.6z"/></svg>',
    starOn: '<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"><path d="M8 1.9l1.9 3.9 4.2.6-3 3 .7 4.2L8 11.6l-3.8 2 .7-4.2-3-3 4.2-.6z"/></svg>',
    me: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"><circle cx="8" cy="5.6" r="2.6"/><path d="M2.8 13.6c.8-2.6 2.8-4 5.2-4s4.4 1.4 5.2 4"/></svg>',
    up: '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"><path d="M5 7.2l2.6-5c1.1.1 1.8.9 1.6 2.1l-.4 2.2h3.5c.9 0 1.5.8 1.3 1.7l-1 4.4c-.2.7-.8 1.2-1.5 1.2H5zM2 7.2h3v7.2H2z"/></svg>',
    down: '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"><path d="M11 8.8l-2.6 5c-1.1-.1-1.8-.9-1.6-2.1l.4-2.2H3.7c-.9 0-1.5-.8-1.3-1.7l1-4.4c.2-.7.8-1.2 1.5-1.2H11zM14 8.8h-3V1.6h3z"/></svg>',
  };
  const KIND_TAG = { cross: "Cross-list", replace: "Updated", "replace-cross": "Updated cross-list" };
  const SCORE = { 3: "Central", 2: "Related", 1: "Worth a look" };

  const keep = {
    get(k, d) { try { const v = localStorage.getItem(`paper_news:${ag.instance}:${k}`); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem(`paper_news:${ag.instance}:${k}`, JSON.stringify(v)); } catch { /* storage off: kept for now only */ } },
  };
  async function get(path) {
    const r = await ag.api(path);
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || `${r.status}`);
    return j;
  }
  async function post(path, body) {
    const r = await ag.api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || `${r.status}`);
    return j;
  }
  function el(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "html") n.innerHTML = v;                // our own icons only
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else if (k === "value") n.value = v;
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const c of kids.flat()) if (c !== null && c !== undefined && c !== false) n.append(c.nodeType ? c : document.createTextNode(String(c)));
    return n;
  }
  const dateOf = (day) => { const [y, m, d] = day.split("-").map(Number); return new Date(Date.UTC(y, m - 1, d)); };
  const dayShort = (day) => dateOf(day).toLocaleDateString(undefined, { timeZone: "UTC", weekday: "short", month: "short", day: "numeric" });
  const dayLong = (day) => dateOf(day).toLocaleDateString(undefined, { timeZone: "UTC", weekday: "long", month: "long", day: "numeric" });
  const clock = (ts) => {
    const d = new Date(ts * 1000), today = new Date();
    const t = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
    return d.toDateString() === today.toDateString() ? t : `${d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })} ${t}`;
  };
  const listedOf = (d) => (d.kinds.new || 0) + (d.kinds.cross || 0);
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many || `${one}s`}`;

  // ---------------------------------------------------------------- links
  // A web page opened in the dashboard's Browser app, by app_kit's open-url intent: in a Browser shown beside this panel
  // (a new tab of it), else in a new Browser. No app here to take it (no Browser installed): a tab of the browser's own.
  function openPage(url) {
    ag.intents.open("open-url", { url }).catch(() => window.open(url, "_blank", "noopener"));
  }
  // Every link to a web page in the panel, plainly clicked: there. A click with a key held (⌘, Ctrl, Shift, ⌥) or another
  // button is left to the browser -- a tab of its own, outside -- as a link in an actor's pane is.
  document.addEventListener("click", (e) => {
    const a = e.target.closest ? e.target.closest("a[href]") : null;
    if (!a || e.defaultPrevented || e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    if (!/^https?:$/.test(a.protocol) || a.origin === location.origin) return;
    e.preventDefault();
    openPage(a.href);
  });

  // ---------------------------------------------------------------- state
  const S = {
    state: null,                                            // the backend's: {settings, days, status, saved, interests}
    view: keep.get("view", null),                           // {type: "day", day, tab: "for"|"all"} | {type: "saved"} |
                                                            // {type: "search", q} | {type: "interests"}
    papers: [], info: null, judged: null,                   // the view's papers; its day's record; when it was judged
    cat: "all", kind: "listed", find: "", shown: PAGE, at: -1,
    seen: new Set(keep.get("seen", [])),                    // days looked at
    sideOpen: false,
    mine: null,                                             // the interests page's: GET interests
  };

  async function loadState() {
    try { S.state = await get("state"); } catch (e) { S.state = S.state || { settings: {}, days: [], status: { error: e.message }, saved: 0, interests: {} }; }
    drawSide();
  }

  async function open(view, opts = {}) {
    S.view = view;
    keep.set("view", view);
    if (!opts.keepFilters) { S.cat = "all"; S.kind = "listed"; S.shown = PAGE; S.at = -1; }
    try {
      if (view.type === "day") {
        const got = await get(`day?day=${encodeURIComponent(view.day)}`);
        S.papers = got.papers; S.info = got.day; S.judged = got.judged;
        S.seen.add(view.day); keep.set("seen", [...S.seen].slice(-200));
      } else if (view.type === "saved") {
        S.papers = (await get("saved")).papers; S.info = null;
      } else if (view.type === "search") {
        S.papers = (await get(`search?q=${encodeURIComponent(view.q)}`)).papers; S.info = null;
      } else if (view.type === "interests") {
        S.mine = await get("interests"); S.papers = []; S.info = null;
      }
    } catch (e) {
      S.papers = []; S.info = { status: "error", note: e.message };
    }
    if (S.sideOpen) { S.sideOpen = false; $("app").classList.remove("side-open"); }
    drawSide(); drawMain();
    if (!opts.keepScroll) $("scroll").scrollTop = 0;
  }

  function latestDay() {
    const d = (S.state?.days || []).find((x) => x.status === "got");
    return d ? d.day : null;
  }
  const told = () => !!S.state?.interests?.told;

  // ---------------------------------------------------------------- the sidebar
  function drawSide() {
    const st = S.state || { days: [], settings: {}, status: {}, saved: 0, interests: {} };
    const mine = st.interests || {};
    $("side-cats").textContent = (st.settings.categories || []).join(" · ");
    const nav = $("days");
    nav.replaceChildren();
    const cur = S.view || {};
    const sub = !mine.told ? "Tell it what you work on" : mine.summarizing ? "Writing your summary…"
      : mine.profile ? `${mine.feedback || 0} of ${mine.every} marks until the summary updates` : "No summary yet";
    nav.append(el("button", { class: `day mine${!mine.told ? " todo" : ""}`, type: "button", "aria-current": cur.type === "interests" ? "true" : null,
      onclick: () => open({ type: "interests" }) },
      el("span", { class: "ic", html: SVG.me }), el("span", { class: "lbl" }, "Your interests", el("span", { class: "sub" }, sub))));
    nav.append(el("button", { class: "day", type: "button", "aria-current": cur.type === "saved" ? "true" : null, onclick: () => open({ type: "saved" }) },
      el("span", { class: "ic star", html: SVG.starOn }), el("span", { class: "lbl" }, "Saved"), el("span", { class: "n" }, st.saved || "")));
    nav.append(el("h3", null, "Days"));
    const waiting = st.status && st.status.waiting;
    if (waiting && !st.days.some((d) => d.day === waiting)) {
      nav.append(el("button", { class: "day quiet", type: "button", onclick: () => noteOnly(waiting) },
        el("span", { class: "lbl" }, dayShort(waiting), el("span", { class: "sub" }, "Not out yet"))));
    }
    if (!st.days.length && !waiting) nav.append(el("div", { class: "day quiet" }, st.status?.fetching ? "Fetching…" : "Nothing yet"));
    for (const d of st.days) {
      const on = cur.type === "day" && cur.day === d.day;
      if (d.status === "got") {
        const j = d.judged || {};
        const picking = j.asked_at && !j.done_at;
        const forYou = j.done_at ? el("span", { class: `fy${j.n ? "" : " none"}`, title: `${plural(j.n, "paper")} for you` }, j.n)
          : picking ? el("span", { class: "fy busy", title: "The agent is picking" }, "…") : null;
        nav.append(el("button", { class: "day", type: "button", "aria-current": on ? "true" : null, onclick: () => open({ type: "day", day: d.day, tab: "for" }) },
          el("span", { class: "lbl" }, dayShort(d.day)),
          !S.seen.has(d.day) ? el("span", { class: "new", title: "Not looked at yet" }) : null,
          forYou, el("span", { class: "n", title: `${listedOf(d)} papers in all` }, listedOf(d))));
      } else {
        const s2 = d.status === "none" ? "No listing" : "Couldn't be read";
        nav.append(el("button", { class: "day quiet", type: "button", "aria-current": on ? "true" : null, onclick: () => open({ type: "day", day: d.day }) },
          el("span", { class: "lbl" }, dayShort(d.day), el("span", { class: "sub" }, s2))));
      }
    }
    drawStatus();
  }

  function drawStatus() {
    const s = S.state?.status || {};
    const box = $("status");
    box.replaceChildren();
    if (s.fetching) box.append(el("div", { class: "busy" }, "Fetching from arXiv…"));
    else if (s.error) box.append(el("div", { class: "err" }, s.error));
    else if (s.waiting) box.append(el("div", null, `Waiting for ${dayShort(s.waiting)}'s listing · checking every 30 min`));
    if (s.checked) box.append(el("div", null, `Checked ${clock(s.checked)}`));
    if (s.next) box.append(el("div", null, `Next check ${clock(s.next)}`));
    $("fetch").classList.toggle("spin", !!s.fetching);
    $("fetch").disabled = !!s.fetching;
  }

  function noteOnly(day) {
    S.view = { type: "waiting", day }; S.papers = []; S.info = { status: "waiting" };
    drawSide(); drawMain();
  }

  // ---------------------------------------------------------------- the day open
  const forTab = () => S.view?.type === "day" && S.view.tab !== "all";

  function filtered() {
    const terms = S.find.toLowerCase().split(/\s+/).filter(Boolean);
    const picked = forTab();
    const out = S.papers.filter((p) => {
      if (picked && !p.pick) return false;
      if (S.cat !== "all" && !p.categories.includes(S.cat)) return false;
      const k = p.kind || "new";
      if (!picked) {
        if (S.kind === "listed" && !(k === "new" || k === "cross")) return false;
        if (S.kind === "new" && k !== "new") return false;
        if (S.kind === "cross" && k !== "cross") return false;
        if (S.kind === "updated" && !(k === "replace" || k === "replace-cross")) return false;
      }
      if (terms.length) {
        const hay = `${p.title} ${p.authors.join(" ")} ${p.abstract} ${p.id} ${p.pick ? p.pick.why : ""}`.toLowerCase();
        if (!terms.every((t) => hay.includes(t))) return false;
      }
      return true;
    });
    if (picked) out.sort((a, b) => b.pick.score - a.pick.score);
    return out;
  }

  function drawMain() {
    const v = S.view || {};
    const page = v.type === "interests";
    $("page").hidden = !page;
    $("list").hidden = page;
    $("find").closest(".find").hidden = page;
    const settings = S.state?.settings || {};
    const listed = S.papers.filter((p) => !p.kind || p.kind === "new" || p.kind === "cross");
    const updated = S.papers.length - listed.length;
    const picks = S.papers.filter((p) => p.pick);
    $("head").textContent = v.type === "day" ? dayLong(v.day) : v.type === "saved" ? "Saved papers"
      : v.type === "search" ? `“${v.q}” in all days` : v.type === "waiting" ? dayLong(v.day)
        : page ? "Your interests" : "Paper news";
    const nNew = listed.filter((p) => p.kind === "new").length;
    $("counts").textContent = v.type === "day" && S.papers.length
      ? (forTab() ? (S.judged?.done_at ? `${picks.length} of ${listed.length} papers for you` : `${listed.length} papers`)
        : `${listed.length} papers · ${nNew} new · ${listed.length - nNew} cross-lists` + (settings.replacements && updated ? ` · ${updated} updated` : ""))
      : (v.type === "saved" || v.type === "search") && S.papers.length ? plural(S.papers.length, "paper") : "";
    // For you / All papers
    const tabs = $("tabs");
    tabs.replaceChildren();
    if (v.type === "day" && S.papers.length) {
      const tab = (key, label, n) => el("button", { type: "button", role: "tab", "aria-selected": (key === "all") === (v.tab === "all") ? "true" : "false",
        onclick: () => open({ ...v, tab: key }, { keepScroll: false }) }, label, n !== null ? el("span", { class: "k" }, n) : null);
      tabs.append(tab("for", "For you", S.judged?.done_at ? picks.length : null), tab("all", "All papers", listed.length));
    }
    // categories, and kinds (in All papers)
    const cats = $("cats");
    cats.replaceChildren();
    const asked = (S.info && S.info.categories) || settings.categories || [];
    const inTab = forTab() ? picks : listed;
    if (v.type === "day" && inTab.length && asked.length > 1) {
      const seg = (key, label, n) => el("button", { type: "button", role: "tab", "aria-selected": S.cat === key ? "true" : "false",
        onclick: () => { S.cat = key; S.shown = PAGE; S.at = -1; drawMain(); } }, label, n !== null ? el("span", { class: "k" }, n) : null);
      cats.append(seg("all", "All", null));
      for (const c of asked) cats.append(seg(c, c, inTab.filter((p) => p.categories.includes(c)).length));
    }
    const kinds = $("kinds");
    kinds.replaceChildren();
    if (v.type === "day" && S.papers.length && !forTab()) {
      const seg = (key, label) => el("button", { type: "button", role: "tab", "aria-selected": S.kind === key ? "true" : "false",
        onclick: () => { S.kind = key; S.shown = PAGE; S.at = -1; drawMain(); } }, label);
      kinds.append(seg("listed", "All"), seg("new", "New"), seg("cross", "Cross-lists"));
      if (settings.replacements && updated) kinds.append(seg("updated", "Updated"));
    } else if (v.type !== "day") {
      S.kind = "all";
    }
    if (page) { $("note").hidden = true; $("more").hidden = true; drawInterests(); return; }
    drawNote();
    drawList();
  }

  function button(label, onclick, cls = "btn small") { return el("button", { class: cls, type: "button", onclick }, label); }

  async function askJudge(day) {
    try { await post("judge", { day }); } catch (e) { flash(e.message); return; }
    open(S.view, { keepFilters: true, keepScroll: true });
  }

  function drawNote() {
    const v = S.view || {};
    const note = $("note");
    const info = S.info;
    const j = S.judged || {};
    let parts = null;
    if (v.type === "waiting" || (info && info.status === "waiting")) {
      parts = [`arXiv hasn't published ${dayShort(v.day)}'s listing yet. It announces at 8 PM New York time, Sunday to Thursday. `,
        "Checking every 30 minutes."];
    } else if (info && info.status === "none") {
      parts = ["arXiv announced nothing for this day (a holiday, or no mailing)."];
    } else if (info && info.status === "missed") {
      const cats = info.categories || S.state?.settings.categories || [];
      parts = [`Couldn't read this day's listing${info.note ? ` (${info.note})` : ""}. The app will try again on its next run. On arXiv: `,
        ...cats.flatMap((c, i) => [i ? ", " : "", el("a", { href: `https://arxiv.org/catchup/${c}/${v.day}?abs=True`, target: "_blank", rel: "noopener noreferrer" }, c)])];
    } else if (info && info.status === "error") {
      parts = [`Couldn't load: ${info.note}`];
    } else if (forTab() && S.papers.length) {
      const all = () => open({ ...v, tab: "all" });
      const n = S.papers.filter((p) => !p.kind || p.kind === "new" || p.kind === "cross").length;
      if (!told()) {
        parts = ["Tell the Paper news agent what you work on, and it will pick papers for you each day. ",
          button("Set up your interests", () => open({ type: "interests" }), "btn small primary"), " ", button(`See all ${n} papers`, all, "btn small quiet")];
      } else if (!S.state?.interests?.profile) {
        parts = ["The Paper news agent is summarizing your interests. It will pick from this day after that. ", button(`See all ${n} papers`, all, "btn small quiet")];
      } else if (j.asked_at && !j.done_at && !j.stale) {
        parts = [el("span", { class: "dots" }), ` The Paper news agent is picking from this day's ${n} papers. `, button(`See all ${n} papers`, all, "btn small quiet")];
      } else if (!j.done_at) {
        parts = [j.asked_at ? "The Paper news agent didn't finish picking from this day. " : "The Paper news agent hasn't picked from this day yet. ",
          button("Ask it to pick", () => askJudge(v.day), "btn small primary"), " ", button(`See all ${n} papers`, all, "btn small quiet")];
      } else if (!S.papers.some((p) => p.pick)) {
        parts = ["The agent found nothing for you this day. ", button(`See all ${n} papers`, all, "btn small quiet")];
      } else if (S.find && !filtered().length) {
        parts = ["None of your papers match. ", el("a", { href: "#", onclick: (e) => { e.preventDefault(); searchAll(); } }, "Search all days"), "."];
      }
    } else if (v.type === "day" && S.find && !filtered().length) {
      parts = ["No papers match. ", el("a", { href: "#", onclick: (e) => { e.preventDefault(); searchAll(); } }, "Search all days"), "."];
    }
    note.hidden = !parts;
    if (parts) note.replaceChildren(...parts);
  }

  function drawList() {
    const list = $("list");
    const papers = filtered();
    list.replaceChildren();
    const v = S.view || {};
    if (!papers.length && !$("note").hidden) { $("more").hidden = true; return; }
    if (!papers.length) {
      const st = S.state || {};
      const empty = !v.type ? (st.status?.fetching ? "Fetching arXiv's listings…" : (st.days || []).length ? "Pick a day." : "No listing yet.")
        : v.type === "saved" ? "No saved papers yet. Click a paper's star to save it." : S.papers.length ? "No papers match." : "No papers.";
      list.append(el("div", { class: "empty" }, empty));
      $("more").hidden = true;
      return;
    }
    const terms = S.find.toLowerCase().split(/\s+/).filter(Boolean);
    for (const [i, p] of papers.slice(0, S.shown).entries()) list.append(paperEl(p, i, terms, v.type !== "day"));
    const left = papers.length - S.shown;
    const more = $("more");
    more.hidden = left <= 0;
    if (left > 0) more.replaceChildren(el("button", { class: "btn", type: "button", onclick: () => { S.shown += PAGE; drawList(); } },
      `Show ${Math.min(left, PAGE)} more of ${left}`));
  }

  function marked(text, terms) {
    if (!terms.length) return [text];
    const re = new RegExp(`(${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
    return text.split(re).map((part, i) => (i % 2 ? el("mark", null, part) : part));
  }

  function paperEl(p, i, terms, showDay) {
    const authors = p.authors.length > 8 ? [p.authors.slice(0, 8).join(", "), el("span", { class: "more-a" }, ` and ${p.authors.length - 8} more`)]
      : [p.authors.join(", ")];
    const abs = el("p", { class: "pp-abs clamp", title: "Show more", onclick: (e) => toggleAbs(e.currentTarget) }, ...marked(p.abstract, terms));
    const star = el("button", { class: "star-btn", type: "button", "aria-pressed": p.saved ? "true" : "false",
      title: p.saved ? "Saved · click to unsave (s)" : "Save (s)", "aria-label": p.saved ? "Unsave" : "Save",
      html: p.saved ? SVG.starOn : SVG.star, onclick: () => save(p) });
    const say = (verdict, label, icon) => el("button", { class: `fb ${verdict}`, type: "button", "aria-pressed": p.verdict === verdict ? "true" : "false",
      title: p.verdict === verdict ? "Click to undo" : `Mark as ${label.toLowerCase()}`, onclick: () => feedback(p, p.verdict === verdict ? null : verdict) },
      el("span", { html: icon }), label);
    return el("article", { class: `pp${i === S.at ? " on" : ""}${p.pick ? ` picked s${p.pick.score}` : ""}`, tabindex: "-1", "data-i": i, "data-id": p.id },
      p.pick ? el("div", { class: "why" }, el("span", { class: `score s${p.pick.score}` }, SCORE[p.pick.score] || ""), ...marked(p.pick.why, terms)) : null,
      el("a", { class: "pp-title", href: p.links.abs, target: "_blank", rel: "noopener noreferrer" }, ...marked(p.title, terms)),
      el("div", { class: "pp-authors" }, ...authors.map((a) => (typeof a === "string" ? marked(a, terms) : a)).flat()),
      el("div", { class: "pp-tags" },
        ...p.categories.map((c, k) => el("span", { class: `cat${k === 0 ? " pri" : ""}`, title: k === 0 ? "Primary category" : null }, c)),
        KIND_TAG[p.kind] ? el("span", { class: `tag ${p.kind === "cross" ? "cross" : ""}` }, KIND_TAG[p.kind]) : null,
        el("span", { class: "pp-id" }, p.id + (p.version ? `v${p.version}` : "")),
        showDay && p.day ? el("span", null, `· ${dayShort(p.day)}`) : null),
      abs,
      el("div", { class: "pp-links" },
        el("a", { href: p.links.abs, target: "_blank", rel: "noopener noreferrer" }, "Abstract page"),
        el("a", { href: p.links.pdf, target: "_blank", rel: "noopener noreferrer" }, "PDF"),
        el("a", { href: p.links.html, target: "_blank", rel: "noopener noreferrer" }, "HTML"),
        p.comments ? el("span", { class: "meta" }, p.comments) : null,
        p.journal_ref ? el("span", { class: "meta" }, p.journal_ref) : null,
        p.verdict !== undefined ? el("span", { class: "fbs" }, say("relevant", "Relevant", SVG.up), say("not", "Not for me", SVG.down)) : null),
      star);
  }

  function toggleAbs(n) {
    n.classList.toggle("clamp");
    n.title = n.classList.contains("clamp") ? "Show more" : "Show less";
  }

  async function save(p) {
    const on = !p.saved;
    p.saved = on;
    drawList();
    try {
      await post("save", { id: p.id, saved: on });
      if (S.state) S.state.saved = Math.max(0, (S.state.saved || 0) + (on ? 1 : -1));
      drawSide();
    } catch { p.saved = !on; drawList(); }
  }

  async function feedback(p, verdict) {
    const was = p.verdict;
    p.verdict = verdict;
    drawList();
    try {
      const got = await post("feedback", { id: p.id, verdict, day: S.view?.type === "day" ? S.view.day : p.day || null });
      if (S.state?.interests) { S.state.interests.feedback = got.count; if (got.summarizing) S.state.interests.summarizing = true; }
      drawSide();
      if (got.summarizing) flash(`That's ${got.every} marks. The agent is updating your summary.`);
    } catch (e) { p.verdict = was; drawList(); flash(e.message); }
  }

  let flashTimer = 0;
  function flash(text) {
    const f = $("flash");
    f.textContent = text; f.hidden = false;
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => { f.hidden = true; }, 4000);
  }

  function searchAll() {
    const q = S.find.trim();
    if (!q) return;
    S.find = "";
    $("find").value = "";
    open({ type: "search", q });
  }

  // ---------------------------------------------------------------- your interests
  const linesOf = (v) => (Array.isArray(v) ? v.join("\n") : v || "");

  function drawInterests() {
    const m = S.mine || {};
    const page = $("page");
    page.replaceChildren();
    const inputs = m.inputs || {};
    const told = (key, label, hint, area, value) => el("label", { class: "field" }, label,
      area ? el("textarea", { "data-in": key, rows: 3, spellcheck: "true" }, value || "")
        : el("input", { "data-in": key, type: "text", value: value || "", spellcheck: "false", autocomplete: "off" }),
      hint ? el("span", { class: "hint" }, hint) : null);
    const form = el("div", { class: "form" },
      told("scholar", "Your profile", "Your Google Scholar page or personal site. The agent reads your papers there.", false, inputs.scholar),
      told("keywords", "Keywords", "Words that should flag a paper, separated by commas.", false, (inputs.keywords || []).join(", ")),
      told("topics", "Topics you follow", "One per line.", true, linesOf(inputs.topics)),
      told("papers", "Papers to follow related work on", "arXiv IDs, links or titles, one per line.", true, linesOf(inputs.papers)),
      told("notes", "Anything else", "What you want to see, and what you don't.", true, inputs.notes));
    const err = el("p", { class: "err", hidden: true });
    const send = async (b) => {
      const body = {};
      for (const n of form.querySelectorAll("[data-in]")) body[n.dataset.in] = n.value;
      b.disabled = true; err.hidden = true;
      try { S.mine = await post("interests", body); await loadState(); drawMain(); }
      catch (e) { err.textContent = e.message; err.hidden = false; }
      finally { b.disabled = false; }
    };
    if (!m.inputs) {                                         // first: what it does, and the form
      page.append(el("section", { class: "sec intro" },
        el("h2", null, "Tell the Paper news agent about your research"),
        el("p", null, "It summarizes your interests, then picks papers for you from each weekday's listing and says why. Mark papers Relevant or Not for me as you go. Every ", String(m.feedback?.every || 20), " marks, it updates the summary."),
        form, err,
        el("div", { class: "row" }, el("button", { class: "btn primary", type: "button", onclick: (e) => send(e.currentTarget) }, "Make my summary"))));
      fit(page);
      return;
    }
    // the summary, as the agent judges by it
    const p = m.profile;
    const asking = m.summarizing;
    const sum = el("section", { class: "sec" }, el("h2", null, "What the agent judges by"));
    if (asking && !asking.stale) sum.append(el("p", { class: "banner" }, el("span", { class: "dots" }), " The Paper news agent is writing your summary",
      asking.why === "feedback" ? " from your feedback…" : "…"));
    else if (asking && asking.stale) sum.append(el("p", { class: "banner" }, "The agent hasn't written it yet. ",
      button("Ask it again", async () => { try { S.mine = await post("summarize", {}); drawMain(); } catch (e) { flash(e.message); } })));
    if (p) {
      const edited = new Set(p.edited || []);
      sum.append(el("p", { class: "hint" }, p.by === "agent" ? `Written by the agent, ${clock(p.at)}` : `Edited by you, ${clock(p.at)}`,
        edited.size ? ` · kept as you wrote them: ${m.fields.filter((f) => edited.has(f.name)).map((f) => f.label).join(", ")}` : ""));
      const boxes = el("div", { class: "form" });
      for (const f of m.fields) {
        const v = p.fields[f.name];
        boxes.append(el("label", { class: `field${edited.has(f.name) ? " yours" : ""}` }, f.label,
          el("span", { class: "hint" }, f.help + (f.kind === "list" ? " One per line." : "")),
          el("textarea", { "data-f": f.name, "data-kind": f.kind, rows: Math.min(8, Math.max(2, f.kind === "list" ? (v || []).length + 1 : 3)), spellcheck: "true" }, linesOf(v))));
      }
      const saveBtn = el("button", { class: "btn primary", type: "button", disabled: true, onclick: async () => {
        const fields = {};
        for (const n of boxes.querySelectorAll("[data-f]")) {
          const was = linesOf(p.fields[n.dataset.f]);
          if (n.value !== was) fields[n.dataset.f] = n.dataset.kind === "list" ? n.value.split("\n") : n.value;
        }
        saveBtn.disabled = true;
        try { S.mine = await post("profile", { fields }); drawMain(); flash("Saved. The agent uses it from the next day on."); }
        catch (e) { flash(e.message); saveBtn.disabled = false; }
      } }, "Save changes");
      boxes.addEventListener("input", () => { saveBtn.disabled = false; });
      sum.append(boxes, el("div", { class: "row" }, saveBtn));
    } else if (!asking) {
      sum.append(el("p", null, "No summary yet."));
    }
    page.append(sum);
    // feedback
    const fb = m.feedback || { count: 0, every: 20, recent: [] };
    const fsec = el("section", { class: "sec" }, el("h2", null, "Your feedback"),
      el("p", { class: "hint" }, `${fb.count} of ${fb.every} marks since the summary was written. At ${fb.every}, the agent updates it.`));
    if (fb.recent.length) {
      fsec.append(el("ul", { class: "fb-list" }, ...fb.recent.map((r) => el("li", null,
        el("span", { class: `chip ${r.verdict}` }, r.verdict === "relevant" ? "Relevant" : "Not for me"),
        el("a", { href: `https://arxiv.org/abs/${r.id}`, target: "_blank", rel: "noopener noreferrer" }, r.title),
        el("span", { class: "hint" }, r.picked ? " · picked by the agent" : " · not picked"),
        el("button", { class: "x", type: "button", title: "Remove", "aria-label": "Remove", onclick: async () => {
          try { await post("feedback", { id: r.id, verdict: null }); S.mine = await get("interests"); await loadState(); drawMain(); } catch (e) { flash(e.message); }
        } }, "×")))));
    }
    page.append(fsec);
    // what they told it
    page.append(el("section", { class: "sec" }, el("h2", null, "What you told it"),
      el("p", { class: "hint" }, "If you change these, the agent rewrites the summary. Fields you edited are kept."),
      form, err, el("div", { class: "row" }, el("button", { class: "btn", type: "button", onclick: (e) => send(e.currentTarget) }, "Save and rewrite the summary"))));
    if (m.agent) page.append(el("section", { class: "sec" }, el("h2", null, "The agent"),
      el("p", { class: "hint" }, "The Paper news actor. Ask it why it picked a paper, or for more like one."),
      el("div", { class: "row" }, button("Talk to it", () => { try { ag.agents.focus(m.agent); } catch { /* not in this page */ } }))));
    fit(page);
  }

  // A textarea as tall as what it holds (up to 320px), as it is drawn and as it is typed in.
  function fit(root) {
    const size = (t) => { t.style.height = "auto"; t.style.height = `${Math.min(t.scrollHeight + 2, 320)}px`; };
    for (const t of root.querySelectorAll("textarea")) { size(t); t.addEventListener("input", () => size(t)); }
  }

  // ---------------------------------------------------------------- settings
  function openSettings() {
    const s = S.state?.settings || {};
    $("set-cats").value = (s.categories || []).join(" ");
    $("set-repl").checked = !!s.replacements;
    $("set-sys").checked = !!s.notify_system;
    $("set-err").hidden = true;
    const when = S.state?.status?.schedule || [];
    $("set-when").textContent = "arXiv announces new papers Sunday to Thursday at 8 PM New York time. The app fetches them "
      + (when.length ? `${when.join("; ")}` : "each weekday") + ", and catches up on days missed while the dashboard was off.";
    $("sheet").hidden = false;
    $("gear").setAttribute("aria-expanded", "true");
    $("set-cats").focus();
  }
  function closeSettings() { $("sheet").hidden = true; $("gear").setAttribute("aria-expanded", "false"); }
  async function saveSettings() {
    $("set-save").disabled = true;
    try {
      const got = await post("settings", { categories: $("set-cats").value, replacements: $("set-repl").checked, notify_system: $("set-sys").checked });
      if (S.state) S.state.settings = got.settings;
      closeSettings();
      await loadState();
      drawMain();
    } catch (e) {
      $("set-err").textContent = e.message; $("set-err").hidden = false;
    } finally { $("set-save").disabled = false; }
  }

  // ---------------------------------------------------------------- keys and wiring
  function move(by) {
    const items = [...document.querySelectorAll(".pp")];
    if (!items.length) return;
    S.at = Math.max(0, Math.min(items.length - 1, S.at + by));
    items.forEach((n, i) => n.classList.toggle("on", i === S.at));
    items[S.at].scrollIntoView({ block: "nearest" });
    items[S.at].focus({ preventScroll: true });
  }
  document.addEventListener("keydown", (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const typing = e.target.closest("input, textarea");
    if (e.key === "Escape") {
      if (!$("sheet").hidden) { closeSettings(); e.preventDefault(); }
      else if (typing && e.target.id === "find" && S.find) { e.target.value = ""; S.find = ""; drawMain(); e.preventDefault(); }
      return;
    }
    if (typing || !$("sheet").hidden) return;
    const items = [...document.querySelectorAll(".pp")];
    const cur = items[S.at];
    if (e.key === "j") { move(1); e.preventDefault(); }
    else if (e.key === "k") { move(-1); e.preventDefault(); }
    else if (e.key === "/") { $("find").focus(); e.preventDefault(); }
    else if (cur && e.key === "s") { cur.querySelector(".star-btn").click(); e.preventDefault(); }
    else if (cur && e.key === "o") { openPage(cur.querySelector(".pp-title").href); e.preventDefault(); }
    else if (cur && e.key === "Enter" && e.target === cur) { toggleAbs(cur.querySelector(".pp-abs")); e.preventDefault(); }
  });

  $("gear").innerHTML = SVG.gear;
  $("fetch").innerHTML = SVG.fetch;
  $("side-toggle").innerHTML = SVG.side;
  $("gear").addEventListener("click", () => ($("sheet").hidden ? openSettings() : closeSettings()));
  $("set-cancel").addEventListener("click", closeSettings);
  $("set-save").addEventListener("click", saveSettings);
  $("sheet").addEventListener("click", (e) => { if (e.target === $("sheet")) closeSettings(); });
  $("set-cats").addEventListener("keydown", (e) => { if (e.key === "Enter") saveSettings(); });
  $("fetch").addEventListener("click", async () => {
    try { await post("fetch", { force: false }); } catch { /* shown by the status, if it failed */ }
    if (S.state) S.state.status.fetching = true;
    drawStatus();
  });
  $("side-toggle").addEventListener("click", () => {
    if (window.matchMedia("(max-width: 640px)").matches) {
      S.sideOpen = !S.sideOpen; $("app").classList.toggle("side-open", S.sideOpen);
    } else {
      const off = $("app").classList.toggle("side-off"); keep.set("sideOff", off);
    }
  });
  if (keep.get("sideOff", false)) $("app").classList.add("side-off");
  let findTimer = 0;
  $("find").addEventListener("input", (e) => {
    clearTimeout(findTimer);
    findTimer = setTimeout(() => { S.find = e.target.value; S.shown = PAGE; S.at = -1; drawMain(); }, 120);
  });
  $("find").addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.value.trim() && S.view?.type !== "search") { S.find = e.target.value; searchAll(); } });

  ag.onMessage(async (m) => {
    if (!m || !m.news) return;
    const before = latestDay();
    await loadState();
    const v = S.view;
    if (m.news === "days" || m.news === "settings") {
      const now = latestDay();
      if (!v || (v.type === "day" && v.day === before && now !== before && !S.find && S.at < 0 && $("scroll").scrollTop < 40)) {
        if (now) open({ type: "day", day: now, tab: "for" });   // looking at the top of the day before: the new one shown
      } else if (v.type === "day" && v.day === m.day) {
        open(v, { keepFilters: true, keepScroll: true });
      }
    } else if (m.news === "saved" && v?.type === "saved") {
      open(v, { keepFilters: true, keepScroll: true });
    } else if ((m.news === "interests" || m.news === "agent" || m.news === "feedback") && v?.type === "interests"
               && !document.activeElement?.closest?.("#page textarea, #page input")) {
      open(v, { keepScroll: true });                          // not under the reader's typing
    }
  });
  ag.notices.onOpen((where) => { if (where && where.day) open({ type: "day", day: where.day, tab: "for" }); });
  // A link to it clicked in Chat (app.toml's [[links]]): a day's listing, all of it; a paper, in the listing of the day
  // it was in -- picked, as j/k pick one, and scrolled to. Before the state is read: once it is.
  let linked = null, started = false;
  async function openLinked(l) {
    const v = (l && l.values) || {};
    let day = v.day || null;
    if (v.id) day = await get(`paper?id=${encodeURIComponent(v.id)}`).then((r) => r.day).catch(() => null);
    if (!day) return flash(v.id ? `No paper ${v.id} in the days kept` : "No such day");
    await open({ type: "day", day, tab: "all" });
    if (!v.id) return;
    let i = filtered().findIndex((p) => p.id === v.id);
    if (i < 0) { S.kind = "all"; i = filtered().findIndex((p) => p.id === v.id); }
    if (i < 0) return;
    S.shown = Math.max(S.shown, i + 1);
    S.at = i;
    drawMain();
    const item = document.querySelector(`.pp[data-id="${CSS.escape(v.id)}"]`);
    if (item) { item.scrollIntoView({ block: "center" }); item.focus({ preventScroll: true }); }
  }
  ag.links.onOpen((l) => { if (started) openLinked(l); else linked = l; });

  await loadState();
  started = true;
  const v = S.view;
  const kept = (S.state?.days || []).map((d) => d.day);
  if (linked) openLinked(linked);                        // opened by a link: there, not where it was left
  else if (!told()) open({ type: "interests" });
  else if (v && (v.type === "saved" || v.type === "search" || v.type === "interests" || (v.type === "day" && kept.includes(v.day)))) open(v);
  else if (latestDay()) open({ type: "day", day: latestDay(), tab: "for" });
  else drawMain();
  setInterval(() => {
    const busy = S.state?.status?.fetching || S.state?.interests?.summarizing;
    if (busy) loadState();
  }, 3000);
})();

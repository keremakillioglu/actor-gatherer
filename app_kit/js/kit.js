// The panels' kit: what every app's panel builds its page with, the same in each -- served by the host at
// /_ag/lib/kit.js (ag_dashboard/libs.py) and loaded before the panel's own script, as `window.agKit`. Plain script, no
// module: a panel loads it with a <script> tag, as it does the SDK (/_ag/app.js).
//
//   agKit.el(tag, attrs, ...kids)   an element: each attribute set (below), each child appended -- nodes as they are,
//                                   anything else as its text; arrays flattened; null, undefined and false left out
//   agKit.patch(box, kids)          box's children made `kids` (nodes, or a fragment's), each child of box that is the
//                                   same as one of them (its markup) kept in its place of that one: a list drawn anew,
//                                   only what changed in it replaced -- a selection, an image loaded, a menu's place in
//                                   the others kept
(() => {
  "use strict";

  // An attribute: left out when null, undefined or false; "class", "text" (its text), "html" (the panel's own markup
  // only: never what a user or an agent wrote), "value" and "checked" (the element's own, an input's: checked by true
  // or "", as a present attribute), "on<event>" (a listener); any other set as given, true as present ("").
  function el(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k === "html") n.innerHTML = v;
      else if (k === "value" && "value" in n) n.value = v;
      else if (k === "checked") n.checked = v === "" || !!v;   // "" as a present attribute: checked
      else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid === null || kid === undefined || kid === false) continue;
      n.append(kid instanceof Node ? kid : String(kid));
    }
    return n;
  }

  // Kept: a child the same as a new one, markup and all. Its listeners are the ones it was drawn with, which do as the
  // new one's would (drawn from the same data). Each moved only if it isn't where it goes.
  function patch(box, kids) {
    const fresh = kids instanceof Node && kids.nodeType === 11 ? [...kids.childNodes] : [...kids];
    const had = new Map();
    for (const n of box.childNodes) {
      const k = n.nodeType === 1 ? n.outerHTML : n.textContent;
      had.set(k, [...(had.get(k) || []), n]);
    }
    const out = fresh.map((n) => {
      const same = had.get(n.nodeType === 1 ? n.outerHTML : n.textContent);
      return (same && same.shift()) || n;
    });
    let at = box.firstChild;
    for (const n of out) {
      if (n === at) at = at.nextSibling;
      else box.insertBefore(n, at);
    }
    while (at) { const next = at.nextSibling; at.remove(); at = next; }
  }

  window.agKit = Object.freeze({ el, patch });
})();

// The panels' kit: what every app's panel builds its page with, the same in each -- served by the host at
// /_ag/lib/kit.js (ag_dashboard/libs.py) and loaded before the panel's own script, as `window.agKit`. Plain script, no
// module: a panel loads it with a <script> tag, as it does the SDK (/_ag/app.js).
//
//   agKit.el(tag, attrs, ...kids)   an element: each attribute set (below), each child appended -- nodes as they are,
//                                   anything else as its text; arrays flattened; null, undefined and false left out
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

  window.agKit = Object.freeze({ el });
})();

// ag's settings drawn into the dashboard's panel (frontend/index.html's #cfg), read once the page is up; and, with no
// model set, the panel opened at the model's box.
import { createRoot } from "react-dom/client";
import { AgSettings } from "./AgSettings";
import { unset, useSettings } from "./store";

export interface Panel {
  open: () => void;
  close: () => void;
}

export function mountSettings(host: HTMLElement, panel: Panel) {
  host.hidden = false;
  createRoot(host).render(<AgSettings closePanel={panel.close} />);
  // "No model set" on the panel's button, in the page's header (still the old page's: features/page/data.js)
  const flag = document.getElementById("cfg-flag");
  useSettings.subscribe((st) => {
    if (flag) flag.hidden = !unset(st.settings);
  });
  useSettings
    .getState()
    .load()
    .then((s) => {
      if (!unset(s)) return;
      panel.open();
      setTimeout(() => document.getElementById("cfg-model-name")?.focus(), 0); // once drawn
    })
    .catch(() => {});
}

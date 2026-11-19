// WHAT "+" ON AN ACTOR OR A TASK DOES WITH AN APP, on the Apps page (catalog.ts's details, beside how it opens:
// `opensWith`; ag_dashboard/app_policy.py): "join", put in the task; "folder", opened at the actor's directory, shown
// with the task, not put in it; "no", not offered. Its choices those it can take (a group app: not "join"), its
// manifest's own marked "default", a line under them saying what the one chosen does. One picked is kept at once with
// the app's other choices (POST /api/apps/settings: app_settings.py), the page then told (`after`).
import { post } from "../../core/api/client";
import type { CatalogApp } from "./catalog";
import { el } from "./catalog-parts";

export type OnTask = "join" | "folder" | "no";

// each choice: its button's words, and what it does
const SAID: Record<OnTask, [string, string]> = {
  join: ["Joins it", "Put in the task: its agents are attached to it and get its tools."],
  folder: ["At the agent's folder", "Opened at the agent's directory, shown with the task, not part of it."],
  no: ["Not offered", "Left out of the + menu, and not put in a task by dragging."],
};

/** The choice, as a row like "Opens" -- its label, a button for each choice -- and what the one chosen does; none when
 * it can take one only. `after`: called once a pick is kept (`note` "") or refused (`note` why). */
export function onTaskChoice(a: CatalogApp, after: (note: string) => void): HTMLElement | null {
  const can = a.on_task_can || [];
  if (!a.on_task || can.length < 2) return null;
  const pick = (v: OnTask) => {
    if (v === a.on_task) return;
    post<{ on_task: OnTask }>("/api/apps/settings", { app: a.name, on_task: v })
      .then((got) => {
        a.on_task = got.on_task;
        after("");
      })
      .catch((e: Error) => after(`${a.label}: ${e.message}`));
  };
  return el(
    "div",
    { class: "ap-opens ap-on-task" },
    el("span", { class: "ap-opens-l", text: "Added to a task" }),
    el(
      "div",
      { class: "ap-seg", role: "group", "aria-label": `What + on an actor or a task does with ${a.label}` },
      ...can.map((v) =>
        el(
          "button",
          {
            type: "button",
            class: "ap-seg-b",
            "aria-pressed": String(v === a.on_task),
            title: v === a.on_task_own ? `${SAID[v][1]} (its default)` : SAID[v][1],
            onclick: () => pick(v),
          },
          SAID[v][0],
        ),
      ),
    ),
    el("span", {
      class: "ap-opens-note",
      text: SAID[a.on_task][1] + (a.on_task === a.on_task_own ? " Its default." : ""),
    }),
  );
}

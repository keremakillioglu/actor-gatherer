// WHAT "+" ON AN ACTOR OR A TASK DOES WITH AN APP, on the Apps page (catalog.ts's details; ag_dashboard/app_policy.py):
// "join", put in the task; "folder", opened at the actor's directory, shown with the task, not put in it; "no", not
// offered. Its choices those it can take (a group app: not "join"), its manifest's own marked "default"; one picked kept
// at once (POST /api/apps/on_task), the page then told (`after`).
import { post } from "../../core/api/client";
import type { CatalogApp } from "./catalog";
import { el } from "./catalog-parts";

export type OnTask = "join" | "folder" | "no";

// what each choice does, in words
const SAID: Record<OnTask, [string, string]> = {
  join: ["Joins the task", "The task's agents are attached to it and get its tools."],
  folder: ["Opens at the agent's directory", "Shown with the task, not part of it. No agent is attached."],
  no: ["Not offered", "Left out of the + menu, and not put in a task by dragging."],
};

/** The choice, as a heading and a group of radio buttons; none when it can take one only. `after`: called once a pick
 * is kept (`note` "") or refused (`note` why). */
export function onTaskChoice(a: CatalogApp, after: (note: string) => void): HTMLElement[] {
  const can = a.on_task_can || [];
  if (!a.on_task || can.length < 2) return [];
  const pick = (v: OnTask) => {
    if (v === a.on_task) return;
    post<{ on_task: OnTask }>("/api/apps/on_task", { name: a.name, on_task: v })
      .then((got) => {
        a.on_task = got.on_task;
        after("");
      })
      .catch((e: Error) => after(`${a.label}: ${e.message}`));
  };
  return [
    el("h3", { text: "Added to an actor or a task" }),
    el(
      "div",
      { class: "ap-choice", role: "radiogroup", "aria-label": `What + on an actor or a task does with ${a.label}` },
      ...can.map((v) => {
        const [what, note] = SAID[v];
        const input = el("input", { type: "radio", name: `on-task-${a.name}`, value: v }) as HTMLInputElement;
        input.checked = v === a.on_task;
        input.addEventListener("change", () => pick(v));
        return el(
          "label",
          { class: "ap-opt" },
          input,
          el(
            "span",
            {},
            el("span", { class: "ap-opt-what", text: what }),
            v === a.on_task_own ? el("span", { class: "ap-quiet", text: " · default" }) : null,
            el("span", { class: "ap-opt-note", text: note }),
          ),
        );
      }),
    ),
  ];
}

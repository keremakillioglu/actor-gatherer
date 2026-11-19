// Each TASK's arrangement (arrange.ts's tree, work.ts lays it out), kept in this browser -- and its TABS: a task may hold
// several, one shown at a time, each a set of its panels and how they are arranged. A task of one tab is as a task
// always was. A panel may be in several tabs of its task. The tab shown is the tree the work area lays out; one added to
// gets the panel opened in the task since; one emptied (its last panel closed, or moved out) goes. And a task's strip
// (work.ts places it), drawn: its name, then, its tabs being two or more, each tab's name (pressed, shown; double-clicked,
// named; its ×, closed), and a "+" for another.
import { glyph } from "../../core/ui/glyphs";
import * as M from "./model";
import type { TaskLayout, TaskTab } from "./model";
import { shadow } from "./shadow";
import type { Node } from "./tree";

export type { TaskTab };

export class Tasks {
  // each task's record: the layout model's (model.ts, kept by shadow.ts) -- changed by its rules, kept with it
  private get kept(): Record<string, TaskLayout> {
    return shadow.now().tasks;
  }

  /** Each task's tree shown: its tab's. */
  trees(): Record<string, Node> {
    const out: Record<string, Node> = {};
    for (const [k, v] of Object.entries(this.kept)) if (v.tree) out[k] = v.tree;
    return out;
  }
  tree(key: string): Node | null {
    return this.kept[key]?.tree ?? null;
  }
  /** The tree of a task's tab shown, as it is now (changed in place: a bar dragged; or given a new one). */
  set(key: string, tree: Node): void {
    shadow.update(M.setTree, key, tree, Date.now());
  }
  touch(key: string): void {
    shadow.update(M.touchTask, key, Date.now());
  }

  /** A task's tabs, with the one shown -- none, a task of one tab. */
  tabs(key: string): { tabs: TaskTab[]; shown: string } | null {
    const k = this.kept[key];
    return k && k.tabs && k.tabs.length > 1 ? { tabs: k.tabs, shown: k.tab! } : null;
  }
  /** Another tab of a task, holding `tree` (a panel moved or copied there, its lead actor's): its id. The task's one tab so
   * far named "Tab 1". */
  addTab(key: string, tree: Node): string {
    shadow.update(M.addTaskTab, key, tree, Date.now());
    const tabs = this.kept[key].tabs!;
    return tabs[tabs.length - 1].id;
  }
  /** A tab of a task shown: its tree. */
  showTab(key: string, id: string): Node | null {
    if (!this.kept[key]?.tabs?.some((t) => t.id === id)) return null;
    shadow.update(M.showTaskTab, key, id, Date.now());
    return this.kept[key].tree ?? null;
  }
  /** A tab's tree, changed as `change` says (the tab shown: its tree shown too); emptied, the tab gone: false. */
  changeTab(key: string, id: string, change: (tree: Node) => Node | null): boolean {
    const tab = this.kept[key]?.tabs?.find((t) => t.id === id);
    if (!tab) return false;
    const tree = change(tab.tree);
    shadow.update(M.changeTaskTab, key, id, tree);
    return !!tree;
  }
  /** A tab closed: the next one shown, if it was (its id); one tab left, the task as a task of one tab. */
  closeTab(key: string, id: string): string | null {
    if (!this.kept[key]?.tabs?.some((t) => t.id === id)) return null;
    shadow.update(M.closeTaskTab, key, id);
    return this.kept[key].tab ?? null;
  }
  rename(key: string, id: string, name: string): void {
    shadow.update(M.renameTaskTab, key, id, name);
  }

  save(): void {
    shadow.persist();
  }
}

export interface StripHooks {
  show: (tab: string) => void;
  close: (tab: string) => void;
  rename: (tab: string, name: string) => void;
  /** Another tab of the task (its lead actor's chat in it); null: none to put in one (a task of apps alone). */
  add: (() => void) | null;
  /** The task closed here (its × ): its panels out of the tab shown, its agents going on; none, no ×. */
  closeTask?: (() => void) | null;
}
/** What a task's card's head says: its name, its actors' faces (and its apps' marks), what is in it in words. */
export interface StripHead {
  name: string;
  faces: HTMLElement[];
  about: string;
}
/** A task's strip -- the head of its card -- drawn: a grip, its faces, its name and what is in it; its tabs, if it has
 * two or more, as a switch, each pressed to be shown, double-clicked to be named, closed by its ×; and a "+" for
 * another tab. Drawn again only as what it shows changes. */
export function drawStrip(
  e: HTMLElement,
  head: StripHead,
  tabs: { tabs: TaskTab[]; shown: string } | null,
  hooks: StripHooks,
): void {
  const sig = JSON.stringify([
    head.name,
    head.about,
    head.faces.map((f) => f.outerHTML),
    tabs && tabs.tabs.map((t) => [t.id, t.name]),
    tabs?.shown,
    !!hooks.add,
    !!hooks.closeTask,
  ]);
  if (e.dataset.sig === sig || e.querySelector("input")) return;
  e.dataset.sig = sig;
  e.dataset.name = head.name;
  const span = (cls: string, text = ""): HTMLElement => {
    const x = document.createElement("span");
    x.className = cls;
    x.textContent = text;
    return x;
  };
  const grip = span("lay-grip", "⋮⋮");
  grip.setAttribute("aria-hidden", "true");
  const faces = span("lay-faces");
  faces.setAttribute("aria-hidden", "true");
  faces.append(...head.faces);
  const parts: HTMLElement[] = [grip, ...(head.faces.length ? [faces] : []), span("lay-sname", head.name)];
  if (head.about) parts.push(span("lay-sabout", head.about));
  const right = span("lay-sright");
  if (tabs) {
    const box = span("lay-ttabs");
    box.setAttribute("role", "tablist");
    box.setAttribute("aria-label", `${head.name} tabs`);
    for (const t of tabs.tabs) box.append(chipOf(t));
    right.append(box);
  }
  if (hooks.add) {
    const add = document.createElement("button");
    add.type = "button";
    add.className = "lay-tadd";
    add.append(glyph("plus", 16));
    add.title = add.ariaLabel = "New tab for this task";
    add.addEventListener("click", (ev) => {
      ev.stopPropagation();
      hooks.add!();
    });
    right.append(add);
  }
  if (hooks.closeTask) {
    const x = document.createElement("button");
    x.type = "button";
    x.className = "lay-sclose";
    x.append(glyph("x", 16));
    x.title = x.ariaLabel = `Close ${head.name} here (agents keep running)`;
    x.addEventListener("click", (ev) => {
      ev.stopPropagation();
      hooks.closeTask!();
    });
    right.append(x);
  }
  parts.push(right);
  e.replaceChildren(...parts);

  function chipOf(t: TaskTab): HTMLElement {
    const chip = span("lay-ttab");
    chip.dataset.tab = t.id;
    chip.setAttribute("role", "tab");
    chip.setAttribute("aria-selected", String(t.id === tabs!.shown));
    chip.title = `${t.name} · double-click to rename · drop a panel here to move it (⌥ to copy)`;
    const n = span("", t.name);
    const x = document.createElement("button");
    x.type = "button";
    x.className = "lay-tclose";
    x.append(glyph("x", 12));
    x.title = x.ariaLabel = `Close ${t.name} (panels stay in the task)`;
    x.addEventListener("click", (ev) => {
      ev.stopPropagation();
      hooks.close(t.id);
    });
    chip.append(n, x);
    chip.addEventListener("click", (ev) => {
      ev.stopPropagation();
      hooks.show(t.id);
    });
    chip.addEventListener("dblclick", (ev) => {
      ev.stopPropagation();
      const input = document.createElement("input");
      input.className = "lay-naming";
      input.value = t.name;
      let done = false;
      const end = (keep: boolean): void => {
        if (done) return;
        done = true;
        input.remove();
        e.dataset.sig = "";
        if (keep && input.value.trim()) hooks.rename(t.id, input.value);
        else drawStrip(e, head, tabs, hooks);
      };
      input.addEventListener("keydown", (k) => {
        k.stopPropagation();
        if (k.key === "Enter") end(true);
        else if (k.key === "Escape") end(false);
      });
      input.addEventListener("blur", () => end(true));
      input.addEventListener("click", (k) => k.stopPropagation());
      n.replaceWith(input);
      input.focus();
      input.select();
    });
    return chip;
  }
}

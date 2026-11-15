// WHAT IS DRAGGED OVER THE TABS' BAR (tabs.ts), shown there as it goes. A tab, by its name, along the bar: the others
// slid aside as they would lie were it let go there, its own place dimmed. A task, by its card head (work.ts's carry):
// "New tab" in the bar meanwhile, and where it would go marked -- another tab's name, into that tab; the tab shown's,
// nowhere; anywhere else on the bar, a new tab.

/** Where a task dragged over the bar would go: a tab (its name), a new tab, or nowhere. */
export type Into = HTMLElement | "new" | null;

export class BarDrag {
  /** The tab dragged along the bar (its id), if one is. */
  lifted: string | null = null;
  /** "New tab", while a task that can go to another tab is dragged. */
  readonly ghost: HTMLElement;

  constructor(private readonly list: HTMLElement) {
    this.ghost = document.createElement("div");
    this.ghost.className = "lay-tab-ghost";
    this.ghost.textContent = "New tab";
    this.ghost.hidden = true;
  }

  /** Tab `id` picked up by its name (`chip`): dimmed, the others sliding, once the browser has its picture to drag. */
  lift(id: string, chip: HTMLElement): void {
    this.lifted = id;
    setTimeout(() => {
      if (this.lifted !== id) return;
      chip.classList.add("lay-lifted");
      this.list.classList.add("lay-sorting");
    }, 0);
  }
  /** Where the tab dragged would go, the pointer at `x`: its place among the others -- before the first whose middle is
   * past the pointer, as they lie (offsets: not as they are slid aside meanwhile). */
  slotAt(x: number): number {
    const at = x - this.list.getBoundingClientRect().left,
      others = this.chips().filter((e) => e.dataset.id !== this.lifted),
      i = others.findIndex((e) => e.offsetLeft + e.offsetWidth / 2 > at);
    return i < 0 ? others.length : i;
  }
  /** The tabs slid aside as they would lie with the one dragged at place `slot` among the others: the ones it passes a
   * place toward where it was, it past them -- none, as they lie. */
  slide(slot: number | null): void {
    const chips = this.chips(),
      from = chips.findIndex((e) => e.dataset.id === this.lifted);
    for (const e of chips) e.style.transform = "";
    if (slot === null || from < 0 || slot === from) return;
    const gap = parseFloat(getComputedStyle(this.list).columnGap) || 0,
      step = (e: HTMLElement): number => e.offsetWidth + gap,
      passed = slot > from ? chips.slice(from + 1, slot + 1) : chips.slice(slot, from),
      way = slot > from ? -1 : 1;
    for (const e of passed) e.style.transform = `translateX(${way * step(chips[from])}px)`;
    chips[from].style.transform = `translateX(${-way * passed.reduce((n, e) => n + step(e), 0)}px)`;
  }
  /** The tab dragged let go (dropped, or the drag given up): the others back where they lie. False if none was. */
  drop(): boolean {
    if (!this.lifted) return false;
    this.list.classList.remove("lay-sorting");
    this.slide(null);
    this.lifted = null;
    for (const e of this.chips()) e.classList.remove("lay-lifted");
    return true;
  }

  /** A task that can go to another tab picked up, or put down: "New tab" shown in the bar meanwhile. */
  carrying(on: boolean): void {
    this.ghost.hidden = !on;
    if (!on) this.mark(null);
  }
  /** Where a task dragged over the bar would go, `current` the tab shown. */
  into(ev: DragEvent, current: string): Into {
    const chip = ev.target instanceof Element ? ev.target.closest<HTMLElement>(".lay-tab[data-id]") : null;
    if (!chip) return "new";
    return chip.dataset.id === current ? null : chip;
  }
  /** That place marked (none: no mark). */
  mark(to: Into): void {
    for (const e of this.list.querySelectorAll(".lay-into")) if (e !== to) e.classList.remove("lay-into");
    if (to instanceof HTMLElement) to.classList.add("lay-into");
    this.ghost.classList.toggle("lay-into", to === "new");
  }

  private chips(): HTMLElement[] {
    return [...this.list.querySelectorAll<HTMLElement>(".lay-tab[data-id]")];
  }
}

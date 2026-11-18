// A screen tab's name typed in place (tabs.ts, a double-click on it): Enter or leaving the box keeps it, Esc leaves it as
// it was.

/** A box in place of `span`, holding `was`: `end(keep, value)` once Enter, Esc or a click elsewhere ends it. */
export function nameInPlace(span: HTMLElement, was: string, end: (keep: boolean, value: string) => void): void {
  const input = document.createElement("input");
  input.className = "lay-naming";
  input.value = was;
  input.placeholder = "Name this tab";
  let done = false;
  const stop = (keep: boolean): void => {
    if (done) return;
    done = true;
    input.remove();
    end(keep, input.value);
  };
  input.addEventListener("keydown", (ev) => {
    ev.stopPropagation();
    if (ev.key === "Enter") stop(true);
    else if (ev.key === "Escape") stop(false);
  });
  input.addEventListener("blur", () => stop(true));
  input.addEventListener("click", (ev) => ev.stopPropagation());
  span.replaceWith(input);
  input.focus();
  input.select();
}

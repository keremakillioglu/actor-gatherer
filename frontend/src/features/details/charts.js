import { axisTime, clock, compact, el, full, svgEl } from "../../core/page/helpers.js";

// ------------------------------------------------------------------ charts
function lineChart(host, { reads, series, height = 220, rebuilds = true, step = false, onPick, picked }) {
  host.replaceChildren();
  const box = el("div", { class: "chart" });
  host.append(box);
  const W = Math.max(320, host.clientWidth || 640), H = height, m = { l: 48, r: 12, t: 12, b: 26 };
  const xs = reads.map((r) => r.at).filter((t) => t);
  if (!xs.length) { box.append(el("div", { class: "desc", text: "No reads yet." })); return; }
  let x0 = Math.min(...xs), x1 = Math.max(...xs);
  if (x1 === x0) { x0 -= 30; x1 += 30; }
  const vals = series.flatMap((s) => reads.map((r) => r[s.field]).filter((v) => typeof v === "number"));
  let ymax = Math.max(1, ...vals);
  const stepY = Math.max(1, niceStep(ymax / 4)); ymax = Math.ceil(ymax / stepY) * stepY;
  const X = (t) => m.l + (t - x0) / (x1 - x0) * (W - m.l - m.r), Y = (v) => H - m.b - v / ymax * (H - m.t - m.b);
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img" });
  for (let v = 0; v <= ymax + 1e-9; v += stepY) {
    svg.append(svgEl("line", { x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), stroke: v === 0 ? "var(--axis)" : "var(--grid)", "stroke-width": 1 }));
    const t = svgEl("text", { x: m.l - 6, y: Y(v) + 4, "text-anchor": "end" }); t.textContent = compact(v); svg.append(t);
  }
  const days = (x1 - x0) > 86400;
  const ticks = Math.max(2, Math.min(6, Math.floor((W - m.l - m.r) / 110)));
  for (let i = 0; i <= ticks; i++) {
    const t = x0 + (x1 - x0) * i / ticks;
    const lab = svgEl("text", { x: X(t), y: H - 8, "text-anchor": i === 0 ? "start" : i === ticks ? "end" : "middle" });
    lab.textContent = axisTime(t, days, (x1 - x0) < 600); svg.append(lab);
  }
  if (rebuilds) for (const r of reads) if (r.rebuild && r.at)
    svg.append(svgEl("line", { x1: X(r.at), x2: X(r.at), y1: m.t, y2: H - m.b, stroke: "var(--muted)", "stroke-width": 1, opacity: .7 }));
  for (const s of series) {
    const pts = reads.filter((r) => typeof r[s.field] === "number" && r.at);
    if (!pts.length) continue;
    let d = "";
    pts.forEach((r, i) => {
      const x = X(r.at), y = Y(r[s.field]);
      if (i === 0) d += `M${x},${y}`;
      else if (step) d += `H${x}V${y}`; else d += `L${x},${y}`;
    });
    svg.append(svgEl("path", { d, fill: "none", stroke: s.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    const last = pts[pts.length - 1];
    svg.append(svgEl("circle", { cx: X(last.at), cy: Y(last[s.field]), r: 4, fill: s.color, stroke: "var(--surface)", "stroke-width": 2 }));
  }
  if (picked) {
    const r = reads.find((q) => q.read_id === picked);
    if (r && r.at) svg.append(svgEl("line", { x1: X(r.at), x2: X(r.at), y1: m.t, y2: H - m.b, stroke: "var(--s1)", "stroke-width": 1 }));
  }
  const cross = svgEl("line", { y1: m.t, y2: H - m.b, stroke: "var(--axis)", "stroke-width": 1, visibility: "hidden" });
  svg.append(cross);
  const hit = svgEl("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent", style: onPick ? "cursor:pointer" : "" });
  svg.append(hit);
  box.append(svg);
  const tip = el("div", { class: "tooltip" });
  box.append(tip);
  const nearest = (ev) => {
    const rect = svg.getBoundingClientRect();
    const px = (ev.clientX - rect.left) * W / rect.width;
    const t = x0 + (px - m.l) / (W - m.l - m.r) * (x1 - x0);
    let best = null;
    for (const r of reads) if (r.at && (!best || Math.abs(r.at - t) < Math.abs(best.at - t))) best = r;
    return { best, rect };
  };
  hit.addEventListener("pointermove", (ev) => {
    const { best, rect } = nearest(ev);
    if (!best) return;
    cross.setAttribute("x1", X(best.at)); cross.setAttribute("x2", X(best.at)); cross.setAttribute("visibility", "visible");
    tip.replaceChildren(el("div", { class: "t", text: `${clock(best.at, days)} · read ${best.read_id}${best.rebuild ? " · rebuild" : ""}` }));
    for (const s of series) tip.append(el("div", { class: "row" }, el("span", { class: "key-line", style: `background:${s.color}` }),
      el("b", { text: s.format ? s.format(best[s.field]) : full(best[s.field]) }), el("span", { text: s.label })));
    tip.style.display = "block";
    const left = X(best.at) / W * rect.width;
    tip.style.left = Math.min(Math.max(0, left + 12), rect.width - 190) + "px";
    tip.style.top = "8px";
  });
  hit.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); tip.style.display = "none"; });
  if (onPick) hit.addEventListener("click", (ev) => { const { best } = nearest(ev); if (best) onPick(best.read_id); });
}
function niceStep(raw) {
  const p = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1e-9))));
  for (const f of [1, 2, 2.5, 5, 10]) if (raw <= f * p) return f * p;
  return 10 * p;
}
function legend(items) {
  return el("div", { class: "legend" }, ...items.map((i) => el("span", {},
    el("span", { class: i.kind === "rule" ? "key-rule" : i.kind === "rect" ? "key-rect" : "key-line", style: i.color ? `background:${i.color}` : "" }),
    i.label)));
}

export { legend, lineChart };

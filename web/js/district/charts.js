// Charts for the district workspace: plain SVG drawn at the width of the box they are put in, redrawn when the box
// changes size, readable in print, and each with the same figures as a table for screen readers.
//   barChart(el, {labels, values, unit, title})
//   stackedBar(el, {labels, series:[{name, values}], unit, title})
//   lineChart(el, {x, series:[{name, values}], unit, title})
//   waterfall(el, {steps:[{label, value, kind:"start"|"minus"|"plus"|"total"}], unit, title})
//   tornado(el, {rows:[{label, low, high}], base, unit, title})
//   donut(el, {labels, values, unit, title})
// Every function returns { redraw(), destroy() }. `unit` is a unit code from the data contract (sf, usd, usd_per_sf_yr,
// pct, acres, ...) or words to put after the number ("homes"). Missing numbers are left out, never drawn as zero.
import { drawIn } from "../calm.js";

const PALETTE = ["#1f4436", "#c98a0b", "#2f7f73", "#b5562f", "#4f6b8a", "#7b8b3a", "#7a4f7a", "#9a7b4f", "#3d6f99", "#8a3a4a"];
export const colourAt = (i) => PALETTE[i % PALETTE.length];

const esc = (v) => String(v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const isNum = (v) => v !== null && v !== undefined && v !== "" && isFinite(Number(v));
const n0 = (v, d = 0) => Number(v).toLocaleString("en-US", { maximumFractionDigits: d });

// ---------------------------------------------------------------- numbers with their units

const UNIT_AFTER = {
  sf: " SF", acres: " acres", units: " homes", keys: " keys", people: " people", households: " households", jobs: " jobs",
  count: "", years: " years", months: " months", sf_per_yr: " SF/yr", units_per_yr: " homes/yr", miles: " miles", ratio: "x",
};
const MONEY_AFTER = {
  usd: "", usd_per_yr: "/yr", usd_per_sf_yr: "/SF/yr", usd_per_sf_mo: "/SF/mo", usd_per_sf: "/SF", usd_per_acre: "/acre",
  usd_per_unit: "/home", usd_per_unit_mo: "/home/mo", usd_per_night: "/night",
};
// a short number for an axis: 1.2M, 450K
function compact(v) {
  const a = Math.abs(v);
  if (a >= 1e9) return n0(v / 1e9, a >= 1e10 ? 0 : 1) + "B";
  if (a >= 1e6) return n0(v / 1e6, a >= 1e7 ? 0 : 1) + "M";
  if (a >= 1e4) return n0(v / 1e3, 0) + "K";
  return n0(v, a < 10 ? 2 : a < 100 ? 1 : 0);
}
// the value as people read it, with its unit; short=true for axes
export function formatValue(v, unit, short = false) {
  if (!isNum(v)) return "not given";
  v = Number(v);
  const u = unit || "";
  if (u in MONEY_AFTER) {
    const digits = /per_sf/.test(u) ? 2 : 0;
    const body = short ? compact(Math.abs(v)) : n0(Math.abs(v), digits);
    return (v < 0 ? "-" : "") + "$" + body + MONEY_AFTER[u];
  }
  if (u === "pct") return n0(v, short ? 0 : 1) + "%";
  const body = short ? compact(v) : n0(v, Math.abs(v) < 10 ? 2 : 0);
  if (u in UNIT_AFTER) return body + UNIT_AFTER[u];
  return u ? body + " " + u : body;
}
// what the unit is called above an axis
export function unitWords(unit) {
  return { sf: "Square feet (SF)", acres: "Acres", usd: "US dollars", usd_per_yr: "Dollars per year", usd_per_sf_yr: "Dollars per SF per year",
    usd_per_sf_mo: "Dollars per SF per month", usd_per_sf: "Dollars per SF", usd_per_acre: "Dollars per acre", pct: "Percent",
    units: "Homes", keys: "Hotel keys", people: "People", households: "Households", jobs: "Jobs", usd_per_night: "Dollars per night",
    sf_per_yr: "SF per year", units_per_yr: "Homes per year" }[unit] || unit || "";
}

// ---------------------------------------------------------------- the frame every chart shares

function niceStep(span, count) {
  const raw = span / Math.max(1, count), mag = Math.pow(10, Math.floor(Math.log10(raw || 1))), r = raw / mag;
  return (r <= 1 ? 1 : r <= 2 ? 2 : r <= 2.5 ? 2.5 : r <= 5 ? 5 : 10) * mag;
}
function ticks(lo, hi, count) {
  if (!(hi > lo)) hi = lo + 1;
  const step = niceStep(hi - lo, count);
  const a = Math.floor(lo / step + 1e-9) * step, b = Math.ceil(hi / step - 1e-9) * step, out = [];
  for (let t = a; t <= b + step / 2; t += step) out.push(Math.round(t / step) * step);
  return { lo: a, hi: b, list: out };
}
// a label cut to fit about `chars` characters
function clip(s, chars) { s = String(s); return s.length > chars ? s.slice(0, Math.max(1, chars - 1)) + "…" : s; }

// the hidden table a screen reader reads instead of the picture
function srTable(title, head, rows) {
  return `<div class="dc-sr-box"><table><caption>${esc(title)}</caption><thead><tr>${head.map((h) => `<th scope="col">${esc(h)}</th>`).join("")}</tr></thead><tbody>` +
    rows.map((r) => `<tr>${r.map((c, i) => (i ? `<td>${esc(c)}</td>` : `<th scope="row">${esc(c)}</th>`)).join("")}</tr>`).join("") + "</tbody></table></div>";
}
function legend(names) {
  return `<p class="dc-legend" aria-hidden="true">${names.map((nm, i) => `<span><i style="background:${colourAt(i)}"></i>${esc(nm)}</span>`).join("")}</p>`;
}
function empty(el, title) {
  el.innerHTML = `<p class="dc-chart-empty">${esc(title ? title + ": " : "")}no figures to draw yet.</p>`;
}

// mount: draws now, again when the box changes width, and draws in once when first seen
function mount(el, draw) {
  let width = 0, stopped = false, first = true;
  const paint = () => {
    if (stopped) return;
    const w = Math.max(240, Math.floor(el.clientWidth || el.getBoundingClientRect().width || 600));
    width = w;
    try { el.innerHTML = draw(w); } catch (e) { console.error(e); el.innerHTML = '<p class="dc-chart-empty">This chart could not be drawn.</p>'; }
    el.classList.add("dc-chart");
    if (first) { first = false; drawIn(el); }
  };
  paint();
  let ro = null;
  if (window.ResizeObserver) {
    ro = new ResizeObserver(() => {
      if (!el.isConnected) { ro.disconnect(); return; }
      const w = Math.floor(el.clientWidth);
      if (w && Math.abs(w - width) > 8) paint();
    });
    ro.observe(el);
  }
  const printing = () => paint();
  window.addEventListener("beforeprint", printing);
  return {
    redraw: paint,
    destroy() { stopped = true; if (ro) ro.disconnect(); window.removeEventListener("beforeprint", printing); },
  };
}
const svgOpen = (W, H, title) => `<svg class="dc-svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${esc(title || "Chart")}" focusable="false">`;
const titleLine = (title) => (title ? `<p class="dc-chart-title">${esc(title)}</p>` : "");

// ---------------------------------------------------------------- bars (horizontal: long category names read well)

export function barChart(el, o = {}) {
  const labels = o.labels || [], values = (o.values || []).map(Number);
  const rows = labels.map((l, i) => [l, values[i]]).filter((r) => isNum(r[1]));
  if (!rows.length) { empty(el, o.title); return { redraw() {}, destroy() {} }; }
  return mount(el, (W) => {
    const bar = 22, gap = 12, top = 8, labelW = Math.min(Math.max(90, W * 0.34), 260), chars = Math.floor(labelW / 7.2);
    const valW = 96, H = top + rows.length * (bar + gap) + 26;
    const lo = Math.min(0, ...rows.map((r) => r[1])), hi = Math.max(0, ...rows.map((r) => r[1]));
    const t = ticks(lo, hi, W < 500 ? 3 : 5), left = labelW + 10, right = W - valW, pw = Math.max(40, right - left);
    const x = (v) => left + (v - t.lo) / (t.hi - t.lo) * pw;
    let s = svgOpen(W, H, o.title);
    t.list.forEach((v) => { const xx = x(v).toFixed(1); s += `<line class="dc-grid${v === 0 ? " zero" : ""}" x1="${xx}" x2="${xx}" y1="${top}" y2="${H - 22}"/><text class="dc-xlab" x="${xx}" y="${H - 6}" text-anchor="middle">${esc(formatValue(v, o.unit, true))}</text>`; });
    s += '<g class="calm-data">';
    rows.forEach((r, i) => {
      const y = top + i * (bar + gap), a = x(Math.min(0, r[1])), b = x(Math.max(0, r[1]));
      s += `<text class="dc-lab" x="${labelW}" y="${y + bar / 2 + 4}" text-anchor="end">${esc(clip(r[0], chars))}<title>${esc(r[0])}</title></text>`;
      s += `<rect x="${a.toFixed(1)}" y="${y}" width="${Math.max(1, b - a).toFixed(1)}" height="${bar}" rx="3" fill="${o.colour || colourAt(0)}"><title>${esc(r[0])}: ${esc(formatValue(r[1], o.unit))}</title></rect>`;
      s += `<text class="dc-val" x="${(b + 6).toFixed(1)}" y="${y + bar / 2 + 4}">${esc(formatValue(r[1], o.unit, W < 560))}</text>`;
    });
    s += "</g></svg>";
    return titleLine(o.title) + `<div aria-hidden="true">${s}</div>` + srTable(o.title || "Chart", ["", unitWords(o.unit) || "Value"], rows.map((r) => [r[0], formatValue(r[1], o.unit)]));
  });
}

// ---------------------------------------------------------------- vertical frame for columns and lines

function columnsFrame(W, H, t, o, slots, xLabel) {
  const labs = t.list.map((v) => formatValue(v, o.unit, true));
  const left = 14 + Math.max(...labs.map((l) => l.length)) * 6.8, right = 10, top = 22;
  const slotW = (W - left - right) / Math.max(1, slots), tilt = slotW < 64;
  const bottom = tilt ? 64 : 34, ph = H - top - bottom;
  const y = (v) => top + ph - (v - t.lo) / (t.hi - t.lo) * ph;
  const x = (i) => left + (i + 0.5) * slotW;
  let s = "";
  t.list.forEach((v, i) => { const yy = y(v).toFixed(1); s += `<line class="dc-grid${v === 0 ? " zero" : ""}" x1="${left.toFixed(1)}" x2="${W - right}" y1="${yy}" y2="${yy}"/><text class="dc-ylab" x="${(left - 6).toFixed(1)}" y="${yy}" dy="4" text-anchor="end">${esc(labs[i])}</text>`; });
  s += `<text class="dc-unit" x="${left.toFixed(1)}" y="12">${esc(unitWords(o.unit))}</text>`;
  const every = tilt ? Math.max(1, Math.ceil(18 / slotW)) : 1;
  for (let i = 0; i < slots; i++) {
    if (i % every) continue;
    const lab = xLabel(i), xx = x(i).toFixed(1), yy = H - bottom + 16;
    s += tilt ? `<text class="dc-xlab" transform="translate(${xx} ${yy}) rotate(-38)" text-anchor="end">${esc(clip(lab, 14))}<title>${esc(lab)}</title></text>`
      : `<text class="dc-xlab" x="${xx}" y="${yy}" text-anchor="middle">${esc(clip(lab, Math.max(4, Math.floor(slotW / 6.6))))}<title>${esc(lab)}</title></text>`;
  }
  return { s, x, y, slotW, top, base: top + ph, left, right: W - right };
}

export function stackedBar(el, o = {}) {
  const labels = o.labels || [], series = (o.series || []).filter((sr) => (sr.values || []).some(isNum));
  if (!labels.length || !series.length) { empty(el, o.title); return { redraw() {}, destroy() {} }; }
  const totals = labels.map((_, i) => series.reduce((t, sr) => t + (isNum(sr.values[i]) && Number(sr.values[i]) > 0 ? Number(sr.values[i]) : 0), 0));
  return mount(el, (W) => {
    const H = o.height || 280, t = ticks(0, Math.max(...totals) * 1.04 || 1, H > 240 ? 5 : 4);
    const f = columnsFrame(W, H, t, o, labels.length, (i) => labels[i]);
    let s = svgOpen(W, H, o.title) + f.s + '<g class="calm-data">';
    const w = Math.min(64, f.slotW * 0.62);
    labels.forEach((lab, i) => {
      let acc = 0;
      series.forEach((sr, k) => {
        const v = Number(sr.values[i]);
        if (!isNum(sr.values[i]) || v <= 0) return;
        const y1 = f.y(acc + v), y0 = f.y(acc);
        s += `<rect x="${(f.x(i) - w / 2).toFixed(1)}" y="${y1.toFixed(1)}" width="${w.toFixed(1)}" height="${Math.max(0.5, y0 - y1).toFixed(1)}" fill="${colourAt(k)}" stroke="#fff" stroke-width="1"><title>${esc(lab)}, ${esc(sr.name)}: ${esc(formatValue(v, o.unit))}</title></rect>`;
        acc += v;
      });
      if (totals[i] > 0 && f.slotW > 40) s += `<text class="dc-val" x="${f.x(i).toFixed(1)}" y="${(f.y(totals[i]) - 5).toFixed(1)}" text-anchor="middle">${esc(formatValue(totals[i], o.unit, true))}</text>`;
    });
    s += "</g></svg>";
    const head = [""].concat(series.map((sr) => sr.name), ["Total"]);
    const rows = labels.map((lab, i) => [lab].concat(series.map((sr) => formatValue(sr.values[i], o.unit)), [formatValue(totals[i], o.unit)]));
    return titleLine(o.title) + `<div aria-hidden="true">${s}</div>` + legend(series.map((sr) => sr.name)) + srTable(o.title || "Chart", head, rows);
  });
}

export function lineChart(el, o = {}) {
  const xs = o.x || [], series = (o.series || []).filter((sr) => (sr.values || []).some(isNum));
  if (!xs.length || !series.length) { empty(el, o.title); return { redraw() {}, destroy() {} }; }
  const all = series.flatMap((sr) => sr.values.filter(isNum).map(Number));
  return mount(el, (W) => {
    const H = o.height || 260, lo = Math.min(...all), hi = Math.max(...all), pad = (hi - lo) * 0.1 || Math.abs(hi) * 0.1 || 1;
    const t = ticks(o.zero === false ? lo - pad : Math.min(0, lo), hi + pad, H > 240 ? 5 : 4);
    const f = columnsFrame(W, H, t, o, xs.length, (i) => xs[i]);
    let s = svgOpen(W, H, o.title) + f.s + '<g class="calm-data">';
    series.forEach((sr, k) => {
      let d = "", run = 0;
      sr.values.forEach((v, i) => {
        if (!isNum(v)) { run = 0; return; }
        d += (run ? "L" : "M") + f.x(i).toFixed(1) + " " + f.y(Number(v)).toFixed(1); run++;
      });
      s += `<path d="${d}" fill="none" stroke="${colourAt(k)}" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"/>`;
      sr.values.forEach((v, i) => { if (isNum(v)) s += `<circle cx="${f.x(i).toFixed(1)}" cy="${f.y(Number(v)).toFixed(1)}" r="3.6" fill="#fff" stroke="${colourAt(k)}" stroke-width="2"><title>${esc(sr.name)}, ${esc(xs[i])}: ${esc(formatValue(v, o.unit))}</title></circle>`; });
    });
    s += "</g></svg>";
    const head = [""].concat(series.map((sr) => sr.name));
    const rows = xs.map((xv, i) => [String(xv)].concat(series.map((sr) => formatValue(sr.values[i], o.unit))));
    return titleLine(o.title) + `<div aria-hidden="true">${s}</div>` + (series.length > 1 ? legend(series.map((sr) => sr.name)) : "") + srTable(o.title || "Chart", head, rows);
  });
}

// start and total stand on zero; plus and minus float from the running total
export function waterfall(el, o = {}) {
  const steps = (o.steps || []).filter((st) => isNum(st.value));
  if (!steps.length) { empty(el, o.title); return { redraw() {}, destroy() {} }; }
  let run = 0;
  const bars = steps.map((st) => {
    const v = Number(st.value), kind = st.kind || (v < 0 ? "minus" : "plus");
    let a, b;
    if (kind === "start" || kind === "total") { a = 0; b = v; run = v; }
    else if (kind === "minus") { a = run; b = run - Math.abs(v); run = b; }
    else { a = run; b = run + v; run = b; }
    return { label: st.label, v, kind, a, b };
  });
  const lo = Math.min(0, ...bars.map((r) => Math.min(r.a, r.b))), hi = Math.max(0, ...bars.map((r) => Math.max(r.a, r.b)));
  const COL = { start: colourAt(0), total: colourAt(0), plus: "#2f7f73", minus: "#b5562f" };
  return mount(el, (W) => {
    const H = o.height || 300, t = ticks(lo, hi * 1.05, 5), f = columnsFrame(W, H, t, o, bars.length, (i) => bars[i].label);
    let s = svgOpen(W, H, o.title) + f.s + '<g class="calm-data">';
    const w = Math.min(70, f.slotW * 0.64);
    bars.forEach((r, i) => {
      const y1 = f.y(Math.max(r.a, r.b)), y0 = f.y(Math.min(r.a, r.b));
      const shown = r.kind === "minus" ? -Math.abs(r.v) : r.v;
      s += `<rect x="${(f.x(i) - w / 2).toFixed(1)}" y="${y1.toFixed(1)}" width="${w.toFixed(1)}" height="${Math.max(1, y0 - y1).toFixed(1)}" rx="2" fill="${COL[r.kind] || COL.plus}"${r.kind === "minus" ? ' fill-opacity=".9"' : ""}><title>${esc(r.label)}: ${esc(formatValue(shown, o.unit))}</title></rect>`;
      if (i < bars.length - 1) s += `<line class="dc-link" x1="${(f.x(i) + w / 2).toFixed(1)}" x2="${(f.x(i + 1) - w / 2).toFixed(1)}" y1="${f.y(r.b).toFixed(1)}" y2="${f.y(r.b).toFixed(1)}"/>`;
      if (f.slotW > 46) s += `<text class="dc-val" x="${f.x(i).toFixed(1)}" y="${(y1 - 5).toFixed(1)}" text-anchor="middle">${esc((r.kind === "minus" ? "-" : r.kind === "plus" ? "+" : "") + formatValue(Math.abs(r.v), o.unit, true))}</text>`;
    });
    s += "</g></svg>";
    const kindWords = { start: "Start", plus: "Added", minus: "Taken away", total: "Total" };
    return titleLine(o.title) + `<div aria-hidden="true">${s}</div>` +
      `<p class="dc-legend" aria-hidden="true"><span><i style="background:${COL.total}"></i>Start and total</span><span><i style="background:${COL.plus}"></i>Adds</span><span><i style="background:${COL.minus}"></i>Takes away</span></p>` +
      srTable(o.title || "Chart", ["Step", "Kind", unitWords(o.unit) || "Value"], bars.map((r) => [r.label, kindWords[r.kind] || "", formatValue(r.kind === "minus" ? -Math.abs(r.v) : r.v, o.unit)]));
  });
}

// how far the result moves when each input goes to its low and its high, widest first
export function tornado(el, o = {}) {
  const base = Number(o.base);
  const rows = (o.rows || []).filter((r) => isNum(r.low) || isNum(r.high)).map((r) => ({ label: r.label, low: isNum(r.low) ? Number(r.low) : base, high: isNum(r.high) ? Number(r.high) : base }))
    .sort((a, b) => Math.abs(b.high - b.low) - Math.abs(a.high - a.low));
  if (!rows.length || !isNum(o.base)) { empty(el, o.title); return { redraw() {}, destroy() {} }; }
  const lo = Math.min(base, ...rows.map((r) => Math.min(r.low, r.high))), hi = Math.max(base, ...rows.map((r) => Math.max(r.low, r.high)));
  return mount(el, (W) => {
    const bar = 22, gap = 12, top = 24, labelW = Math.min(Math.max(90, W * 0.3), 240), chars = Math.floor(labelW / 7.2);
    const H = top + rows.length * (bar + gap) + 26, pad = (hi - lo) * 0.06 || 1, t = ticks(lo - pad, hi + pad, W < 500 ? 3 : 5);
    const left = labelW + 10, right = W - 14, x = (v) => left + (v - t.lo) / (t.hi - t.lo) * (right - left);
    let s = svgOpen(W, H, o.title);
    t.list.forEach((v) => { const xx = x(v).toFixed(1); s += `<line class="dc-grid" x1="${xx}" x2="${xx}" y1="${top}" y2="${H - 22}"/><text class="dc-xlab" x="${xx}" y="${H - 6}" text-anchor="middle">${esc(formatValue(v, o.unit, true))}</text>`; });
    s += '<g class="calm-data">';
    rows.forEach((r, i) => {
      const y = top + i * (bar + gap);
      s += `<text class="dc-lab" x="${labelW}" y="${y + bar / 2 + 4}" text-anchor="end">${esc(clip(r.label, chars))}<title>${esc(r.label)}</title></text>`;
      [["low", r.low, "#b5562f"], ["high", r.high, "#2f7f73"]].forEach(([w, v, c]) => {
        const a = x(Math.min(base, v)), b = x(Math.max(base, v));
        s += `<rect x="${a.toFixed(1)}" y="${y}" width="${Math.max(1, b - a).toFixed(1)}" height="${bar}" fill="${c}"><title>${esc(r.label)}, ${w} case: ${esc(formatValue(v, o.unit))}</title></rect>`;
      });
    });
    const bx = x(base).toFixed(1);
    s += `</g><line class="dc-base" x1="${bx}" x2="${bx}" y1="${top - 8}" y2="${H - 22}"/><text class="dc-unit" x="${bx}" y="12" text-anchor="middle">Base ${esc(formatValue(base, o.unit))}</text></svg>`;
    return titleLine(o.title) + `<div aria-hidden="true">${s}</div>` +
      `<p class="dc-legend" aria-hidden="true"><span><i style="background:#b5562f"></i>Input at its low end</span><span><i style="background:#2f7f73"></i>Input at its high end</span></p>` +
      srTable(o.title || "Chart", ["Input", "Low case", "High case"], rows.map((r) => [r.label, formatValue(r.low, o.unit), formatValue(r.high, o.unit)]));
  });
}

export function donut(el, o = {}) {
  const items = (o.labels || []).map((l, i) => [l, Number((o.values || [])[i])]).filter((r) => isNum(r[1]) && r[1] > 0);
  if (!items.length) { empty(el, o.title); return { redraw() {}, destroy() {} }; }
  const total = items.reduce((t, r) => t + r[1], 0);
  return mount(el, (W) => {
    const size = Math.min(240, Math.max(160, W * 0.42)), R = size / 2 - 4, r0 = R * 0.6, c = size / 2;
    let s = svgOpen(size, size, o.title) + '<g class="calm-data">', ang = -Math.PI / 2;
    items.forEach((it, i) => {
      const share = it[1] / total, a1 = ang + share * Math.PI * 2 - (items.length > 1 ? 0.004 : 0);
      const big = share > 0.5 ? 1 : 0, p = (a, rr) => [(c + rr * Math.cos(a)).toFixed(2), (c + rr * Math.sin(a)).toFixed(2)];
      const d = share >= 0.9999 ? `M${c} ${c - R}A${R} ${R} 0 1 1 ${c - 0.01} ${c - R}L${c - 0.01} ${c - r0}A${r0} ${r0} 0 1 0 ${c} ${c - r0}Z`
        : `M${p(ang, R)}A${R} ${R} 0 ${big} 1 ${p(a1, R)}L${p(a1, r0)}A${r0} ${r0} 0 ${big} 0 ${p(ang, r0)}Z`;
      s += `<path d="${d}" fill="${colourAt(i)}"><title>${esc(it[0])}: ${esc(formatValue(it[1], o.unit))} (${n0(share * 100, 1)}%)</title></path>`;
      ang += share * Math.PI * 2;
    });
    s += `</g><text class="dc-donut-total" x="${c}" y="${c - 2}" text-anchor="middle">${esc(formatValue(total, o.unit, true))}</text><text class="dc-unit" x="${c}" y="${c + 16}" text-anchor="middle">in all</text></svg>`;
    const list = `<ul class="dc-donut-list" aria-hidden="true">${items.map((it, i) => `<li><i style="background:${colourAt(i)}"></i><span>${esc(it[0])}</span><b>${esc(formatValue(it[1], o.unit))}</b><small>${n0(it[1] / total * 100, 1)}%</small></li>`).join("")}</ul>`;
    return titleLine(o.title) + `<div class="dc-donut" aria-hidden="false"><div aria-hidden="true">${s}</div>${list}</div>` +
      srTable(o.title || "Chart", ["", unitWords(o.unit) || "Value", "Share"], items.map((it) => [it[0], formatValue(it[1], o.unit), n0(it[1] / total * 100, 1) + "%"]));
  });
}

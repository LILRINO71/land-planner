// Small pure helpers of the Plan page: keeping the mix's acres adding up to the parcel, and reading or writing a
// cost sheet as CSV. No page, no network: they run the same in a browser and in node.

const tenth = (v) => Math.round(v * 10) / 10;

// acres: {use: acres}. One use is set to `value`; the others shrink or grow in proportion to what they have, so
// the total stays `total`. When no other use has any acres, the difference goes to `fallback` (parks, unless that
// is the use being changed, then the first other use in `order`). Nothing goes below zero; all to 0.1 acre.
export function balance(acres, use, value, total, order = Object.keys(acres), fallback = "park") {
  const out = {};
  order.forEach((u) => { out[u] = Math.max(0, Number(acres[u]) || 0); });
  const v = Math.max(0, Math.min(total, Number(value) || 0));
  out[use] = tenth(v);
  const others = order.filter((u) => u !== use);
  const room = total - out[use];
  const now = others.reduce((t, u) => t + out[u], 0);
  if (now > 1e-9) {
    others.forEach((u) => { out[u] = tenth(out[u] * room / now); });
  } else if (room > 0) {
    const to = fallback !== use && order.includes(fallback) ? fallback : others[0];
    others.forEach((u) => { out[u] = 0; });
    if (to !== undefined) out[to] = tenth(room);
  }
  // rounding can leave a tenth over or under: the largest other use takes it
  const gap = tenth(total - order.reduce((t, u) => t + out[u], 0));
  if (Math.abs(gap) >= 0.05 && others.length) {
    const big = others.reduce((a, b) => (out[b] > out[a] ? b : a), others[0]);
    out[big] = tenth(Math.max(0, out[big] + gap));
  }
  return out;
}

// ---------------------------------------------------------------- CSV

// One CSV line into cells, with "quoted, cells" and "" inside quotes.
export function csvCells(line) {
  const cells = [];
  let cell = "", quoted = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (quoted) {
      if (ch === '"' && line[i + 1] === '"') { cell += '"'; i++; }
      else if (ch === '"') quoted = false;
      else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === "," || ch === ";" || ch === "\t") { cells.push(cell); cell = ""; }
    else cell += ch;
  }
  cells.push(cell);
  return cells.map((c) => c.trim());
}

// "$1,234.50", "1234", "15%", "(500)" as numbers; anything else is null.
export function money(text) {
  let s = String(text == null ? "" : text).trim();
  if (!s) return null;
  let negative = false;
  if (/^\(.*\)$/.test(s)) { negative = true; s = s.slice(1, -1); }
  s = s.replace(/\s+/g, "").replace(/^(-?)\$/, "$1").replace(/^\$(-)/, "$1").replace(/%$/, "").replace(/,/g, "");
  if (s.startsWith("-")) { negative = !negative; s = s.slice(1); }
  if (!/^\d*\.?\d+$/.test(s) && !/^\d+\.$/.test(s)) return null;
  const n = Number(s);
  return Number.isFinite(n) ? (negative ? -n : n) : null;
}

// One row's name and amount. Commas inside a name or a number that was not quoted split it into more cells:
// the amount is the first cell after the name that reads as a number, joined with the 3-digit groups after it.
function nameAndAmount(cells) {
  for (let k = 1; k < cells.length; k++) {
    let text = cells[k];
    if (money(text) === null) continue;
    let j = k + 1;
    while (j < cells.length && /^\d{3}(\.\d+)?%?$/.test(cells[j]) && /^\(?-?\$?\s*\d{1,3}$/.test(text.replace(/,\d{3}/g, ""))) {
      text += "," + cells[j]; j++;
    }
    return { name: cells.slice(0, k).join(", ").trim(), amount: money(text) };
  }
  return { name: cells.join(", ").trim(), amount: null };
}

// Reads a cost sheet. Rows are "name, amount". A name that is exactly a figure's id or label (any case) sets that
// figure; every other row is a cost line of its own. A first row without a number is taken as the header.
// Returns {figures: [{id, label, value, row}], extra: [{name, amount, row}], skipped: [{row, text, why}], rows}.
export function readCostSheet(text, figures = []) {
  const byName = new Map();
  figures.forEach((f) => { byName.set(String(f.id).toLowerCase(), f); byName.set(String(f.label).toLowerCase(), f); });
  const out = { figures: [], extra: [], skipped: [], rows: 0, header: false };
  const lines = String(text || "").replace(/^﻿/, "").split(/\r\n|\n|\r/);
  let first = true;
  lines.forEach((line, i) => {
    const row = i + 1;
    if (!line.trim()) return;
    const cells = csvCells(line);
    if (cells.every((c) => !c)) return;
    out.rows++;
    const { name, amount } = nameAndAmount(cells);
    if (first) {
      first = false;
      if (amount === null) { out.header = true; out.rows--; return; }
    }
    if (amount === null) { out.skipped.push({ row, text: line.trim().slice(0, 80), why: "no amount that reads as a number" }); return; }
    if (!name) { out.skipped.push({ row, text: line.trim().slice(0, 80), why: "no name before the amount" }); return; }
    const f = byName.get(name.toLowerCase());
    if (f) {
      if (amount < 0) { out.skipped.push({ row, text: line.trim().slice(0, 80), why: `${f.label} cannot be below zero` }); return; }
      const seen = out.figures.findIndex((x) => x.id === f.id);
      const item = { id: f.id, label: f.label, value: amount, row };
      if (seen >= 0) out.figures[seen] = item; else out.figures.push(item);
    } else {
      out.extra.push({ name: name.slice(0, 80), amount, row });
    }
  });
  return out;
}

// Adds the rows read to a plan's settings. Extra lines with the same name as one already there replace its amount.
export function applyCostSheet(settings, read) {
  const s = JSON.parse(JSON.stringify(settings));
  s.assumptions = s.assumptions || {};
  s.extra_costs = s.extra_costs || [];
  read.figures.forEach((f) => { s.assumptions[f.id] = f.value; });
  read.extra.forEach((x) => {
    const at = s.extra_costs.findIndex((e) => String(e.name).toLowerCase() === x.name.toLowerCase());
    if (at >= 0) s.extra_costs[at].amount = x.amount; else s.extra_costs.push({ name: x.name, amount: x.amount });
  });
  return s;
}

export function csvCell(v) {
  const s = String(v == null ? "" : v);
  return /[",;\t\r\n]/.test(s) || s !== s.trim() ? '"' + s.replace(/"/g, '""') + '"' : s;
}

// The cost sheet as CSV: name, amount, then words that say what the amount is (ignored when read back).
// figures: the plan's figures (for the allowance and fees); costs: the plan's costs.
export function costSheet(costs, figures) {
  const fig = (id) => figures.find((f) => f.id === id);
  const rows = [["name", "amount", "unit", "what it is"]];
  costs.lines.forEach((l) => rows.push([l.label, l.unit_cost, l.unit, `times ${l.quantity} ${l.quantity_unit} (${l.quantity_from})`]));
  ["contingency_pct", "fees_total"].forEach((id) => { const f = fig(id); if (f) rows.push([f.label, f.value, f.unit, f.basis]); });
  (costs.extra || []).forEach((x) => rows.push([x.name, x.amount, "$", "a cost line you added"]));
  return rows.map((r) => r.map(csvCell).join(",")).join("\r\n") + "\r\n";
}

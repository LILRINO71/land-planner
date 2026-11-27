// Shared pieces of the district workspace: numbers in their units, column names, sortable folded tables, the side
// panel and small dialogs. Nothing here knows about a particular project.
import { esc, has } from "../util.js";
import { formatValue } from "./charts.js";

export { esc, has };
export const isNum = (v) => v !== null && v !== undefined && v !== "" && isFinite(Number(v));
export const n0 = (v, d = 0) => Number(v).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: 0 });
export const nFix = (v, d) => Number(v).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });
export const NOT_GIVEN = "not given";

// ---------------------------------------------------------------- a register figure as words

const UNIT_SHORT = { sf: "SF", acres: "acres", units: "units", keys: "keys", people: "people", households: "households", jobs: "jobs",
  years: "years", months: "months", miles: "miles", sf_per_yr: "SF/yr", units_per_yr: "units/yr" };
function moneyParts(v, unit) {
  const per = { usd_per_yr: "/yr", usd_per_sf_yr: "/SF/yr", usd_per_sf_mo: "/SF/mo", usd_per_sf: "/SF", usd_per_acre: "/acre",
    usd_per_unit: "/unit", usd_per_unit_mo: "/unit/mo", usd_per_night: "/night" }[unit] || "";
  return per;
}
// plain value in its unit: 180,000 SF; $36.00/SF/yr; 18%
export function valueIn(v, unit) {
  if (!isNum(v)) return NOT_GIVEN;
  v = Number(v);
  if (unit && unit.startsWith("usd")) {
    const d = /per_sf/.test(unit) ? 2 : 0;
    return (v < 0 ? "-$" : "$") + nFix(Math.abs(v), d) + moneyParts(v, unit);
  }
  if (unit === "pct") return n0(v, 2) + "%";
  if (unit === "ratio") return n0(v, 2) + "x";
  if (unit === "acres") return n0(v, 2) + " acres";
  if (unit === "text" || !unit || unit === "count") return n0(v, 2);
  return n0(v, 2) + (UNIT_SHORT[unit] ? " " + UNIT_SHORT[unit] : " " + unit);
}
// the other way of saying a rent: per year shown with per month, and the other way round
export function rentAside(v, unit) {
  if (!isNum(v)) return "";
  if (unit === "usd_per_sf_yr") return "$" + nFix(Number(v) / 12, 2) + "/SF/mo";
  if (unit === "usd_per_sf_mo") return "$" + nFix(Number(v) * 12, 2) + "/SF/yr";
  return "";
}
function millions(v, unit) {
  const m = Number(v) / 1e6, d = Math.abs(m) >= 1000 ? 0 : Math.abs(m) >= 10 ? 1 : 2;
  return (m < 0 ? "-$" : "$") + nFix(Math.abs(m), d) + "M" + (unit === "usd_per_yr" ? "/yr" : moneyParts(v, unit));
}
// a figure (an assumption record) shown the way a card asks: { main, aside }
export function figureWords(fig, format, opts = {}) {
  const w = figureWordsRaw(fig, format);
  // on a card, large dollar amounts read as $12.6M/yr; the exact amount stays in the panel and on hover
  if (opts.compact && fig && isNum(fig.value) && Math.abs(Number(fig.value)) >= 1e6 && String(fig.unit || "").startsWith("usd") &&
      !/per_sf|per_acre|per_unit|per_night/.test(fig.unit) && ["", "usd", "usd_m", "int", "number"].includes(format || "")) {
    return { main: millions(fig.value, fig.unit), aside: w.aside, exact: valueIn(fig.value, fig.unit) };
  }
  return w;
}
function figureWordsRaw(fig, format) {
  if (!fig) return { main: NOT_GIVEN, aside: "" };
  const unit = fig.unit, f = format || "";
  const range = () => {
    if (isNum(fig.value_low) && isNum(fig.value_high)) {
      const u = unit && unit.startsWith("usd") ? unit : unit;
      const lo = valueIn(fig.value_low, u), hi = valueIn(fig.value_high, u);
      const unitTail = (s) => s.replace(/^[-$\d.,]+/, "");
      const tail = unitTail(hi);
      return lo.endsWith(tail) && tail ? lo.slice(0, lo.length - tail.length) + " to " + hi : lo + " to " + hi;
    }
    return null;
  };
  if (f === "text" || (!isNum(fig.value) && !range() && has(fig.value_text))) return { main: fig.value_text || NOT_GIVEN, aside: "" };
  if (f === "range" || (!isNum(fig.value) && range())) {
    const r = range();
    if (r) return { main: r, aside: has(fig.value_text) ? fig.value_text : "" };
    return { main: fig.value_text || valueIn(fig.value, unit), aside: "" };
  }
  const v = fig.value;
  if (!isNum(v)) return { main: fig.value_text || NOT_GIVEN, aside: "" };
  switch (f) {
    case "sf": return { main: n0(v) + " SF", aside: "" };
    case "acres": return { main: n0(v, 2) + " acres", aside: "" };
    case "units": return { main: n0(v) + " units", aside: "" };
    case "keys": return { main: n0(v) + " keys", aside: "" };
    case "usd": return { main: valueIn(v, unit && unit.startsWith("usd") ? unit : "usd"), aside: "" };
    case "usd_m": return { main: millions(v, unit), aside: "" };
    case "usd_per_sf_yr": return { main: "$" + nFix(v, 2) + "/SF/yr", aside: "$" + nFix(v / 12, 2) + "/SF/mo" };
    case "usd_per_sf_mo": return { main: "$" + nFix(v, 2) + "/SF/mo", aside: "$" + nFix(v * 12, 2) + "/SF/yr" };
    case "pct": return { main: n0(v, 2) + "%", aside: "" };
    case "int": return { main: n0(v), aside: unit && UNIT_SHORT[unit] ? UNIT_SHORT[unit] : "" };
    case "number": return { main: n0(v, 2), aside: "" };
    default: return { main: valueIn(v, unit), aside: rentAside(v, unit) };
  }
}
// a number ready for counting up: the leading number in the words and how to rewrite it
export function countable(words) {
  const m = /^(-?\$?)([\d,]+(?:\.\d+)?)(.*)$/.exec(words);
  if (!m || /\sto\s/.test(words)) return null;
  const value = Number(m[2].replace(/,/g, "")), d = (m[2].split(".")[1] || "").length;
  return { value, format: (x) => m[1] + nFix(x, d) + m[3] };
}

// ---------------------------------------------------------------- columns of the entities

export const FIELD_WORDS = {
  id: "Id", label: "Name", use: "Use", phase: "Phase", scenario: "Case", sf: "Area (SF)", units: "Units", keys: "Keys",
  acres: "Acres", net_acres: "Net acres", base_rent_usd_sf_yr: "Base rent ($/SF/yr)", status: "Status", assumption: "Register id",
  metric: "Measure", geography: "Area", year: "Year", value: "Value", unit: "Unit", segment: "Segment", source_id: "Source",
  name: "Name", type: "Type", rent: "Rent", rent_unit: "Rent per", occupancy_pct: "Occupancy (%)", absorption: "Absorption",
  absorption_unit: "Absorption per", sales_usd_sf: "Sales ($/SF)", adr: "ADR ($/night)", revpar: "RevPAR ($/night)",
  market_flag: "Market", relocation_candidate: "May relocate", apn: "APN", hold_sell: "Plan", buyer_type: "Buyer",
  timing: "Timing", price_floor: "Price floor ($)", target_price: "Asking price ($)", rlv: "Residual land value ($)",
  rlv_per_acre: "Residual land value ($/acre)", funding_target: "Funding target", provenance: "Provenance", item: "Item",
  category: "Category", quantity: "Quantity", quantity_unit: "Per", cost_usd: "Cost ($)", title: "Title", likelihood: "Likelihood",
  impact: "Impact", mitigation: "What is done", owner: "Owner", kind: "Kind", address: "Address", date: "Date",
  price_usd: "Price ($)", size: "Size", size_unit: "Size in", provider: "Provider", cadence: "How often",
  source_document: "Document", section: "Section", text: "Requirement", where_in_app: "Where in the app", note: "Note",
  task: "Task", version: "Version", upload_date: "Arrived", accepted: "Accepted", start_year: "Starts", end_year: "Ends",
  value_low: "Low", value_high: "High", value_text: "In words", source_doc: "Source document", source_model: "Source model",
  as_of: "As of", confidence: "Confidence", conflict: "Conflict", typology: "Building form", use_group: "Group",
};
const MONEY_FIELDS = new Set(["price_floor", "target_price", "rlv", "cost_usd", "price_usd"]);
const RATE_FIELDS = { base_rent_usd_sf_yr: "usd_per_sf_yr", rlv_per_acre: "usd_per_acre", sales_usd_sf: "usd_per_sf", adr: "usd_per_night", revpar: "usd_per_night" };
export const planWords = (v) => ({ hold: "Hold", sell: "Sell", jv: "Joint venture", "ground lease": "Ground lease", undecided: "Undecided" }[v] || String(v));
export const fieldWords = (f) => FIELD_WORDS[f] || String(f).replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
export function isNumericField(f) {
  return ["sf", "units", "keys", "acres", "net_acres", "year", "value", "rent", "occupancy_pct", "absorption", "quantity", "size",
    "start_year", "end_year", "value_low", "value_high", "order"].includes(f) || MONEY_FIELDS.has(f) || f in RATE_FIELDS;
}
// a cell of an entity's row: { html, sort, num }
export function cell(entity, field, row, lookups) {
  const v = row[field];
  if (v === undefined || v === null || v === "") return { html: '<span class="muted">-</span>', sort: null, num: isNumericField(field) };
  if (typeof v === "boolean") return { html: v ? "Yes" : "No", sort: v ? 1 : 0, num: false };
  if (field === "use" && lookups.uses[v]) return { html: esc(lookups.uses[v]), sort: lookups.uses[v], num: false };
  if (field === "phase" && lookups.phases[v]) return { html: esc(lookups.phases[v]), sort: lookups.phasesOrder[v] ?? v, num: false };
  if (field === "hold_sell") return { html: esc(planWords(v)), sort: planWords(v), num: false };
  if (field === "where_in_app" && /^#\/districts\//.test(String(v))) return { html: `<a href="${esc(v)}">Open</a>`, sort: v, num: false };
  if (field === "value" && entity === "market_metrics" && row.unit) return { html: esc(valueIn(v, row.unit)), sort: Number(v), num: true };
  if (field === "rent" && row.rent_unit) {
    const aside = rentAside(v, row.rent_unit);
    return { html: esc(valueIn(v, row.rent_unit)) + (aside ? `<small>${esc(aside)}</small>` : ""), sort: Number(v), num: true };
  }
  if (isNum(v) && field in RATE_FIELDS) {
    const aside = rentAside(v, RATE_FIELDS[field]);
    return { html: esc(valueIn(v, RATE_FIELDS[field])) + (aside ? `<small>${esc(aside)}</small>` : ""), sort: Number(v), num: true };
  }
  if (isNum(v) && MONEY_FIELDS.has(field)) return { html: esc(valueIn(v, "usd")), sort: Number(v), num: true };
  if (isNum(v) && field === "year") return { html: esc(String(v)), sort: Number(v), num: true };
  if (typeof v === "number") return { html: esc(n0(v, 2)), sort: v, num: true };
  if (Array.isArray(v)) return { html: esc(v.join(", ")), sort: v.join(", "), num: false };
  if (typeof v === "object") return { html: esc(JSON.stringify(v)), sort: "", num: false };
  return { html: esc(v), sort: String(v), num: false };
}
export function lookupsOf(content) {
  const e = (content && content.entities) || {};
  const uses = {}, phases = {}, phasesOrder = {};
  (e.uses || []).forEach((u) => { uses[u.id] = u.label || u.category || u.id; });
  (e.phases || []).forEach((p) => { phases[p.id] = p.label || p.id; phasesOrder[p.id] = p.order ?? 0; });
  const assumptions = {};
  (e.assumptions || []).forEach((a) => { assumptions[a.id] = a; });
  return { uses, phases, phasesOrder, assumptions };
}

// ---------------------------------------------------------------- a sortable table that folds after a few rows

let tableSeq = 0;
// columns: [{label, num}], rows: [[{html, sort}]], caption. Returns html; call wireTables(root) once for the page.
export function tableHtml({ columns, rows, caption, foldAfter = 8, cls = "" }) {
  const id = "dt" + (++tableSeq), long = rows.length > foldAfter + 2;
  const head = columns.map((c, i) => `<th scope="col"${c.num ? ' class="num"' : ""} aria-sort="none"><button type="button" class="sort" data-sort="${i}">${esc(c.label)}<i aria-hidden="true"></i></button></th>`).join("");
  const body = rows.map((r, k) => `<tr${long && k >= foldAfter ? ' class="dt-more"' : ""}>${r.map((c, i) => `<td${columns[i] && columns[i].num ? ' class="num"' : ""} data-sort="${esc(c.sort === null || c.sort === undefined ? "" : c.sort)}">${c.html}</td>`).join("")}</tr>`).join("");
  return `<div class="dt${long ? " dt-folded" : ""} ${cls}" id="${id}" data-fold-after="${foldAfter}"><div class="scroll"><table class="data">${caption ? `<caption class="dc-sr-cap">${esc(caption)}</caption>` : ""}<thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>` +
    (long ? `<button type="button" class="btn small dt-toggle" aria-expanded="false" aria-controls="${id}">Show all ${rows.length} rows</button>` : "") + "</div>";
}
export function wireTables(root) {
  root.addEventListener("click", (e) => {
    const t = e.target.closest && e.target.closest(".dt-toggle");
    if (t && root.contains(t)) {
      const box = t.closest(".dt"), open = box.classList.toggle("dt-folded") === false;
      t.setAttribute("aria-expanded", String(open));
      t.textContent = open ? "Show fewer rows" : `Show all ${box.querySelectorAll("tbody tr").length} rows`;
      return;
    }
    const b = e.target.closest && e.target.closest("button.sort[data-sort]");
    if (!b || !root.contains(b) || !b.closest(".dt")) return;
    const th = b.closest("th"), table = b.closest("table"), i = Number(b.dataset.sort);
    const dir = th.getAttribute("aria-sort") === "ascending" ? "descending" : "ascending";
    table.querySelectorAll("thead th").forEach((x) => { x.setAttribute("aria-sort", "none"); const s = x.querySelector(".sort"); if (s) { s.classList.remove("on"); s.querySelector("i").textContent = ""; } });
    th.setAttribute("aria-sort", dir); b.classList.add("on"); b.querySelector("i").textContent = dir === "ascending" ? "▲" : "▼";
    const tbody = table.tBodies[0], rows = [...tbody.rows], numeric = th.classList.contains("num");
    const val = (r) => { const s = r.cells[i] ? r.cells[i].dataset.sort : ""; return numeric ? (s === "" ? -Infinity : Number(s)) : s.toLowerCase(); };
    rows.sort((a, c) => { const x = val(a), y = val(c); const r = x < y ? -1 : x > y ? 1 : 0; return dir === "ascending" ? r : -r; });
    const after = Number(b.closest(".dt").dataset.foldAfter) || 8, folded = b.closest(".dt").querySelector(".dt-toggle");
    rows.forEach((r, k) => { r.classList.toggle("dt-more", !!folded && k >= after); tbody.appendChild(r); });
  });
}

// ---------------------------------------------------------------- the side panel and dialogs

let openPanel = null;
// a panel sliding in from the right; returns { body, close }. Escape and the close button close it; focus goes back.
export function panel(title, { wide = false, onClose } = {}) {
  if (openPanel) openPanel.close();
  const back = document.activeElement;
  const shade = document.createElement("div");
  shade.className = "dp-shade";
  shade.innerHTML = `<aside class="dp${wide ? " wide" : ""}" role="dialog" aria-modal="true" aria-labelledby="dp-title">
    <header class="dp-head"><h2 id="dp-title" tabindex="-1">${esc(title)}</h2><button type="button" class="btn small dp-close" aria-label="Close">Close</button></header>
    <div class="dp-body"></div></aside>`;
  document.body.appendChild(shade);
  const aside = shade.firstElementChild;
  const close = () => {
    if (!shade.isConnected) return;
    shade.remove(); document.removeEventListener("keydown", key, true); openPanel = null;
    if (onClose) onClose();
    if (back && back.isConnected) back.focus({ preventScroll: true });
  };
  const key = (e) => {
    if (e.key === "Escape") { e.preventDefault(); close(); return; }
    if (e.key === "Tab") {
      const f = [...aside.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select,textarea,[tabindex="0"]')].filter((n) => n.offsetParent !== null);
      if (!f.length) return;
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
    }
  };
  document.addEventListener("keydown", key, true);
  shade.addEventListener("mousedown", (e) => { if (e.target === shade) close(); });
  aside.querySelector(".dp-close").addEventListener("click", close);
  setTimeout(() => aside.querySelector("#dp-title").focus(), 0);
  openPanel = { close, body: aside.querySelector(".dp-body"), aside };
  return openPanel;
}
export function closePanel() { if (openPanel) openPanel.close(); }

// a status line under a form: say(el, "Saved.", "ok")
export function say(el, text, kind = "") {
  if (!el) return;
  el.className = "dz-status" + (kind ? " " + kind : "");
  el.textContent = text;
}
export const chip = (text, cls = "") => `<span class="dz-chip${cls ? " " + cls : ""}">${esc(text)}</span>`;
export const sourceTags = (tags) => (tags || []).filter(Boolean).map((t) => `<span class="dz-src" title="${esc(t)}">${esc(t)}</span>`).join("");
export function when(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return String(iso);
  return d.toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
}
export function day(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ""));
  if (!m) return iso ? String(iso) : "";
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}
// the first sentence of a text, and the rest
export function leadOf(text) {
  const s = String(text || "").trim();
  const m = /^(.+?[.!?])(\s+)(?=[A-Z0-9"“(\[])/.exec(s);
  return m ? { lead: m[1], rest: s.slice(m[0].length) } : { lead: s, rest: "" };
}
export { formatValue };

// Shared pieces of the eight district tools (web/js/district/tools/*.js): asking the compute routes, numbers in
// their units, "where this number comes from" for computed figures, the calm "what the package does not give yet"
// list, the city view's one sentence about what it leaves out, and the page frame (the answer first, then one part
// at a time). Nothing here knows about a particular project.
import { esc, isNum, n0, nFix, valueIn, panel, fieldWords, wireTables } from "../ui.js";
import { openFigure } from "../figure.js";
import { chapters, fold, watchFolds, watchMotion, printEverything, countUp, motionOn } from "../../calm.js";

export { esc, isNum, n0, nFix, valueIn, fold, motionOn };
export const NK = "not known";

// ---------------------------------------------------------------- numbers

export function usd(v) { return isNum(v) ? (Number(v) < 0 ? "-$" : "$") + n0(Math.abs(Number(v)), 0) : NK; }
// $12.6M, $1.24B, $450,000
export function usdM(v) {
  if (!isNum(v)) return NK;
  const x = Number(v), a = Math.abs(x), s = x < 0 ? "-$" : "$";
  if (a >= 1e9) return s + nFix(a / 1e9, 2) + "B";
  if (a >= 1e6) return s + nFix(a / 1e6, a >= 1e8 ? 0 : 1) + "M";
  return s + n0(a, 0);
}
export const usdSf = (v) => (isNum(v) ? (Number(v) < 0 ? "-$" : "$") + nFix(Math.abs(Number(v)), 2) + "/SF" : NK);
export const pct = (v, d = 1) => (isNum(v) ? nFix(Number(v), d) + "%" : NK);
export const acres = (v) => { if (!isNum(v)) return NK; const t = nFix(Number(v), Number(v) >= 100 ? 0 : 1); return t + (Number(t) === 1 ? " acre" : " acres"); };
// the noun that goes with a count: noun(1, "parcel") = "parcel", noun(2, "parcel") = "parcels"; plural() keeps the count
export const noun = (n, one, many = one + "s") => (Number(n) === 1 ? one : many);
export const plural = (n, one, many) => `${n} ${noun(n, one, many)}`;
export const int = (v) => (isNum(v) ? n0(Number(v), 0) : NK);
export const ratio = (v) => (isNum(v) ? nFix(Number(v), 2) + "x" : NK);
export const sum = (list) => list.reduce((t, v) => t + (isNum(v) ? Number(v) : 0), 0);
export const SF_PER_ACRE = 43560;

// ---------------------------------------------------------------- the compute routes

// GET (no body) or POST (a what-if: {assumptions, records, options}); the answer is already filtered for the audience
export function compute(ctx, tool, { body = null, options = null } = {}) {
  const path = `/projects/${encodeURIComponent(ctx.project.id)}/compute/${tool}`;
  const params = { dataset: ctx.dataset, version: ctx.version, audience: ctx.viewAs || "" };
  if (!body) return ctx.api.get(path, { ...params, ...(options || {}) });
  const b = { dataset: ctx.dataset, version: ctx.version, ...body };
  if (ctx.viewAs) b.audience = ctx.viewAs;
  return ctx.api.post(path, b);
}

export const entities = (ctx) => (ctx.content && ctx.content.entities) || {};
export function rowOf(ctx, entity, id) { return (entities(ctx)[entity] || []).find((r) => String(r.id) === String(id)) || null; }
export function figureOf(ctx, id) { return rowOf(ctx, "assumptions", id); }
export const useLabel = (ctx, id) => { const u = rowOf(ctx, "uses", id) || rowOf(ctx, "land_uses", id); return u ? u.label || u.category || id : id; };
export const phaseLabel = (ctx, id) => { const p = rowOf(ctx, "phases", id); return p ? p.label || id : id === "full" ? "Full buildout" : "Phase " + id; };
export const parcelLabel = (ctx, id) => { const p = rowOf(ctx, "parcels", id); return p ? p.label || p.apn || id : id; };
// a sale piece by its id: a block's name, else a parcel's label
export const pieceLabel = (ctx, id) => { const b = rowOf(ctx, "blocks", id); return b ? b.name || id : parcelLabel(ctx, id); };

// ---------------------------------------------------------------- what the package does not give yet

const TOKENS = [[/\bland_uses rows\b/g, "finance library rows"], [/\bland_uses row\b/g, "finance library row"], [/\bland_uses\b/g, "finance library"],
  [/\bcost_items\b/g, "cost items"], [/\bland_value_usd\b/g, "land value"], [/\bstrategy_inputs\b/g, "strategy inputs"],
  [/\bprogram_lines\b/g, "program lines"], [/\bcapital_targets\b/g, "capital targets"], [/\bdue_period\b/g, "due year"],
  [/\bunits_absorbed\b/g, "homes sold and occupied"], [/\bpre_leasing_pct\b/g, "pre-leasing"], [/\s+[—–]\s+/g, ": "]];
export function plain(s) { let t = String(s || ""); TOKENS.forEach(([re, w]) => { t = t.replace(re, w); }); return t; }

// the tool's `missing` sentences grouped so a long list reads as a few calm lines
export function groupMissing(list) {
  const plainLines = [], starting = [], noFig = [], noLib = [], byParcel = new Map(), noScore = [], byId = new Map();
  (list || []).forEach((line) => {
    const s = String(line);
    let m;
    if ((m = /^(.+?): no figure in the register \(assumption id ([^)]+)\); the engine's starting figure (.+?) was used\.?$/.exec(s))) starting.push({ label: m[1], id: m[2], value: m[3] });
    else if ((m = /^(.+?): no figure in the register \(assumption id ([^)]+)\)\.?$/.exec(s))) noFig.push({ label: m[1], id: m[2] });
    else if ((m = /^(.+?) \(([^)]+)\) has no land_uses row, so it is left out\.?$/.exec(s))) noLib.push({ label: m[1], id: m[2] });
    else if ((m = /^(?:Parcel|Block) (\S+) has no (.+)$/.exec(s))) { const k = m[2]; if (!byParcel.has(k)) byParcel.set(k, []); byParcel.get(k).push(m[1]); }
    else if ((m = /^([a-z0-9][\w.-]*[-_][\w.-]*): (.+)$/.exec(s))) { const k = m[2]; if (!byId.has(k)) byId.set(k, []); byId.get(k).push(m[1]); }
    else plainLines.push(s);
  });
  return { plainLines, starting, noFig, noLib, byParcel, noScore, byId };
}
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
export function missingHtml(resp, { title = "What the package does not give yet", open = null, intro = "", labelOf = (id) => id } = {}) {
  const g = groupMissing(resp && resp.missing);
  const items = [];
  g.plainLines.forEach((s) => items.push(`<li>${esc(plain(s))}</li>`));
  if (g.noLib.length) items.push(`<li>${g.noLib.length === 1 ? `${esc(g.noLib[0].label)} has no finance library row, so it is left out.` : `${g.noLib.length} uses have no finance library row (density, revenue, cap rate and required return), so they are left out.`}
    ${g.noLib.length > 1 ? fold("miss-lib", "Show which uses", `<ul class="tl-mini">${g.noLib.map((x) => `<li>${esc(x.label)} <code>${esc(x.id)}</code></li>`).join("")}</ul>`, open) : ""}</li>`);
  g.byId.forEach((ids, rest) => {
    const r = plain(rest).replace(/\.$/, "");
    const many = ids.length > 1;
    const inc = /^an income use needs (.+)$/.exec(r);
    items.push(`<li>${many ? (inc ? `${ids.length} income uses need ${esc(inc[1])}.` : /^no /.test(r) ? `${ids.length} uses have ${esc(r)}.` : `${ids.length} uses: ${esc(r)}.`) : `${esc(labelOf(ids[0]))}: ${esc(r)}.`}
      ${many ? fold("miss-id-" + rest.slice(0, 24), "Show which uses", `<ul class="tl-mini">${ids.map((x) => `<li>${esc(labelOf(x))} <code>${esc(x)}</code></li>`).join("")}</ul>`, open) : ""}</li>`);
  });
  g.byParcel.forEach((apns, rest) => {
    let r = plain(rest);
    if (apns.length > 1) r = r.replace(/\bits\b/g, "their").replace(/\bit is\b/g, "they are").replace(/\bit\b/g, "they");
    items.push(`<li>${apns.length === 1 ? `Parcel ${esc(apns[0])} has no ${esc(r)}` : `${apns.length} parcels have no ${esc(r)}`}
      ${apns.length > 1 ? fold("miss-p-" + rest.slice(0, 24), "Show which parcels", `<p class="tl-apns">${apns.map(esc).join(", ")}</p>`, open) : ""}</li>`);
  });
  if (g.noFig.length) items.push(`<li>${g.noFig.length === 1 ? `${esc(cap(g.noFig[0].label))} is not in the register (<code>${esc(g.noFig[0].id)}</code>), so the parts that need it are left out.` : `${g.noFig.length} figures are not in the register and have no starting figure, so the parts that need them are left out.`}
    ${g.noFig.length > 1 ? fold("miss-nofig", "Show which figures", `<ul class="tl-mini">${g.noFig.map((x) => `<li>${esc(cap(x.label))} <code>${esc(x.id)}</code></li>`).join("")}</ul>`, open) : ""}</li>`);
  if (g.starting.length) items.push(`<li>${g.starting.length === 1 ? `${esc(cap(g.starting[0].label))} is not in the register, so the engine used its starting figure (${esc(g.starting[0].value)}).` : `${g.starting.length} figures are not in the register, so the engine used its own starting figures for them.`}
    ${fold("miss-start", "Show the starting figures used", `<ul class="tl-mini">${g.starting.map((x) => `<li>${esc(cap(x.label))}: <b>${esc(x.value)}</b> <code>${esc(x.id)}</code></li>`).join("")}</ul>`, open)}</li>`);
  if (!items.length) return "";
  const n = (resp.missing || []).length;
  // the answer comes first: one line says how much is missing, the list waits behind a fold
  const key = "miss-all-" + title.toLowerCase().replace(/[^a-z]+/g, "-").slice(0, 30), hid = "tl-" + key;
  const list = `<ul class="tl-missing-list">${items.join("")}</ul>`;
  return `<section class="tl-missing" aria-labelledby="${hid}">
    <h2 id="${hid}">${esc(title)}</h2>
    <p class="tl-missing-intro">${intro ? esc(intro) : `The calculation runs on what the package holds. ${n === 1 ? "One input is" : n + " inputs are"} not there yet; nothing is guessed in their place.`}</p>
    ${items.length > 1 ? fold(key, "Show what is missing", list, open, "tl-missing-fold") : list}</section>`;
}

// ---------------------------------------------------------------- what an audience does not see

const PART_WORDS = { by_parcel: "residual value by parcel", pricing_tiers: "pricing", waterfall: "sale proceeds", capital_plan: "the capital plan",
  targets: "capital targets", break_even: "break-evens", tornado: "the sensitivity chart", decisions: "hold and sell decisions",
  conflicts: "critical-asset conflicts", retained_value: "retained land value", paced_releases: "paced land releases",
  retained_parcels: "the parcels kept", funding_gap: "the funding gap against land sales", returns: "returns" };
const AUD_WORDS = { city: "city", partner: "partner", consultant: "consultant", internal: "internal" };
export function hiddenWords(resp, extra = []) {
  const parts = [...extra, ...((resp && resp.hidden_parts) || [])].map((p) => PART_WORDS[p] || String(p).replace(/_/g, " "));
  const uniq = [...new Set(parts)];
  if (!uniq.length) return "";
  const list = uniq.length === 1 ? uniq[0] : uniq.slice(0, -1).join(", ") + " and " + uniq[uniq.length - 1];
  return `${cap(list)} ${uniq.length === 1 && !/^(returns|break-evens|capital targets|sale proceeds|hold and sell decisions|critical-asset conflicts|paced land releases|the parcels kept)$/.test(uniq[0]) ? "is" : "are"} not shown in the ${AUD_WORDS[resp.audience] || resp.audience} view.`;
}
export function hiddenHtml(resp, extra = []) {
  const w = hiddenWords(resp, extra);
  return w ? `<p class="tl-hidden" role="note">${esc(w)}</p>` : "";
}
export const isOutside = (resp) => resp && resp.audience && resp.audience !== "internal";

// ---------------------------------------------------------------- where a computed number comes from

// One registry per page: add(spec) gives a key; a button with data-src="<key>" opens the panel for it.
//   spec: { label, value, how: [sentences], inputs: [inputs_used entries], figure: assumption id, note, starting }
export function sources() {
  const map = new Map();
  let n = 0;
  return { add(spec) { const k = "s" + (++n); map.set(k, spec); return k; }, get: (k) => map.get(k) };
}
// a number that opens its source; text is what is shown
export function num(reg, text, spec, cls = "") {
  const k = reg.add(spec);
  return `<button type="button" class="tl-n${cls ? " " + cls : ""}" data-src="${k}" aria-label="${esc((spec.label ? spec.label + ": " : "") + text)}. Where this number comes from">${esc(text)}</button>`;
}

const PROV_HELP = { "ENGINE STARTING FIGURE": "the engine's own starting figure: the package does not give one", CALCULATED: "worked out from other figures",
  "REQUIRES VALIDATION": "needs checking before it is relied on" };
// an inputs_used entry in words: { label, value, prov, figure, starting }
export function inputWords(ctx, inp) {
  const prov = inp.provenance || "";
  const val = inp.unit ? valueIn(inp.value, inp.unit) : isNum(inp.value) ? n0(inp.value, 2) : String(inp.value ?? NK);
  if (inp.assumption_id) {
    const f = figureOf(ctx, inp.assumption_id);
    return { label: cap((f && f.label) || inp.label || inp.assumption_id), id: inp.assumption_id, value: val, prov, figure: f ? inp.assumption_id : "", starting: prov === "ENGINE STARTING FIGURE", whatIf: !!inp.what_if };
  }
  const [entity, id, field] = String(inp.field || "").split("/");
  const row = rowOf(ctx, entity, id);
  const who = row ? row.label || row.name || row.item || row.apn || id : id;
  return { label: `${who}: ${fieldWords(field || "").replace(/\bsf\b/gi, "SF")}`, id: inp.field, value: val, prov, figure: row && row.assumption && field !== "amount" ? "" : "", starting: false, whatIf: !!inp.what_if };
}
function inputLi(ctx, w, i) {
  return `<li class="tl-in${w.starting ? " start" : ""}">
    ${w.figure ? `<button type="button" class="link" data-fig="${esc(w.figure)}">${esc(w.label)}</button>` : `<span>${esc(w.label)}</span>`}
    <b>${esc(w.value)}</b>
    <small>${w.starting ? '<span class="dz-chip gold">Engine starting figure</span> ' : ""}${w.whatIf ? '<span class="dz-chip warn">What-if, not saved</span> ' : ""}${esc(w.prov && !w.starting ? w.prov : "")}${w.id && !String(w.id).includes("/") ? ` <code>${esc(w.id)}</code>` : ""}</small></li>`;
}
export function openSource(ctx, spec, resp) {
  if (spec.figure && figureOf(ctx, spec.figure) && !spec.how) { openFigure(ctx, spec.figure); return; }
  const p = panel("Where this number comes from");
  const inputs = (spec.inputs || []).map((x) => inputWords(ctx, x));
  const starting = spec.starting || (spec.figure && !figureOf(ctx, spec.figure));
  p.body.innerHTML = `<p class="dp-label">${esc(spec.label || "")}</p><p class="dp-value">${esc(spec.value || "")}</p>
    <p class="tl-kind">${starting ? '<span class="dz-chip gold">Engine starting figure</span> The package does not give this figure, so the engine used its own starting figure. It is not a fact about the project.'
      : spec.figure && figureOf(ctx, spec.figure) ? `From the register: <button type="button" class="link" data-fig="${esc(spec.figure)}">${esc(spec.figure)}</button>`
      : '<span class="dz-chip">Calculated</span> Worked out by the finance engine from the figures below.'}</p>
    ${spec.note ? `<p>${esc(spec.note)}</p>` : ""}
    ${(spec.how || []).length ? `<h3 class="dp-sub">How it is worked out</h3><ol class="tl-how">${spec.how.map((h) => `<li>${esc(plain(h))}</li>`).join("")}</ol>` : ""}
    ${inputs.length ? `<h3 class="dp-sub">Figures it uses (${inputs.length})</h3><ul class="tl-ins">${inputs.slice(0, 60).map((w, i) => inputLi(ctx, w, i)).join("")}</ul>${inputs.length > 60 ? `<p class="fine">And ${inputs.length - 60} more.</p>` : ""}` : ""}
    ${resp && resp.disclaimer ? `<p class="fine">${esc(resp.disclaimer)}</p>` : ""}`;
  p.body.addEventListener("click", (e) => { const f = e.target.closest("[data-fig]"); if (f) openFigure(ctx, f.dataset.fig); });
}
// the inputs of a response whose field or id starts with one of the prefixes
export function inputsFor(resp, ...prefixes) {
  return ((resp && resp.inputs_used) || []).filter((x) => prefixes.some((p) => (x.field || x.assumption_id || "").startsWith(p)));
}

// ---------------------------------------------------------------- the page frame

// el: the tool's box. Returns a page object: chart(kind, spec) -> html of a box; set(html) writes the page;
// paint() draws the charts now on screen; book (the chapters) after set().
export function page(el, ctx) {
  const reg = sources(), charts = [], mounted = [], openFolds = new Set(), stops = [];
  let book = null, counted = false, resp = null;
  const P = {
    reg, openFolds,
    set resp(r) { resp = r; }, get resp() { return resp; },
    chart(kind, spec, cls = "") { charts.push([kind, spec]); return `<div class="dz-chart-box tl-chart${cls ? " " + cls : ""}" data-tchart="${charts.length - 1}"></div>`; },
    paint() {
      el.querySelectorAll("[data-tchart]").forEach((box) => {
        if (box.dataset.drawn || box.offsetParent === null) return;
        const [kind, spec] = charts[Number(box.dataset.tchart)];
        box.dataset.drawn = "1";
        const fn = { bar: ctx.charts.barChart, stacked: ctx.charts.stackedBar, line: ctx.charts.lineChart, waterfall: ctx.charts.waterfall, tornado: ctx.charts.tornado, donut: ctx.charts.donut }[kind];
        try { mounted.push(fn(box, spec)); } catch (e) { console.error(e); box.innerHTML = '<p class="dc-chart-empty">This chart could not be drawn.</p>'; }
      });
      if (!counted) {
        const b = el.querySelector(".tl-big[data-count]");
        if (b && b.offsetParent !== null) {
          counted = true;
          const m = /^(-?\$?)([\d,]+(?:\.\d+)?)(.*)$/.exec(b.textContent.trim());
          if (m && motionOn()) { const v = Number(m[2].replace(/,/g, "")), d = (m[2].split(".")[1] || "").length; if (v > 0) countUp(b, v, (x) => m[1] + nFix(x, d) + m[3], 700); }
        }
      }
    },
    // parts: [[id, words, html]]; lead: html of the answer; before: html between the answer and the parts
    set({ lead = "", before = "", parts = [], after = "" }) {
      parts = parts.filter((p) => p && p[2]);
      el.innerHTML = `<div class="tl-page">${lead}${before}
        ${parts.length > 1 ? "<div data-tabs></div>" : ""}
        ${parts.map(([id, words, html]) => `<div class="tl-part" data-part="${esc(id)}">${parts.length > 1 ? `<h2 class="dz-part-title">${esc(words)}</h2>` : ""}${html}</div>`).join("")}
        ${parts.length > 1 ? "<div data-calm-pager></div>" : ""}${after}</div>`;
      const root = el.querySelector(".tl-page");
      book = parts.length > 1 ? chapters({ root, list: parts.map((p) => [p[0], p[1]]), param: "part", onShow: () => P.paint() }) : null;
      if (book) { root.querySelector("[data-tabs]").outerHTML = book.tabs(); book.open(book.current(), { write: false, first: true }); }
      P.book = book;
      P.paint();
    },
    // replace the html inside one node (a what-if result) and draw its charts
    swap(node, html) { node.innerHTML = html; P.paint(); },
  };
  stops.push(watchFolds(el, openFolds, () => P.paint()), watchMotion(el), printEverything(el, () => P.paint()));
  wireTables(el);
  el.addEventListener("click", (e) => {
    const s = e.target.closest("[data-src]");
    if (s && el.contains(s)) { const spec = reg.get(s.dataset.src); if (spec) openSource(ctx, spec, resp); return; }
    const f = e.target.closest("[data-fig]");
    if (f && el.contains(f)) openFigure(ctx, f.dataset.fig);
  });
  if (ctx.alive && ctx.alive.onLeave) ctx.alive.onLeave(() => { stops.forEach((s) => s()); mounted.forEach((c) => c && c.destroy && c.destroy()); });
  return P;
}

// the answer in one sentence and the headline number (with its source)
export function leadHtml({ kicker = "The answer", sentence, big = "", bigLabel = "", bigSrc = "", aside = "", chips = "" }) {
  return `<section class="tl-lead" aria-label="The answer">
    <div class="tl-lead-text"><p class="tl-kicker">${esc(kicker)}</p><p class="tl-answer">${sentence}</p>${aside ? `<p class="tl-aside">${aside}</p>` : ""}${chips ? `<div class="tl-chips">${chips}</div>` : ""}</div>
    ${big ? `<div class="tl-lead-num">${bigSrc ? `<button type="button" class="tl-big-btn" data-src="${bigSrc}" aria-label="${esc(bigLabel + ": " + big)}. Where this number comes from"><b class="tl-big" data-count>${esc(big)}</b></button>` : `<b class="tl-big" data-count>${esc(big)}</b>`}<span class="tl-big-label">${esc(bigLabel)}</span></div>` : ""}
  </section>`;
}
// a calm box for when a part has nothing to show yet
export const calmBox = (title, text) => `<div class="tl-calm"><h3>${esc(title)}</h3>${text ? `<p>${text}</p>` : ""}</div>`;
export const disclaimerHtml = (resp, extra = "") => `<p class="fine tl-disc">${esc(extra ? extra + " " : "")}${esc((resp && resp.disclaimer) || "")}${resp && resp.as_of ? ` Worked out ${esc(resp.as_of)} from ${esc(resp.dataset)} version ${esc(resp.version ?? "")}.` : ""}</p>`;

// a small table: columns [{label, num}], rows [[html]]; every cell is already html
export function smallTable(columns, rows, caption = "", cls = "") {
  return `<div class="scroll tl-table${cls ? " " + cls : ""}"><table class="data">${caption ? `<caption class="dc-sr-cap">${esc(caption)}</caption>` : ""}
    <thead><tr>${columns.map((c) => `<th scope="col"${c.num ? ' class="num"' : ""}>${esc(c.label)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((r) => `<tr${r.cls ? ` class="${r.cls}"` : ""}>${(r.cells || r).map((c, i) => (i === 0 ? `<th scope="row">${c}</th>` : `<td${columns[i] && columns[i].num ? ' class="num"' : ""}>${c}</td>`)).join("")}</tr>`).join("")}</tbody></table></div>`;
}

// a segmented control: options [[value, words]]; name is what data-seg says
export function seg(name, options, current, label) {
  return `<div class="tl-seg-wrap"><span class="tl-seg-label" id="tl-seg-${esc(name)}">${esc(label)}</span><div class="dz-seg tl-seg" role="radiogroup" aria-labelledby="tl-seg-${esc(name)}">${options.map(([v, w]) =>
    `<button type="button" role="radio" aria-checked="${String(v) === String(current)}" data-seg="${esc(name)}" data-val="${esc(v)}"${String(v) === String(current) ? ' class="on"' : ""}>${esc(w)}</button>`).join("")}</div></div>`;
}
// arrow keys move inside a segmented control, as a radio group should
export function wireSegKeys(root) {
  root.addEventListener("keydown", (e) => {
    const b = e.target.closest && e.target.closest(".tl-seg [role=radio]");
    if (!b || !["ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp"].includes(e.key)) return;
    const all = [...b.parentElement.querySelectorAll("[role=radio]")], i = all.indexOf(b);
    const next = all[(i + (e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : all.length - 1)) % all.length];
    e.preventDefault(); next.focus(); next.click();
  });
}

// a calm problem card in place of the tool, with a way to try again
export function problemHtml(e) {
  return `<div class="tl-calm tl-problem" role="alert"><h3>The calculation could not be run just now</h3><p>${esc((e && e.message) || "Something went wrong.")}</p><p><button type="button" class="btn small" data-retry>Try again</button></p></div>`;
}
// runs a tool's drawing; anything that goes wrong becomes a calm card, never a broken page
export async function guarded(el, ctx, draw) {
  try { await draw(); }
  catch (e) {
    console.error(e);
    if (ctx.alive && !ctx.alive()) return;
    if (e && (e.code === "sign-in-needed" || e.code === "session-expired")) return;
    el.innerHTML = problemHtml(e);
    const r = el.querySelector("[data-retry]");
    if (r) r.addEventListener("click", () => { el.innerHTML = loadingHtml("Trying again…"); guarded(el, ctx, draw); });
  }
}
export const loadingHtml = (words) => `<div class="state loading" role="status"><span class="spinner" aria-hidden="true"></span><p>${esc(words)}</p></div>`;

// waits a moment after the last call (sliders)
export function debounce(fn, ms = 350) { let t = 0; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
// the first value in the register for an id, else the response's input, else a default
export function inputValue(resp, id, fallback = null) {
  const x = ((resp && resp.inputs_used) || []).find((i) => i.assumption_id === id);
  return x && isNum(x.value) ? Number(x.value) : fallback;
}
// the source spec of a register input used by a response (a figure, or an engine starting figure)
export function inputSpec(ctx, resp, id, label) {
  const x = ((resp && resp.inputs_used) || []).find((i) => i.assumption_id === id);
  if (!x) return { label, value: NK, how: ["This figure is not in the register and the engine has no starting figure for it."], starting: false };
  const w = inputWords(ctx, x);
  if (w.figure && !x.what_if) return { label: w.label, value: w.value, figure: id };
  return { label: w.label, value: w.value, starting: w.starting, how: x.what_if ? ["A what-if value you set on this screen. It is not saved."] : [], inputs: [x] };
}

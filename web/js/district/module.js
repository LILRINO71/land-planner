// A page defined by the project's data (modules.json): its rule banner, KPI cards, tables, charts, sections
// (narrative, table, banner, questions and answers) and the reconciliations that belong to it. Every page of every
// project is drawn by this one file, so a new module needs no code.
import { esc, has, isNum, n0, nFix, figureWords, countable, fieldWords, cell, lookupsOf, planWords, tableHtml, wireTables, sourceTags, leadOf, valueIn } from "./ui.js";
import { viewBar, wireViewBar, groupOf } from "./router.js";
import { openFigure } from "./figure.js";
import { exportButtons, wireExports } from "./exports.js";
import { chapters, fold, watchFolds, watchMotion, printEverything, countUp } from "../calm.js";

const ENTITY_WORDS = { program_lines: "Program", parcels: "Parcels", market_metrics: "Market figures", competitors: "Competitors",
  assumptions: "Register figures", infrastructure: "Infrastructure", risks: "Risks", comps: "Comparables", data_sources: "Data sources",
  requirements: "Requirements", deliverables: "Deliverables", phases: "Phases", uses: "Uses", reconciliations: "Reconciliations" };
const SCENARIO_WORDS = { low: "Low case", base: "Base case", high: "High case" };

// ---------------------------------------------------------------- reconciliations

function localReconciliation(r, content, look) {
  const total = look.assumptions[r.total], e = (content && content.entities) || {};
  const tv = total && isNum(total.value) ? Number(total.value) : null;
  let parts = [], missing = [];
  if ((r.parts || []).length) {
    (r.parts || []).forEach((id) => { const a = look.assumptions[id]; if (a && isNum(a.value)) parts.push({ id, value: Number(a.value) }); else missing.push(id); });
  } else if (r.parts_entity) {
    const where = r.parts_where || {};
    (e[r.parts_entity] || []).filter((row) => Object.entries(where).every(([k, v]) => String(row[k]) === String(v)))
      .forEach((row) => { if (isNum(row[r.parts_field])) parts.push({ id: row.id, value: Number(row[r.parts_field]) }); });
  }
  const pt = parts.reduce((t, x) => t + x.value, 0), diff = tv === null ? null : tv - pt;
  return { id: r.id, label: r.label, total: r.total, parts_total: pt, difference: diff,
    difference_pct: tv ? diff / tv * 100 : null, within_tolerance: diff !== null && Math.abs(diff) <= (Number(r.tolerance) || 0),
    explanation: r.explanation || "", explained: !!r.explanation, parts, missing };
}
function reconHtml(rc, look) {
  const t = look.assumptions[rc.total], unit = t ? t.unit : "";
  const totalWords = t && isNum(t.value) ? valueIn(t.value, unit) : "not given";
  const ok = rc.within_tolerance;
  const diff = isNum(rc.difference) ? valueIn(Math.abs(rc.difference), unit) : "not known";
  const pct = isNum(rc.difference_pct) ? ` (${nFix(Math.abs(rc.difference_pct), 1)}%)` : "";
  return `<article class="dz-recon${ok ? " ok" : ""}">
    <p class="dz-recon-kicker">These should add up</p><h3>${esc(rc.label)}</h3>
    <div class="dz-recon-sum">
      <button type="button" class="dz-recon-a" data-fig="${esc(rc.total)}"><small>${esc(t ? t.label : rc.total)}</small><b>${esc(totalWords)}</b></button>
      <span aria-hidden="true">vs</span>
      <div class="dz-recon-b"><small>The parts add up to</small><b>${esc(valueIn(rc.parts_total, unit))}</b></div>
      <div class="dz-recon-d"><small>Difference</small><b>${ok ? "None that matters" : esc(diff) + pct}</b></div>
    </div>
    ${ok ? "" : `<p class="dz-recon-why">${rc.explained || rc.explanation ? esc(rc.explanation) : '<span class="muted">Not explained in the documents.</span>'}</p>`}
    ${(rc.missing || []).length ? `<p class="fine">Not in the register: ${esc(rc.missing.join(", "))}.</p>` : ""}</article>`;
}

// ---------------------------------------------------------------- tables and their charts

function rowsOf(content, t) {
  const where = t.where || {};
  return ((content.entities || {})[t.entity] || []).filter((row) => Object.entries(where).every(([k, v]) => String(row[k]) === String(v)));
}
function whereWords(where) {
  return Object.entries(where || {}).map(([k, v]) => (k === "scenario" ? SCENARIO_WORDS[v] || v : `${fieldWords(k)} ${v}`)).join(", ");
}
// a chart (or two) that the rows of an entity call for
function chartsFor(entity, rows, look) {
  const out = [], sumBy = (key, val) => {
    const m = new Map();
    rows.forEach((r) => { const v = val(r); if (!isNum(v)) return; const k = key(r); m.set(k, (m.get(k) || 0) + Number(v)); });
    return { labels: [...m.keys()], values: [...m.values()] };
  };
  if (entity === "program_lines") {
    const sf = sumBy((r) => look.uses[r.use] || r.use, (r) => r.sf);
    if (sf.values.length > 1) out.push(["bar", { ...sf, unit: "sf", title: "Square feet by category" }]);
    const rent = sumBy((r) => look.uses[r.use] || r.use, (r) => (isNum(r.sf) && isNum(r.base_rent_usd_sf_yr) ? r.sf * r.base_rent_usd_sf_yr : null));
    if (rent.values.length > 1) out.push(["bar", { ...rent, unit: "usd_per_yr", title: "Annual base rent by category (per year)" }]);
  } else if (entity === "parcels") {
    const ac = sumBy((r) => r.label || r.apn || r.id, (r) => r.acres);
    if (ac.values.length > 1) out.push(["bar", { ...ac, unit: "acres", title: "Gross acres by parcel" }]);
    const plan = sumBy((r) => planWords(r.hold_sell || "undecided"), (r) => r.acres);
    if (plan.values.length > 1) out.push(["donut", { ...plan, unit: "acres", title: "Acres by plan" }]);
  } else if (entity === "infrastructure") {
    const c = sumBy((r) => r.category || r.item, (r) => r.cost_usd);
    if (c.values.length > 1) out.push(["bar", { ...c, unit: "usd", title: "Cost by category" }]);
  } else if (entity === "market_metrics") {
    const years = [...new Set(rows.map((r) => r.year))].sort();
    const keys = [...new Set(rows.map((r) => r.metric + "|" + r.geography + "|" + r.unit))];
    if (years.length > 1) keys.slice(0, 1).forEach((k) => {
      const [metric, geo, unit] = k.split("|");
      const series = [{ name: `${metric}, ${geo}`, values: years.map((y) => { const r = rows.find((x) => x.year === y && x.metric === metric && x.geography === geo); return r ? r.value : null; }) }];
      if (series[0].values.filter(isNum).length > 1) out.push(["line", { x: years, series, unit, title: `${metric[0].toUpperCase() + metric.slice(1)}, ${geo}` }]);
    });
  } else if (entity === "competitors") {
    const occ = rows.filter((r) => isNum(r.occupancy_pct));
    if (occ.length > 1) out.push(["bar", { labels: occ.map((r) => r.name), values: occ.map((r) => r.occupancy_pct), unit: "pct", title: "Occupancy by competitor" }]);
  }
  return out;
}
function entityTable(t, content, look) {
  const rows = rowsOf(content, t), cols = (t.columns && t.columns.length ? t.columns : Object.keys(rows[0] || {}).filter((k) => !["tags", "city_safe"].includes(k)));
  const present = cols.filter((c) => rows.some((r) => r[c] !== undefined) || !rows.length);
  const cells = rows.map((r) => present.map((c) => cell(t.entity, c, r, look)));
  const columns = present.map((c, i) => ({ label: fieldWords(c), num: cells.length ? cells.every((row) => row[i].num || row[i].sort === null) && cells.some((row) => row[i].num) : false }));
  return { rows, columns, cells };
}
// a section's own table: lists of cells under its column names
function sectionTable(s) {
  const columns = s.columns || [], rows = s.rows || [];
  const numeric = columns.map((_, i) => rows.length > 0 && rows.every((r) => r[i] === null || r[i] === "" || isNum(r[i])) && rows.some((r) => isNum(r[i])));
  const money = columns.map((c) => /\$|price|value|cost|rent|revenue/i.test(c));
  const perSf = columns.map((c) => /\/\s*sf/i.test(c));
  const fmt = (v, i) => {
    if (!isNum(v)) return { html: v === null || v === "" || v === undefined ? '<span class="muted">-</span>' : esc(v), sort: v === null || v === undefined ? "" : String(v) };
    const x = Number(v);
    if (money[i]) return { html: esc((x < 0 ? "-$" : "$") + nFix(Math.abs(x), perSf[i] ? 2 : 0)), sort: x };
    return { html: esc(n0(x, 2)), sort: x };
  };
  return { columns: columns.map((c, i) => ({ label: c, num: numeric[i] })), cells: rows.map((r) => columns.map((_, i) => fmt(r[i], i))), numeric, rows };
}
function sectionCharts(s) {
  const cols = s.columns || [], rows = s.rows || [], out = [];
  if (rows.length < 2 || !cols.length) return out;
  const sfI = cols.findIndex((c) => /(^|\s)sf($|\s|\b)/i.test(c) && !/\$/.test(c));
  const rentI = cols.findIndex((c) => /rent/i.test(c) && /\$/.test(c));
  const labels = rows.map((r) => String(r[0]));
  if (sfI > 0 && rows.every((r) => isNum(r[sfI]))) out.push(["bar", { labels, values: rows.map((r) => Number(r[sfI])), unit: "sf", title: `Square feet by ${cols[0].toLowerCase()}` }]);
  if (sfI > 0 && rentI > 0 && rows.every((r) => isNum(r[sfI]) && isNum(r[rentI]))) {
    const monthly = /mo/i.test(cols[rentI]);
    out.push(["bar", { labels, values: rows.map((r) => Number(r[sfI]) * Number(r[rentI]) * (monthly ? 12 : 1)), unit: "usd_per_yr", title: `Annual base rent by ${cols[0].toLowerCase()} (per year)` }]);
  }
  return out;
}
const chartBox = (spec, k) => `<div class="dz-chart-box" data-chart="${k}"></div>`;

// ---------------------------------------------------------------- questions and answers, one at a time

// the figures a text cites: the first few as buttons, the rest behind one fold
const CITES_SHOWN = 4;
function citeChips(ids, look) {
  const chip = (id) => { const f = look.assumptions[id]; return `<button type="button" class="dz-cite" data-fig="${esc(id)}">${esc(f ? `${f.label}: ${figureWords(f).main}` : id)}</button>`; };
  const list = ids || [];
  if (list.length <= CITES_SHOWN + 1) return list.map(chip).join("");
  const rest = list.slice(CITES_SHOWN);
  return list.slice(0, CITES_SHOWN).map(chip).join("") +
    `<details class="calm-fold dz-cites-more"><summary>Show ${rest.length} more ${rest.length === 1 ? "figure" : "figures"}</summary><div class="calm-fold-body">${rest.map(chip).join("")}</div></details>`;
}
function qaHtml(s, i, look) {
  const items = s.items || [], it = items[i] || {}, a = leadOf(it.answer || "");
  const cites = citeChips(it.cites, look);
  return `<div class="dz-qa-main" aria-live="polite">
      <p class="dz-qa-count">Question ${i + 1} of ${items.length}</p>
      <h3 class="dz-qa-q" tabindex="-1">${esc(it.question || "")}</h3>
      ${it.answer ? `<p class="dz-qa-lead${a.lead.length > 220 ? " long" : ""}">${esc(a.lead)}</p>${a.rest ? `<div class="dz-qa-rest">${esc(a.rest).split(/\n{2,}/).map((x) => `<p>${x.replace(/\n/g, "<br>")}</p>`).join("")}</div>` : ""}`
        : '<p class="dz-qa-lead muted">Not answered in the documents yet.</p>'}
      ${cites ? `<div class="dz-cites"><span>Figures it cites</span>${cites}</div>` : ""}
      <div class="dz-qa-nav"><button type="button" class="btn" data-qa-step="-1"${i ? "" : " disabled"}>Previous</button><button type="button" class="btn primary" data-qa-step="1"${i < items.length - 1 ? "" : " disabled"}>Next question</button></div>
    </div>`;
}
function qaListHtml(s, cur) {
  return `<ol class="dz-qa-list">${(s.items || []).map((it, k) => `<li><button type="button" data-qa-go="${k}"${k === cur ? ' aria-current="true" class="on"' : ""}><small>${k + 1}</small><span>${esc(it.question || "")}</span></button></li>`).join("")}</ol>`;
}

// ---------------------------------------------------------------- the page

export function renderEmptyProject(el, ctx) {
  el.innerHTML = `<header class="page-head"><p class="kicker">${esc(ctx.project.name || "")}</p><h1>No pages yet</h1></header>
    <div class="card dz-calm"><p>This project has no pages defined yet. An administrator adds them in the project's modules.</p></div>`;
}

export async function render(el, ctx, moduleId, alive) {
  const m = ctx.modules.find((x) => x.id === moduleId);
  if (!m) {
    el.innerHTML = `<header class="page-head"><p class="kicker">${esc(ctx.project.name || "")}</p><h1>That page is not here</h1></header>
      <div class="card dz-calm"><p>${ctx.viewAs ? "This audience does not see that page." : "The project has no page with that name."}</p><p><a class="btn" href="${ctx.link([])}">Back to the project</a></p></div>`;
    wireViewBar(el, ctx);
    return;
  }
  const content = ctx.content, look = lookupsOf(content);
  const sections = ((content.entities || {}).sections || []).filter((s) => s.module === m.id).sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
  // a banner section shows only when it says something the module's own banner does not
  const banners = [];
  [m.banner].concat(sections.filter((s) => s.kind === "banner").map((s) => s.body)).forEach((b) => {
    if (b && !banners.some((x) => same(x, b))) banners.push(b);
  });
  // a card cites one register entry, or two (the low and high ends of a range)
  const cards = (m.cards || []).map((c) => {
    const ids = (c.assumptions && c.assumptions.length ? c.assumptions : [c.assumption]).filter(Boolean);
    const figs = ids.map((id) => look.assumptions[id]).filter(Boolean);
    let f = figs[0];
    if (figs.length >= 2) {
      const lo = figs[0], hi = figs[figs.length - 1], end = (x, k) => (isNum(x.value) ? x.value : x[k]);
      f = { ...lo, label: c.label || lo.label, value: null, value_low: end(lo, "value_low"), value_high: end(hi, "value_high"),
        value_text: lo.value_text && hi.value_text && lo.value_text !== hi.value_text ? "" : lo.value_text || "", conflict: figs.some((x) => x.conflict) };
    }
    return { c, f, id: ids[0] || "", ids };
  });
  const tables = (m.tables || []).map((t) => ({ t, ...entityTable(t, content, look) })).filter((x) => x.rows.length);
  const pageTags = new Set((m.source_tags || []).map(norm));
  const narratives = sections.filter((s) => s.kind === "narrative"), sTables = sections.filter((s) => s.kind === "table" && (s.rows || []).length);
  const qas = sections.filter((s) => s.kind === "qa" && (s.items || []).length);

  // reconciliations about the figures this page shows
  const cited = new Set(cards.flatMap((x) => x.ids).concat(sections.flatMap((s) => s.cites || [])));
  let recs = ((content.entities || {}).reconciliations || []).filter((r) => cited.has(r.total) || (r.parts || []).some((p) => cited.has(p)));
  let recon = recs.map((r) => localReconciliation(r, content, look));
  if (recs.length && ctx.can.checks) {
    try {
      const ch = await ctx.api.checks(ctx.project.id, ctx.dataset, { version: ctx.version, audience: ctx.viewAs || "" });
      const byId = Object.fromEntries((ch.reconciliations || []).map((r) => [r.id, r]));
      recon = recon.map((r) => (byId[r.id] ? { ...r, ...byId[r.id], total: r.total } : r));
    } catch (e) { /* the page's own sums are shown */ }
    if (!alive()) return;
  }

  const openFolds = new Set(), charts = [];
  const chartSpecs = (list) => list.map((spec) => { charts.push(spec); return chartBox(spec, charts.length - 1); }).join("");
  const parts = [];
  // chapter 1: the lead
  const lead = cards.length || narratives.length || recon.length;
  if (lead) parts.push(["glance", "At a glance", `
    ${cards.length ? `<div class="dz-kpis">${cards.map(({ c, f, id, ids }) => {
      const w = figureWords(f, c.format, { compact: true });
      const main = glue(w.main), aside = w.aside && !same(w.aside, w.main) ? w.aside : "";
      const desc = c.description && !same(c.description, w.main) && !same(c.description, aside) ? c.description : "";
      const size = main.length > 22 ? " xlong" : main.length > 15 ? " long" : "";
      return `<button type="button" class="dz-kpi" data-fig="${esc(id)}" aria-label="${esc(c.label)}: ${esc(w.main)}. Where this number comes from">
        <span class="dz-kpi-label">${esc(c.label || (f && f.label) || id)}</span>
        <b class="dz-kpi-value${size}" data-count="${esc(main)}"${w.exact ? ` title="${esc(w.exact)}"` : ""}>${esc(main)}</b>
        ${aside ? `<span class="dz-kpi-aside">${esc(aside)}</span>` : ""}
        ${desc ? `<span class="dz-kpi-desc">${esc(desc)}</span>` : ""}
        <span class="dz-kpi-foot">${sourceTags((c.source_tags || []).filter((t) => !pageTags.has(norm(t))))}${f && f.conflict ? '<span class="dz-chip warn">Sources disagree</span>' : ""}${f && f.status === "Superseded" ? '<span class="dz-chip warn">Superseded</span>' : ""}<span class="dz-kpi-id">${esc(ids.join(", "))}</span></span>
      </button>`;
    }).join("")}</div>` : ""}
    ${narratives.map((s) => narrativeHtml(s, look)).join("")}
    ${recon.length ? `<div class="dz-recons">${recon.map((r) => reconHtml(r, look)).join("")}</div>` : ""}`]);
  // chapter 2: tables and charts
  const tableBlocks = tables.map(({ t, columns, cells, rows }) => {
    const title = `${ENTITY_WORDS[t.entity] || fieldWords(t.entity)}${t.where ? ", " + whereWords(t.where) : ""}`;
    const specs = chartsFor(t.entity, rows, look);
    return `<section class="dz-block"><div class="dz-block-head"><h2>${esc(t.title || title)}</h2>${exportButtons(ctx, { entity: t.entity, small: true, pdf: false })}</div>
      ${specs.length ? `<div class="dz-charts">${chartSpecs(specs)}</div>` : ""}
      ${specs.length ? fold("t-" + t.entity, `Show the ${rows.length} rows as a table`, tableHtml({ columns, rows: cells, caption: title }), openFolds) : tableHtml({ columns, rows: cells, caption: title })}</section>`;
  }).concat(sTables.map((s) => {
    const st = sectionTable(s), specs = sectionCharts(s);
    return `<section class="dz-block"><div class="dz-block-head"><h2>${esc(s.heading || "Table")}</h2>${exportButtons(ctx, { entity: "section:" + s.id, small: true, pdf: false })}</div>
      ${specs.length ? `<div class="dz-charts">${chartSpecs(specs)}</div>` : ""}
      ${tableHtml({ columns: st.columns, rows: st.cells, caption: s.heading || "Table" })}
      ${citesLine(s, look)}</section>`;
  }));
  // many tables: the first few stand open, the rest wait behind their own heading
  const OPEN_TABLES = 3;
  const blocksHtml = tableBlocks.map((html, i) => {
    if (tableBlocks.length <= OPEN_TABLES + 1 || i < OPEN_TABLES) return html;
    const head = /<h2>([\s\S]*?)<\/h2>/.exec(html), n = (html.match(/<tr/g) || []).length - 1;
    const words = head ? head[1].replace(/<[^>]+>/g, "").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'") : "Table";
    return `<div class="dz-block dz-block-later">${fold("tb-" + i, `${words}${n > 0 ? ` (${n} ${n === 1 ? "row" : "rows"})` : ""}`, html.replace(/<h2>[\s\S]*?<\/h2>/, ""), openFolds)}</div>`;
  });
  if (tableBlocks.length) parts.push(["figures", "Tables and charts", (tableBlocks.length > OPEN_TABLES + 1 ? `<p class="dz-shown">${tableBlocks.length} tables. The first ${OPEN_TABLES} are open; open any other by its name.</p>` : "") + blocksHtml.join("")]);
  // chapter 3: questions
  const qaIndex = new Map(qas.map((s) => [s.id, 0]));
  if (qas.length) parts.push(["questions", qas.length === 1 ? (qas[0].heading || "Questions") : "Questions and answers", qas.map((s) => `
    <section class="dz-block dz-qa" data-qa="${esc(s.id)}">
      <div class="dz-block-head"><h2>${esc(s.heading || "Questions and answers")}</h2>${(s.heading || "").includes(`(${s.items.length})`) ? "" : `<span class="muted">${s.items.length} ${s.items.length === 1 ? "question" : "questions"}</span>`}</div>
      <div class="dz-qa-grid"><div class="dz-qa-cur">${qaHtml(s, 0, look)}</div>
        <nav class="dz-qa-side" aria-label="All questions">${fold("qa-" + s.id, `All ${s.items.length} questions`, `<div data-qa-list>${qaListHtml(s, 0)}</div>`, openFolds, "dz-qa-fold")}</nav></div>
    </section>`).join("")]);

  const group = groupOf(m);
  const empty = !parts.length;
  el.innerHTML = `<header class="page-head dz-head">
      <p class="kicker">${esc(ctx.project.name || "")}${group ? " · " + esc(group) : ""}</p>
      <div class="head-row"><h1>${esc(m.label || m.id)}</h1><div class="head-actions">${exportButtons(ctx, { module: m.id })}</div></div>
      ${m.description ? `<p class="lead">${esc(m.description)}</p>` : ""}
      ${(m.source_tags || []).length ? `<p class="dz-srcs">${sourceTags(m.source_tags)}</p>` : ""}
    </header>
    ${viewBar(ctx)}
    ${banners.length ? `<div class="dz-rule" role="note" aria-label="Rule for this page">${banners.map((b) => `<p>${esc(b)}</p>`).join("")}</div>` : ""}
    <div class="dz-audio-slot"></div>
    <div class="dz-page">
      ${empty ? `<div class="card dz-calm"><p>${esc(emptySentence(m, ctx))}</p></div>` : ""}
      ${parts.length > 1 ? "<div data-tabs></div>" : ""}
      ${parts.map(([id, words, html]) => `<div class="dz-part" data-part="${id}">${parts.length > 1 ? `<h2 class="dz-part-title">${esc(words)}</h2>` : ""}${html}</div>`).join("")}
      ${parts.length > 1 ? '<div data-calm-pager></div>' : ""}
    </div>
    ${m.footer ? `<p class="fine foot dz-foot">${esc(m.footer)}</p>` : ""}`;

  wireViewBar(el, ctx);
  wireTables(el);
  wireExports(el, ctx);
  // on a wide screen the list of questions stands open beside the question
  if (window.innerWidth >= 1180) el.querySelectorAll(".dz-qa-fold").forEach((d) => { d.open = true; });
  const page = el.querySelector(".dz-page"), rule = el.querySelector(".dz-rule");
  if (rule) el.style.setProperty("--dz-rule-h", rule.offsetHeight + "px");
  let counted = false;
  const mounted = [];
  const book = parts.length > 1 ? chapters({ root: page, list: parts.map((p) => [p[0], p[1]]), param: "part", onShow: () => paintCharts() }) : null;
  if (book) { page.querySelector("[data-tabs]").outerHTML = book.tabs(); book.open(book.current(), { write: false, first: true }); }
  const stops = [watchFolds(el, openFolds, () => paintCharts()), watchMotion(el), printEverything(el, () => paintCharts())];
  function paintCharts() {
    el.querySelectorAll("[data-chart]").forEach((box) => {
      if (box.dataset.drawn || box.offsetParent === null) return;
      const [kind, spec] = charts[Number(box.dataset.chart)];
      box.dataset.drawn = "1";
      const fn = { bar: ctx.charts.barChart, donut: ctx.charts.donut, line: ctx.charts.lineChart, stacked: ctx.charts.stackedBar }[kind];
      mounted.push(fn(box, spec));
    });
    if (!counted && el.querySelector(".dz-kpi-value") && el.querySelector(".dz-kpi-value").offsetParent !== null) {
      counted = true;
      el.querySelectorAll(".dz-kpi-value").forEach((b) => { const c = countable(b.dataset.count); if (c && c.value > 0) countUp(b, c.value, c.format, 800); });
    }
  }
  paintCharts();
  alive.onLeave(() => { stops.forEach((s) => s()); mounted.forEach((c) => c.destroy()); });

  el.addEventListener("click", (e) => {
    const f = e.target.closest("[data-fig]");
    if (f && el.contains(f)) { openFigure(ctx, f.dataset.fig); return; }
    const box = e.target.closest("[data-qa]");
    if (!box) return;
    const s = qas.find((x) => x.id === box.dataset.qa);
    const step = e.target.closest("[data-qa-step]"), pick = e.target.closest("[data-qa-go]");
    if (!step && !pick) return;
    let i = qaIndex.get(s.id);
    i = pick ? Number(pick.dataset.qaGo) : Math.min(s.items.length - 1, Math.max(0, i + Number(step.dataset.qaStep)));
    qaIndex.set(s.id, i);
    box.querySelector(".dz-qa-cur").innerHTML = qaHtml(s, i, look);
    const list = box.querySelector("[data-qa-list]");
    if (list) { list.innerHTML = qaListHtml(s, i); const on = list.querySelector(".on"); if (on && on.scrollIntoView && pick) on.scrollIntoView({ block: "nearest" }); }
    const q = box.querySelector(".dz-qa-q");
    if (q) q.focus({ preventScroll: true });
    if (box.getBoundingClientRect().top < 0) box.scrollIntoView({ block: "start" });
  });
  el.addEventListener("keydown", (e) => {
    const box = e.target.closest && e.target.closest("[data-qa]");
    if (!box || e.target.matches("input,textarea,select") || (e.key !== "ArrowRight" && e.key !== "ArrowLeft")) return;
    const b = box.querySelector(`[data-qa-step="${e.key === "ArrowRight" ? 1 : -1}"]`);
    if (b && !b.disabled) { e.preventDefault(); b.click(); }
  });

  // the spoken briefing, when this browser can speak
  try {
    const audio = await import("./audio.js");
    if (alive()) audio.mount(el.querySelector(".dz-audio-slot"), ctx, { module: m, cards, banners, narratives, alive });
  } catch (e) { /* no briefing bar */ }
}

// two texts that say the same thing (case, spaces, dashes and punctuation aside)
const norm = (t) => String(t || "").toLowerCase().replace(/[–—-]/g, "-").replace(/[^a-z0-9$%+.-]+/g, "");
function same(a, b) { return !!a && !!b && norm(a) === norm(b); }
// a number and its unit never part at the end of a line
function glue(t) { return String(t).replace(/ (SF|acres|units|keys|homes|people|households|jobs|years|months|miles)\b/g, " $1").replace(/ to /g, " to "); }

function narrativeHtml(s, look) {
  const t = leadOf(s.body || "");
  return `<section class="dz-block dz-narr">${s.heading ? `<h2>${esc(s.heading)}${s.ai_assisted ? ' <span class="dz-chip ai">AI-assisted</span>' : ""}</h2>` : ""}
    <p class="dz-narr-lead">${esc(t.lead)}</p>${t.rest ? `<p>${esc(t.rest)}</p>` : ""}${citesLine(s, look)}</section>`;
}
function citesLine(s, look) {
  const c = s.cites || [];
  if (!c.length) return s.ai_assisted ? '<p class="fine">AI-assisted text that cites no register entry.</p>' : "";
  return `<div class="dz-cites"><span>${s.ai_assisted ? "AI-assisted; cites" : "Figures it cites"}</span>${citeChips(c, look)}</div>`;
}
function emptySentence(m, ctx) {
  if (ctx.viewAs) return `For this audience the ${m.label || m.id} page has nothing to show: its figures are not shared with them.`;
  return `The ${m.label || m.id} page has no figures, tables or text in this dataset yet.`;
}

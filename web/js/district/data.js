// The data area: the assumptions register, import, compare, documents, map layers, data sources, notes and checks.
// One part at a time (the sub-navigation at the top), each answering first with its headline.
import { esc, isNum, n0, nFix, valueIn, figureWords, tableHtml, wireTables, panel, say, chip, when, day, fieldWords, cell, lookupsOf } from "./ui.js";
import { viewBar, wireViewBar, DATA_PARTS, forget } from "./router.js";
import { openFigure } from "./figure.js";
import { exportButtons, wireExports } from "./exports.js";
import { debounce, loading, toast } from "../util.js";

const STATUSES = ["Baseline", "Consultant", "Legacy Assumption", "Superseded"];
const PROVENANCE = ["VERIFIED PROJECT FACT", "CURRENT OWNERSHIP INPUT", "CONSULTANT INPUT", "ESRI / ARCGIS DATA", "OWNERSHIP ASSUMPTION",
  "MARKET ASSUMPTION", "CALCULATED", "REQUIRES VALIDATION", "HISTORICAL / SUPERSEDED"];
const UNITS = ["sf", "acres", "units", "keys", "usd", "usd_per_yr", "usd_per_sf_yr", "usd_per_sf_mo", "usd_per_sf", "usd_per_acre", "usd_per_unit",
  "usd_per_unit_mo", "usd_per_night", "pct", "ratio", "people", "households", "jobs", "count", "years", "months", "sf_per_yr", "units_per_yr", "miles", "text"];
const AUD = [["internal", "Internal"], ["consultant", "Consultant"], ["partner", "Partner"], ["city", "City"]];
const opts = (list, cur) => list.map((x) => { const [v, w] = Array.isArray(x) ? x : [x, x]; return `<option value="${esc(v)}"${String(cur) === String(v) ? " selected" : ""}>${esc(w)}</option>`; }).join("");
const fileOf = (form) => { const f = form.querySelector("input[type=file]"); return f && f.files && f.files[0]; };

export async function render(el, ctx, part, alive) {
  const parts = DATA_PARTS.filter((d) => !d[2] || ctx.can[d[2]]);
  const cur = parts.find((p) => p[0] === part) || parts[0];
  el.innerHTML = `<header class="page-head"><p class="kicker">${esc(ctx.project.name || "")} · Data</p><h1>${esc(cur[1])}</h1></header>
    <nav class="dz-sub-nav" aria-label="Data area">${parts.map(([id, w]) => `<a href="${ctx.link(["data", id])}"${id === cur[0] ? ' class="on" aria-current="page"' : ""}>${esc(w)}</a>`).join("")}</nav>
    <div class="dz-data"></div>`;
  const box = el.querySelector(".dz-data");
  wireTables(el);
  const fn = { register, import: importPart, compare, documents, layers, sources, notes, checks }[cur[0]];
  try { await fn(box, ctx, alive); }
  catch (e) { console.error(e); if (alive()) box.innerHTML = `<div class="state problem" role="alert"><p>${esc(e.message || "This part could not be shown.")}</p></div>`; }
}

// ---------------------------------------------------------------- the assumptions register

async function register(box, ctx) {
  const all = (ctx.content.entities || {}).assumptions || [];
  const editable = ctx.can["dataset.edit"] && !ctx.viewAs;
  const st = { q: "", status: "", prov: "", conflict: "" };
  box.innerHTML = `${viewBar(ctx, { exports: exportButtons(ctx, { entity: "assumptions" }) })}
    <p class="lead">${all.length} figures in the register${all.filter((a) => a.conflict).length ? `, ${all.filter((a) => a.conflict).length} with sources that disagree` : ""}.
      ${editable ? (ctx.version === "draft" ? "Edits change this draft and are written to the revision log." : "Edits go to the draft of this dataset.") : ""}</p>
    <div class="card filters dz-filters">
      <label class="field grow"><span>Search</span><input type="search" data-q placeholder="Id, name or source"></label>
      <label class="field"><span>Status</span><select data-f="status"><option value="">All</option>${opts(STATUSES)}</select></label>
      <label class="field"><span>Provenance</span><select data-f="prov"><option value="">All</option>${opts(PROVENANCE)}</select></label>
      <label class="field"><span>Conflict</span><select data-f="conflict"><option value="">All</option><option value="yes">Sources disagree</option><option value="no">No conflict</option></select></label>
    </div><p class="dz-shown" role="status" aria-live="polite"></p><div data-list></div>`;
  wireViewBar(box, ctx); wireExports(box, ctx);
  const list = box.querySelector("[data-list]"), shown = box.querySelector(".dz-shown");
  const draw = () => {
    const q = st.q.toLowerCase();
    const rows = all.filter((a) => (!st.status || a.status === st.status) && (!st.prov || a.provenance === st.prov) &&
      (!st.conflict || (st.conflict === "yes") === !!a.conflict) && (!q || [a.id, a.label, a.source_doc, a.source_model, a.owner].join(" ").toLowerCase().includes(q)));
    shown.textContent = rows.length === all.length ? `Showing all ${all.length}.` : `Showing ${rows.length} of ${all.length}.`;
    const columns = [{ label: "Id" }, { label: "Figure" }, { label: "Value", num: true }, { label: "Status" }, { label: "Provenance" }, { label: "Source" }, { label: "As of" }, { label: "" }];
    list.innerHTML = rows.length ? tableHtml({ caption: "Assumptions register", foldAfter: 25, columns, rows: rows.map((a) => {
      const w = figureWords(a);
      return [{ html: `<button type="button" class="link" data-fig="${esc(a.id)}"><code>${esc(a.id)}</code></button>`, sort: a.id },
        { html: esc(a.label) + (a.conflict ? ' <span class="dz-chip warn">Sources disagree</span>' : ""), sort: a.label },
        { html: esc(w.main) + (w.aside ? `<small>${esc(w.aside)}</small>` : ""), sort: isNum(a.value) ? Number(a.value) : "" },
        { html: esc(a.status || ""), sort: a.status }, { html: `<small>${esc(a.provenance || "")}</small>`, sort: a.provenance },
        { html: `<small>${esc([a.source_doc, a.source_model].filter(Boolean).join(" · "))}</small>`, sort: a.source_doc },
        { html: esc(day(a.as_of)), sort: a.as_of || "" },
        { html: `<span class="dz-row">${editable ? `<button type="button" class="btn small" data-edit="${esc(a.id)}">Edit</button>` : ""}${ctx.can["revisions.read"] ? `<button type="button" class="btn small" data-hist="${esc(a.id)}">History</button>` : ""}</span>`, sort: "" }];
    }) }) : '<div class="card dz-calm"><p>No figure matches. Clear a filter to see more.</p></div>';
  };
  box.querySelector("[data-q]").addEventListener("input", debounce((e) => { st.q = e.target.value; draw(); }, 150));
  box.addEventListener("change", (e) => { const f = e.target.dataset.f; if (f) { st[f] = e.target.value; draw(); } });
  box.addEventListener("click", (e) => {
    const f = e.target.closest("[data-fig]"); if (f) return openFigure(ctx, f.dataset.fig);
    const ed = e.target.closest("[data-edit]"); if (ed) return editFigure(ctx, all.find((a) => a.id === ed.dataset.edit));
    const h = e.target.closest("[data-hist]"); if (h) return history(ctx, h.dataset.hist);
  });
  draw();
}

function editFigure(ctx, a) {
  const p = panel(`Edit ${a.id}`);
  const fld = (name, label, val, type = "text") => `<label class="field"><span>${label}</span><input name="${name}" type="${type}" value="${esc(val ?? "")}"${type === "number" ? ' step="any"' : ""}></label>`;
  const sel = (name, label, list, val) => `<label class="field"><span>${label}</span><select name="${name}">${opts(list, val)}</select></label>`;
  p.body.innerHTML = `<p class="muted">Saved to the draft of <b>${esc(ctx.datasetMeta.label || ctx.dataset)}</b>. Every change is written to the revision log with your reason.</p>
    <form class="dz-form" data-edit-form>
      ${fld("label", "Name", a.label)}
      <div class="dz-grid2">${fld("value", "Value", a.value, "number")}${sel("unit", "Unit", UNITS, a.unit)}</div>
      <div class="dz-grid2">${fld("value_low", "Low end (a range)", a.value_low, "number")}${fld("value_high", "High end (a range)", a.value_high, "number")}</div>
      ${fld("value_text", "Value in words", a.value_text)}
      <div class="dz-grid2">${sel("status", "Status", STATUSES, a.status)}${sel("provenance", "Provenance", PROVENANCE, a.provenance)}</div>
      <div class="dz-grid2">${fld("source_doc", "Source document", a.source_doc)}${fld("source_model", "Source model", a.source_model)}</div>
      <div class="dz-grid2">${fld("as_of", "As of", a.as_of, "date")}${fld("owner", "Owner", a.owner)}</div>
      <div class="dz-grid2">${sel("confidence", "Confidence", [["", "Not given"], "high", "medium", "low"], a.confidence || "")}<label class="check"><input type="checkbox" name="conflict"${a.conflict ? " checked" : ""}> Sources disagree</label></div>
      ${fld("conflict_note", "What disagrees with what", a.conflict_note)}
      <label class="field"><span>Reason for the change (required)</span><textarea name="reason" rows="2" required></textarea></label>
      <button class="btn primary" type="submit">Save to the draft</button><p class="dz-status" role="status" aria-live="polite"></p></form>`;
  const form = p.body.querySelector("form");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(form), reason = String(f.get("reason") || "").trim();
    if (!reason) return say(form.querySelector(".dz-status"), "Say why the figure changes.", "bad");
    const rec = { ...a };
    ["label", "unit", "value_text", "status", "provenance", "source_doc", "source_model", "as_of", "owner", "confidence", "conflict_note"].forEach((k) => {
      const v = String(f.get(k) ?? "").trim(); if (v) rec[k] = v; else delete rec[k];
    });
    ["value", "value_low", "value_high"].forEach((k) => { const v = String(f.get(k) ?? "").trim(); if (v !== "" && isFinite(Number(v))) rec[k] = Number(v); else delete rec[k]; });
    if (f.get("conflict")) rec.conflict = true; else if (a.conflict !== undefined) rec.conflict = false; else delete rec.conflict;
    say(form.querySelector(".dz-status"), "Saving…", "busy");
    try {
      const ans = await ctx.api.saveRecord(ctx.project.id, ctx.dataset, { entity: "assumptions", record: rec, reason });
      p.close(); forget(ctx.project.id);
      toast(`Saved: ${(ans.changes || []).length} ${(ans.changes || []).length === 1 ? "change" : "changes"} in the draft.`);
      location.hash = ctx.link(["data", "register"], { v: "draft" });
    } catch (err) { say(form.querySelector(".dz-status"), err.message, "bad"); }
  });
}

async function history(ctx, id) {
  const p = panel(`History of ${id}`, { wide: true });
  p.body.innerHTML = loading("Reading the revision log…");
  try {
    const ans = await ctx.api.revisions(ctx.project.id, { entity: "assumptions", id, limit: 200 });
    const rows = ans.revisions || [];
    p.body.innerHTML = (ans.chain ? `<p class="${ans.chain.ok ? "dz-ok" : "dz-bad"}">${ans.chain.ok ? "The revision log is intact." : `The revision log is broken at line ${esc(ans.chain.broken_at)}.`}</p>` : "") +
      (rows.length ? tableHtml({ caption: `Changes to ${id}`, foldAfter: 20, columns: [{ label: "When" }, { label: "Who" }, { label: "Dataset" }, { label: "Field" }, { label: "Was" }, { label: "Now" }, { label: "Reason" }],
        rows: rows.map((r) => [{ html: esc(when(r.at)), sort: r.at }, { html: esc(r.name || r.user), sort: r.name }, { html: `<small>${esc(r.dataset)}</small>`, sort: r.dataset },
          { html: esc(r.field === "*" ? "Whole record" : fieldWords(r.field || "")), sort: r.field }, { html: esc(r.field === "*" ? (r.oldValue ? "earlier record" : "-") : fmt(r.oldValue)), sort: "" }, { html: esc(r.field === "*" ? (r.newValue ? "added" : "removed") : fmt(r.newValue)), sort: "" }, { html: esc(r.reason || ""), sort: r.reason }]) })
        : '<p class="muted">No changes are recorded for this figure.</p>');
    wireTables(p.body);
  } catch (e) { p.body.innerHTML = `<p class="notice">${esc(e.message)}</p>`; }
}
const fmt = (v) => (v === null || v === undefined ? "-" : typeof v === "number" ? n0(v, 4) : typeof v === "object" ? JSON.stringify(v) : String(v));

// ---------------------------------------------------------------- import

async function importPart(box, ctx, alive) {
  let tpl = null;
  try { tpl = await ctx.api.templates(); } catch (e) { tpl = { entities: [] }; }
  if (!alive()) return;
  const ents = tpl.entities || [];
  const targets = [];
  if (ctx.internal) targets.push(["baseline", "The baseline (draft)"]);
  targets.push(["consultant", "A new consultant submission"]);
  ctx.datasets.filter((d) => d.kind !== "baseline").forEach((d) => targets.push([d.id, `${d.label} (${d.kind === "scenario" ? "scenario" : "consultant submission"})`]));
  box.innerHTML = `<p class="lead">Pick a CSV or Excel file. It is checked first; nothing changes until you commit it.</p>
    <div class="dz-grid2">
      <form class="card dz-form" data-check>
        <h2>1. Check a file</h2>
        <label class="field"><span>File (CSV or Excel)</span><input type="file" accept=".csv,.xlsx" required></label>
        <label class="field"><span>What the file holds (needed for a CSV; an Excel sheet is matched by its name)</span><select name="entity"><option value="">Match by sheet name</option>${opts(ents.map((e) => [e, fieldWords(e)]))}</select></label>
        <button class="btn primary" type="submit">Check the file</button><p class="dz-status" role="status" aria-live="polite"></p>
      </form>
      <div class="card"><h2>Templates</h2><p>Start from a template so the columns match.</p>
        <p class="dz-row"><a class="btn small" href="${ctx.api.templateUrl("workbook.xlsx")}" download>Excel workbook, every sheet</a><a class="btn small" href="${ctx.api.templateUrl("dictionary.csv")}" download>Data dictionary (CSV)</a></p>
        <details class="calm-fold"><summary>Show one CSV per kind of record</summary><div class="calm-fold-body"><ul class="plain">${ents.map((e) => `<li><a href="${ctx.api.templateUrl(e + ".csv")}" download>${esc(fieldWords(e))} (${esc(e)}.csv)</a></li>`).join("")}</ul></div></details>
      </div>
    </div><div data-preview></div>`;
  const form = box.querySelector("[data-check]"), out = box.querySelector("[data-preview]");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const file = fileOf(form), status = form.querySelector(".dz-status");
    if (!file) return say(status, "Pick a file first.", "bad");
    say(status, "Checking the file…", "busy");
    try {
      const pv = await ctx.api.importPreview(ctx.project.id, file, file.name, form.entity.value);
      say(status, "");
      showPreview(out, pv, ctx, targets);
    } catch (err) { say(status, err.message, "bad"); }
  });
}
function showPreview(out, pv, ctx, targets) {
  const ents = Object.entries(pv.entities || {});
  out.innerHTML = `<section class="card dz-block" style="margin-top:16px">
    <h2>2. What the check found in ${esc(pv.file || "the file")}</h2>
    <div class="dz-kv"><span><b class="dz-big">${n0(pv.rows_ok || 0)}</b> ${pv.rows_ok === 1 ? "row" : "rows"} ready</span><span><b class="dz-big ${pv.rows_rejected ? "dz-bad" : ""}">${n0(pv.rows_rejected || 0)}</b> ${pv.rows_rejected === 1 ? "row" : "rows"} refused</span></div>
    ${(pv.errors || []).length ? `<ul class="plain dz-bad">${pv.errors.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
    ${ents.map(([name, r]) => `<h3 style="margin-top:16px">${esc(fieldWords(name))}: ${n0(r.rows_ok || 0)} ready, ${n0(r.rows_rejected || 0)} refused</h3>
      ${(r.unknown_columns || []).length ? `<p>Columns not used (not in the template): ${r.unknown_columns.map((c) => chip(c, "warn")).join(" ")}</p>` : ""}
      ${(r.missing_columns || []).length ? `<p>Columns missing: ${r.missing_columns.map((c) => chip(c, "warn")).join(" ")}</p>` : ""}
      ${(r.rejected || []).length ? `<details class="calm-fold" open><summary>Why ${r.rejected.length} ${r.rejected.length === 1 ? "row was" : "rows were"} refused</summary><div class="calm-fold-body">${tableHtml({ caption: "Refused rows", columns: [{ label: "Row", num: true }, { label: "Why" }],
        rows: r.rejected.map((x) => [{ html: esc(x.row), sort: x.row }, { html: esc((x.errors || []).join("; ")), sort: "" }]) })}</div></details>` : ""}
      ${(r.sample || []).length ? `<details class="calm-fold"><summary>Show the first ${r.sample.length} clean rows</summary><div class="calm-fold-body">${sampleTable(name, r.sample)}</div></details>` : ""}`).join("")}
    ${pv.can_commit ? `<form class="dz-form" data-commit style="margin-top:18px;border-top:1px solid var(--line-soft);padding-top:14px">
      <h2>3. Commit</h2>
      <div class="dz-grid2"><label class="field"><span>Put it into</span><select name="target">${opts(targets)}</select></label>
        <label class="field" data-label-field><span>Name of the new submission</span><input name="label" value="${esc((pv.file || "Submission").replace(/\.[^.]+$/, ""))}"></label></div>
      <fieldset class="dz-fieldset"><legend>How</legend><div class="dz-checks">
        <label class="check"><input type="radio" name="mode" value="merge" checked> Add and update rows (keep the rest)</label>
        <label class="check"><input type="radio" name="mode" value="replace"> Replace those kinds of records completely</label></div></fieldset>
      <label class="field"><span>Reason (written to the revision log)</span><input name="reason" required></label>
      <button class="btn primary" type="submit">Commit ${n0(pv.rows_ok || 0)} ${pv.rows_ok === 1 ? "row" : "rows"}</button><p class="dz-status" role="status" aria-live="polite"></p></form>`
      : '<p class="notice">Nothing can be committed from this file. Fix the rows above and check it again.</p>'}</section>`;
  wireTables(out);
  const form = out.querySelector("[data-commit]");
  if (!form) return;
  const lab = form.querySelector("[data-label-field]");
  const sync = () => { lab.hidden = form.target.value !== "consultant"; };
  form.target.addEventListener("change", sync); sync();
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const status = form.querySelector(".dz-status");
    say(status, "Committing…", "busy");
    try {
      const ans = await ctx.api.importCommit(ctx.project.id, pv.import_id, { target: form.target.value, mode: form.mode.value, label: form.label.value, reason: form.reason.value });
      forget(ctx.project.id);
      const ds = ans.dataset && (ans.dataset.id || ans.dataset);
      const n = Object.values(ans.imported || {}).reduce((t, x) => t + Number(x || 0), 0);
      out.innerHTML = `<div class="card dz-calm" role="status"><h2>Imported ${n0(n)} rows</h2><p>They are in the draft of ${esc((ans.dataset && ans.dataset.label) || ds)}.</p>
        <p class="dz-row"><a class="btn primary" href="${ctx.link(["data", "compare"], { other: ds })}">Compare it with the baseline</a><a class="btn" href="${ctx.link(["data", "register"], { ds, v: "draft" })}">Open its register</a></p></div>`;
    } catch (err) { say(status, err.message, "bad"); }
  });
}
function sampleTable(entity, sample) {
  const cols = [...new Set(sample.flatMap((r) => Object.keys(r)))].filter((c) => !["tags", "city_safe"].includes(c)).slice(0, 10);
  const look = { uses: {}, phases: {}, phasesOrder: {} };
  return tableHtml({ caption: "Clean rows", columns: cols.map((c) => ({ label: fieldWords(c) })), rows: sample.map((r) => cols.map((c) => cell(entity, c, r, look))) });
}

// ---------------------------------------------------------------- compare

async function compare(box, ctx, alive) {
  const q = Object.fromEntries((location.hash.split("?")[1] || "").split("&").filter(Boolean).map((kv) => kv.split("=").map(decodeURIComponent)));
  const others = ctx.datasets.filter((d) => d.id !== "baseline");
  const thr = (ctx.project.settings && ctx.project.settings.compare_threshold_pct) || 10;
  const st = { base: "baseline", base_version: "published", other: q.other || (others[0] && others[0].id) || "baseline", other_version: "draft", threshold: thr };
  const dsOpts = ctx.datasets.map((d) => [d.id, d.label || d.id]);
  box.innerHTML = `<form class="card filters dz-filters" data-cmp>
      <label class="field"><span>Compare</span><select name="base">${opts(dsOpts, st.base)}</select></label>
      <label class="field"><span>Its version</span><select name="base_version">${opts([["published", "Published"], ["draft", "Draft"]], st.base_version)}</select></label>
      <label class="field"><span>With</span><select name="other">${opts(dsOpts, st.other)}</select></label>
      <label class="field"><span>Its version</span><select name="other_version">${opts([["draft", "Draft"], ["published", "Published"]], st.other_version)}</select></label>
      <label class="field"><span>Flag changes above (%)</span><input name="threshold" type="number" min="0" max="1000" step="1" value="${esc(st.threshold)}" style="width:110px"></label>
      <button class="btn primary" type="submit">Compare</button></form><div data-out></div>`;
  const form = box.querySelector("[data-cmp]"), out = box.querySelector("[data-out]");
  const run = async () => {
    const f = new FormData(form); Object.keys(st).forEach((k) => { st[k] = f.get(k); });
    out.innerHTML = loading("Comparing…");
    try {
      const c = await ctx.api.compare(ctx.project.id, st);
      if (!alive()) return;
      const changed = Object.entries(c.entities || {}).flatMap(([ent, x]) => (x.changed || []).map((ch) => ({ ent, ...ch })));
      const flagged = changed.filter((x) => x.flagged), rest = changed.filter((x) => !x.flagged);
      const adds = Object.entries(c.entities || {}).flatMap(([ent, x]) => (x.added || []).map((id) => [ent, id]));
      const gone = Object.entries(c.entities || {}).flatMap(([ent, x]) => (x.removed || []).map((id) => [ent, id]));
      const tbl = (list, cap) => tableHtml({ caption: cap, foldAfter: 12, columns: [{ label: "Kind" }, { label: "Record" }, { label: "Field" }, { label: "Was", num: true }, { label: "Now", num: true }, { label: "Change", num: true }],
        rows: list.map((x) => [{ html: esc(fieldWords(x.ent)), sort: x.ent }, { html: x.ent === "assumptions" ? `<button type="button" class="link" data-fig="${esc(x.id)}">${esc(x.id)}</button>` : esc(x.id), sort: x.id },
          { html: esc(fieldWords(x.field)), sort: x.field }, { html: esc(fmt(x.base)), sort: isNum(x.base) ? x.base : "" }, { html: esc(fmt(x.other)), sort: isNum(x.other) ? x.other : "" },
          { html: x.change_pct === null || x.change_pct === undefined ? (isNum(x.change) ? "from zero" : "changed") : `<span class="${x.change_pct >= 0 ? "dz-diff-up" : "dz-diff-down"}">${x.change_pct >= 0 ? "+" : ""}${nFix(x.change_pct, 1)}%</span>`, sort: isNum(x.change_pct) ? Math.abs(x.change_pct) : 1e9 }]) });
      out.innerHTML = `<p class="lead"><b>${n0(c.flagged || flagged.length)}</b> ${flagged.length === 1 ? "change is" : "changes are"} above ${esc(c.threshold_pct ?? st.threshold)}%, out of ${n0(c.changed || changed.length)} changed ${changed.length === 1 ? "value" : "values"}${adds.length ? `, ${adds.length} added` : ""}${gone.length ? `, ${gone.length} removed` : ""}.</p>
        ${flagged.length ? `<section class="dz-block"><h2>Above the threshold</h2>${tbl(flagged, "Changes above the threshold")}</section>` : '<div class="card dz-calm"><p>No change is above the threshold.</p></div>'}
        ${rest.length ? `<details class="calm-fold"><summary>Show the ${rest.length} smaller ${rest.length === 1 ? "change" : "changes"}</summary><div class="calm-fold-body">${tbl(rest, "Smaller changes")}</div></details>` : ""}
        ${adds.length ? `<details class="calm-fold"><summary>Show the ${adds.length} added ${adds.length === 1 ? "record" : "records"}</summary><div class="calm-fold-body"><ul class="plain">${adds.map(([e, id]) => `<li>${esc(fieldWords(e))}: ${esc(id)}</li>`).join("")}</ul></div></details>` : ""}
        ${gone.length ? `<details class="calm-fold"><summary>Show the ${gone.length} removed ${gone.length === 1 ? "record" : "records"}</summary><div class="calm-fold-body"><ul class="plain">${gone.map(([e, id]) => `<li>${esc(fieldWords(e))}: ${esc(id)}</li>`).join("")}</ul></div></details>` : ""}`;
    } catch (e) { out.innerHTML = `<p class="notice" role="alert">${esc(e.message)}</p>`; }
  };
  form.addEventListener("submit", (e) => { e.preventDefault(); run(); });
  box.addEventListener("click", (e) => { const f = e.target.closest("[data-fig]"); if (f) openFigure(ctx, f.dataset.fig); });
  run();
}

// ---------------------------------------------------------------- documents

async function documents(box, ctx, alive) {
  const ans = await ctx.api.documents(ctx.project.id);
  if (!alive()) return;
  const docs = ans.documents || [];
  const kb = (n) => (n >= 1048576 ? nFix(n / 1048576, 1) + " MB" : n0(Math.max(1, n / 1024)) + " KB");
  box.innerHTML = `<p class="lead">${docs.length ? `${docs.length} ${docs.length === 1 ? "document" : "documents"} in the library.` : "The library is empty."}</p>
    <div class="dz-grid2"><ul class="dz-list">${docs.map((d) => {
      const vs = (d.versions || []).slice().reverse(), last = vs[0] || {};
      return `<li class="card"><h3>${esc(d.title || d.id)}</h3>
        <p class="dz-kv"><span>${esc((d.kind || "").toUpperCase())}</span>${d.task ? `<span>${esc(d.task)}</span>` : ""}<span>Version <b>${esc(last.version || 1)}</b></span>${last.size ? `<span><b>${kb(last.size)}</b></span>` : ""}<span>${esc(when(last.uploaded_at))}${last.uploaded_by_name ? " by " + esc(last.uploaded_by_name) : ""}</span></p>
        <p class="dz-kv"><span>Who may see it:</span>${(d.audiences || []).map((a) => chip((AUD.find((x) => x[0] === a) || [a, a])[1])).join(" ")}</p>
        <p class="dz-row"><button type="button" class="btn small primary" data-dl="${esc(d.id)}" data-v="latest">Download</button>${ctx.can["documents.share"] ? `<button type="button" class="btn small" data-share="${esc(d.id)}">Who may see it</button>` : ""}</p>
        ${vs.length > 1 ? `<details class="calm-fold"><summary>Show all ${vs.length} versions</summary><div class="calm-fold-body"><ul class="plain">${vs.map((v) => `<li>Version ${esc(v.version)}, ${esc(when(v.uploaded_at))}${v.note ? ": " + esc(v.note) : ""} <button type="button" class="link" data-dl="${esc(d.id)}" data-v="${esc(v.version)}">Download</button></li>`).join("")}</ul></div></details>` : ""}</li>`;
    }).join("")}</ul>
    ${ctx.can["documents.upload"] ? `<form class="card dz-form" data-up><h2>Add a document</h2>
      <label class="field"><span>File (PDF, PPTX, XLSX, DOCX or CSV)</span><input type="file" accept=".pdf,.pptx,.xlsx,.docx,.csv" required></label>
      <label class="field"><span>Title</span><input name="title"></label>
      <label class="field"><span>Scope-of-work task</span><input name="task" placeholder="Task 1"></label>
      <label class="field"><span>A new version of</span><select name="document"><option value="">Nothing: a new document</option>${opts(docs.map((d) => [d.id, d.title || d.id]))}</select></label>
      <label class="field"><span>Note</span><input name="note"></label>
      <button class="btn primary" type="submit">Upload</button><p class="dz-status" role="status" aria-live="polite"></p></form>` : ""}</div>`;
  box.addEventListener("click", async (e) => {
    const dl = e.target.closest("[data-dl]");
    if (dl) { try { await ctx.api.downloadDocument(ctx.project.id, dl.dataset.dl, dl.dataset.v); } catch (err) { toast(err.message); } return; }
    const sh = e.target.closest("[data-share]");
    if (sh) {
      const d = docs.find((x) => x.id === sh.dataset.share), p = panel(`Who may see ${d.title || d.id}`);
      p.body.innerHTML = `<form class="dz-form"><fieldset class="dz-fieldset"><legend>Audiences</legend><div class="dz-checks">${AUD.map(([a, w]) => `<label class="check"><input type="checkbox" name="a" value="${a}"${(d.audiences || []).includes(a) ? " checked" : ""}> ${w}</label>`).join("")}</div></fieldset>
        <button class="btn primary" type="submit">Save</button><p class="dz-status" role="status"></p></form>`;
      const f = p.body.querySelector("form");
      f.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        try { await ctx.api.shareDocument(ctx.project.id, d.id, [...f.querySelectorAll("[name=a]:checked")].map((x) => x.value)); p.close(); documents(box, ctx, alive); }
        catch (err) { say(f.querySelector(".dz-status"), err.message, "bad"); }
      });
    }
  });
  const up = box.querySelector("[data-up]");
  if (up) up.addEventListener("submit", async (e) => {
    e.preventDefault();
    const file = fileOf(up), status = up.querySelector(".dz-status");
    if (!file) return say(status, "Pick a file first.", "bad");
    say(status, "Uploading…", "busy");
    try {
      await ctx.api.uploadDocument(ctx.project.id, file, { name: file.name, title: up.title.value, task: up.task.value, document: up.document.value, note: up.note.value });
      toast("Uploaded."); documents(box, ctx, alive);
    } catch (err) { say(status, err.message, "bad"); }
  });
}

// ---------------------------------------------------------------- map layers

async function layers(box, ctx, alive) {
  const ans = await ctx.api.layers(ctx.project.id);
  if (!alive()) return;
  const list = (ans.layers || []).filter((l) => !l.removed);
  const KIND = { trade_area: "Trade area", competitors: "Competitors", parcels: "Parcels", other: "Other" };
  box.innerHTML = `<p class="lead">${list.length ? `${list.length} map ${list.length === 1 ? "layer" : "layers"}.` : "No map layers yet."} The Map tool draws them.</p>
    <div class="dz-grid2"><ul class="dz-list">${list.map((l) => `<li class="card"><h3>${esc(l.label || l.id)}</h3>
      <p class="dz-kv"><span>${esc(KIND[l.kind] || l.kind || "")}</span><span><b>${n0(l.features || 0)}</b> shapes</span><span>${esc(when(l.uploaded_at))}</span></p>
      ${(l.warnings || []).length ? `<p class="fine">${l.warnings.map(esc).join(" ")}</p>` : ""}
      ${ctx.can["gis.remove"] ? `<p><button type="button" class="btn small" data-rm="${esc(l.id)}">Remove from the map</button></p>` : ""}</li>`).join("")}</ul>
    ${ctx.can["gis.upload"] ? `<form class="card dz-form" data-up><h2>Add a layer</h2>
      <label class="field"><span>GeoJSON, or a zipped shapefile</span><input type="file" accept=".geojson,.json,.zip" required></label>
      <label class="field"><span>Name</span><input name="label"></label>
      <label class="field"><span>Kind</span><select name="kind">${opts(Object.entries(KIND))}</select></label>
      <button class="btn primary" type="submit">Upload</button><p class="dz-status" role="status" aria-live="polite"></p></form>` : ""}</div>`;
  box.addEventListener("click", async (e) => {
    const rm = e.target.closest("[data-rm]");
    if (!rm) return;
    if (rm.dataset.sure !== "1") { rm.dataset.sure = "1"; rm.textContent = "Press again to remove"; return; }
    try { await ctx.api.removeLayer(ctx.project.id, rm.dataset.rm); toast("Removed from the map. The file is kept."); layers(box, ctx, alive); }
    catch (err) { toast(err.message); }
  });
  const up = box.querySelector("[data-up]");
  if (up) up.addEventListener("submit", async (e) => {
    e.preventDefault();
    const file = fileOf(up), status = up.querySelector(".dz-status");
    if (!file) return say(status, "Pick a file first.", "bad");
    say(status, "Uploading…", "busy");
    try {
      const r = await ctx.api.uploadLayer(ctx.project.id, file, { name: file.name, kind: up.kind.value, label: up.label.value });
      toast("Layer added." + ((r.warnings || []).length ? " " + r.warnings.join(" ") : "")); layers(box, ctx, alive);
    } catch (err) { say(status, err.message, "bad"); }
  });
}

// ---------------------------------------------------------------- data sources, one at a time

async function sources(box, ctx) {
  const list = (ctx.content.entities || {}).data_sources || [];
  if (!list.length) { box.innerHTML = '<div class="card dz-calm"><p>No data sources are described in this dataset.</p></div>'; return; }
  let i = 0;
  const draw = () => {
    const s = list[i];
    const rows = [["Who publishes it", s.provider], ["Where", s.url && /^https?:\/\//.test(s.url) ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.url)}</a>` : esc(s.url || "")],
      ["How to get it", esc(s.how_to_get || "")], ["How often", esc(s.cadence || "")], ["How a new copy is checked", esc(s.validation || "")],
      ["Terms", esc(s.license || "")], ["Last read", esc(day(s.last_refreshed))], ["Keeps it current", esc(s.owner || "")], ["Note", esc(s.note || "")]];
    box.innerHTML = `<p class="lead">${list.length} data sources: where each comes from, how to get it and how often it is refreshed.</p>
      <div class="dz-qa-grid"><article class="dz-qa-main"><p class="dz-qa-count">Source ${i + 1} of ${list.length}</p><h2 class="dz-qa-q" tabindex="-1">${esc(s.name)}</h2>
        <dl class="facts">${rows.filter((r) => r[1]).map((r) => `<dt>${r[0]}</dt><dd>${r[0] === "Who publishes it" ? esc(r[1]) : r[1]}</dd>`).join("")}</dl>
        <div class="dz-qa-nav"><button type="button" class="btn" data-step="-1"${i ? "" : " disabled"}>Previous</button><button type="button" class="btn primary" data-step="1"${i < list.length - 1 ? "" : " disabled"}>Next source</button></div></article>
        <nav class="dz-qa-side" aria-label="All sources"><ol class="dz-qa-list">${list.map((x, k) => `<li><button type="button" data-go="${k}"${k === i ? ' class="on" aria-current="true"' : ""}><small>${k + 1}</small><span>${esc(x.name)}</span></button></li>`).join("")}</ol></nav></div>`;
  };
  box.addEventListener("click", (e) => {
    const s = e.target.closest("[data-step]"), g = e.target.closest("[data-go]");
    if (!s && !g) return;
    i = g ? Number(g.dataset.go) : Math.max(0, Math.min(list.length - 1, i + Number(s.dataset.step)));
    draw(); box.querySelector(".dz-qa-q").focus({ preventScroll: true });
  });
  draw();
}

// ---------------------------------------------------------------- notes

async function notes(box, ctx, alive) {
  let status = "open";
  const draw = async () => {
    box.innerHTML = loading("Reading the notes…");
    const ans = await ctx.api.notes(ctx.project.id, { status });
    if (!alive()) return;
    const list = ans.notes || [];
    box.innerHTML = `<div class="dz-seg" role="radiogroup" aria-label="Which notes" style="margin-bottom:14px">${[["open", "Open"], ["resolved", "Resolved"]].map(([s, w]) => `<button type="button" role="radio" aria-checked="${s === status}" data-st="${s}"${s === status ? ' class="on"' : ""}>${w}</button>`).join("")}</div>
      <p class="lead">${list.length ? `${list.length} ${status} ${list.length === 1 ? "note" : "notes"}.` : `No ${status} notes.`}</p>
      <ul class="dz-notes">${list.map((n) => `<li class="dz-note"><p class="dz-note-head"><b>${esc(n.by_name || n.name || "")}</b> <small>${esc(when(n.at))}</small> on
        ${n.target && n.target.entity === "assumptions" ? `<button type="button" class="link" data-fig="${esc(n.target.id)}">${esc(n.target.id)}</button>` : esc(n.target ? `${fieldWords(n.target.entity)} ${n.target.id}` : "")}</p>
        <p>${esc(n.text)}</p>${(n.replies || []).length ? `<p class="fine">${n.replies.length} ${n.replies.length === 1 ? "reply" : "replies"}. Open the figure to read them.</p>` : ""}
        ${n.resolution ? `<p class="fine">Resolution: ${esc(n.resolution)}</p>` : ""}</li>`).join("")}</ul>`;
  };
  box.addEventListener("click", (e) => {
    const s = e.target.closest("[data-st]"); if (s) { status = s.dataset.st; draw(); return; }
    const f = e.target.closest("[data-fig]"); if (f) openFigure(ctx, f.dataset.fig);
  });
  await draw();
}

// ---------------------------------------------------------------- checks

async function checks(box, ctx, alive) {
  const c = await ctx.api.checks(ctx.project.id, ctx.dataset, { version: ctx.version });
  if (!alive()) return;
  const look = lookupsOf(ctx.content);
  const recs = c.reconciliations || [];
  const off = recs.filter((r) => !r.within_tolerance);
  const groups = [
    ["unregistered", "Figures without a register entry", "Every figure on a page has a register entry."],
    ["uncited", "Figures nothing cites", "Every register entry is used somewhere."],
    ["conflicts", "Figures whose sources disagree", "No register entry has a recorded conflict."],
    ["superseded_in_use", "Superseded figures still in use", "No superseded figure is still in use."],
    ["untagged_sensitive", "Words that sound sensitive but are not tagged", "Everything that sounds sensitive is tagged."],
  ];
  const itemWords = (x) => {
    if (typeof x === "string") return esc(x);
    const id = x.id || x.assumption || "", label = x.label || x.heading || "";
    const extra = x.conflict_note || x.where || (x.sounds_like ? "sounds like " + x.sounds_like.join(", ") : "") || (x.superseded_by ? "replaced by " + x.superseded_by : "") || (x.used_by ? "used by " + [].concat(x.used_by).map((u) => (typeof u === "string" ? u : u.module || u.id)).join(", ") : "");
    const idHtml = look.assumptions[id] ? `<button type="button" class="link" data-fig="${esc(id)}">${esc(id)}</button>` : esc([x.entity ? fieldWords(x.entity) : "", id].filter(Boolean).join(" "));
    return `${idHtml}${label ? ": " + esc(label) : ""}${extra ? ` <small class="muted">(${esc(extra)})</small>` : ""}`;
  };
  const total = groups.reduce((t, g) => t + (c[g[0]] || []).length, 0) + off.length;
  box.innerHTML = `${viewBar(ctx)}<p class="lead">${total ? `${total} ${total === 1 ? "thing needs" : "things need"} a look in this dataset.` : "Everything checks out in this dataset."}</p>
    <section class="dz-block"><h2>Figures that should add up</h2>${recs.length ? `<ul class="dz-list">${recs.map((r) => {
      const t = look.assumptions[r.total_id || r.total], unit = t ? t.unit : "";
      return `<li class="card"><p><b>${esc(r.label)}</b> ${r.within_tolerance ? '<span class="dz-chip">Adds up</span>' : '<span class="dz-chip warn">Does not add up</span>'}</p>
        <p class="dz-kv"><span>Total <b>${esc(valueIn(r.total, unit))}</b></span><span>Parts <b>${esc(valueIn(r.parts_total, unit))}</b></span><span>Difference <b>${esc(valueIn(r.difference, unit))}</b>${isNum(r.difference_pct) ? ` (${nFix(r.difference_pct, 1)}%)` : ""}</span></p>
        ${r.within_tolerance ? "" : `<p>${r.explanation ? esc(r.explanation) : '<span class="muted">Not explained in the documents.</span>'}</p>`}</li>`;
    }).join("")}</ul>` : '<p class="muted">No reconciliations are defined.</p>'}</section>
    ${groups.map(([k, title, none]) => { const list = c[k] || []; return `<section class="dz-block"><h2>${esc(title)} <span class="muted">(${list.length})</span></h2>${list.length ? `<ul class="plain">${list.map((x) => `<li>${itemWords(x)}</li>`).join("")}</ul>` : `<p class="dz-ok">${esc(none)}</p>`}</section>`; }).join("")}`;
  wireViewBar(box, ctx);
  box.addEventListener("click", (e) => { const f = e.target.closest("[data-fig]"); if (f) openFigure(ctx, f.dataset.fig); });
}

// The requirements checklist that came with the project: how many are done, then every row with where it is met.
import { esc, debounce } from "../util.js";
import { viewBar, wireViewBar } from "./router.js";
import { exportButtons, wireExports } from "./exports.js";

const STATUS = [["done", "Done"], ["adapted", "Adapted"], ["needs-owner", "Needs the owner"], ["not-applicable", "Not applicable"], ["open", "Open"]];
const statusWords = (s) => (STATUS.find((x) => x[0] === s) || [s, s || "Open"])[1];
const PAGE = 25;

export async function render(el, ctx) {
  const all = ((ctx.content.entities || {}).requirements || []).map((r) => ({ ...r, status: r.status || "open" }));
  const docs = [...new Set(all.map((r) => r.source_document).filter(Boolean))].sort();
  const kinds = [...new Set(all.map((r) => r.kind).filter(Boolean))].sort();
  const count = (s) => all.filter((r) => r.status === s).length;
  const state = { q: "", doc: "", kind: "", status: "", shown: PAGE };
  const done = count("done") + count("adapted");
  el.innerHTML = `<header class="page-head"><p class="kicker">${esc(ctx.project.name || "")} · Requirements</p><h1>Requirements checklist</h1>
      <p class="lead">${all.length ? `${done} of ${all.length} requirements are met or adapted.` : "No requirements were loaded with this project."}</p></header>
    ${viewBar(ctx, { exports: all.length ? exportButtons(ctx, { entity: "requirements" }) : "" })}
    ${all.length ? `<div class="dz-counts" role="group" aria-label="Filter by status">${STATUS.map(([s, w]) => `<button type="button" class="dz-count s-${s}" data-status="${s}" aria-pressed="false"><b>${count(s)}</b><span>${w}</span></button>`).join("")}</div>
    <div class="card filters dz-filters">
      <label class="field grow"><span>Search</span><input type="search" data-q placeholder="Id or words"></label>
      <label class="field"><span>Document</span><select data-doc><option value="">All documents</option>${docs.map((d) => `<option>${esc(d)}</option>`).join("")}</select></label>
      <label class="field"><span>Kind</span><select data-kind><option value="">All kinds</option>${kinds.map((d) => `<option>${esc(d)}</option>`).join("")}</select></label>
      <label class="field"><span>Status</span><select data-st><option value="">All</option>${STATUS.map(([s, w]) => `<option value="${s}">${w}</option>`).join("")}</select></label>
    </div>
    <p class="dz-shown" role="status" aria-live="polite"></p><ul class="dz-reqs"></ul><div class="dz-more"></div>` : '<div class="card dz-calm"><p>The checklist is empty: no requirements are in this dataset.</p></div>'}`;
  wireViewBar(el, ctx);
  wireExports(el, ctx);
  if (!all.length) return;
  const list = el.querySelector(".dz-reqs"), shown = el.querySelector(".dz-shown"), more = el.querySelector(".dz-more");
  function draw() {
    const q = state.q.toLowerCase();
    const rows = all.filter((r) => (!state.doc || r.source_document === state.doc) && (!state.kind || r.kind === state.kind) && (!state.status || r.status === state.status) &&
      (!q || [r.id, r.text, r.note, r.section].join(" ").toLowerCase().includes(q)));
    shown.textContent = rows.length === all.length ? `Showing all ${all.length}.` : `Showing ${rows.length} of ${all.length}.`;
    list.innerHTML = rows.slice(0, state.shown).map((r) => `<li class="dz-req s-${esc(r.status)}">
      <div class="dz-req-id"><b>${esc(r.id)}</b><small>${esc([r.source_document, r.section].filter(Boolean).join(" · "))}</small></div>
      <div class="dz-req-text"><p>${esc(r.text || "")}</p>${r.note ? `<details class="calm-fold"><summary>Show the note</summary><div class="calm-fold-body"><p>${esc(r.note)}</p></div></details>` : ""}</div>
      <div class="dz-req-end"><span class="dz-chip st-${esc(r.status)}">${esc(statusWords(r.status))}</span>${r.kind ? `<small>${esc(r.kind)}</small>` : ""}
        ${r.where_in_app && /^#\/districts\//.test(r.where_in_app) ? `<a href="${esc(r.where_in_app)}">Where it is met</a>` : ""}</div></li>`).join("") ||
      '<li class="dz-req none"><p class="muted">No requirement matches. Clear a filter to see more.</p></li>';
    more.innerHTML = rows.length > state.shown ? `<button type="button" class="btn" data-more>Show ${Math.min(PAGE, rows.length - state.shown)} more</button>` : "";
    el.querySelectorAll("[data-status]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.status === state.status)));
    el.querySelector("[data-st]").value = state.status;
  }
  const typed = debounce(() => { state.shown = PAGE; draw(); }, 150);
  el.querySelector("[data-q]").addEventListener("input", (e) => { state.q = e.target.value; typed(); });
  el.addEventListener("change", (e) => {
    if (e.target.matches("[data-doc]")) state.doc = e.target.value;
    else if (e.target.matches("[data-kind]")) state.kind = e.target.value;
    else if (e.target.matches("[data-st]")) state.status = e.target.value;
    else return;
    state.shown = PAGE; draw();
  });
  el.addEventListener("click", (e) => {
    const s = e.target.closest("[data-status]");
    if (s) { state.status = state.status === s.dataset.status ? "" : s.dataset.status; state.shown = PAGE; draw(); }
    if (e.target.closest("[data-more]")) { state.shown += PAGE; draw(); }
  });
  draw();
}

// "Where this number comes from": the register entry behind a figure, what uses it, and the notes on it.
import { esc, panel, figureWords, valueIn, day, when, say, has, isNum } from "./ui.js";

const STATUS_HELP = { Baseline: "the project's own figure", Consultant: "from a consultant", "Legacy Assumption": "an older assumption still in use", Superseded: "replaced by a newer figure" };

function usedWords(u, ctx) {
  if (typeof u === "string") return esc(u);
  if (!u || typeof u !== "object") return "";
  const e = (ctx.content && ctx.content.entities) || {};
  const mod = ctx.modules.find((m) => m.id === u.module);
  const page = mod ? mod.label || mod.id : u.module || "";
  const href = mod ? ctx.link(["m", mod.id]) : "";
  let what = u.id || "";
  if (u.kind === "card" && mod) { const c = (mod.cards || []).find((x) => x.id === u.id); what = "card " + (c ? c.label : u.id); }
  else if (u.kind === "section") { const sct = (e.sections || []).find((x) => x.id === u.id); what = sct && sct.heading ? sct.heading : "text " + u.id; }
  else if (u.kind === "reconciliation") { const r = (e.reconciliations || []).find((x) => x.id === u.id); return esc("Check that adds up: " + (r ? r.label : u.id)); }
  else if (u.kind) what = `${u.kind.replace(/_/g, " ")} ${u.id || ""}`;
  const text = page ? `${page} page: ${what}` : what;
  return href ? `<a href="${esc(href)}">${esc(text)}</a>` : esc(text);
}

function noteHtml(n, ctx) {
  const resolved = n.status === "resolved";
  const replies = (n.replies || []).map((r) => `<li><p>${esc(r.text)}</p><small>${esc(r.by_name || r.name || r.user || "")} · ${esc(when(r.at))}</small></li>`).join("");
  return `<li class="dz-note${resolved ? " resolved" : ""}" data-note="${esc(n.id)}">
    <p class="dz-note-head"><b>${esc(n.by_name || n.name || n.user || "Someone")}</b> <small>${esc(when(n.at))}</small> ${resolved ? '<span class="dz-chip">Resolved</span>' : '<span class="dz-chip gold">Open</span>'}</p>
    <p>${esc(n.text)}</p>
    ${n.resolution ? `<p class="fine">Resolution: ${esc(n.resolution)}</p>` : ""}
    ${replies ? `<ul class="dz-replies">${replies}</ul>` : ""}
    <div class="dz-note-actions">
      ${ctx.can["notes.write"] ? `<button type="button" class="btn small" data-reply>Reply</button>` : ""}
      ${ctx.can["notes.resolve"] ? `<button type="button" class="btn small" data-resolve="${resolved ? "open" : "resolved"}">${resolved ? "Open again" : "Mark resolved"}</button>` : ""}
    </div></li>`;
}

export async function openFigure(ctx, id) {
  const p = panel("Where this number comes from", { wide: false });
  p.body.innerHTML = '<div class="state loading" role="status"><span class="spinner" aria-hidden="true"></span><p>Reading the register…</p></div>';
  const params = { version: ctx.version, audience: ctx.viewAs || "" };
  const load = async () => {
    let ans;
    try { ans = await ctx.api.figure(ctx.project.id, ctx.dataset, id, params); }
    catch (e) {
      p.body.innerHTML = `<p class="notice">${esc(e.status === 404 ? `The register has no entry ${id} in this dataset${ctx.viewAs ? " for this audience" : ""}.` : e.message)}</p>`;
      return;
    }
    if (!p.aside.isConnected) return;
    const f = ans.figure || {};
    if (!ans.found && !f.id) { p.body.innerHTML = `<p class="notice">The register has no entry ${esc(id)} in this dataset. The figure is shown without a source.</p>`; return; }
    const words = figureWords(f, null);
    const rows = [
      ["Register entry", `<code>${esc(f.id || id)}</code>`],
      ["Value and unit", esc(f.display || words.main) + (words.aside ? ` <span class="muted">(${esc(words.aside)})</span>` : "") +
        (isNum(f.value_low) && isNum(f.value_high) && isNum(f.value) ? `<br><small>Range ${esc(valueIn(f.value_low, f.unit))} to ${esc(valueIn(f.value_high, f.unit))}</small>` : "")],
      ["Status", f.status ? `${esc(f.status)} <small class="muted">${esc(STATUS_HELP[f.status] || "")}</small>` : ""],
      ["Provenance", f.provenance ? `<span class="dz-prov">${esc(f.provenance)}</span>` : ""],
      ["Source document", esc(f.source_doc || "")], ["Source model", esc(f.source_model || "")],
      ["As of", esc(day(f.as_of))], ["Owner", esc(f.owner || "")], ["Confidence", esc(f.confidence || "")],
      ["Conflict", f.conflict ? `<span class="dz-chip warn">Sources disagree</span>${f.conflict_note ? `<br>${esc(f.conflict_note)}` : ""}` : "No conflict recorded"],
    ];
    if (f.superseded_by) rows.push(["Replaced by", `<button type="button" class="link" data-fig="${esc(f.superseded_by)}">${esc(f.superseded_by)}</button>`]);
    const used = (ans.used_by || []).map((u) => usedWords(u, ctx)).filter(Boolean);
    const notes = ans.notes || [];
    p.body.innerHTML = `<p class="dp-label">${esc(f.label || id)}</p><p class="dp-value">${esc(f.display || words.main)}</p>
      ${f.description ? `<p>${esc(f.description)}</p>` : ""}
      <dl class="facts dp-facts">${rows.filter((r) => has(r[1])).map((r) => `<dt>${r[0]}</dt><dd>${r[1]}</dd>`).join("")}</dl>
      ${f.note ? `<p class="fine">Note: ${esc(f.note)}</p>` : ""}
      <h3 class="dp-sub">What uses it</h3>
      ${used.length ? `<ul class="plain">${used.map((u) => `<li>${u}</li>`).join("")}</ul>` : '<p class="muted">Nothing else in the package cites this entry.</p>'}
      ${ctx.can["notes.read"] ? `<h3 class="dp-sub">Notes and comments</h3>
        ${notes.length ? `<ul class="dz-notes">${notes.map((n) => noteHtml(n, ctx)).join("")}</ul>` : '<p class="muted">No notes on this figure yet.</p>'}
        ${ctx.can["notes.write"] ? `<form class="dz-form" data-add><label class="field"><span>Add a note</span><textarea name="text" rows="3" required maxlength="4000"></textarea></label><button class="btn primary small" type="submit">Add the note</button><p class="dz-status" role="status" aria-live="polite"></p></form>` : ""}` : ""}`;
    const target = { dataset: ctx.dataset, entity: "assumptions", id: f.id || id };
    const add = p.body.querySelector("[data-add]");
    if (add) add.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = add.elements.text.value.trim();
      if (!text) return;
      try { await ctx.api.addNote(ctx.project.id, target, text); await load(); }
      catch (err) { say(add.querySelector(".dz-status"), err.message, "bad"); }
    });
  };
  p.body.addEventListener("click", async (e) => {
    const fig = e.target.closest("[data-fig]");
    if (fig) { openFigure(ctx, fig.dataset.fig); return; }
    const li = e.target.closest("[data-note]");
    if (!li) return;
    const nid = li.dataset.note;
    if (e.target.closest("[data-reply]")) {
      if (li.querySelector("form")) return;
      li.insertAdjacentHTML("beforeend", `<form class="dz-form dz-reply"><label class="field"><span>Your reply</span><textarea name="text" rows="2" required></textarea></label><button class="btn small primary" type="submit">Send the reply</button><p class="dz-status" role="status"></p></form>`);
      const f = li.querySelector("form");
      f.elements.text.focus();
      f.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        try { await ctx.api.reply(ctx.project.id, nid, f.elements.text.value.trim()); await load(); }
        catch (err) { say(f.querySelector(".dz-status"), err.message, "bad"); }
      });
    }
    const r = e.target.closest("[data-resolve]");
    if (r) {
      try { await ctx.api.resolveNote(ctx.project.id, nid, r.dataset.resolve, ""); await load(); }
      catch (err) { li.insertAdjacentHTML("beforeend", `<p class="dz-status bad">${esc(err.message)}</p>`); }
    }
  });
  await load();
}

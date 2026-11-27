// Administration: users, the audit log, settings, backups, the project file, and publishing or rolling back a dataset.
// Only administrators see it; the server refuses everyone else anyway.
import { esc, n0, nFix, tableHtml, wireTables, panel, say, chip, when, day } from "./ui.js";
import { ADMIN_PARTS, roleWords, forget } from "./router.js";
import { debounce, loading, toast } from "../util.js";

const ROLES = ["administrator", "analyst", "consultant", "viewer_partner", "viewer_city"];
const opts = (list, cur) => list.map((x) => { const [v, w] = Array.isArray(x) ? x : [x, x]; return `<option value="${esc(v)}"${String(cur) === String(v) ? " selected" : ""}>${esc(w)}</option>`; }).join("");
const kb = (n) => (n >= 1048576 ? nFix(n / 1048576, 1) + " MB" : n0(Math.max(1, n / 1024)) + " KB");

export async function render(el, ctx, part, alive) {
  if (!ctx.can["users.manage"]) {
    el.innerHTML = `<header class="page-head"><h1>Admin</h1></header><div class="card dz-calm"><p>Only an administrator can open this part of the workspace.</p></div>`;
    return;
  }
  const cur = ADMIN_PARTS.find((p) => p[0] === part) || ADMIN_PARTS[0];
  el.innerHTML = `<header class="page-head"><p class="kicker">${esc(ctx.project.name || "")} · Admin</p><h1>${esc(cur[1])}</h1></header>
    <nav class="dz-sub-nav" aria-label="Admin">${ADMIN_PARTS.map(([id, w]) => `<a href="${ctx.link(["admin", id])}"${id === cur[0] ? ' class="on" aria-current="page"' : ""}>${esc(w)}</a>`).join("")}</nav>
    <div class="dz-data"></div>`;
  const box = el.querySelector(".dz-data");
  wireTables(el);
  try { await { users, audit, settings, backups, file, publish }[cur[0]](box, ctx, alive); }
  catch (e) { console.error(e); if (alive()) box.innerHTML = `<div class="state problem" role="alert"><p>${esc(e.message || "This part could not be shown.")}</p></div>`; }
}

// ---------------------------------------------------------------- users

async function users(box, ctx, alive) {
  const [u, pr] = await Promise.all([ctx.api.users(), ctx.api.projects()]);
  if (!alive()) return;
  const list = u.users || [], projects = pr.projects || [];
  const active = list.filter((x) => x.status !== "INACTIVE");
  box.innerHTML = `<p class="lead">${active.length} active ${active.length === 1 ? "person" : "people"}${list.length > active.length ? `, ${list.length - active.length} turned off` : ""}.</p>
    <p><button type="button" class="btn primary" data-new>Add a person</button></p>
    ${tableHtml({ caption: "People who may sign in", foldAfter: 30, columns: [{ label: "Name" }, { label: "Role" }, { label: "Projects" }, { label: "Status" }, { label: "Last sign-in" }, { label: "" }],
      rows: list.map((x) => [{ html: `<b>${esc(x.name)}</b>${x.email ? `<small>${esc(x.email)}</small>` : ""}`, sort: x.name }, { html: esc(roleWords(x.role)), sort: x.role },
        { html: esc((x.projects || []).includes("*") ? "All projects" : (x.projects || []).map((p) => (projects.find((q) => q.id === p) || { name: p }).name).join(", ") || "None"), sort: "" },
        { html: x.status === "INACTIVE" ? chip("Turned off", "warn") : chip("Active"), sort: x.status }, { html: esc(when(x.last_sign_in) || "Never"), sort: x.last_sign_in || "" },
        { html: `<button type="button" class="btn small" data-edit="${esc(x.id)}">Change</button>`, sort: "" }]) })}
    <div class="dz-sessions" data-sessions style="margin-top:28px"></div>`;
  signedIn(box.querySelector("[data-sessions]"), alive).catch((e) => { if (alive()) box.querySelector("[data-sessions]").innerHTML = `<p class="dz-bad">${esc(e.message)}</p>`; });
  box.addEventListener("click", (e) => {
    if (e.target.closest("[data-new]")) return userForm(ctx, null, projects, () => users(box, ctx, alive));
    const ed = e.target.closest("[data-edit]");
    if (ed) userForm(ctx, list.find((x) => x.id === ed.dataset.edit), projects, () => users(box, ctx, alive));
  });
}
function userForm(ctx, user, projects, done) {
  const p = panel(user ? `Change ${user.name}` : "Add a person");
  const all = !user || (user.projects || []).includes("*");
  p.body.innerHTML = `<form class="dz-form">
    <label class="field"><span>Name</span><input name="name" required value="${esc(user ? user.name : "")}"></label>
    <label class="field"><span>Google e-mail (for "Continue with Google")</span><input name="email" type="email" value="${esc(user && user.email ? user.email : "")}"></label>
    <label class="field"><span>Role</span><select name="role">${opts(ROLES.map((r) => [r, roleWords(r)]), user ? user.role : "viewer_partner")}</select></label>
    <fieldset class="dz-fieldset"><legend>Projects a consultant or viewer may open</legend><div class="dz-checks">
      <label class="check"><input type="checkbox" name="all"${all ? " checked" : ""}> All projects</label>
      ${projects.map((q) => `<label class="check"><input type="checkbox" name="p" value="${esc(q.id)}"${user && (user.projects || []).includes(q.id) ? " checked" : ""}> ${esc(q.name || q.id)}</label>`).join("")}</div></fieldset>
    <label class="field"><span>${user && user.has_passcode ? "New passcode (leave empty to keep it)" : "Passcode (at least 8 characters)"}</span><input name="passcode" type="password" autocomplete="new-password" minlength="8"></label>
    ${user ? `<label class="check"><input type="checkbox" name="off"${user.status === "INACTIVE" ? " checked" : ""}> Turned off: this person cannot sign in</label>` : ""}
    <div class="dz-row"><button class="btn primary" type="submit">${user ? "Save" : "Add"}</button>${user ? '<button class="btn danger" type="button" data-remove>Remove</button>' : ""}</div>
    <p class="dz-status" role="status" aria-live="polite"></p></form>`;
  const f = p.body.querySelector("form"), status = f.querySelector(".dz-status");
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = { name: f.name.value.trim(), email: f.email.value.trim() || null, role: f.role.value,
      projects: f.all.checked ? ["*"] : [...f.querySelectorAll("[name=p]:checked")].map((x) => x.value) };
    if (user) { body.id = user.id; body.status = f.off && f.off.checked ? "INACTIVE" : "ACTIVE"; }
    if (f.passcode.value) body.passcode = f.passcode.value;
    say(status, "Saving…", "busy");
    try { await ctx.api.saveUser(body); p.close(); toast(user ? "Saved." : "Added."); done(); }
    catch (err) { say(status, err.message, "bad"); }
  });
  const rm = f.querySelector("[data-remove]");
  if (rm) rm.addEventListener("click", async () => {
    if (rm.dataset.sure !== "1") { rm.dataset.sure = "1"; rm.textContent = "Press again to remove"; return; }
    try { await ctx.api.removeUser(user.id); p.close(); toast("Removed."); done(); }
    catch (err) { say(status, err.message, "bad"); rm.dataset.sure = ""; rm.textContent = "Remove"; }
  });
}

// ---------------------------------------------------------------- who is signed in now (under People)

async function sessionsCall(method, path) {
  let res, data = null;
  try { res = await fetch("/api/districts/sessions" + path, { method, credentials: "same-origin" }); }
  catch (e) { throw new Error("Land Planner is not running. Start it again, then reload this page."); }
  try { data = await res.json(); } catch (e) { /* not JSON */ }
  if (!res.ok || !data) throw new Error((data && data.error && data.error.message) || "The signed-in sessions could not be read.");
  return data;
}
async function signedIn(holder, alive) {
  const a = await sessionsCall("GET", "");
  if (!alive() || !holder.isConnected) return;
  const rows = a.sessions || [];
  holder.innerHTML = `<h2>Signed in now</h2>
    <p>${rows.length} ${rows.length === 1 ? "session" : "sessions"}. A session ends after ${esc(a.idle_minutes)} minutes without use, after ${esc(a.longest_hours)} hours at most, or when it is ended here. Turning a person off or removing them ends theirs too.</p>
    ${tableHtml({ caption: "Signed-in sessions", foldAfter: 30, columns: [{ label: "Who" }, { label: "From" }, { label: "Signed in" }, { label: "Last used" }, { label: "" }],
      rows: rows.map((r) => [{ html: `<b>${esc(r.user.name || r.user.id)}</b><small>${esc(roleWords(r.user.role))}</small>`, sort: r.user.name || "" },
        { html: `${esc(r.client || "This computer")}${r.agent ? `<small>${esc(String(r.agent).slice(0, 70))}</small>` : ""}`, sort: r.client || "" },
        { html: esc(when(r.started)), sort: r.started }, { html: esc(when(r.last)), sort: r.last },
        { html: r.current ? "<small>This is you</small>" : `<button type="button" class="btn small" data-end="${esc(r.id)}">End this session</button>`, sort: "" }]) })}
    <p class="dz-status" role="status" aria-live="polite"></p>`;
  const status = holder.querySelector(".dz-status");
  holder.onclick = async (e) => {      // one handler however often the list is redrawn
    const b = e.target.closest("[data-end]");
    if (!b) return;
    if (b.dataset.sure !== "1") { b.dataset.sure = "1"; b.textContent = "Press again to sign them out"; return; }
    try { await sessionsCall("DELETE", "/" + encodeURIComponent(b.dataset.end)); toast("Signed out."); signedIn(holder, alive); }
    catch (err) { say(status, err.message, "bad"); b.dataset.sure = ""; b.textContent = "End this session"; }
  };
}

// ---------------------------------------------------------------- audit log

async function audit(box, ctx, alive) {
  const st = { q: "", outcome: "", offset: 0, limit: 100 };
  box.innerHTML = `<div data-chain></div><div class="card filters dz-filters">
      <label class="field grow"><span>Search</span><input type="search" data-q placeholder="Name, action or detail"></label>
      <label class="field"><span>Outcome</span><select data-o><option value="">All</option><option value="ok">Done</option><option value="denied">Refused</option><option value="failed">Failed</option></select></label></div>
    <div data-out></div>`;
  const out = box.querySelector("[data-out]"), chain = box.querySelector("[data-chain]");
  const draw = async () => {
    out.innerHTML = loading("Reading the audit log…");
    const a = await ctx.api.audit({ q: st.q, outcome: st.outcome, limit: st.limit, offset: st.offset });
    if (!alive()) return;
    const c = a.chain || {};
    chain.innerHTML = `<p class="lead ${c.ok ? "dz-ok" : "dz-bad"}">${c.ok ? `The log is intact (${n0(c.lines || 0)} lines checked).` : `The log is broken at line ${esc(c.broken_at)}${c.reason ? ": " + esc(c.reason) : ""}.`}</p>`;
    const rows = a.entries || [];
    const det = (d) => (d && typeof d === "object" ? Object.entries(d).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(", ") : d || "");
    out.innerHTML = `<p class="dz-shown">${n0(a.total || rows.length)} entries${st.q || st.outcome ? " match" : ""}; showing ${rows.length ? st.offset + 1 : 0} to ${st.offset + rows.length}.</p>` +
      tableHtml({ caption: "Audit log", foldAfter: 100, columns: [{ label: "When" }, { label: "Who" }, { label: "Action" }, { label: "Outcome" }, { label: "Project" }, { label: "Detail" }],
        rows: rows.map((r) => [{ html: esc(when(r.at)), sort: r.at }, { html: esc(r.name || r.user || "") + (r.role ? `<small>${esc(roleWords(r.role))}</small>` : ""), sort: r.name },
          { html: esc(r.action), sort: r.action }, { html: r.outcome === "ok" ? "Done" : `<span class="dz-bad">${r.outcome === "denied" ? "Refused" : "Failed"}</span>`, sort: r.outcome },
          { html: esc(r.project || ""), sort: r.project || "" }, { html: `<small>${esc(det(r.detail)).slice(0, 300)}</small>`, sort: "" }]) }) +
      `<p class="dz-row" style="margin-top:10px">${st.offset ? '<button type="button" class="btn small" data-page="-1">Newer</button>' : ""}${st.offset + rows.length < (a.total || 0) ? '<button type="button" class="btn small" data-page="1">Older</button>' : ""}</p>`;
  };
  box.querySelector("[data-q]").addEventListener("input", debounce((e) => { st.q = e.target.value; st.offset = 0; draw(); }, 250));
  box.querySelector("[data-o]").addEventListener("change", (e) => { st.outcome = e.target.value; st.offset = 0; draw(); });
  box.addEventListener("click", (e) => { const b = e.target.closest("[data-page]"); if (b) { st.offset = Math.max(0, st.offset + Number(b.dataset.page) * st.limit); draw(); } });
  await draw();
}

// ---------------------------------------------------------------- settings

async function settings(box, ctx) {
  const s = await ctx.api.settings();
  const d = s.disclaimers || {};
  box.innerHTML = `<form class="card dz-form" data-workspace style="max-width:820px"><h2>The whole workspace</h2>
    <label class="field"><span>Google client id (from Google Cloud; empty turns Google sign-in off)</span><input name="google_client_id" value="${esc(s.google_client_id || "")}" placeholder="1234-abc.apps.googleusercontent.com"></label>
    <label class="field"><span>Sign people out after this many minutes without use</span><input name="idle_minutes" type="number" min="5" max="720" value="${esc(s.idle_minutes || 30)}" style="width:140px"></label>
    <label class="field"><span>Confidentiality agreement (NDA) text</span><textarea name="nda_text" rows="5">${esc(s.nda_text || "")}</textarea></label>
    <label class="check"><input type="checkbox" name="bump"> Ask everyone to accept it again (new version ${esc((s.nda_version || 1) + 1)})</label>
    <fieldset class="dz-fieldset"><legend>Disclaimer on every export, by audience</legend>
      ${["internal", "consultant", "partner", "city"].map((a) => `<label class="field"><span>${a[0].toUpperCase() + a.slice(1)}</span><input name="d_${a}" value="${esc(d[a] || "")}"></label>`).join("")}</fieldset>
    <button class="btn primary" type="submit">Save the settings</button><p class="dz-status" role="status" aria-live="polite"></p></form>
    <div data-project-settings style="margin-top:28px"></div>`;
  projectSettings(box.querySelector("[data-project-settings]"), ctx);
  const f = box.querySelector("form[data-workspace]");
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = { google_client_id: f.google_client_id.value.trim(), idle_minutes: Number(f.idle_minutes.value) || 30, nda_text: f.nda_text.value,
      disclaimers: Object.fromEntries(["internal", "consultant", "partner", "city"].map((a) => [a, f["d_" + a].value])) };
    if (f.bump.checked) body.nda_version = (s.nda_version || 1) + 1;
    try { await ctx.api.saveSettings(body); say(f.querySelector(".dz-status"), "Saved.", "ok"); }
    catch (err) { say(f.querySelector(".dz-status"), err.message, "bad"); }
  });
}

// this project's own settings: what partners and the city may download, and when a change counts as large
function projectSettings(holder, ctx) {
  const s = ctx.project.settings || {};
  const pct = s.compare_threshold_pct ?? 10;
  holder.innerHTML = `<form class="card dz-form" style="max-width:820px"><h2>This project: ${esc(ctx.project.name || ctx.project.id)}</h2>
    <label class="check"><input type="checkbox" name="partner_export"${s.partner_export ? " checked" : ""}> Partners may download PDFs and Excel files</label>
    <p class="muted">Off: partners can read the pages but not take copies away. Their downloads always carry the partner disclaimer and only what partners may see.</p>
    <label class="check"><input type="checkbox" name="city_export"${s.city_export ? " checked" : ""}> City staff may download PDFs and Excel files</label>
    <p class="muted">Off: city staff can read the city view but not take copies away. Their downloads never hold returns, land values or sale prices.</p>
    <label class="field"><span>Mark a figure as a large change when baseline and a submission differ by more than this percent</span><input name="compare_threshold_pct" type="number" min="0" max="1000" step="0.5" value="${esc(pct)}" style="width:140px"></label>
    <p class="muted">Used by Compare: smaller differences are still listed, larger ones are flagged for a closer look.</p>
    <button class="btn primary" type="submit">Save this project's settings</button><p class="dz-status" role="status" aria-live="polite"></p></form>`;
  const f = holder.querySelector("form"), status = f.querySelector(".dz-status");
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const t = Number(f.compare_threshold_pct.value);
    if (!(t >= 0 && t <= 1000)) return say(status, "The percent is a number from 0 to 1,000.", "bad");
    say(status, "Saving…", "busy");
    try {
      const a = await ctx.api.saveProject(ctx.project.id, { settings: { partner_export: f.partner_export.checked, city_export: f.city_export.checked, compare_threshold_pct: t } });
      ctx.project.settings = (a.project && a.project.settings) || ctx.project.settings;
      forget(ctx.project.id);
      say(status, "Saved.", "ok");
    } catch (err) { say(status, err.message, "bad"); }
  });
}

// ---------------------------------------------------------------- backups

async function backups(box, ctx, alive) {
  const a = await ctx.api.backups(ctx.project.id);
  if (!alive()) return;
  const list = a.backups || [];
  box.innerHTML = `<p class="lead">${list.length ? `The newest backup is from ${esc(when(list[0].at))}.` : "No backups yet."} A backup is made on the first use each day; the last 14 are kept.</p>
    <p class="dz-row"><button type="button" class="btn primary" data-now>Back up now</button><span class="dz-status" role="status" aria-live="polite"></span></p>
    <ul class="dz-list">${list.map((b) => `<li class="card"><p class="dz-kv"><b>${esc(b.name)}</b><span>${esc(when(b.at))}</span><span>${kb(b.size || 0)}</span></p>
      <p><button type="button" class="btn small" data-restore="${esc(b.name)}">Restore this backup</button></p></li>`).join("")}</ul>`;
  const status = box.querySelector(".dz-status");
  box.addEventListener("click", async (e) => {
    if (e.target.closest("[data-now]")) {
      say(status, "Backing up…", "busy");
      try { await ctx.api.backupNow(ctx.project.id); toast("Backed up."); backups(box, ctx, alive); } catch (err) { say(status, err.message, "bad"); }
    }
    const r = e.target.closest("[data-restore]");
    if (r) {
      if (r.dataset.sure !== "1") { r.dataset.sure = "1"; r.textContent = "Press again: the project goes back to this backup"; return; }
      try {
        const ans = await ctx.api.restore(ctx.project.id, r.dataset.restore);
        forget(ctx.project.id);
        toast(`Restored. A safety backup of what was there was kept${ans.safety_backup ? " (" + (ans.safety_backup.name || ans.safety_backup) + ")" : ""}.`);
        backups(box, ctx, alive);
      } catch (err) { say(status, err.message, "bad"); }
    }
  });
}

// ---------------------------------------------------------------- the project file

async function file(box, ctx) {
  box.innerHTML = `<div class="dz-grid2">
    <div class="card"><h2>Download the project</h2><p>The whole project as one file: every dataset and version, the logs, documents and map layers, with a checksum for each file. Keep it on a private drive.</p>
      <p class="dz-row"><button type="button" class="btn primary" data-zip>Download the project file</button><span class="dz-status" role="status" aria-live="polite"></span></p></div>
    <form class="card dz-form" data-open><h2>Open a project file</h2>
      <label class="field"><span>Project file (.zip)</span><input type="file" accept=".zip" required></label>
      <label class="check"><input type="checkbox" name="replace"> Replace a project with the same id (a safety backup is kept)</label>
      <button class="btn" type="submit">Open the file</button><p class="dz-status" role="status" aria-live="polite"></p></form></div>`;
  box.querySelector("[data-zip]").addEventListener("click", async (e) => {
    const st = e.target.parentElement.querySelector(".dz-status");
    say(st, "Preparing…", "busy");
    try { await ctx.api.packageZip(ctx.project.id); say(st, ""); } catch (err) { say(st, err.message, "bad"); }
  });
  const f = box.querySelector("[data-open]");
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const file = f.querySelector("input[type=file]").files[0], st = f.querySelector(".dz-status");
    if (!file) return say(st, "Pick a file first.", "bad");
    say(st, "Opening…", "busy");
    try {
      const ans = await ctx.api.importProject(file, f.replace.checked);
      forget();
      const p = ans.project || {};
      st.className = "dz-status ok";
      st.innerHTML = `${ans.replaced ? "Replaced" : "Added"} ${esc(p.name || p.id)}. <a href="#/districts/${encodeURIComponent(p.id)}">Open it</a>`;
    } catch (err) { say(st, err.message, "bad"); }
  });
}

// ---------------------------------------------------------------- publish and roll back

async function publish(box, ctx) {
  const kind = { baseline: "Baseline", scenario: "Scenario", consultant: "Consultant submission" };
  // a new scenario starts as a copy of a dataset's published version or working copy
  const sources = ctx.datasets.filter((d) => d.kind !== "consultant").flatMap((d) => [
    ...(d.current ? [[`${d.id}|published`, `${d.label || d.id}, published version ${d.current}`]] : []),
    [`${d.id}|draft`, `${d.label || d.id}, working copy`]]);
  box.innerHTML = `<p class="lead">Publishing copies a dataset's draft into a new version that viewers see. Rolling back publishes an older version again; nothing is deleted.</p>
    ${ctx.can["dataset.create_scenario"] ? `<form class="card dz-form" data-new-scenario><h2>New scenario</h2>
      <p class="muted">A scenario is a separate copy of the figures to try other assumptions in. The baseline is not changed; publish the scenario when others should see it.</p>
      <div class="dz-row"><label class="field grow"><span>Name</span><input name="label" required maxlength="120" placeholder="For example: Slower absorption"></label>
      <label class="field"><span>Start from</span><select name="from">${opts(sources)}</select></label>
      <button class="btn primary" type="submit">Make the scenario</button></div><p class="dz-status" role="status" aria-live="polite"></p></form>` : ""}
    <ul class="dz-list">${ctx.datasets.map((d) => {
      const pubs = (d.published || []).slice().reverse();
      return `<li class="card" data-ds="${esc(d.id)}"><h3>${esc(d.label || d.id)} <span class="muted">${esc(kind[d.kind] || d.kind)}</span></h3>
        <p class="dz-kv"><span>Draft changed <b>${esc(when(d.draft_updated_at) || "never")}</b></span><span>Published version <b>${esc(d.current || "none")}</b></span></p>
        <form class="dz-form dz-row" data-pub><label class="field grow"><span>Note for the new version</span><input name="note" placeholder="What changed"></label><button class="btn primary" type="submit">Publish the draft</button></form>
        ${pubs.length ? `<details class="calm-fold"><summary>Show the ${pubs.length} published ${pubs.length === 1 ? "version" : "versions"} and roll back</summary><div class="calm-fold-body">
          <ul class="plain">${pubs.map((v) => `<li>Version ${esc(v.version)}, ${esc(when(v.at))}${v.note ? ": " + esc(v.note) : ""}${v.from_version ? ` (from version ${esc(v.from_version)})` : ""}</li>`).join("")}</ul>
          ${pubs.length > 1 ? `<form class="dz-form dz-row" data-roll><label class="field"><span>Publish again</span><select name="version">${opts(pubs.slice(1).map((v) => [v.version, "Version " + v.version]))}</select></label>
            <label class="field grow"><span>Reason</span><input name="reason" required></label><button class="btn" type="submit">Roll back</button></form>` : ""}</div></details>` : ""}
        <p class="dz-status" role="status" aria-live="polite"></p></li>`;
    }).join("")}</ul>`;
  box.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (e.target.matches("[data-new-scenario]")) {
      const f = e.target, st = f.querySelector(".dz-status"), [dataset, version] = f.from.value.split("|");
      if (!f.label.value.trim()) return say(st, "Give the scenario a name.", "bad");
      say(st, "Making the scenario…", "busy");
      try {
        const a = await ctx.api.createDataset(ctx.project.id, { kind: "scenario", label: f.label.value.trim(), copy_from: { dataset, version } });
        toast(`Made ${(a.dataset && (a.dataset.label || a.dataset.id)) || "the scenario"}.`);
        ctx.refresh();
      } catch (err) { say(st, err.message, "bad"); }
      return;
    }
    const li = e.target.closest("[data-ds]");
    if (!li) return;
    const st = li.querySelector(":scope > .dz-status"), d = li.dataset.ds;
    say(st, "Working…", "busy");
    try {
      if (e.target.matches("[data-pub]")) { const a = await ctx.api.publish(ctx.project.id, d, e.target.note.value); toast(`Published version ${a.version && a.version.version ? a.version.version : a.version}.`); }
      else { const a = await ctx.api.rollback(ctx.project.id, d, Number(e.target.version.value), e.target.reason.value); toast(`Version ${a.from_version} is published again as version ${a.version}.`); }
      ctx.refresh();
    } catch (err) { say(st, err.message, "bad"); }
  });
}

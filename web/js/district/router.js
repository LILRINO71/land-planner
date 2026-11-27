// The district workspace inside Land Planner. Addresses:
//   #/districts                         sign-in, then the list of projects
//   #/districts/<p>                     a project (its first page)
//   #/districts/<p>/m/<module>          a page defined by the project's data (modules.json)
//   #/districts/<p>/tool/<name>         one of the eight tools (web/js/district/tools/<name>.js)
//   #/districts/<p>/data/<part>         the data area      #/districts/<p>/requirements      the checklist
//   #/districts/<p>/admin/<part>        administration
// After the route: ?ds=<dataset>&v=<published|draft|n>&as=<audience> (what is being looked at, and as whom).
import { dapi, onSignedOut, DistrictError } from "./api.js";
import * as charts from "./charts.js";
import { esc, panel, closePanel } from "./ui.js";
import { signInPage, ndaPage, watchIdle, stopIdle } from "./signin.js";
import { loading, problem } from "../util.js";

export const TOOLS = [["map", "Map and trade area"], ["scenarios", "Phases and scenarios"], ["landvalue", "Land value and pricing"],
  ["proforma", "Phase returns"], ["strategy", "Hold, sell, partner or lease"], ["funding", "Infrastructure and funding"],
  ["cityrecord", "Papers vs. city record"], ["ask", "Ask the package"]];
export const DATA_PARTS = [["register", "Assumptions register", null], ["import", "Import", "import"], ["compare", "Compare", "compare"],
  ["documents", "Documents", "documents.read"], ["layers", "Map layers", "gis.read"], ["sources", "Data sources", null],
  ["notes", "Notes", "notes.read"], ["checks", "Checks", "checks"]];
export const ADMIN_PARTS = [["users", "Users"], ["audit", "Audit log"], ["settings", "Settings"], ["backups", "Backups"],
  ["file", "Project file"], ["publish", "Publish and roll back"]];
const GROUPS = ["Overview", "Market", "Program", "Land strategy", "Advisory", "Context"];
// the module's own `group` (as modules.json writes it) and the sidebar heading it goes under
const GROUP_CODES = { overview: "Overview", market: "Market", program: "Program", "land-strategy": "Land strategy", land_strategy: "Land strategy",
  advisory: "Advisory", context: "Context", corridor: "Context", data: "Data", requirements: "Requirements" };
const AUDIENCES = [["internal", "Internal"], ["partner", "Partner"], ["city", "City"], ["consultant", "Consultant"]];

// which sidebar group a data-defined page sits in: its own `group`, else what its id and name say
export function groupOf(m) {
  if (m.group) {
    const g = GROUP_CODES[String(m.group).toLowerCase()] || GROUPS.find((x) => x.toLowerCase() === String(m.group).toLowerCase());
    if (g) return g;
  }
  const s = (m.id + " " + (m.label || "")).toLowerCase();
  if (/overview|summary|dashboard|cockpit/.test(s)) return "Overview";
  if (/advis/.test(s)) return "Advisory";
  if (/corridor|scope|rfp|conflict|open.items|context/.test(s)) return "Context";
  if (/trade|demograph|segment|market|demand|spend|competit|supply|comps?\b/.test(s)) return "Market";
  if (/parcel|land|dispos|residual|rlv|acquisit|entitle/.test(s)) return "Land strategy";
  if (/question|recommend|return|risk|fiscal|impact|strategy|econom|finance/.test(s)) return "Advisory";
  return "Program";
}

// ---------------------------------------------------------------- state kept while the app is open

const S = { info: null, session: null, message: "", projects: null, project: new Map(), content: new Map(), nav: null, drawer: false };
const decode = (x) => { try { return decodeURIComponent(x); } catch (e) { return x; } };
function hashQuery() {
  const q = location.hash.split("?")[1] || "", out = {};
  q.split("&").filter(Boolean).forEach((kv) => { const [k, v = ""] = kv.split("="); out[decode(k)] = decode(v); });
  return out;
}
export function link(parts, q) {
  const cur = hashQuery(), keep = {};
  ["ds", "v", "as"].forEach((k) => { if (cur[k]) keep[k] = cur[k]; });
  const next = Object.assign(keep, q || {});
  Object.keys(next).forEach((k) => { if (next[k] === null || next[k] === "") delete next[k]; });
  const qs = Object.entries(next).map(([k, v]) => k + "=" + encodeURIComponent(v)).join("&");
  return "#/districts" + (parts.length ? "/" + parts.map(encodeURIComponent).join("/") : "") + (qs ? "?" + qs : "");
}
export function go(parts, q) { location.hash = link(parts, q); }
export function forget(projectId) {
  [...S.project.keys()].forEach((k) => { if (!projectId || k.startsWith(projectId + "|")) S.project.delete(k); });
  [...S.content.keys()].forEach((k) => { if (!projectId || k.startsWith(projectId + "|")) S.content.delete(k); });
  if (!projectId) S.projects = null;
}

onSignedOut((e) => {
  S.session = null; S.message = e.code === "session-expired" ? e.message : "Your session ended. Sign in again to go back to where you were.";
  forget(); stopIdle(); closePanel();
  if (location.hash.startsWith("#/districts")) window.dispatchEvent(new HashChangeEvent("hashchange"));
});

// ---------------------------------------------------------------- the sidebar (called by main.js on every draw)

export function side(route) {
  const nav = S.nav, user = S.session && S.session.signed_in ? S.session.user : null;
  if (!user) return "";
  let html = `<div class="side-land side-district">`;
  if (nav) {
    const rest = route.rest || [], here = rest.slice(1).join("/");
    const item = (href, label, on) => `<a href="${href}" class="nav sub${on ? " on" : ""}"${on ? ' aria-current="page"' : ""}><span>${esc(label)}</span></a>`;
    const group = (title, items) => (items.length ? `<p class="side-title">${esc(title)}</p><nav aria-label="${esc(title)}">${items.join("")}</nav>` : "");
    html += `<button type="button" class="dz-drawer-btn" aria-expanded="${S.drawer}" aria-controls="dz-drawer">Menu<span class="dz-drawer-name">${esc(nav.name)}</span></button>
      <div id="dz-drawer" class="dz-drawer${S.drawer ? " open" : ""}">
      <a class="side-parcel" href="${link([nav.id])}"><b>${esc(nav.name)}</b><span>${esc(nav.place || "District project")}</span></a>`;
    GROUPS.forEach((g) => {
      html += group(g, nav.modules.filter((m) => groupOf(m) === g).map((m) => item(link([nav.id, "m", m.id]), m.label || m.id, here === "m/" + m.id)));
    });
    html += group("Tools", TOOLS.map(([id, label]) => item(link([nav.id, "tool", id]), label, here === "tool/" + id)));
    const modsIn = (g) => nav.modules.filter((m) => groupOf(m) === g).map((m) => item(link([nav.id, "m", m.id]), m.label || m.id, here === "m/" + m.id));
    html += group("Data", modsIn("Data").concat(DATA_PARTS.filter((d) => !d[2] || nav.can[d[2]]).map(([id, label]) => item(link([nav.id, "data", id]), label, here === "data/" + id))));
    html += group("Requirements", [item(link([nav.id, "requirements"]), "Requirements checklist", here === "requirements")].concat(modsIn("Requirements")));
    if (nav.can["users.manage"]) html += group("Admin", ADMIN_PARTS.map(([id, label]) => item(link([nav.id, "admin", id]), label, here === "admin/" + id)));
    html += `<a class="nav sub dz-all" href="#/districts"><span>All projects</span></a></div>`;
  }
  html += `<p class="dz-who"><span>${esc(user.name || "Signed in")}</span><small>${esc(roleWords(user.role))}</small><button type="button" class="link dz-signout" data-dz-signout>Sign out</button></p></div>`;
  return html;
}
export const roleWords = (r) => ({ administrator: "Administrator", analyst: "Analyst", consultant: "Consultant", viewer_partner: "Partner (view only)", viewer_city: "City (view only)" }[r] || r || "");

let sideWired = false;
function wireSide() {
  if (sideWired) return;
  sideWired = true;
  const sideEl = document.getElementById("side");
  sideEl.addEventListener("click", async (e) => {
    const out = e.target.closest("[data-dz-signout]");
    if (out) { e.preventDefault(); await signOut(); return; }
    const btn = e.target.closest(".dz-drawer-btn");
    if (btn) { S.drawer = !S.drawer; btn.setAttribute("aria-expanded", String(S.drawer)); sideEl.querySelector(".dz-drawer").classList.toggle("open", S.drawer); return; }
    if (e.target.closest(".dz-drawer a")) S.drawer = false;
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && S.drawer) {
      S.drawer = false;
      const d = sideEl.querySelector(".dz-drawer"), b = sideEl.querySelector(".dz-drawer-btn");
      if (d) d.classList.remove("open");
      if (b) { b.setAttribute("aria-expanded", "false"); b.focus(); }
    }
  });
}
function redrawSide(route) {
  const sideEl = document.getElementById("side");
  const old = sideEl.querySelector(".side-district");
  if (old) old.remove();
  sideEl.insertAdjacentHTML("beforeend", side(route));
}
async function signOut() {
  try { await dapi.signOut(); } catch (e) { /* signed out anyway */ }
  S.session = null; S.message = "You are signed out."; S.nav = null; forget(); stopIdle(); closePanel();
  location.hash = "#/districts";
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}

// ---------------------------------------------------------------- loading a project and what is being looked at

async function projectData(p, as) {
  const key = p + "|" + (as || "");
  if (!S.project.has(key)) {
    const asking = dapi.project(p, as ? { audience: as } : null);
    asking.catch(() => { if (S.project.get(key) === asking) S.project.delete(key); });
    S.project.set(key, asking);
  }
  return S.project.get(key);
}
async function contentOf(p, d, v, as) {
  const key = [p, d, v, as || ""].join("|");
  if (!S.content.has(key)) {
    const asking = dapi.dataset(p, d, { version: v, audience: as || "" });
    asking.catch(() => { if (S.content.get(key) === asking) S.content.delete(key); });
    S.content.set(key, asking);
  }
  return S.content.get(key);
}

// the context every page and tool gets
async function context(p, route) {
  const q = hashQuery(), session = S.session;
  const internal = session.audience === "internal";
  const viewAs = internal && q.as && q.as !== "internal" && AUDIENCES.some((a) => a[0] === q.as) ? q.as : "";
  const pd = await projectData(p, viewAs);
  const datasets = pd.datasets || [], can = pd.can || {};
  const ds = datasets.find((d) => d.id === q.ds) || datasets.find((d) => d.id === "baseline") || datasets[0];
  if (!ds) throw new DistrictError("This project has no datasets yet.", "not-found", 404);
  const published = (ds.published || []).length > 0;
  let v = q.v || (published ? "published" : "draft");
  if (v === "draft" && !can["dataset.read_draft"] && published) v = "published";
  const data = await contentOf(p, ds.id, v, viewAs);
  const modules = (pd.modules && pd.modules.modules) || pd.modules || [];
  const sorted = [...modules].sort((a, b) => (a.order ?? 99) - (b.order ?? 99));
  const ctx = {
    project: pd.project || {}, datasets, modules: sorted, can, is_sample: !!pd.is_sample,
    audience: data.audience || viewAs || session.audience, viewAs, internal, session, user: session.user,
    dataset: ds.id, datasetMeta: ds, version: v, versionShown: data.version, content: data.content || { entities: {} },
    api: dapi, charts, route,
    go: (parts, extra) => go([p].concat(parts || []), extra), link: (parts, extra) => link([p].concat(parts || []), extra),
    refresh: () => { forget(p); window.dispatchEvent(new HashChangeEvent("hashchange")); },
  };
  S.nav = { id: p, name: ctx.project.name || p, place: ctx.project.place, modules: sorted.filter((m) => m.id !== "requirements"), can };
  return ctx;
}

// ---------------------------------------------------------------- the bar above every page: what is being looked at

export function viewBar(ctx, { exports = null } = {}) {
  const ds = ctx.datasets, kindWords = { baseline: "Baseline", scenario: "Scenario", consultant: "Consultant submission" };
  const pubs = (ctx.datasetMeta.published || []).slice().reverse();
  const versions = [];
  if (pubs.length) versions.push(["published", `Published (latest, v${ctx.datasetMeta.current || pubs[0].version})`]);
  if (ctx.can["dataset.read_draft"]) versions.push(["draft", "Draft (working copy)"]);
  pubs.forEach((p) => versions.push([String(p.version), `Version ${p.version}${p.note ? ": " + p.note : ""}`]));
  const opt = (val, words, cur) => `<option value="${esc(val)}"${String(cur) === String(val) ? " selected" : ""}>${esc(words)}</option>`;
  let html = `<div class="dz-bar" role="group" aria-label="What you are looking at">
    <label class="field"><span>Dataset</span><select data-dz-ds>${ds.map((d) => opt(d.id, `${d.label || d.id} (${kindWords[d.kind] || d.kind})`, ctx.dataset)).join("")}</select></label>
    <label class="field"><span>Version</span><select data-dz-v>${versions.map(([v, w]) => opt(v, w, ctx.version)).join("")}</select></label>`;
  if (ctx.internal) {
    const cur = ctx.viewAs || "internal";
    html += `<div class="field"><span id="dz-as-l">View as</span><div class="dz-seg" role="radiogroup" aria-labelledby="dz-as-l">${AUDIENCES.map(([a, w]) =>
      `<button type="button" role="radio" aria-checked="${a === cur}" data-dz-as="${a}"${a === cur ? ' class="on"' : ""}>${w}</button>`).join("")}</div></div>`;
  }
  if (exports) html += `<div class="dz-bar-end">${exports}</div>`;
  html += "</div>";
  if (ctx.viewAs) html += `<p class="dz-viewing" role="status">You are seeing exactly what the <b>${esc(AUDIENCES.find((a) => a[0] === ctx.viewAs)[1])}</b> audience gets. <a href="${ctx.link(ctx.route.rest.slice(1), { as: "" })}">Back to the internal view</a></p>`;
  if (ctx.version === "draft") html += `<p class="dz-viewing draft">This is the draft: the working copy, not yet published.</p>`;
  return html;
}
export function wireViewBar(root, ctx) {
  root.addEventListener("change", (e) => {
    if (e.target.matches("[data-dz-ds]")) location.hash = ctx.link(ctx.route.rest.slice(1), { ds: e.target.value, v: "" });
    if (e.target.matches("[data-dz-v]")) location.hash = ctx.link(ctx.route.rest.slice(1), { v: e.target.value });
  });
  root.addEventListener("click", (e) => {
    const b = e.target.closest("[data-dz-as]");
    if (b && root.contains(b)) location.hash = ctx.link(ctx.route.rest.slice(1), { as: b.dataset.dzAs === "internal" ? "" : b.dataset.dzAs });
  });
}

// ---------------------------------------------------------------- pages

const notBuilt = (label) => `<header class="page-head"><p class="kicker">Tools</p><h1>${esc(label)}</h1></header>
  <div class="card dz-calm"><h2>This tool is not built yet</h2><p>It will appear here when it is ready. Everything else in the workspace works without it.</p></div>`;

async function toolPage(el, ctx, name, alive) {
  const t = TOOLS.find((x) => x[0] === name);
  if (!t) { el.innerHTML = notBuilt("That tool"); return; }
  el.innerHTML = loading("Opening " + t[1].toLowerCase() + "…");
  let mod = null;
  try { mod = await import(`./tools/${name}.js`); } catch (e) { mod = null; }
  if (!alive()) return;
  if (!mod || typeof mod.render !== "function") { el.innerHTML = notBuilt(t[1]); return; }
  el.innerHTML = `<header class="page-head"><p class="kicker">Tools</p><h1>${esc(t[1])}</h1></header>${viewBar(ctx)}<div class="dz-tool"></div>`;
  wireViewBar(el, ctx);
  try { await mod.render(el.querySelector(".dz-tool"), { ...ctx, alive }); }
  catch (e) { console.error(e); if (alive()) el.innerHTML = notBuilt(t[1]); }
}

async function lazyPage(el, ctx, file, part, alive, label) {
  let mod = null;
  try { mod = await import(file); } catch (e) { console.error(e); mod = null; }
  if (!alive()) return;
  if (!mod || typeof mod.render !== "function") {
    el.innerHTML = `<header class="page-head"><h1>${esc(label)}</h1></header><div class="card dz-calm"><h2>This part is not built yet</h2><p>It will appear here when it is ready.</p></div>`;
    return;
  }
  await mod.render(el, ctx, part, alive);
}

function projectList(el, list) {
  const user = S.session.user, admin = user.role === "administrator";
  el.innerHTML = `<header class="page-head"><p class="kicker">District workspace</p><h1>Projects</h1>
    <p class="lead">${list.length ? "Choose a project to open its market package." : "There are no projects you can open yet."}</p></header>
    <div class="dz-projects">${list.map((p) => {
      const b = p.branding || {};
      return `<a class="card dz-project" href="${link([p.id])}">
        ${p.sample ? '<span class="dz-chip gold">Sample data</span>' : ""}
        <h2>${esc(p.name || p.id)}</h2><p class="muted">${esc(p.place || b.location || "")}</p>
        ${b.subtitle ? `<p>${esc(b.subtitle)}</p>` : ""}<span class="dz-open">Open the project</span></a>`;
    }).join("")}</div>
    ${admin ? `<p class="fine foot">${list.some((p) => p.sample) ? "The Sample District holds invented figures for trying the workspace." : ""}
      <button type="button" class="btn small" data-sample>${list.some((p) => p.sample) ? "Reinstall the Sample District" : "Add the Sample District"}</button></p>` : ""}`;
  const b = el.querySelector("[data-sample]");
  if (b) b.addEventListener("click", async () => {
    b.disabled = true;
    try { await dapi.installSample(); forget(); window.dispatchEvent(new HashChangeEvent("hashchange")); }
    catch (e) { b.disabled = false; b.insertAdjacentHTML("afterend", ` <span class="dz-status bad">${esc(e.message)}</span>`); }
  });
}

// ---------------------------------------------------------------- render (main.js calls this for #/districts...)

export async function render(main, route, alive) {
  wireSide();
  closePanel();
  document.body.classList.add("in-district");
  alive.onLeave(() => { if (!location.hash.startsWith("#/districts")) { document.body.classList.remove("in-district"); closePanel(); } });
  main.innerHTML = '<div class="dz-root"></div>';
  const el = main.firstChild;
  const rest = route.rest || [];
  el.innerHTML = loading("Opening the district workspace…");
  try {
    if (!S.info) S.info = await dapi.info();
    if (!S.session || !S.session.signed_in) S.session = await dapi.session();
  } catch (e) {
    if (!alive()) return;
    S.info = null;
    if (e.status === 404 || e.status === 405) {
      el.innerHTML = `<header class="page-head"><p class="kicker">District workspace</p><h1>Districts</h1></header>
        <div class="card dz-calm"><h2>The district workspace is not switched on here yet</h2><p>This copy of Land Planner does not have the district workspace. Update Land Planner, then open this page again.</p></div>`;
    } else if (e.code !== "sign-in-needed" && e.code !== "session-expired") {
      el.innerHTML = `<header class="page-head"><h1>Districts</h1></header>` + problem(e.message);
      el.querySelector("[data-retry]").addEventListener("click", () => render(main, route, alive));
    } else { S.session = { signed_in: false }; return render(main, route, alive); }
    return;
  }
  if (!alive()) return;
  if (!S.session.signed_in) {
    S.nav = null; redrawSide(route);
    document.body.classList.add("dz-gated");
    alive.onLeave(() => document.body.classList.remove("dz-gated"));
    const msg = S.message; S.message = "";
    signInPage(el, S.info, { message: msg, done: (s) => { S.session = s; S.info = null; forget(); render(main, route, alive); } });
    return;
  }
  if (S.session.nda && S.session.nda.required) {
    document.body.classList.add("dz-gated");
    alive.onLeave(() => document.body.classList.remove("dz-gated"));
    ndaPage(el, S.info, S.session, { done: (s) => { S.session = s; render(main, route, alive); }, signOut });
    return;
  }
  document.body.classList.remove("dz-gated");
  watchIdle(S.session.idle_minutes || (S.info && S.info.idle_minutes), {
    onEnded: () => { S.session = null; S.message = "You were signed out after a while without use. Sign in again to go back to where you were."; forget(); if (location.hash.startsWith("#/districts")) window.dispatchEvent(new HashChangeEvent("hashchange")); },
  });

  try {
    if (!rest.length) {
      S.nav = null; redrawSide(route);
      if (!S.projects) S.projects = (await dapi.projects()).projects || [];
      if (!alive()) return;
      projectList(el, S.projects);
      document.title = "Projects · Districts · Land Planner";
      return;
    }
    const p = rest[0], kind = rest[1] || "", part = rest[2] || "";
    const ctx = await context(p, route);
    if (!alive()) return;
    redrawSide(route);
    document.title = `${ctx.project.name || p} · Districts · Land Planner`;
    if (!kind) {
      const first = S.nav.modules[0];
      if (first) { location.replace(link([p, "m", first.id])); return; }
      const m = await import("./module.js");
      return m.renderEmptyProject(el, ctx);
    }
    if (kind === "m") { const m = await import("./module.js"); if (alive()) await m.render(el, ctx, part, alive); return; }
    if (kind === "tool") return toolPage(el, ctx, part, alive);
    if (kind === "requirements") return lazyPage(el, ctx, "./requirements.js", part, alive, "Requirements");
    if (kind === "data") return lazyPage(el, ctx, "./data.js", part || "register", alive, "Data");
    if (kind === "admin") return lazyPage(el, ctx, "./admin.js", part || "users", alive, "Admin");
    el.innerHTML = `<header class="page-head"><h1>That page is not in the workspace</h1></header><p><a class="btn" href="${link([p])}">Back to the project</a></p>`;
  } catch (e) {
    console.error(e);
    if (!alive() || e.code === "sign-in-needed" || e.code === "session-expired") return;
    const gone = e.status === 404 || e.status === 403;
    el.innerHTML = `<header class="page-head"><p class="kicker">District workspace</p><h1>${gone ? "That project cannot be opened" : "This page could not be shown"}</h1></header>` +
      problem(e.message || "Something went wrong.", gone ? "" : "Try again") + `<p><a class="btn" href="#/districts">All projects</a></p>`;
    const r = el.querySelector("[data-retry]");
    if (r) r.addEventListener("click", () => { forget(rest[0]); render(main, route, alive); });
  }
}
export { panel };

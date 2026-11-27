// One client for every /api/districts route in docs/district-data-contract.md. Errors come back as DistrictError
// with a plain message by code. When a request answers "sign-in-needed" or "session-expired", every listener of
// onSignedOut() hears it, so the workspace can show sign-in and come back to the same address afterwards.

export class DistrictError extends Error {
  constructor(message, code, status) { super(message); this.code = code; this.status = status; }
}

const BASE = "/api/districts";
const PLAIN = {
  "sign-in-needed": "Sign in to open the district workspace.",
  "session-expired": "You were signed out after a while without use. Sign in again to go back to where you were.",
  "nda-needed": "Accept the confidentiality agreement first.",
  forbidden: "Your account is not allowed to do that.",
  "not-found": "That is not in the workspace.",
  "bad-request": "That could not be used. Check what was typed and try again.",
  conflict: "Someone changed this at the same time. Reload the page and try again.",
  "last-admin": "The last administrator cannot be removed, turned off or given another role.",
  "too-large": "That file is too large for the workspace.",
  "too-many-tries": "Too many wrong tries. Wait 15 minutes, then try again.",
  "not-ready": "This download is not available yet: the writer for it is not installed on this computer.",
  "google-not-set-up": "Google sign-in has not been set up by the owner yet.",
  "google-unreachable": "Google could not be reached just now. Try again in a minute.",
};
export const plainMessage = (code, fallback) => PLAIN[code] || fallback || "Something went wrong. Try again.";

const lost = new Set();
let lastRequest = Date.now();
export const lastRequestAt = () => lastRequest;
export function onSignedOut(fn) { lost.add(fn); return () => lost.delete(fn); }

function query(params) {
  const q = new URLSearchParams();
  Object.entries(params || {}).forEach(([k, v]) => { if (v !== "" && v !== null && v !== undefined) q.set(k, String(v)); });
  const s = q.toString();
  return s ? "?" + s : "";
}
const seg = (s) => encodeURIComponent(String(s));

async function send(method, path, { body, file, params, blob } = {}) {
  let res;
  const init = { method, credentials: "same-origin", headers: {} };
  if (file) { init.headers["Content-Type"] = "application/octet-stream"; init.body = file; }
  else if (body !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(body); }
  try { res = await fetch(BASE + path + query(params), init); }
  catch (e) { throw new DistrictError("Land Planner is not running. Start it again, then reload this page.", "stopped", 0); }
  lastRequest = Date.now();
  if (res.ok && blob) {
    const cd = res.headers.get("Content-Disposition") || "";
    const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
    return { blob: await res.blob(), name: m ? decodeURIComponent(m[1]) : "" };
  }
  let data = null;
  try { data = await res.json(); } catch (e) { /* not JSON */ }
  if (!res.ok || !data) {
    const err = (data && data.error) || {};
    const code = err.code || (res.status === 404 ? "not-found" : res.status === 501 ? "not-ready" : "unknown");
    const e = new DistrictError(err.message || plainMessage(code), code, res.status);
    if (code === "sign-in-needed" || code === "session-expired") lost.forEach((fn) => { try { fn(e); } catch (x) { console.error(x); } });
    throw e;
  }
  return data;
}

// a file the server sends back, saved by the browser under the server's name
export async function download(path, params, fallbackName) {
  const { blob, name } = await send("GET", path, { params, blob: true });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name || fallbackName || "download";
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1500);
  return a.download;
}

const P = (p) => `/projects/${seg(p)}`;
export const dapi = {
  info: () => send("GET", ""),
  session: () => send("GET", "/session"),
  signIn: (body) => send("POST", "/session", { body }),
  signOut: () => send("DELETE", "/session"),
  acceptNda: () => send("POST", "/session/nda", { body: { accept: true } }),
  changePasscode: (old, next) => send("POST", "/session/passcode", { body: { old, new: next } }),

  users: () => send("GET", "/users"),
  saveUser: (user) => send("POST", "/users", { body: user }),
  removeUser: (id) => send("DELETE", `/users/${seg(id)}`),
  settings: () => send("GET", "/settings"),
  saveSettings: (s) => send("POST", "/settings", { body: s }),
  audit: (params) => send("GET", "/audit", { params }),

  templates: () => send("GET", "/templates"),
  templateUrl: (name) => `${BASE}/templates/${seg(name)}`,

  projects: () => send("GET", "/projects"),
  createProject: (body) => send("POST", "/projects", { body }),
  installSample: () => send("POST", "/projects/sample", { body: {} }),
  importProject: (file, replace) => send("POST", "/projects/import", { file, params: { replace: replace ? 1 : "" } }),
  project: (p, params) => send("GET", P(p), { params }),
  saveProject: (p, body) => send("POST", P(p), { body }),
  packageZip: (p) => download(`${P(p)}/package.zip`, null, `${p}.zip`),
  backups: (p) => send("GET", `${P(p)}/backups`),
  backupNow: (p) => send("POST", `${P(p)}/backups`, { body: {} }),
  restore: (p, name) => send("POST", `${P(p)}/backups/${seg(name)}/restore`, { body: {} }),

  modules: (p, params) => send("GET", `${P(p)}/modules`, { params }),
  saveModules: (p, modules, reason) => send("POST", `${P(p)}/modules`, { body: { modules, reason } }),

  datasets: (p) => send("GET", `${P(p)}/datasets`),
  createDataset: (p, body) => send("POST", `${P(p)}/datasets`, { body }),
  dataset: (p, d, params) => send("GET", `${P(p)}/datasets/${seg(d)}`, { params }),
  versions: (p, d) => send("GET", `${P(p)}/datasets/${seg(d)}/versions`),
  saveRecord: (p, d, body) => send("POST", `${P(p)}/datasets/${seg(d)}/records`, { body }),
  removeRecord: (p, d, entity, id, reason) => send("DELETE", `${P(p)}/datasets/${seg(d)}/records/${seg(entity)}/${seg(id)}`, { params: { reason } }),
  publish: (p, d, note) => send("POST", `${P(p)}/datasets/${seg(d)}/publish`, { body: { note } }),
  rollback: (p, d, version, reason) => send("POST", `${P(p)}/datasets/${seg(d)}/rollback`, { body: { version, reason } }),
  figure: (p, d, id, params) => send("GET", `${P(p)}/datasets/${seg(d)}/figures/${seg(id)}`, { params }),
  checks: (p, d, params) => send("GET", `${P(p)}/datasets/${seg(d)}/checks`, { params }),
  revisions: (p, params) => send("GET", `${P(p)}/revisions`, { params }),
  compare: (p, params) => send("GET", `${P(p)}/compare`, { params }),

  importPreview: (p, file, name, entity) => send("POST", `${P(p)}/imports`, { file, params: { name, entity } }),
  importCommit: (p, id, body) => send("POST", `${P(p)}/imports/${seg(id)}/commit`, { body }),

  documents: (p) => send("GET", `${P(p)}/documents`),
  uploadDocument: (p, file, params) => send("POST", `${P(p)}/documents`, { file, params }),
  shareDocument: (p, doc, audiences) => send("POST", `${P(p)}/documents/${seg(doc)}/share`, { body: { audiences } }),
  downloadDocument: (p, doc, version, name) => download(`${P(p)}/documents/${seg(doc)}/${seg(version || "latest")}`, null, name),

  layers: (p) => send("GET", `${P(p)}/gis`),
  uploadLayer: (p, file, params) => send("POST", `${P(p)}/gis`, { file, params }),
  layer: (p, id) => send("GET", `${P(p)}/gis/${seg(id)}`),
  removeLayer: (p, id) => send("DELETE", `${P(p)}/gis/${seg(id)}`),

  notes: (p, params) => send("GET", `${P(p)}/notes`, { params }),
  addNote: (p, target, text) => send("POST", `${P(p)}/notes`, { body: { target, text } }),
  reply: (p, n, text) => send("POST", `${P(p)}/notes/${seg(n)}/replies`, { body: { text } }),
  resolveNote: (p, n, status, resolution) => send("POST", `${P(p)}/notes/${seg(n)}/resolve`, { body: { status, resolution } }),

  exportXlsx: (p, params) => download(`${P(p)}/export/table.xlsx`, params, "export.xlsx"),
  exportPdf: (p, params) => download(`${P(p)}/export/module.pdf`, params, "export.pdf"),

  // for the tools written later: any other route under a project, already scrubbed by the server
  get: (path, params) => send("GET", path, { params }),
  post: (path, body) => send("POST", path, { body }),
};

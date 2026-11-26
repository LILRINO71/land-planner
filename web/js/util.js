// Small helpers every page uses. Nothing here knows about a particular city or parcel.

export const NONE = "not covered yet";

export function esc(v) {
  return String(v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
export function has(v) { return v !== null && v !== undefined && v !== ""; }
export function show(v, suffix = "") { return has(v) ? esc(v) + suffix : NONE; }
export function num(v, digits = 0) {
  if (!has(v) || isNaN(Number(v))) return NONE;
  return Number(v).toLocaleString("en-US", { maximumFractionDigits: digits });
}
// The word for a count: plural(1, "acre") is "acre", plural(2, "acre") is "acres", plural(1, "person", "people") is "person".
// `digits` is how many decimals the number is shown with, so 1.004 shown as "1" is "1 acre".
export function plural(n, one, many = one + "s", digits = 0) {
  const shown = Number(String(num(n, digits)).replace(/,/g, ""));
  return shown === 1 ? one : many;
}
export function acres(v) { return has(v) ? num(v, 2) + " " + plural(v, "acre", "acres", 2) : "size " + NONE; }
export function money(v) { return has(v) && !isNaN(Number(v)) ? "$" + num(v) : NONE; }
export function cap(s) { s = String(s); return s.charAt(0).toUpperCase() + s.slice(1); }
// "SCOTT ROAD" as a place name: "Scott Road"
export function placeName(s) { return String(s || "").toLowerCase().replace(/(^|[\s,\/-])([a-z])/g, (m, gap, letter) => gap + letter.toUpperCase()); }
export function apnText(p) { return (p && (p.apn_formatted || p.apn)) || ""; }
export function missing(text = "Not covered yet.") { return `<p class="missing">${esc(text)}</p>`; }

// A moment as people say it: "today at 8:14 PM", "yesterday at 3:02 PM", "Nov 25, 2026".
export function when(seconds) {
  if (!has(seconds)) return "";
  const d = new Date(Number(seconds) * 1000), now = new Date();
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const time = d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  const gap = Math.round((day(now) - day(d)) / 86400000);
  if (gap === 0) return "today at " + time;
  if (gap === 1) return "yesterday at " + time;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}
export function dateOnly(iso) {
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

// head: column titles; rows: arrays of ready-made HTML. Cells that are only a number line up on the right.
export function table(head, rows) {
  const numeric = (c) => /^[$\d,.%–\-\s]+$/.test(c) && /\d/.test(c);
  return '<div class="scroll"><table class="data"><thead><tr>' + head.map((h) => `<th>${h}</th>`).join("") + "</tr></thead><tbody>" +
    rows.map((r) => "<tr>" + r.map((c, i) => `<td${i && numeric(c) ? ' class="num"' : ""}>${c}</td>`).join("") + "</tr>").join("") +
    "</tbody></table></div>";
}

const ICONS = {
  cities: '<path d="M3 21h18M5 21V8l6-3v16M11 21V11l8 3v7M8 10v.01M8 13v.01M8 16v.01M15 16v.01M15 18.5v.01"/>',
  lands: '<path d="M9 4 3 6.5v13.5L9 17.5l6 2.5 6-2.5V4l-6 2.5L9 4zM9 4v13.5M15 6.5V20"/>',
  saved: '<path d="M6 3h12a1 1 0 0 1 1 1v17l-7-4.5L5 21V4a1 1 0 0 1 1-1z"/>',
  overview: '<path d="M4 4h7v7H4zM13 4h7v4h-7zM13 10h7v10h-7zM4 13h7v7H4z"/>',
  zoning: '<path d="m12 3 9 5-9 5-9-5 9-5zM3 12.5l9 5 9-5M3 17l9 5 9-5"/>',
  surroundings: '<circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2 5-5 2 2-5 5-2z"/>',
  terrain: '<path d="m2 20 7-12 4 6 2.5-3.5L22 20H2zM9 8l1.5 2.5"/>',
  traffic: '<path d="M7 21 9 3M17 21 15 3M12 4v3M12 10.5v3M12 17v3"/>',
  plan: '<path d="M4 20h16M6 16l1-4L16.5 2.5a1.4 1.4 0 0 1 2 0l1 1a1.4 1.4 0 0 1 0 2L10 15l-4 1zM14.5 4.5l3 3"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 6.3M20 4v7h-7"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  alert: '<path d="M12 3 2 20h20L12 3zM12 10v4.5M12 17.5v.01"/>',
  pin: '<path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
};
export function icon(name, cls = "") {
  return `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ""}</svg>`;
}

// The parcel's outline as a small picture (north up), for cards and lists.
export function shapeSvg(rings, size = 96, colour = "#f2b632") {
  const pts = (rings || []).flat();
  if (pts.length < 3) return `<div class="shape none" style="width:${size}px;height:${size}px">no outline</div>`;
  const lat = pts.reduce((t, p) => t + p[1], 0) / pts.length, squeeze = Math.cos(lat * Math.PI / 180);
  const xs = pts.map((p) => p[0] * squeeze), ys = pts.map((p) => p[1]);
  const west = Math.min(...xs), east = Math.max(...xs), south = Math.min(...ys), north = Math.max(...ys);
  const span = Math.max(east - west, north - south) || 1, pad = 6, scale = (size - 2 * pad) / span;
  const offX = (size - (east - west) * scale) / 2, offY = (size - (north - south) * scale) / 2;
  const d = rings.map((r) => r.map((p, i) => (i ? "L" : "M") + (offX + (p[0] * squeeze - west) * scale).toFixed(1) + " " +
    (offY + (north - p[1]) * scale).toFixed(1)).join("") + "Z").join("");
  return `<svg class="shape" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" role="img" aria-label="Outline of the parcel"><path d="${d}" fill="${colour}" fill-opacity=".28" stroke="${colour}" stroke-width="2" stroke-linejoin="round" fill-rule="evenodd"/></svg>`;
}

let toastTimer = 0;
export function toast(message) {
  let box = document.getElementById("toast");
  if (!box) { box = document.createElement("div"); box.id = "toast"; box.setAttribute("role", "status"); document.body.appendChild(box); }
  box.textContent = message;
  box.classList.add("on");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => box.classList.remove("on"), 3200);
}

export function loading(text) {
  return `<div class="state loading" role="status"><span class="spinner" aria-hidden="true"></span><p>${esc(text)}</p></div>`;
}
// A problem with a way forward. `retry` is the button's label (leave it out for no button).
export function problem(message, retry = "Try again") {
  return `<div class="state problem" role="alert">${icon("alert")}<p>${esc(message)}</p>${retry ? `<button class="btn" data-retry>${esc(retry)}</button>` : ""}</div>`;
}

export function debounce(fn, ms) {
  let t = 0;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

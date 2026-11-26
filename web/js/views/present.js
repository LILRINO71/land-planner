// The presentation: the forecast and the wider outlook told as slides, for the city's planners and council.
// Address: #/present/<city>/<apn+apn+...>   (?slide=<id> keeps the presenter's place across a reload)
// One slide at a time, moved with the arrow keys, space, a click or a swipe. F: full screen. Esc: back to the forecast.
// Every slide is drawn at 1920 x 1080 and scaled to the screen, so it looks the same on a laptop, a projector and in
// print (Ctrl+P gives one landscape page per slide). On a phone the same slides run down the page instead.
// Every value comes from the server's forecast and outlook answers; a value they do not give reads "not covered yet".
import { api } from "../api.js";
import { createMap, ll } from "../maps.js";
import { mountTerrain } from "../terrain3d.js";
import { NONE, esc, has, num, plural, cap, icon } from "../util.js";

const DW = 1920, DH = 1080;
// one motion switch for the whole app ("landplanner.motion"); the older key is still read, so a choice made before is kept
const MOTION_KEY = "landplanner.motion", OLD_MOTION_KEY = "landplanner.present.motion";
// the park's colour is the Plan page's own (the forecast lists only the uses that are sold)
const PARK = { id: "park", label: "Parks, open space and drainage", short: "Parks", colour: "#3f9d68" };
const KINDS = {
  city: { word: "With the city", colour: "#1f4436" },
  study: { word: "Study", colour: "#4f7fa6" },
  check: { word: "Check", colour: "#b98207" },
  sell: { word: "Offering the land", colour: "#f2b632" },
};
const LEVELS = {
  clear: { word: "Clear", mark: "check" },
  note: { word: "Know about it", mark: "note" },
  work: { word: "Adds work", mark: "alert" },
};
// an entrance onto a street, by what the traffic answer says about a signal there (word, not colour alone)
const ENTRANCES = {
  study: { short: "Study a signal", word: "a new signal is worth studying" },
  existing: { short: "Signal there", word: "a signal already stands there" },
  none: { short: "No signal", word: "no signal likely" },
  unknown: { short: "Not known", word: "not known whether a signal stands there" },
};
const PLACE_COLOURS = {
  park: "#3f9d68", "transit stop": "#4f7fa6", "fire station": "#c4434f", college: "#8a6bbd",
  library: "#e08a2e", police: "#1f4436", hospital: "#d9455f", school: "#f2b632",
};
const INCOME_RAMP = ["#fff2c4", "#f8c26a", "#e9814b", "#c4434f", "#7b1f5c"];
const PERIOD_COLOURS = ["#9cb7a7", "#1f4436", "#f2b632", "#5b8fb9"];
const UNSOLD = "#f5f2ea";

// ---------------------------------------------------------------- words and numbers

const isNum = (v) => has(v) && !isNaN(Number(v)) && isFinite(Number(v));
const colourOf = (c) => (/^#[0-9a-f]{3,8}$/i.test(String(c || "")) ? c : "#9aa0a6");
const miles = (m) => (isNum(m) ? `${num(m, 2)} ${Number(m) === 1 ? "mile" : "miles"}` : NONE);
const money = (v) => (isNum(v) ? "$" + num(v) : NONE);
const pct = (v, d = 0) => (isNum(v) ? num(v, d) + "%" : NONE);
function range(o, d = 0) {
  if (!o || !isNum(o.low) || !isNum(o.high)) return NONE;
  return Number(o.low) === Number(o.high) ? num(o.low, d) : `${num(o.low, d)} to ${num(o.high, d)}`;
}
function listWords(items) {
  if (items.length <= 1) return items.join("");
  return items.slice(0, -1).join(", ") + " and " + items[items.length - 1];
}
const WORDS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"];
const countWord = (n) => WORDS[n] || String(n);
// a number that counts up when its slide comes in; it is written out in full first, so it reads without motion
const big = (v, d = 0) => (isNum(v) ? `<data class="pr-n" value="${Number(v)}" data-to="${Number(v)}" data-d="${d}">${num(v, d)}</data>` : NONE);
const missing = (what) => `<p class="pr-missing">${esc(what)}: not covered yet.</p>`;
const dayWords = (d) => d.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });

// a starting figure with its unit, as people say it: "30%", "$400 per sq ft", "2 years"
function figureWords(f) {
  const u = String(f.unit || ""), v = num(f.value, 2);
  if (u === "%") return v + "%";
  if (u.startsWith("$ ")) return "$" + v + " " + esc(u.slice(2));
  return v + (u ? " " + esc(u) : "");
}
function mark(level) {
  const kind = (LEVELS[level] || LEVELS.note).mark;
  if (kind === "note") return `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.01"/></svg>`;
  return icon(kind);
}

// ---------------------------------------------------------------- charts (inline SVG, drawn at the size of their box)

function niceStep(span, count) {
  const raw = span / Math.max(1, count), mag = Math.pow(10, Math.floor(Math.log10(raw || 1))), r = raw / mag;
  return (r <= 1 ? 1 : r <= 2 ? 2 : r <= 2.5 ? 2.5 : r <= 5 ? 5 : 10) * mag;
}
function ticks(values, count, zero) {
  const v = values.filter(isNum).map(Number);
  let lo = v.length ? Math.min(...v) : 0, hi = v.length ? Math.max(...v) : 1;
  if (zero) { lo = Math.min(0, lo); hi = hi * 1.06; } else { const pad = (hi - lo) * 0.1 || Math.abs(hi) * 0.05 || 1; lo = Math.max(0, lo - pad); hi += pad; }
  if (!(hi > lo)) hi = lo + 1;
  const step = niceStep(hi - lo, count);
  const a = Math.floor(lo / step + 1e-9) * step, b = Math.ceil(hi / step - 1e-9) * step;
  const list = [];
  for (let t = a; t <= b + step / 2; t += step) list.push(Math.round(t / step) * step);
  return { lo: a, hi: b, list, digits: step < 1 ? (step < 0.5 ? 2 : 1) : step % 1 ? 1 : 0 };
}
const pathOf = (pts) => pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join("");

// o: { w, h, fs, x0, x1, values, zero, unit, label, draw(s), xLabel(v), fmt(v) }
function chart(o) {
  const fs = o.fs, W = Math.max(160, Math.round(o.w)), H = Math.max(110, Math.round(o.h));
  const t = ticks(o.values, H >= 300 ? 5 : H >= 190 ? 4 : 3, o.zero);
  const fmt = o.fmt || ((v) => num(v, t.digits));
  const labels = t.list.map(fmt);
  const left = Math.round(fs * 0.6 + Math.max(...labels.map((s) => String(s).length)) * fs * 0.58);
  const right = Math.round(fs * (o.roomRight || 0.9)), top = Math.round(fs * (o.unit ? 2.1 : 0.9)), bottom = Math.round(fs * 2);
  const pw = Math.max(40, W - left - right), ph = Math.max(30, H - top - bottom), count = o.x1 - o.x0 + 1, slot = pw / count;
  const x = (v) => left + (v - o.x0 + 0.5) * slot;
  const y = (v) => top + ph - (Number(v) - t.lo) / (t.hi - t.lo) * ph;
  const s = { x, y, slot, top, bottom: top + ph, left, right: W - right, fs, W, H };
  let out = `<svg class="pr-svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${esc(o.label)}" style="font-size:${fs}px">`;
  t.list.forEach((v, i) => {
    const yy = y(v).toFixed(1);
    out += `<line class="pr-guide${v === 0 ? " zero" : ""}" x1="${left}" x2="${s.right.toFixed(1)}" y1="${yy}" y2="${yy}"/>` +
      `<text class="pr-ylab" x="${(left - fs * 0.45).toFixed(1)}" y="${yy}" dy="0.36em" text-anchor="end">${esc(labels[i])}</text>`;
  });
  if (o.unit) out += `<text class="pr-unit" x="${left}" y="${(fs * 1.05).toFixed(1)}">${esc(o.unit)}</text>`;
  const every = [1, 2, 3, 5, 10].find((k) => slot * k >= fs * (o.xRoom || 3.2)) || 10;
  for (let v = o.x0; v <= o.x1; v++) {
    if ((v - o.x0) % every !== 0) continue;
    out += `<text class="pr-xlab" x="${x(v).toFixed(1)}" y="${(H - fs * 0.45).toFixed(1)}" text-anchor="middle">${esc(o.xLabel ? o.xLabel(v) : v)}</text>`;
  }
  out += o.draw(s);
  return out + "</svg>";
}
// pts: [x, low, high]
function band(s, pts, cls = "pr-band") {
  const ok = pts.filter((p) => isNum(p[1]) && isNum(p[2]));
  if (ok.length < 2) return "";
  const upper = ok.map((p) => [s.x(p[0]), s.y(p[2])]), lower = ok.slice().reverse().map((p) => [s.x(p[0]), s.y(p[1])]);
  return `<path class="${cls} pr-fade" d="${pathOf(upper.concat(lower))}Z"/>`;
}
// pts: [x, value]; a missing value breaks the line
function line(s, pts, cls = "pr-line") {
  let d = "", run = [];
  const flush = () => { if (run.length > 1) d += pathOf(run); run = []; };
  pts.forEach((p) => { if (isNum(p[1])) run.push([s.x(p[0]), s.y(p[1])]); else flush(); });
  flush();
  return d ? `<path class="${cls} pr-draw" pathLength="1" d="${d}"/>` : "";
}
function dots(s, pts, cls = "pr-dot", r = 0.36) {
  return pts.filter((p) => isNum(p[1])).map((p, i) => `<circle class="${cls} pr-pop" style="--k:${i}" cx="${s.x(p[0]).toFixed(1)}" cy="${s.y(p[1]).toFixed(1)}" r="${(s.fs * r).toFixed(1)}"/>`).join("");
}
// bars stand on the bottom of the chart: only charts that start at zero draw them
function bars(s, pts, cls = "pr-bar", share = 0.6) {
  return pts.filter((p) => isNum(p[1]) && Number(p[1]) > 0).map((p, i) => {
    const top = s.y(p[1]), w = s.slot * share;
    return `<rect class="${cls} pr-grow" style="--k:${i}" x="${(s.x(p[0]) - w / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${w.toFixed(1)}" height="${Math.max(0, s.bottom - top).toFixed(1)}"/>`;
  }).join("");
}
function today(s, year, words = "Today") {
  const xx = s.x(year).toFixed(1);
  return `<line class="pr-today" x1="${xx}" x2="${xx}" y1="${s.top}" y2="${s.bottom}"/><text class="pr-today-lab" x="${(s.x(year) + s.fs * 0.4).toFixed(1)}" y="${(s.top + s.fs).toFixed(1)}">${esc(words)}</text>`;
}
function endLabel(s, xv, yv, words, cls = "pr-endlab") {
  if (!isNum(yv)) return "";
  return `<text class="${cls} pr-fade" x="${(s.x(xv) - s.fs * 0.3).toFixed(1)}" y="${(s.y(yv) - s.fs * 0.9).toFixed(1)}" text-anchor="end">${esc(words)}</text>`;
}
const key = (cls, words, style = "") => `<span><i class="pr-key ${cls}"${style ? ` style="${style}"` : ""}></i>${words}</span>`;

// ---------------------------------------------------------------- shapes on the map

const outlineOf = (p) => (p && p.outline && p.outline.coordinates ? ll(p.outline.type === "MultiPolygon" ? p.outline.coordinates.flat() : p.outline.coordinates) : null);
function ringBox(L, at, m) {
  const north = m / 69.05, east = m / (69.17 * Math.cos(at.lat * Math.PI / 180));
  return L.latLngBounds([at.lat - north, at.lon - east], [at.lat + north, at.lon + east]);
}
function label(L, latlng, html, cls = "") {
  return L.marker(latlng, { icon: L.divIcon({ className: "pr-lab " + cls, iconSize: [0, 0], html: `<span>${html}</span>` }), interactive: false, keyboard: false });
}

// A piece of land cut across its longer side into bands of the given shares, starting from the end nearest `toward`.
// Used to shade how much of each use's land is offered in each period. Returns [[lat, lon]...] per band.
function cutBands(ring, shares, toward) {
  let pts = ring.map((p) => [p[0], p[1]]);
  if (pts.length > 1 && pts[0][0] === pts[pts.length - 1][0] && pts[0][1] === pts[pts.length - 1][1]) pts = pts.slice(0, -1);
  if (pts.length < 3) return shares.map(() => null);
  const lat0 = pts.reduce((t, p) => t + p[1], 0) / pts.length, k = Math.cos(lat0 * Math.PI / 180);
  const xy = pts.map((p) => [p[0] * k, p[1]]);
  const xs = xy.map((p) => p[0]), ys = xy.map((p) => p[1]);
  const axis = Math.max(...xs) - Math.min(...xs) >= Math.max(...ys) - Math.min(...ys) ? 0 : 1;
  const lo = Math.min(...xy.map((p) => p[axis])), hi = Math.max(...xy.map((p) => p[axis]));
  const fromLow = toward ? (axis === 0 ? toward[0] * k : toward[1]) <= (lo + hi) / 2 : true;
  const clip = (poly, c, below) => {
    const out = [];
    for (let i = 0; i < poly.length; i++) {
      const a = poly[i], b = poly[(i + 1) % poly.length], ia = below ? a[axis] <= c : a[axis] >= c, ib = below ? b[axis] <= c : b[axis] >= c;
      if (ia) out.push(a);
      if (ia !== ib) { const t = (c - a[axis]) / (b[axis] - a[axis]); out.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]); }
    }
    return out;
  };
  const area = (poly) => Math.abs(poly.reduce((t, p, i) => { const q = poly[(i + 1) % poly.length]; return t + p[0] * q[1] - q[0] * p[1]; }, 0)) / 2;
  const total = area(xy) || 1;
  const cutAt = (f) => {
    if (f <= 0) return fromLow ? lo : hi;
    if (f >= 1) return fromLow ? hi : lo;
    let a = lo, b = hi;
    for (let i = 0; i < 44; i++) {
      const c = (a + b) / 2, share = area(clip(xy, c, fromLow)) / total;
      if ((share < f) === fromLow) a = c; else b = c;
    }
    return (a + b) / 2;
  };
  let sum = 0;
  const cuts = [cutAt(0)].concat(shares.map((f) => cutAt(Math.min(1, (sum += f)))));
  return shares.map((f, i) => {
    if (!(f > 0.004)) return null;
    const band = clip(clip(xy, cuts[i], !fromLow), cuts[i + 1], fromLow);
    return band.length >= 3 ? band.map((p) => [p[1], p[0] / k]) : null;
  });
}

// ---------------------------------------------------------------- the page

export async function render(main, route, alive) {
  const cityId = route.city, apns = route.apns || [];
  const backHref = `#/forecast/${encodeURIComponent(cityId)}/${apns.map(encodeURIComponent).join("+")}`;
  const timers = new Set(), cleanups = [];
  let gone = false;
  alive.onLeave(() => {
    gone = true;
    timers.forEach((t) => clearTimeout(t));
    cleanups.splice(0).forEach((fn) => { try { fn(); } catch (e) { console.error(e); } });
  });
  const later = (fn, ms) => { const t = setTimeout(() => { timers.delete(t); if (!gone) fn(); }, ms); timers.add(t); return t; };

  main.innerHTML = `<div class="pr-root pr-waiting"><div class="pr-wait-box"><span class="spinner" aria-hidden="true"></span>
    <p>Preparing the presentation from the public records around this site. The first time takes several seconds.</p>
    <a class="pr-back" href="${esc(backHref)}">Back to the forecast</a></div></div>`;
  if (!apns.length) {
    main.innerHTML = `<div class="pr-root pr-waiting"><div class="pr-wait-box"><p>This address does not name any parcel numbers. Open a land's forecast and press Present.</p><a class="btn" href="#/my-lands">Go to My lands</a></div></div>`;
    return;
  }
  let F;
  try {
    F = await api.forecast(cityId, apns);
  } catch (e) {
    if (!alive()) return;
    // a parcel that does not exist will not appear by asking again; anything else might
    if (e.status === 404 || e.status === 400) {
      main.innerHTML = `<div class="pr-root pr-waiting"><div class="pr-wait-box" role="alert"><p>${esc(e.message)}</p>
        <p><a class="btn" href="#/lands/${encodeURIComponent(cityId)}">Back to the lands</a></p></div></div>`;
      return;
    }
    main.innerHTML = `<div class="pr-root pr-waiting"><div class="pr-wait-box" role="alert"><p>${esc(e.message)}</p>
      <p><button class="btn" type="button" data-again>Try again</button> <a class="btn" href="${esc(backHref)}">Back to the forecast</a></p></div></div>`;
    main.querySelector("[data-again]").addEventListener("click", () => render(main, route, alive));
    return;
  }
  if (!alive()) return;
  if (!F || F.available === false) {
    main.innerHTML = `<div class="pr-root pr-waiting"><div class="pr-wait-box"><p>The forecast for this site is not covered yet, so there is nothing to present.</p><a class="btn" href="${esc(backHref)}">Back to the forecast</a></div></div>`;
    return;
  }

  // ---------------------------------------------------------------- state

  // O: the outlook. G: the ground under the whole site with the plan drawn on it (for the 3D view).
  const S = { O: null, Oerr: "", G: null, Gerr: "" };
  // the 3D view can be drawn: the ground heights are read and a plan is drawn on them
  const has3d = () => !!(S.G && S.G.surface && S.G.plan && S.G.plan.drawing && (S.G.plan.drawing.pieces || []).length && S.G.parcel && S.G.parcel.outline);
  // why there is no 3D view, in plain words ("" while it is still being read, or when there is one)
  function no3dWords() {
    if (S.Gerr) return `The 3D view could not be made just now (${S.Gerr}).`;
    if (!S.G || has3d()) return "";
    if (!S.G.surface) return "The 3D view is not available for this site: the ground heights under it are not covered yet.";
    return "The 3D view is not available for this site: the parcels do not form one block, so no single plan is drawn on the ground.";
  }
  let motion = true;
  try { motion = (localStorage.getItem(MOTION_KEY) || localStorage.getItem(OLD_MOTION_KEY)) !== "off"; } catch (e) { /* private window: keep the default */ }
  let flow = false, cur = 0, order = [], scaleNow = 1;
  const recs = new Map();
  const wantSlide = (/[?&]slide=([\w-]+)/.exec(location.hash) || [])[1] || "";
  let pendingSlide = "";      // the slide the address asks for, while it does not exist yet (it needs a slower answer)

  main.innerHTML = `<div class="pr-root${motion ? " pr-motion" : ""}" id="prRoot">
    <div class="pr-stage"><div class="pr-canvas">
      <div class="pr-deck"></div>
      <footer class="pr-foot">
        <a class="pr-back" href="${esc(backHref)}">${icon("arrow", "flip")}<span>Back to the forecast</span></a>
        <div class="pr-progress"><div class="pr-segs" role="group" aria-label="Slides"></div><p class="pr-now-title"></p></div>
        <div class="pr-tools">
          <button type="button" class="pr-tool" data-prev aria-label="Previous slide">${icon("arrow", "flip")}</button>
          <span class="pr-count" aria-live="polite"></span>
          <button type="button" class="pr-tool" data-next aria-label="Next slide">${icon("arrow")}</button>
          <button type="button" class="pr-tool pr-switch" data-motion role="switch" aria-checked="${motion}"><i aria-hidden="true"></i><span>Motion ${motion ? "on" : "off"}</span></button>
          <button type="button" class="pr-tool pr-word" data-full aria-keyshortcuts="F">Full screen</button>
          <button type="button" class="pr-tool pr-word" data-print>Print</button>
          <a class="pr-tool pr-word" href="${esc(backHref.replace("#/forecast/", "#/handout/"))}" title="The whole site on one printed page, to leave with the people in the room">One page</a>
        </div>
      </footer>
    </div></div></div>`;
  const root = main.querySelector("#prRoot"), canvas = root.querySelector(".pr-canvas"), deck = root.querySelector(".pr-deck");
  const segs = root.querySelector(".pr-segs"), nowTitle = root.querySelector(".pr-now-title"), counter = root.querySelector(".pr-count");

  // ---------------------------------------------------------------- facts used by several slides

  const site = F.site || {}, parcels = site.parcels || [], G = F.programme || {};
  const ringOf = (m) => (F.rings || []).find((r) => r.miles === m);
  const market = F.market_miles, R = ringOf(market) || (F.rings || [])[0] || null;
  const at = site.centre && isNum(site.centre.lat) ? { lat: Number(site.centre.lat), lon: Number(site.centre.lon) } : null;
  const uses = (G.uses || []).filter((u) => Number(u.acres) > 0);
  const useById = Object.fromEntries(uses.map((u) => [u.id, u]).concat([[PARK.id, PARK]]));
  const drawings = (G.drawings || []).filter((d) => d && (d.pieces || []).length);
  const pieces = drawings.flatMap((d) => d.pieces || []);
  const streetLines = drawings.flatMap((d) => d.street_lines || []);
  const zones = [...new Set(parcels.map((p) => p.zoning_name ? `${p.zoning_name}${p.zoning ? ` (${p.zoning})` : ""}` : p.zoning).filter(Boolean))];
  const lastRow = (rows) => (rows || [])[(rows || []).length - 1];
  const rowAt = (rows, y) => (rows || []).find((r) => r.year === y);
  const headlineItem = (start) => (F.headline || []).find((h) => String(h.label || "").startsWith(start));
  const siteName = `${isNum(site.acres) ? num(site.acres, 2) + " " + plural(site.acres, "acre", "acres", 2) : "The site"} in ${F.city_name || cityId}`;

  function siteBounds(L) {
    const pts = parcels.flatMap((p) => (outlineOf(p) || []).flat());
    return pts.length ? L.latLngBounds(pts) : at ? L.latLngBounds([[at.lat, at.lon], [at.lat, at.lon]]) : null;
  }
  function drawParcels(L, m, { fill = 0.18, weight = 4 } = {}) {
    const out = [];
    parcels.forEach((p) => {
      const shape = outlineOf(p);
      if (!shape) return;
      L.polygon(shape, { color: "#1d2a24", weight: weight + 4, opacity: 0.7, fill: false, interactive: false }).addTo(m);
      out.push(L.polygon(shape, { color: "#f2b632", weight, fillColor: "#f2b632", fillOpacity: fill })
        .bindTooltip(`Parcel ${esc(p.apn_formatted || p.apn)}${isNum(p.acres) ? ", " + num(p.acres, 2) + " " + plural(p.acres, "acre", "acres", 2) : ""}`, { sticky: true }).addTo(m));
    });
    return out;
  }
  function newMap(rec, el, options = {}) {
    const view = createMap(el, { base: "aerial", ...options });
    view.map.scrollWheelZoom.disable();
    if (flow) view.map.dragging.disable();
    // a redraw the canvas has already asked for runs first: taking the map away before it trips Leaflet
    rec.cleanup.push(() => { view.map.getContainer().style.visibility = "hidden"; requestAnimationFrame(() => setTimeout(() => view.destroy(), 0)); });
    rec.views.push(view);
    return view;
  }
  // map shapes that come in one after another when the slide enters
  function reveal(rec, items) {
    rec.reveal = items;
  }
  function playReveal(rec) {
    const items = rec.reveal || [];
    const setTo = (it, t) => {
      if (it.layer && it.layer._map) it.layer.setStyle({ opacity: it.style.opacity * t, fillOpacity: (it.style.fillOpacity || 0) * t });
      if (it.marker) { const e = it.marker.getElement(); if (e) e.style.opacity = String(t); }
    };
    const run = rec.run = {};
    if (!motion) { items.forEach((it) => setTo(it, 1)); return; }
    items.forEach((it) => setTo(it, 0));
    const t0 = performance.now() + 350;
    const gap = Math.min(280, 2600 / Math.max(1, items.length));
    items.forEach((it, i) => {
      const start = t0 + i * gap, step = (now) => {
        if (gone || rec.run !== run) return;
        const t = Math.max(0, Math.min(1, (now - start) / 560));
        setTo(it, 1 - Math.pow(1 - t, 2));
        if (t < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    });
  }

  // ---------------------------------------------------------------- the slides

  const head = (h, lead) => `<header class="pr-head"><h2 data-rise>${h}</h2>${lead ? `<p class="pr-lead" data-rise>${lead}</p>` : ""}</header>`;
  const fig = (value, words, note = "") => `<div class="pr-fig" data-rise><b>${value}</b><span>${words}</span>${note ? `<small>${note}</small>` : ""}</div>`;
  const waiting = (title) => `${head(esc(title))}<div class="pr-pending" data-rise>${S.Oerr
    ? `<p>${esc(S.Oerr)}</p><button type="button" class="btn" data-outlook-again>Try again</button>`
    : `<span class="spinner" aria-hidden="true"></span><p>Reading the city's records for this slide. It fills in by itself in a moment.</p>`}</div>`;
  const outlookKey = () => (S.O ? "ready" : S.Oerr ? "error" : "wait");

  function defs() {
    const list = [];
    const O = S.O;

    // ---- 1. the site
    list.push({
      id: "site", title: "The site", key: "1",
      html() {
        const sources = (F.sources || []).filter((s) => s.answered).map((s) => esc(s.name));
        return `<div class="pr-title">
          <div class="pr-title-text">
            <h1 data-rise>${esc(siteName)}</h1>
            <p class="pr-lead" data-rise>${parcels.length === 1 ? "One parcel" : `${countWord(parcels.length)} ${site.together ? "neighbouring " : ""}parcels`}${zones.length ? `, zoned ${esc(listWords(zones))}` : ""}.${parcels.length > 1 && G.basis ? " " + esc(G.basis) : ""}</p>
            <dl class="pr-title-facts" data-rise>
              <div><dt>${parcels.length === 1 ? "Parcel number" : "Parcel numbers"}</dt><dd>${parcels.map((p) => esc(p.apn_formatted || p.apn)).join("<br>")}</dd></div>
              <div><dt>Acres</dt><dd>${parcels.length > 1 ? parcels.map((p) => isNum(p.acres) ? num(p.acres, 2) : NONE).join("<br>") : isNum(site.acres) ? num(site.acres, 2) : NONE}</dd></div>
              <div><dt>Prepared</dt><dd>${esc(dayWords(new Date()))}</dd></div>
            </dl>
            <p class="pr-sources" data-rise>Prepared with public records: <span data-title-sources>${sources.length ? sources.join(", ") : NONE}</span>.</p>
          </div>
          <div class="pr-title-map pr-mapframe"><div class="pr-map" data-map></div></div>
        </div>`;
      },
      mount(el, rec) {
        const L = window.L, view = newMap(rec, el.querySelector("[data-map]"), { city: F.city, at });
        const shapes = drawParcels(L, view.map, { fill: 0.22 });
        const b = siteBounds(L);
        if (b) view.fit(b.pad(0.5));
        reveal(rec, shapes.map((layer) => ({ layer, style: { opacity: 1, fillOpacity: 0.22 } })));
      },
      enter: playReveal,
    });

    // ---- 2. where it is
    list.push({
      id: "where", title: "Where it is", key: outlookKey(),
      html() {
        const hw = (F.traffic || {}).highway || null;
        const near = O && O.nearby && O.nearby.available ? O.nearby : null;
        const nearest = near ? Object.values(near.nearest || {}).filter((p) => isNum(p.miles_away)).sort((a, b) => a.miles_away - b.miles_away) : [];
        const h = hw && isNum(hw.miles_away) ? `${esc(miles(hw.miles_away))} from Route ${esc(hw.route)}` : "Where the site sits";
        const lead = hw && isNum(hw.miles_away) ? `The state's traffic count point on Route ${esc(hw.route)} at ${esc(hw.where)} is ${esc(miles(hw.miles_away))} from the middle of the site.` : "";
        const rings = (F.rings || []).map((r) => r.miles).filter(isNum);
        let side;
        if (!O && !S.Oerr) side = `<div class="pr-pending small" data-rise><span class="spinner" aria-hidden="true"></span><p>Reading what is close by…</p></div>`;
        else if (!near) side = `<div data-rise>${missing("What is close by")}${S.Oerr ? `<p>${esc(S.Oerr)}</p><button type="button" class="btn" data-outlook-again>Try again</button>` : ""}</div>`;
        else side = `<h3 class="pr-sub" data-rise>Nearest of each kind</h3><ul class="pr-places">${nearest.map((p) => `<li data-rise><i style="background:${PLACE_COLOURS[p.kind] || "#9aa0a6"}"></i><span><b>${esc(p.name)}</b><small>${esc(cap(p.kind))}${p.detail ? ", " + esc(p.detail) : ""}</small></span><em>${esc(miles(p.miles_away))}</em></li>`).join("")}</ul>
          ${(near.not_covered || []).length ? `<p class="pr-note" data-rise>Not covered yet: ${esc(listWords(near.not_covered))}.</p>` : ""}`;
        return `<div class="pr-mapleft">
          <div class="pr-mapframe"><div class="pr-map" data-map></div>
            <p class="pr-maplegend">${key("site", "The site")}${key("ring", esc(listWords(rings.map(miles))) + " around it")}${near ? key("dot", "Places close by, coloured by kind") : ""}</p></div>
          <div class="pr-side">${head(h, lead)}${side}</div></div>`;
      },
      mount(el, rec) {
        const L = window.L, view = newMap(rec, el.querySelector("[data-map]")), m = view.map;
        const rings = (F.rings || []).map((r) => r.miles).filter(isNum), items = [];
        let b = null;
        if (at) {
          rings.slice().sort((a, c) => a - c).forEach((mi) => {
            const c = L.circle([at.lat, at.lon], { radius: mi * 1609.344, color: "#ffffff", weight: 3, opacity: 0.95, dashArray: "10 10", fill: false, interactive: false }).addTo(m);
            const lab = label(L, [at.lat + mi / 69.05, at.lon], esc(miles(mi)), "ring").addTo(m);
            items.push({ layer: c, style: { opacity: 0.95 } }, { marker: lab });
          });
          b = ringBox(L, at, Math.max(...rings, 1));
        }
        drawParcels(L, m, { fill: 0.5, weight: 3 });
        const near = S.O && S.O.nearby && S.O.nearby.available ? S.O.nearby : null;
        if (near) {
          const firsts = new Set(Object.values(near.nearest || {}).map((p) => p.name));
          (near.places || []).forEach((p) => {
            if (!isNum(p.lat) || !isNum(p.lon)) return;
            const dot = L.circleMarker([p.lat, p.lon], { radius: 9, color: "#1d2a24", weight: 2, fillColor: PLACE_COLOURS[p.kind] || "#9aa0a6", fillOpacity: 1 })
              .bindTooltip(`<b>${esc(p.name)}</b><br>${esc(cap(p.kind))}, ${esc(miles(p.miles_away))} away`).addTo(m);
            items.push({ layer: dot, style: { opacity: 1, fillOpacity: 1 } });
            if (firsts.has(p.name)) { const lab = label(L, [p.lat, p.lon], esc(p.name), "place").addTo(m); items.push({ marker: lab }); }
          });
        }
        if (!b) b = siteBounds(L);
        if (b) view.fit(b.pad(0.02));
        reveal(rec, items);
      },
      enter: playReveal,
    });

    // ---- 3. the area is growing
    list.push({
      id: "growing", title: "The area is growing", key: "1",
      html() {
        if (!R || !R.available) return head("The area is growing") + missing(`People within ${miles(market)}`);
        const now = rowAt(R.rows, F.year), end = lastRow(R.rows), mid = rowAt(R.rows, F.year + 5);
        const c = R.counted || {}, years = Object.keys(c).sort();
        const h = `${big(now && now.people.expected)} ${plural(now && now.people.expected, "person", "people")} live within ${esc(miles(R.miles))}; about ${big(end && end.people.expected)} by ${esc(end ? end.year : "")}`;
        const lead = years.length ? `Counted by the Census: ${years.map((y) => `${num(c[y].people)} in ${esc(y)}`).join(" and ")}. The forecast follows the middle of ${countWord((R.readings || []).length).toLowerCase()} readings: homes growing ${pct((R.rates_pct || {}).expected, 2)} a year, from ${pct((R.rates_pct || {}).low, 2)} on the low line to ${pct((R.rates_pct || {}).high, 2)} on the high one.` : "";
        return `${head(h, lead)}<div class="pr-body pr-chartbody">
          <div class="pr-visual"><div class="pr-chart" data-chart="growth"></div>
            <p class="pr-keys" data-rise>${key("dot", "Counted by the Census")}${key("line", "Expected")}${key("band", "Low to high")}</p></div>
          <aside class="pr-aside">
            ${mid ? fig(big(mid.people.expected), `people by ${esc(mid.year)}`, `low to high: ${range(mid.people)}`) : ""}
            ${end ? fig(big(end.people.expected), `people by ${esc(end.year)}`, `low to high: ${range(end.people)}`) : ""}
            <h3 class="pr-sub" data-rise>The readings it rests on</h3>
            <ul class="pr-readings">${(R.readings || []).map((r) => `<li data-rise><span class="pr-tag ${r.kind === "measured" ? "measured" : "official"}">${esc(r.kind === "measured" ? "Measured" : "Official forecast")}</span><span>${esc(r.label)}${r.whole_city ? " (whole city)" : ""}: <b>${pct(r.rate_pct, 2)}</b> a year</span></li>`).join("")}</ul>
          </aside></div>`;
      },
      charts: {
        growth: (w, h, fs) => {
          const rows = R.rows || [], c = R.counted || {};
          const counted = Object.keys(c).map((y) => [Number(y), c[y].people]).filter((p) => isNum(p[1]));
          const xs = rows.map((r) => r.year).concat(counted.map((p) => p[0]));
          const vals = rows.flatMap((r) => [r.people.low, r.people.high]).concat(counted.map((p) => p[1]));
          const end = lastRow(rows);
          return chart({
            w, h, fs, x0: Math.min(...xs), x1: Math.max(...xs), values: vals, zero: false, unit: `people within ${miles(R.miles)}`,
            label: `Chart of people within ${miles(R.miles)}: the Census counts, and the forecast to ${end ? end.year : ""} with its low to high range.`,
            draw: (s) => band(s, rows.map((r) => [r.year, r.people.low, r.people.high])) + today(s, F.year) +
              line(s, rows.map((r) => [r.year, r.people.expected])) +
              dots(s, counted, "pr-dot counted", 0.5) +
              counted.map((p) => `<text class="pr-endlab pr-fade" x="${s.x(p[0]).toFixed(1)}" y="${(s.y(p[1]) - fs * 0.9).toFixed(1)}" text-anchor="middle">${num(p[1])}</text>`).join("") +
              (end ? endLabel(s, end.year, end.people.expected, num(end.people.expected)) : ""),
          });
        },
      },
    });

    // ---- 4. incomes
    list.push({
      id: "incomes", title: "Household incomes", key: "1",
      html() {
        const inc = F.income || {};
        if (!inc.available) return head("Household incomes") + missing("Household income around the site");
        const gap = isNum(inc.typical) && isNum(inc.county) && inc.county > 0 ? Math.round((inc.typical / inc.county - 1) * 100) : null;
        const h = gap === null ? `Typical household income: ${money(inc.typical)}` : gap === 0 ? "Households here earn about what the county does"
          : `Households here earn ${Math.abs(gap)}% ${gap > 0 ? "more" : "less"} than the county`;
        const most = Math.max(Number(inc.typical) || 0, Number(inc.county) || 0, ...(inc.by_direction || []).map((d) => Number(d.income) || 0)) || 1;
        const barRow = (words, v, cls = "") => `<div class="pr-hbar ${cls}" data-rise><span>${words}</span><i><b class="pr-growx" style="width:${(100 * (Number(v) || 0) / most).toFixed(1)}%"></b></i><em>${isNum(v) ? "$" + big(v) : NONE}</em></div>`;
        return `<div class="pr-mapright">
          <div class="pr-side">${head(h, esc(inc.summary || ""))}
            <div class="pr-hbars">${barRow(`Within ${esc(miles(market))}`, inc.typical, "here")}${barRow(esc(inc.county_name || "The county"), inc.county, "county")}</div>
            ${(inc.by_direction || []).length ? `<h3 class="pr-sub" data-rise>By direction from the site</h3><div class="pr-hbars small">${inc.by_direction.map((d) => barRow(esc(cap(d.direction)), d.income)).join("")}</div>` : ""}
            ${isNum(inc.renters_pct) ? `<p class="pr-body-text" data-rise>About <b>${num(inc.renters_pct)}%</b> of households rent and <b>${num(100 - inc.renters_pct)}%</b> own their home.</p>` : ""}
            <p class="pr-note" data-rise>${esc(inc.source || "Census survey")}${inc.survey ? `, ${esc(inc.survey)}` : ""}. Survey dollars, not adjusted for inflation.</p>
          </div>
          <div class="pr-mapframe"><div class="pr-map" data-map></div><p class="pr-maplegend" data-income-legend></p></div></div>`;
      },
      mount(el, rec) {
        const inc = F.income || {};
        if (!inc.available) return;
        const L = window.L, view = newMap(rec, el.querySelector("[data-map]")), m = view.map, items = [];
        drawParcels(L, m, { fill: 0.5, weight: 3 });
        const lo = Number(inc.lowest), hi = Number(inc.highest), ok = isNum(inc.lowest) && isNum(inc.highest) && hi > lo;
        const step = ok ? (hi - lo) / INCOME_RAMP.length : 1;
        const colour = (v) => INCOME_RAMP[Math.min(INCOME_RAMP.length - 1, Math.max(0, Math.floor((Number(v) - lo) / step)))];
        if (at) L.circle([at.lat, at.lon], { radius: market * 1609.344, color: "#ffffff", weight: 3, dashArray: "10 10", fill: false, interactive: false }).addTo(m);
        (inc.tracts || []).slice().sort((a, b) => b.miles_away - a.miles_away).forEach((t) => {
          if (!isNum(t.lat) || !isNum(t.lon) || !ok) return;
          const d = L.circleMarker([t.lat, t.lon], { radius: 14, color: "#1d2a24", weight: 2, fillColor: colour(t.income), fillOpacity: 1 })
            .bindTooltip(`<b>${esc(t.name)}</b><br>Typical household income $${num(t.income)} a year<br>${num(t.households)} ${plural(t.households, "household")}, ${esc(miles(t.miles_away))} ${esc(t.direction || "")}`).addTo(m);
          items.push({ layer: d, style: { opacity: 1, fillOpacity: 1 } });
        });
        items.reverse();
        if (at) view.fit(ringBox(L, at, market).pad(0.05));
        el.querySelector("[data-income-legend]").innerHTML = ok
          ? INCOME_RAMP.map((c, i) => key("swatch", `$${num(Math.round((lo + i * step) / 1000) * 1000)} to $${num(i === INCOME_RAMP.length - 1 ? hi : Math.round((lo + (i + 1) * step) / 1000) * 1000)}`, `background:${c}`)).join("") + `<span class="pr-legend-note">Each dot: one census tract, at its middle. Dashed circle: ${esc(miles(market))}.</span>`
          : `<span>Income bands: not covered yet.</span>`;
        reveal(rec, items);
      },
      enter: playReveal,
    });

    // ---- 5. the typical resident
    list.push({
      id: "residents", title: "Who lives here", key: outlookKey(),
      html() {
        if (!O) return waiting("Who lives here");
        const r = O.resident || {};
        if (!r.available) return head("Who lives here") + missing("The typical resident nearby");
        const t = r.typical || {}, e = r.earlier || {};
        const h = isNum(t.median_age) && isNum(t.household_size) ? `The typical resident is ${big(Math.round(t.median_age))} and lives in a household of ${big(t.household_size, 1)}` : "Who lives here";
        const tiles = [
          ["under_18_pct", "are under 18"], ["over_65_pct", "are 65 or older"], ["bachelors_pct", "of adults have a college degree"],
          ["work_from_home_pct", "work from home"], ["long_commute_pct", "travel an hour or more to work"], ["drive_alone_pct", "drive to work alone"],
          ["spanish_at_home_pct", "speak Spanish at home"],
        ].filter(([k]) => isNum(t[k]));
        const most = Math.max(Number(t.home_value_usd) || 0, Number(e.home_value_usd) || 0) || 1;
        const col = (v, when, cls) => `<div class="pr-vbar ${cls}" data-rise><em>${isNum(v) ? "$" + big(v) : NONE}</em><i><b class="pr-growy" style="height:${(100 * (Number(v) || 0) / most).toFixed(1)}%"></b></i><span>${esc(when)}</span></div>`;
        return `${head(h, esc((r.facts || [])[2] || ""))}<div class="pr-body pr-resbody">
          <div class="pr-homevalue"><h3 class="pr-sub" data-rise>Typical home value</h3>
            <div class="pr-vbars">${col(e.home_value_usd, `${e.years || "earlier"} survey`, "then")}${col(t.home_value_usd, `${r.survey || "latest"} survey`, "now")}</div>
            <p class="pr-body-text" data-rise>Typical rent: <b>${money(t.rent_usd)}</b> a month${isNum(e.rent_usd) ? `, up from ${money(e.rent_usd)}` : ""}.</p></div>
          <div class="pr-tiles">${tiles.map(([k, words]) => fig(big(t[k], 0) + "%", esc(words))).join("")}</div></div>
          <p class="pr-note pr-foot-note" data-rise>${esc(r.source || "Census survey")}, ${esc(r.survey || "")}: census tracts around the site, weighed by their households inside ${esc(miles(market))}.</p>`;
      },
    });

    // ---- 6. the city's economy
    list.push({
      id: "economy", title: "The city's economy", key: outlookKey(),
      html() {
        if (!O) return waiting("The city's economy");
        const E = O.economy || {};
        if (!E.available) return head("The city's economy") + missing("The city's economy by year");
        const rows = E.rows || [], withPeople = rows.filter((r) => isNum(r.people));
        const a = withPeople[0], b = lastRow(withPeople);
        const h = a && b && a !== b ? `${esc(E.place || F.city_name)} grew from ${big(a.people)} ${plural(a.people, "person", "people")} in ${a.year} to ${big(b.people)} in ${b.year}` : `The record of ${esc(E.place || F.city_name)} by year`;
        const tiles = economyTiles(E);
        const answered = (E.sources || []).filter((s) => s.answered).map((s) => esc(s.source));
        return `${head(h, esc((E.facts || [])[2] || ""))}<div class="pr-econ">${tiles.map((t) => `<div class="pr-econ-tile" data-rise>
            <h3>${esc(t.title)}</h3><p class="pr-econ-val">${t.value}</p><p class="pr-econ-when">${esc(t.when)}</p>
            <div class="pr-chart" data-chart="econ-${t.id}"></div>${t.note ? `<p class="pr-note">${esc(t.note)}</p>` : ""}</div>`).join("")}</div>
          <p class="pr-note pr-foot-note" data-rise>Measured records: ${answered.join("; ") || NONE}.</p>`;
      },
      charts: S.O && S.O.economy && S.O.economy.available ? Object.fromEntries(economyTiles(S.O.economy).map((t) => [`econ-${t.id}`, t.chart])) : {},
    });

    // ---- 7. what the area needs
    list.push({
      id: "needs", title: "What the area needs", key: "1",
      html() {
        const H = F.homes || {}, perYear = headlineItem("New homes needed");
        const h = perYear && isNum(perYear.value) ? `About ${big(perYear.value)} new homes are needed each year within ${esc(miles(market))}` : "What the area needs";
        const said = [];
        if (isNum(H.pipeline_covers_years)) said.push(`Homes already on the city's lists cover about ${num(H.pipeline_covers_years, 1)} ${plural(H.pipeline_covers_years, "year", "years", 1)} of that need.`);
        needSpecs().slice(1).forEach((sp) => {
          if (!sp.ok || !isNum(sp.lists10) || !isNum(sp.need10.expected) || !(sp.need10.expected > 0)) return;
          said.push(sp.lists10 >= sp.need10.expected ? `${sp.title}: the lists already hold more than ten years of expected growth.`
            : `${sp.title}: the lists hold about ${Math.round(100 * sp.lists10 / sp.need10.expected)}% of ten years' expected need.`);
        });
        const lead = esc(said.join(" "));
        const cols = needSpecs().map((sp) => `<div class="pr-need" data-rise>
            <h3>${esc(sp.title)}</h3>${sp.ok ? `<div class="pr-chart" data-chart="need-${sp.id}"></div>
            <dl class="pr-need-figs"><div><dt>Needed over ten years</dt><dd>${big(sp.need10.expected)} <small>${esc(sp.unit)}</small></dd><dd class="pr-range">low to high: ${range(sp.need10)}</dd></div>
            <div><dt>Already on the city's lists</dt><dd>${big(sp.lists10)} <small>${esc(sp.unit)}</small></dd></div></dl>` : missing(sp.title)}</div>`).join("");
        return `${head(h, lead)}<div class="pr-needs">${cols}</div>
          <p class="pr-keys" data-rise>${key("line", "Needed each year, expected")}${key("band", "Low to high")}${key("bar", "Already on the city's lists, by the year it is due")}</p>`;
      },
      charts: Object.fromEntries(needSpecs().filter((sp) => sp.ok).map((sp) => [`need-${sp.id}`, (w, h, fs) => {
        const rows = sp.rows, xs = rows.map((r) => r.year), d = sp.div;
        const vals = rows.flatMap((r) => [sp.need(r).low / d, sp.need(r).high / d, sp.list(r) / d]);
        return chart({
          w, h, fs, x0: Math.min(...xs), x1: Math.max(...xs), values: vals, zero: true, unit: sp.axis, xRoom: 3.4,
          label: `Chart of ${sp.title.toLowerCase()} each year: the need as a low to high band and an expected line, and what is on the city's lists as bars.`,
          draw: (s) => bars(s, rows.map((r) => [r.year, sp.list(r) / d])) + band(s, rows.map((r) => [r.year, sp.need(r).low / d, sp.need(r).high / d])) +
            line(s, rows.map((r) => [r.year, sp.need(r).expected / d])),
        });
      }])),
    });

    // ---- 7b. the homes the state requires the city to plan for (only when the state's figures answered)
    if (O && (O.housing || {}).available) {
      const G = O.housing, lower = G.lower || {}, mine = G.site;
      list.push({
        id: "housing-target", title: "The city's housing target", key: outlookKey(),
        html() {
          const h = isNum(G.left) && isNum(G.to_year) ? `${esc(O.city_name || F.city_name)} still has ${big(G.left)} homes to permit by ${esc(G.to_year)}`
            : `${esc(O.city_name || F.city_name)}'s state housing target`;
          const row = (l, k) => {
            const share = isNum(l.target) && Number(l.target) > 0 && isNum(l.permitted) ? 100 * Number(l.permitted) / Number(l.target) : null;
            return `<div class="pr-hbar here" data-rise style="--k:${k}"><span>${esc(l.label)}</span><i><b class="pr-growx" style="width:${share === null ? 0 : Math.min(100, share).toFixed(1)}%"></b></i>
              <em>${isNum(l.permitted) ? big(l.permitted) : NONE} of ${isNum(l.target) ? num(l.target) : NONE}</em></div>`;
          };
          const figs = [];
          if (isNum(G.target)) figs.push(fig(big(G.target), "homes the state requires the city to plan for", isNum(G.from_year) && isNum(G.to_year) ? `${esc(G.from_year)} to ${esc(G.to_year)}` : ""));
          if (isNum(lower.left)) figs.push(fig(big(lower.left), "still to come for very low, low and moderate incomes",
            isNum(lower.a_year_needed) && isNum(lower.a_year_now) ? `about ${num(lower.a_year_needed)} a year needed; about ${num(lower.a_year_now)} a year reported` : ""));
          if (mine) figs.push(fig(big(mine.homes), `${plural(mine.homes, "home")} in this site's plan`, isNum(mine.pct_of_left) ? `${num(mine.pct_of_left, 1)}% of what is still to come` : ""));
          return `${head(h, esc((G.facts || [])[0] || ""))}<div class="pr-body pr-housebody">
            <div><h3 class="pr-sub" data-rise>Permits so far, beside the target for each income level</h3>
              <div class="pr-hbars">${(G.levels || []).map(row).join("")}</div></div>
            <div class="pr-housefigs">${figs.join("")}</div></div>
            <p class="pr-note pr-foot-note" data-rise>Which income level this site's homes count toward depends on what they rent or sell for, which is agreed with the city. ${esc(G.source || "")}${G.as_of ? `; ${esc(G.as_of)}` : ""}.</p>`;
        },
      });
    }

    // ---- 8. the plan
    list.push({
      id: "plan", title: "The plan", key: S.Gerr ? "ground-error" : S.G && !has3d() ? "no-3d" : "1",
      html() {
        const homes = uses.filter((u) => u.kind === "homes").reduce((t, u) => t + (Number(u.amount) || 0), 0);
        const feet = uses.filter((u) => u.kind !== "homes").reduce((t, u) => t + (Number(u.amount) || 0), 0);
        const h = homes && feet ? `${big(homes)} ${plural(homes, "home")} and ${big(feet)}&nbsp;sq&nbsp;ft of shops and work space` : homes ? `Room for ${big(homes)} ${plural(homes, "home")}` : feet ? `${big(feet)}&nbsp;sq&nbsp;ft of shops and work space` : "The plan";
        const parkAcres = pieces.filter((p) => p.use === "park").reduce((t, p) => t + (Number(p.acres) || 0), 0);
        const rows = uses.map((u) => `<li data-rise><i style="background:${colourOf(u.colour)}"></i><span><b>${esc(u.label)}</b><small>${isNum(u.amount) ? num(u.amount) + " " + esc(u.unit || "") : NONE}${u.fit_words ? ` · ${esc(u.fit_words.toLowerCase())}` : ""}</small></span><em>${num(u.acres, 1)} ${plural(u.acres, "acre", "acres", 1)}</em></li>`).join("") +
          (parkAcres ? `<li data-rise><i style="background:${PARK.colour}"></i><span><b>${esc(PARK.label)}</b><small>built with the uses around them</small></span><em>${num(parkAcres, 1)} ${plural(parkAcres, "acre", "acres", 1)}</em></li>` : "");
        const why = [...new Set(drawings.flatMap((d) => d.why || []))];
        return `<div class="pr-mapleft pr-plan">
          <div class="pr-mapframe"><div class="pr-map" data-map></div>
            <p class="pr-maplegend">${key("road", "Streets inside the plan")}${key("city-road", "The city's planned streets")}${key("site", "Parcel lines")}</p></div>
          <div class="pr-side pr-field">${head(h)}
            ${uses.length ? `<ul class="pr-uses">${rows}</ul>` : missing("The uses of the land")}
            ${why.length ? `<h3 class="pr-sub" data-rise>Why each sits where it does</h3><ul class="pr-why">${why.map((w) => `<li data-rise>${esc(w)}</li>`).join("")}</ul>` : ""}
            ${G.basis ? `<p class="pr-note" data-rise>${esc(G.basis)} A first sketch cut from the assessor's outlines: not lot lines.</p>` : ""}
            ${no3dWords() ? `<p class="pr-note" data-rise>${esc(no3dWords())}${S.Gerr ? ` <button type="button" class="btn small" data-ground-again>Try again</button>` : ""}</p>` : ""}
          </div></div>`;
      },
      mount(el, rec) {
        const L = window.L, view = newMap(rec, el.querySelector("[data-map]")), m = view.map, items = [];
        drawStreetLines(L, m);
        drawParcels(L, m, { fill: 0, weight: 3 });
        const labelSpecs = [];
        pieces.forEach((p) => {
          const u = useById[p.use] || { label: p.use, short: p.use, colour: "#9aa0a6" };
          const poly = L.polygon(ll([p.ring]), { color: "#ffffff", weight: 2.5, opacity: 1, fillColor: colourOf(u.colour), fillOpacity: 0.78 })
            .bindTooltip(`${esc(u.label)}: ${num(p.acres, 1)} ${plural(p.acres, "acre", "acres", 1)}`, { sticky: true }).addTo(m);
          items.push({ layer: poly, style: { opacity: 1, fillOpacity: 0.78 } });
          labelSpecs.push({ ring: p.ring, className: "pr-lab use", variants: [`<b>${esc(u.short)}</b> ${num(p.acres, 1)} ac`, `<b>${esc(u.short)}</b>`] });
        });
        view.pieceLabels().set(labelSpecs).forEach((lab) => items.push({ marker: lab }));
        drawings.forEach((d) => (d.streets || []).forEach((s) => {
          const line = s.line.map((q) => [q[1], q[0]]);
          L.polyline(line, { color: "#1d2a24", weight: 11, opacity: 0.45, interactive: false }).addTo(m);
          const st = L.polyline(line, { color: "#ffffff", weight: 6, opacity: 1 }).bindTooltip(`A street inside the plan, about ${num(s.feet)} ft long`, { sticky: true }).addTo(m);
          items.push({ layer: st, style: { opacity: 1 } });
        }));
        const b = siteBounds(L);
        if (b) view.fit(b.pad(0.1));
        reveal(rec, items);
      },
      enter: playReveal,
    });

    // ---- 8b. the plan in 3D: the ground under the whole site with the plan drawn on it. Shown while it is being
    // read; left out (and said so on the plan slide) when the site has no ground heights or no single plan.
    if ((!S.G && !S.Gerr) || has3d()) {
      list.push({
        id: "plan-3d", title: "The plan on the ground", key: S.G ? "ready" : "wait",
        html() {
          if (!S.G) return head("The plan on the land's real ground") + `<div class="pr-pending" data-rise><span class="spinner" aria-hidden="true"></span><p>Reading the ground heights under the site. The 3D view appears here when they arrive; the first time can take a minute or two.</p></div>`;
          const P = S.G.plan, inside = (S.G.surface || {}).inside || {};
          const h = isNum(inside.range_ft) ? `The plan on the real ground, ${big(inside.range_ft, 0)} ft from its lowest to its highest point` : "The plan on the land's real ground";
          const shown = (P.uses || []).filter((u) => Number(u.acres) > 0);
          const what = (u) => (isNum(u.homes) && u.homes > 0 ? `${num(u.homes)} ${plural(u.homes, "home")}` : isNum(u.sq_ft) && u.sq_ft > 0 ? `${num(u.sq_ft)}&nbsp;sq&nbsp;ft` : u.id === "park" ? "built with the uses around them" : "");
          // the ground route plans with the heights in hand, so its mix can differ a little from the plan slide
          // (compared as the slides print them, to a tenth of an acre; the plan slide's park is the sum of its park pieces)
          const planAcres = (id) => id === "park" ? pieces.filter((p) => p.use === "park").reduce((t, p) => t + (Number(p.acres) || 0), 0)
            : (uses.find((x) => x.id === id) || {}).acres;
          const tenths = (v) => Math.round(Number(v) * 10);
          const differs = shown.some((u) => !isNum(planAcres(u.id)) || tenths(planAcres(u.id)) !== tenths(u.acres)) ||
            uses.some((f) => !shown.some((u) => u.id === f.id));
          return `${head(h)}<div class="pr-3dbody">
            <div class="pr-3d view3d" data-3d></div>
            <aside class="pr-3dkey pr-field">
              <ul class="pr-uses">${shown.map((u) => `<li data-rise><i style="background:${colourOf(u.colour)}"></i><span><b>${esc(u.short || u.label)}</b><small>${what(u)}</small></span><em>${num(u.acres, 1)} ac</em></li>`).join("")}</ul>
              <p class="pr-note" data-rise>Buildings are simple boxes, as many and as large as the plan's figures make: a picture of scale, not a site plan.${differs ? " This plan was worked out knowing the ground, so its acres differ a little from the plan slide." : ""}</p>
              ${S.G.surface && S.G.surface.source ? `<p class="pr-note" data-rise>Ground heights: ${esc(S.G.surface.source)}${isNum(S.G.surface.spacing_ft) ? `, every ${num(S.G.surface.spacing_ft)} ft` : ""}.</p>` : ""}
            </aside></div>`;
        },
        mount(el, rec) {
          const box = el.querySelector("[data-3d]");
          if (!box || !has3d()) return;
          const P = S.G.plan, d = P.drawing;
          const colours = Object.fromEntries((P.uses || []).map((u) => [u.id, colourOf(u.colour)]));
          const amounts = Object.fromEntries((P.uses || []).map((u) => [u.id, { homes: u.homes, sq_ft: u.sq_ft }]));
          const off = mountTerrain(box, S.G.parcel, S.G.surface, {
            pieces: d.pieces, streets: (d.streets || []).map((s) => s.line), colours, front: d.front || null, amounts, cap: 1500,
          });
          rec.cleanup.push(() => off());
        },
      });
    }

    // ---- 9. when
    list.push({
      id: "when", title: "When the land is offered", key: "1",
      html() {
        const steps = G.steps || [];
        const first = Math.min(...uses.flatMap((u) => (u.by_year || []).filter((y) => Number(y.taken) > 0).map((y) => y.year)));
        const last = Math.max(...(F.years || [F.year]));
        const offered = uses.reduce((t, u) => t + (Number(u.acres_by_year_10) || 0), 0), forSale = uses.reduce((t, u) => t + (Number(u.acres) || 0), 0);
        const h = isFinite(first) ? `Land goes to builders from ${first}; about ${big(offered, 1)} of ${num(forSale, 1)} ${plural(forSale, "acre", "acres", 1)} by ${last}` : "When the land is offered";
        const periods = periodsOf();
        return `${head(h)}<div class="pr-body pr-whenbody">
          <div class="pr-visual pr-mapframe"><div class="pr-map" data-map></div>
            <p class="pr-maplegend">${periods.filter((p) => p.any).map((p) => key("swatch", `Offered ${esc(p.label)}`, `background:${p.colour}`)).join("")}${key("swatch", `Still unsold in ${last}`, `background:${UNSOLD}`)}${pieces.some((p) => p.use === "park") ? key("swatch", "Parks, built with their neighbours", `background:${PARK.colour}`) : ""}
            <span class="pr-legend-note">Shading shows how much of each use's land is offered in each period; where inside each piece it falls is not decided.</span></p></div>
          <div class="pr-when-side"><div class="pr-steps">${steps.map((st, i) => `<article class="pr-step" data-rise style="--c:${PERIOD_COLOURS[i % PERIOD_COLOURS.length]}">
              <h3>${esc(st.title)}</h3><p class="pr-step-years">${esc(st.label)}</p><ul>${(st.lines || []).map((l) => `<li>${esc(l)}</li>`).join("")}</ul></article>`).join("")}</div>
            ${(G.after || []).length ? `<h3 class="pr-sub" data-rise>Still to come after ${last}</h3><ul class="pr-after">${G.after.map((a) => `<li data-rise>${esc(a)}</li>`).join("")}</ul>` : ""}
            ${(G.not_forecast || []).length ? `<p class="pr-note" data-rise>Not forecast: ${esc(listWords(G.not_forecast.map((x) => typeof x === "string" ? x : x.label || x.id || "")))}.</p>` : ""}
          </div></div>`;
      },
      mount(el, rec) {
        const L = window.L, view = newMap(rec, el.querySelector("[data-map]")), m = view.map, items = [];
        const periods = periodsOf();
        const busiest = streetLines.slice().sort((a, b) => (b.rank || 0) - (a.rank || 0))[0];
        drawParcels(L, m, { fill: 0, weight: 3 });
        pieces.forEach((p) => {
          const u = useById[p.use];
          if (!u || p.use === "park" || !(Number(u.acres) > 0)) {
            const poly = L.polygon(ll([p.ring]), { color: "#ffffff", weight: 2, fillColor: PARK.colour, fillOpacity: 0.85 }).bindTooltip(`${esc(PARK.label)}: built with the uses around them`, { sticky: true }).addTo(m);
            items.push({ layer: poly, style: { opacity: 1, fillOpacity: 0.85 } });
            return;
          }
          const shares = [], words = [];
          let before = 0;
          periods.forEach((pd) => { const f = Math.min(1, pd.acres(u) / u.acres); shares.push(Math.max(0, f - before)); words.push(pd.label); before = Math.max(before, f); });
          shares.push(Math.max(0, 1 - before));
          const mid = p.label_at || p.ring[0];
          const toward = busiest && busiest.path && busiest.path.length ? busiest.path.reduce((best, q) => Math.hypot(q[0] - mid[0], q[1] - mid[1]) < Math.hypot(best[0] - mid[0], best[1] - mid[1]) ? q : best) : null;
          cutBands(p.ring, shares, toward).forEach((ring, i) => {
            if (!ring) return;
            const unsold = i === periods.length, colour = unsold ? UNSOLD : periods[i].colour;
            const poly = L.polygon(ring, { color: "#ffffff", weight: 2, fillColor: colour, fillOpacity: unsold ? 0.7 : 0.88 })
              .bindTooltip(`${esc(u.label)}: ${unsold ? "still unsold at the end of the ten years" : "offered " + esc(words[i])}, about ${num(shares[i] * u.acres, 1)} ${plural(shares[i] * u.acres, "acre", "acres", 1)}`, { sticky: true }).addTo(m);
            items.push({ layer: poly, style: { opacity: 1, fillOpacity: unsold ? 0.7 : 0.88 } });
          });
          if (p.label_at) { const lab = label(L, [p.label_at[1], p.label_at[0]], `<b>${esc(u.short)}</b>`, "use").addTo(m); items.push({ marker: lab }); }
        });
        const b = siteBounds(L);
        if (b) view.fit(b.pad(0.08));
        reveal(rec, items);
      },
      enter: playReveal,
    });

    // ---- 10. traffic
    list.push({
      id: "traffic", title: "Traffic", key: outlookKey(),
      html() {
        const T = F.traffic || {};
        if (!T.available) return head("Traffic") + missing("Highway traffic near the site");
        const hw = T.highway || {}, rows = T.rows || [], mid = rowAt(rows, F.year + 5), end = lastRow(rows);
        const h = `Route ${esc(hw.route)} at ${esc(hw.where)} carries about ${big(hw.today)} vehicles a day`;
        const lead = mid && end ? `If traffic grows with the homes around it: about ${num(mid.highway.expected)} a day by ${mid.year} and ${num(end.highway.expected)} by ${end.year} (${range(end.highway)}).` : "";
        const study = S.O && S.O.todo ? (S.O.todo.steps || []).find((s) => s.kind === "study" && /traffic/i.test(s.what || "")) : null;
        const ents = (T.entrances || []), toStudy = Number(T.signals_to_study) || ents.filter((e) => e.signal === "study").length;
        const entHead = !ents.length ? "Entrances and signals" : toStudy ? `${countWord(toStudy)} ${toStudy === 1 ? "entrance where a new signal is" : "entrances where a new signal is"} worth studying` : `${countWord(ents.length)} ${ents.length === 1 ? "entrance" : "entrances"} onto the streets around`;
        return `${head(h, lead)}<div class="pr-body pr-traffic">
          <div class="pr-visual pr-stack"><div class="pr-chart tall" data-chart="highway"></div><div class="pr-chart short" data-chart="trips"></div>
            <p class="pr-keys" data-rise>${key("line", "Highway, expected")}${key("band", "Low to high")}${key("bar", "Trips a day the site adds as it fills", "background:#e0a91f")}</p></div>
          <div class="pr-tside">
            <div class="pr-mapframe pr-tmap" data-rise><div class="pr-map" data-map></div>
              <p class="pr-maplegend">${key("site", "The site")}${ents.length ? Object.keys(ENTRANCES).filter((k) => ents.some((e) => (ENTRANCES[e.signal] ? e.signal : "unknown") === k)).map((k) => `<span><b class="pr-ent ${k}">${esc(ENTRANCES[k].short)}</b>Entrance</span>`).join("") : ""}${(T.existing_signals || []).length ? key("dot", "Traffic signal today") : ""}</p></div>
            <div class="pr-tnotes">
              <h3 class="pr-sub" data-rise>${esc(entHead)}</h3>
              ${ents.length ? `<ul class="pr-entlist">${ents.map((e) => { const k = ENTRANCES[e.signal] ? e.signal : "unknown"; return `<li data-rise><b class="pr-ent ${k}">${esc(ENTRANCES[k].short)}</b><span><b>${esc(e.street)}</b>${e.class ? ` <small>(${esc(e.class)})</small>` : ""}: ${esc(e.text || ENTRANCES[k].word)}</span></li>`; }).join("")}</ul>` : missing("Entrances and signals for this site")}
              ${isNum(G.trips_at_build_out) ? `<p class="pr-body-text" data-rise>The site adds about <b>${big(G.trips_at_build_out)}</b> trips a day once everything is built.</p>` : ""}
              ${study ? `<p class="pr-body-text" data-rise><b>${esc(study.what)}:</b> ${esc(study.who)}.</p>` : ""}
              <p class="pr-note" data-rise>The highway figure is Caltrans' count on Route ${esc(hw.route)} at ${esc(hw.where)}, ${esc(miles(hw.miles_away))} from the site (the count gives no position to draw); the line ahead is that count grown with the homes around it.</p>
            </div></div></div>`;
      },
      mount(el, rec) {
        const T = F.traffic || {}, box = el.querySelector("[data-map]");
        if (!box) return;
        const L = window.L, view = newMap(rec, box), m = view.map, items = [];
        drawParcels(L, m, { fill: 0.3, weight: 3 });
        let b = siteBounds(L);
        (T.existing_signals || []).forEach((s) => {
          if (!isNum(s.lat) || !isNum(s.lon)) return;
          const dot = L.circleMarker([s.lat, s.lon], { radius: 8, color: "#ffffff", weight: 3, fillColor: "#1d2a24", fillOpacity: 1 })
            .bindTooltip(`Traffic signal today at ${esc(s.street)} and ${esc(s.cross_street)}, ${esc(miles(s.miles_away))} away`).addTo(m);
          items.push({ layer: dot, style: { opacity: 1, fillOpacity: 1 } });
          // the map frames the site and the signals closest to it; farther ones show when the map is moved
          if (b && isNum(s.miles_away) && s.miles_away <= 0.6) b = b.extend([s.lat, s.lon]);
        });
        (T.entrances || []).forEach((e) => {
          if (!isNum(e.lat) || !isNum(e.lon)) return;
          const k = ENTRANCES[e.signal] ? e.signal : "unknown";
          const pin = L.marker([e.lat, e.lon], {
            icon: L.divIcon({ className: "pr-entpin", iconSize: [0, 0], html: `<span><b class="pr-ent ${k}">${esc(ENTRANCES[k].short)}</b>${esc(e.street)}</span>` }),
            title: `Entrance onto ${e.street}: ${ENTRANCES[k].word}`, keyboard: false,
          }).bindTooltip(`<b>Entrance onto ${esc(e.street)}</b>: ${esc(e.text || ENTRANCES[k].word)}`).addTo(m);
          items.push({ marker: pin });
          if (b) b = b.extend([e.lat, e.lon]);
        });
        if (b) view.fit(b.pad(0.12));
        reveal(rec, items);
      },
      enter: playReveal,
      charts: {
        highway: (w, h, fs) => {
          const rows = (F.traffic || {}).rows || [], xs = rows.map((r) => r.year), end = lastRow(rows);
          return chart({
            w, h, fs, x0: Math.min(...xs), x1: Math.max(...xs), values: rows.flatMap((r) => [r.highway.low / 1000, r.highway.high / 1000]), zero: false,
            unit: "thousand vehicles a day on the highway", label: "Chart of highway traffic by year, expected with its low to high range.",
            draw: (s) => band(s, rows.map((r) => [r.year, r.highway.low / 1000, r.highway.high / 1000])) + line(s, rows.map((r) => [r.year, r.highway.expected / 1000])) +
              dots(s, rows.map((r) => [r.year, r.highway.expected / 1000])) + (end ? endLabel(s, end.year, end.highway.expected / 1000, num(end.highway.expected)) : ""),
          });
        },
        trips: (w, h, fs) => {
          const rows = (F.traffic || {}).rows || [], xs = rows.map((r) => r.year);
          return chart({
            w, h, fs, x0: Math.min(...xs), x1: Math.max(...xs), values: rows.map((r) => r.site_trips), zero: true,
            unit: "trips a day the site adds", label: "Chart of the trips a day the site adds each year as its land fills.",
            draw: (s) => bars(s, rows.map((r) => [r.year, r.site_trips]), "pr-bar gold"),
          });
        },
      },
    });

    // ---- 11. weather
    list.push({
      id: "weather", title: "Weather", key: outlookKey(),
      html() {
        if (!O) return waiting("Weather");
        const C = O.climate || {};
        if (!C.available) return head("Weather") + missing("The weather record");
        const y = C.typical_year || {};
        const h = `A typical year: ${big(y.mean_f, 0)} °F and ${big(y.rain_in, 1)} inches of rain`;
        return `${head(h, esc((C.facts || [])[1] || ""))}<div class="pr-body pr-chartbody">
          <div class="pr-visual pr-stack"><div class="pr-chart tall" data-chart="temps"></div><div class="pr-chart short" data-chart="rain"></div>
            <p class="pr-keys" data-rise>${key("band", "Hottest and coldest reading of the month, on average")}${key("line", "Average")}${key("bar", "Rain, inches", "background:#4f7fa6")}</p></div>
          <aside class="pr-aside">
            ${(C.by_decade || []).length ? `<h3 class="pr-sub" data-rise>Ten years at a time</h3><table class="pr-table" data-rise><thead><tr><th>Years</th><th>Average</th><th>Summer high</th><th>Rain</th></tr></thead><tbody>${C.by_decade.map((d) => `<tr><td>${esc(d.years)}</td><td>${num(d.mean_f, 1)} °F</td><td>${num(d.summer_high_f, 1)} °F</td><td>${num(d.rain_in, 1)} in</td></tr>`).join("")}</tbody></table>` : ""}
            ${(C.facts || [])[2] ? `<p class="pr-body-text" data-rise>${esc(C.facts[2])}</p>` : ""}
            <p class="pr-note" data-rise>${esc(C.source || "")}. The grid is coarse: these describe the area, not this exact spot.</p>
          </aside></div>`;
      },
      charts: S.O && S.O.climate && S.O.climate.available ? {
        temps: (w, h, fs) => {
          const ms = S.O.climate.months || [], name = (i) => (ms[i - 1] || {}).month || "";
          return chart({
            w, h, fs, x0: 1, x1: ms.length, values: ms.flatMap((m) => [m.low_f, m.high_f]), zero: false, unit: "°F", xRoom: 2.4, xLabel: name,
            label: "Chart of temperature by month: the average, and the hottest and coldest reading of each month on average.",
            draw: (s) => band(s, ms.map((m, i) => [i + 1, m.low_f, m.high_f]), "pr-band warm") + line(s, ms.map((m, i) => [i + 1, m.mean_f])) + dots(s, ms.map((m, i) => [i + 1, m.mean_f])),
          });
        },
        rain: (w, h, fs) => {
          const ms = S.O.climate.months || [];
          return chart({
            w, h, fs, x0: 1, x1: ms.length, values: ms.map((m) => m.rain_in), zero: true, unit: "inches of rain", xRoom: 2.4, xLabel: (i) => (ms[i - 1] || {}).month || "",
            label: "Chart of rain by month, in inches.", draw: (s) => bars(s, ms.map((m, i) => [i + 1, m.rain_in]), "pr-bar blue"),
          });
        },
      } : {},
    });

    // ---- 12. hazards and limits on the land
    list.push({
      id: "hazards", title: "Hazards and limits", key: outlookKey(),
      html() {
        if (!O) return waiting("Hazards and limits");
        const Z = O.hazards || {};
        if (!Z.available) return head("Hazards and limits") + missing("Hazards on the site");
        const f = Z.findings || [], work = f.filter((x) => x.level === "work"), clear = f.filter((x) => x.level === "clear");
        const h = work.length ? `${countWord(work.length)} ${work.length === 1 ? "finding adds" : "findings add"} work: ${esc(listWords(work.map((x) => String(x.topic).toLowerCase())))}`
          : clear.length === f.length ? "Every finding is clear" : "No finding adds work";
        const order = { work: 0, note: 1, clear: 2 };
        return `${head(h)}<ul class="pr-hazards">${f.slice().sort((a, b) => (order[a.level] ?? 1) - (order[b.level] ?? 1)).map((x) => `<li class="lvl-${esc(LEVELS[x.level] ? x.level : "note")}" data-rise>
            <span class="pr-level">${mark(x.level)}${esc((LEVELS[x.level] || LEVELS.note).word)}</span><b>${esc(x.topic)}</b><p>${esc(x.text)}<small>${esc(x.source || "")}</small></p></li>`).join("")}</ul>
          <p class="pr-note pr-foot-note" data-rise>${Z.evacuation_zone ? `Evacuation zone ${esc(Z.evacuation_zone)}. ` : ""}${(Z.not_covered || []).length ? `Not covered yet: ${esc(Z.not_covered.join("; "))}.` : ""}${(Z.did_not_answer || []).length ? ` Did not answer just now: ${esc(Z.did_not_answer.join(", "))}.` : ""}</p>`;
      },
    });

    // ---- 13. the steps by year
    list.push({
      id: "steps", title: "What needs to be done", key: outlookKey(),
      html() {
        if (!O) return waiting("What needs to be done");
        const st = (O.todo || {}).steps || [];
        if (!st.length) return head("What needs to be done") + missing("The steps to take");
        const pre = st.filter((s) => s.kind !== "sell"), sell = st.filter((s) => s.kind === "sell");
        const y0 = Math.min(...st.map((s) => s.from_year)), y1 = Math.max(...st.map((s) => s.to_year)), span = y1 - y0 + 1;
        const preYears = pre.length ? [Math.min(...pre.map((s) => s.from_year)), Math.max(...pre.map((s) => s.to_year))] : null;
        const h = preYears && sell.length ? `Approvals and studies in ${preYears[0] === preYears[1] ? preYears[0] : `${preYears[0]} and ${preYears[1]}`}; land offered from ${Math.min(...sell.map((s) => s.from_year))}` : "What needs to be done, year by year";
        const kindsShown = [...new Set(st.map((s) => s.kind))].filter((k) => KINDS[k]);
        const years = Array.from({ length: span }, (_, i) => y0 + i);
        const nameOf = (s) => (s.kind === "sell" ? String(s.what || "").split(":")[0] : s.what);
        return `${head(h, esc((O.todo || {}).note || ""))}<div class="pr-gantt" style="--n:${span}">
          <div class="pr-gantt-head"><span></span><div>${years.map((y) => `<b>${y}</b>`).join("")}</div></div>
          ${st.map((s, i) => `<div class="pr-gantt-row" data-rise><span class="pr-gantt-what"><i style="background:${(KINDS[s.kind] || KINDS.check).colour}"></i><span>${esc(nameOf(s))}<small class="pr-gantt-years">, ${esc(s.from_year === s.to_year ? String(s.from_year) : `${s.from_year} to ${s.to_year}`)}</small></span></span>
            <div class="pr-gantt-track"><b class="pr-gantt-bar pr-growx k-${esc(s.kind)}" style="left:${(100 * (s.from_year - y0) / span).toFixed(2)}%;width:${(100 * (s.to_year - s.from_year + 1) / span).toFixed(2)}%;--k:${i};background:${(KINDS[s.kind] || KINDS.check).colour}">${esc(s.from_year === s.to_year ? String(s.from_year) : `${s.from_year} to ${s.to_year}`)}</b></div></div>`).join("")}
          </div><p class="pr-keys" data-rise>${kindsShown.map((k) => key("swatch", esc(KINDS[k].word), `background:${KINDS[k].colour}`)).join("")}</p>`;
      },
    });

    // ---- 14. who does what, before the land is offered (six to a slide)
    const pre = S.O ? ((S.O.todo || {}).steps || []).filter((s) => s.kind !== "sell") : [];
    const chunks = [];
    for (let i = 0; i < pre.length; i += 6) chunks.push(pre.slice(i, i + 6));
    if (!S.O) chunks.push(null);
    chunks.forEach((items, ci) => {
      list.push({
        id: ci ? `before-${ci + 1}` : "before", title: ci ? "Before the land is offered, continued" : "Before the land is offered", key: outlookKey() + ":" + chunks.length,
        html() {
          if (!items) return waiting("Before the land is offered");
          const h = ci ? "Before the land is offered, continued" : `${countWord(pre.length)} things to settle before the first land is offered`;
          return `${head(h)}<div class="pr-todo">${items.map((s) => `<article class="pr-todo-item" data-rise>
              <p class="pr-todo-kind"><i style="background:${(KINDS[s.kind] || KINDS.check).colour}"></i>${esc((KINDS[s.kind] || { word: cap(s.kind) }).word)}, ${esc(s.from_year === s.to_year ? String(s.from_year) : `${s.from_year} to ${s.to_year}`)}</p>
              <h3>${esc(s.what)}</h3><p>${esc(s.why || "")}</p><p class="pr-who">${esc(s.who || "")}</p></article>`).join("")}</div>`;
        },
      });
    });

    // ---- 15. what this rests on
    list.push({
      id: "sources", title: "What this rests on", key: outlookKey(),
      html() {
        const src = allSources();
        const figs = F.figures || [];
        const h = `Built from ${big(src.answered.length)} public sources and ${big(figs.length)} starting figures`;
        return `${head(h, "Every number in this presentation comes from these records. The starting figures are assumptions; each can be changed on the forecast page and the whole forecast follows.")}
          <div class="pr-body pr-twocol">
            <div><h3 class="pr-sub" data-rise>Sources that answered</h3><ul class="pr-srclist">${src.answered.map((s) => `<li data-rise><b>${esc(s.name)}</b>${s.what ? `<span>${esc(s.what)}</span>` : ""}</li>`).join("")}</ul>
              ${src.missed.length ? `<p class="pr-note" data-rise>Did not answer just now: ${esc(listWords(src.missed))}.</p>` : ""}
              ${!S.O ? `<p class="pr-note" data-rise>${S.Oerr ? "The city's wider records could not be read just now." : "The city's wider records are still being read; their sources appear here when they arrive."}</p>` : ""}</div>
            <div><h3 class="pr-sub" data-rise>Starting figures (assumptions)</h3><table class="pr-table pr-figtable" data-rise><tbody>${figs.map((f) => `<tr><td>${esc(f.label)}</td><td class="num">${figureWords(f)}${f.yours ? " <small>(the owner's figure)</small>" : ""}</td></tr>`).join("")}</tbody></table></div>
          </div>`;
      },
    });

    // ---- 16. what it does not know
    list.push({
      id: "limits", title: "What this does not know", key: outlookKey(),
      html() {
        const items = (F.limits || []).slice();
        if (S.O) {
          const nc = [].concat((S.O.hazards || {}).not_covered || [], (S.O.nearby || {}).not_covered || []);
          if (nc.length) items.push(`Not covered yet: ${nc.join("; ")}.`);
          if ((S.O.climate || {}).note) items.push(S.O.climate.note);
        }
        return `<div class="pr-limits pr-field">${head("What this does not know, stated plainly")}<ul class="pr-limitlist">${items.map((t) => `<li data-rise>${esc(t)}</li>`).join("")}</ul>
          <p class="pr-close" data-rise>${esc(siteName)}. Prepared ${esc(dayWords(new Date()))} with public records.</p></div>`;
      },
    });
    return list;
  }

  function economyTiles(E) {
    const rows = E.rows || [], thisYear = S.O ? S.O.year : F.year;
    const lastOf = (pick) => rows.filter((r) => isNum(pick(r))).slice(-1)[0];
    const spark = (pick, kind, unit, digits, cls = "") => (w, h, fs) => {
      const pts = rows.map((r) => [r.year, pick(r)]).filter((p) => isNum(p[1]));
      if (pts.length < 2) return `<p class="pr-missing">Not covered yet.</p>`;
      const xs = pts.map((p) => p[0]);
      return chart({
        w, h, fs, x0: Math.min(...xs), x1: Math.max(...xs), values: pts.map((p) => p[1]), zero: kind === "bars", unit, xRoom: 3.6,
        fmt: (v) => num(v, digits), label: `Chart of ${unit} by year.`,
        draw: (s) => (kind === "bars" ? bars(s, pts, "pr-bar " + cls, 0.66) : line(s, pts) + dots(s, pts, "pr-dot", 0.32)),
      });
    };
    const when = (r, partial) => (r ? (r.year === thisYear && partial ? `so far in ${r.year}` : `in ${r.year}`) : "");
    const out = [];
    const p = lastOf((r) => r.people);
    out.push({ id: "people", title: "People in the city", value: p ? big(p.people) : NONE, when: when(p), chart: spark((r) => r.people, "line", "people", 0) });
    const pm = lastOf((r) => r.homes_permitted);
    const short = rows.filter((r) => isNum(r.homes_permitted) && isNum(r.permit_months) && r.permit_months < 12);
    out.push({ id: "permits", title: "Homes permitted a year", value: pm ? big(pm.homes_permitted) : NONE, when: when(pm), chart: spark((r) => r.homes_permitted, "bars", "homes", 0, "green"),
      note: short.length ? short.map((r) => `${r.year}: ${r.permit_months} ${plural(r.permit_months, "month")} counted.`).join(" ") : "" });
    const full = (r) => (isNum(r.shop_sales_usd) && r.sales_quarters === 4 ? r.shop_sales_usd / 1e6 : null);
    const sl = lastOf(full), part = rows.filter((r) => isNum(r.shop_sales_usd) && r.sales_quarters && r.sales_quarters < 4);
    out.push({ id: "sales", title: "Shop and restaurant sales", value: sl ? "$" + big(full(sl)) + " million" : NONE, when: when(sl), chart: spark(full, "bars", "$ millions a year", 0, "gold"),
      note: part.length ? part.map((r) => `${r.year}: ${r.sales_quarters} of 4 quarters so far, not drawn.`).join(" ") : "" });
    const u = lastOf((r) => r.unemployment_pct);
    out.push({ id: "jobless", title: "Unemployment", value: u ? big(u.unemployment_pct, 1) + "%" : NONE, when: when(u), chart: spark((r) => r.unemployment_pct, "line", "% of the work force", 1) });
    const m = lastOf((r) => r.mortgage_pct);
    out.push({ id: "loan", title: "30-year home-loan rate", value: m ? big(m.mortgage_pct, 2) + "%" : NONE, when: when(m, true), chart: spark((r) => r.mortgage_pct, "line", "% a year, average", 1) });
    return out;
  }
  function needSpecs() {
    const H = F.homes || {}, Sh = F.shops || {}, J = F.jobs || {};
    return [
      { id: "homes", title: "Homes", unit: "homes", axis: "homes a year", div: 1, ok: !!H.available && (H.rows || []).length > 1, rows: H.rows || [],
        need: (r) => r.need || {}, list: (r) => r.pipeline, need10: H.need_10_years || {}, lists10: H.pipeline_10_years },
      { id: "shops", title: "Shops and restaurants", unit: "sq ft", axis: "thousand sq ft a year", div: 1000, ok: !!Sh.available && (Sh.rows || []).length > 1, rows: Sh.rows || [],
        need: (r) => r.new_sq_ft || {}, list: (r) => r.pipeline_sq_ft, need10: Sh.new_10_years_sq_ft || {}, lists10: Sh.pipeline_10_years_sq_ft },
      { id: "work", title: "Offices, clinics and business space", unit: "sq ft", axis: "thousand sq ft a year", div: 1000, ok: !!J.available && (J.rows || []).length > 1, rows: J.rows || [],
        need: (r) => r.space_sq_ft || {}, list: (r) => r.pipeline_sq_ft, need10: J.space_10_years_sq_ft || {}, lists10: J.pipeline_10_years_sq_ft },
    ];
  }
  function periodsOf() {
    return (G.steps || []).map((st, i) => {
      const acres = (u) => {
        const rows = (u.by_year || []).filter((y) => y.year <= st.to_year);
        const r = rows[rows.length - 1];
        return r && isNum(r.acres_so_far) ? Number(r.acres_so_far) : 0;
      };
      return { label: st.label, colour: PERIOD_COLOURS[i % PERIOD_COLOURS.length], acres, any: false };
    }).map((pd, i, all) => {
      pd.any = uses.some((u) => pd.acres(u) > (i ? all[i - 1].acres(u) : 0) + 0.01);
      return pd;
    });
  }
  function drawStreetLines(L, m) {
    const named = new Map();
    streetLines.forEach((s) => {
      if (!s.path || s.path.length < 2) return;
      const line = s.path.map((p) => [p[1], p[0]]), weight = 2 + 1.6 * (Number(s.rank) || 1);
      L.polyline(line, { color: "#1d2a24", weight: weight + 4, opacity: 0.5, interactive: false }).addTo(m);
      L.polyline(line, { color: "#9fd0ff", weight, opacity: 0.95 }).bindTooltip(`${esc(s.name)}: ${esc(s.class)} (the city's planned streets)`, { sticky: true }).addTo(m);
      const len = Math.hypot(s.path[s.path.length - 1][0] - s.path[0][0], s.path[s.path.length - 1][1] - s.path[0][1]);
      if (!named.has(s.name) || named.get(s.name).len < len) named.set(s.name, { len, path: s.path });
    });
    const b = siteBounds(L);
    named.forEach((v, name) => {
      // the label goes on the part of the street nearest the site, so it shows on the map
      const c = b ? b.getCenter() : null;
      const q = c ? v.path.reduce((best, p) => Math.hypot(p[0] - c.lng, p[1] - c.lat) < Math.hypot(best[0] - c.lng, best[1] - c.lat) ? p : best) : v.path[0];
      label(L, [q[1], q[0]], esc(name), "street").addTo(m);
    });
  }
  function allSources() {
    const answered = [], missed = [], seen = new Set();
    const add = (name, what, ok = true) => {
      const k = String(name || "").toLowerCase();
      if (!name || seen.has(k)) return;
      seen.add(k);
      (ok ? answered : missed).push(ok ? { name, what } : name);
    };
    (F.sources || []).forEach((s) => add(s.name, s.what, s.answered));
    const O = S.O;
    if (O) {
      ((O.economy || {}).sources || []).forEach((s) => add(s.source, cap(s.name), s.answered));
      ((O.economy || {}).did_not_answer || []).forEach((s) => add(String(s), "", false));
      if ((O.climate || {}).available) add(O.climate.source, "Weather by month and by year");
      ((O.hazards || {}).findings || []).forEach((f) => add(f.source, f.topic));
      ((O.nearby || {}).places || []).forEach((p) => add(p.source, "Places close by"));
      if ((O.resident || {}).available) add(O.resident.source, "The typical resident");
      if ((O.housing || {}).available) add(O.housing.source, "The city's state housing target");
      ["climate", "hazards", "nearby", "resident"].forEach((b) => ((O[b] || {}).did_not_answer || []).forEach((s) => add(String(s), "", false)));
    }
    return { answered, missed };
  }

  // ---------------------------------------------------------------- building and keeping the deck

  function drawCharts(rec) {
    const fns = rec.def.charts || {};
    rec.el.querySelectorAll("[data-chart]").forEach((box) => {
      const fn = fns[box.dataset.chart];
      if (!fn) return;
      const w = box.clientWidth, h = box.clientHeight;
      if (!w || !h) return;
      try { box.innerHTML = fn(w, h, flow ? 12.5 : box.closest(".pr-econ") ? 16 : 19); } catch (e) { console.error(e); box.innerHTML = `<p class="pr-missing">This chart could not be drawn.</p>`; }
    });
  }
  function teardown(rec) {
    rec.run = null;
    rec.cleanup.splice(0).forEach((fn) => { try { fn(); } catch (e) { console.error(e); } });
    rec.views = []; rec.reveal = []; rec.mounted = false;
  }
  function fill(rec) {
    teardown(rec);
    rec.el.classList.remove("enter");   // measured at rest; enter() plays the entrance again
    const i = order.indexOf(rec.def.id);
    rec.el.setAttribute("aria-label", rec.def.title);
    rec.el.innerHTML = `<div class="pr-slide pr-s-${esc(rec.def.id)}">${rec.def.html()}</div>
      <p class="pr-print-foot"><span>${esc(siteName)}</span><span>${esc(rec.def.title)}</span><span>Prepared with public records${i >= 0 ? ` · ${i + 1} of ${order.length}` : ""}</span></p>`;
    rec.el.querySelectorAll("[data-rise]").forEach((x, k) => x.style.setProperty("--i", Math.min(k, 14)));
    rec.el.querySelectorAll(".pr-side, .pr-aside, .pr-tnotes, .pr-3dkey, .pr-hazards, .pr-todo-item, .pr-when-side, .pr-limitlist, .pr-twocol > div, .pr-gantt").forEach((x) => x.setAttribute("data-fit", ""));
    drawCharts(rec);
    fit(rec);
  }
  // text from the records can run longer on another site: a box whose words do not fit is set a little smaller
  // (never below about three quarters), so a slide never needs scrolling
  function fit(rec) {
    rec.el.querySelectorAll("[data-fit]").forEach((box) => {
      box.style.zoom = "";
      if (flow) return;
      const over = () => {
        const b = box.getBoundingClientRect();
        let bottom = 0, right = 0;
        for (const c of box.children) { const r = c.getBoundingClientRect(); bottom = Math.max(bottom, r.bottom); right = Math.max(right, r.right); }
        return bottom > b.bottom + 1 || right > b.right + 1;
      };
      let k = 1;
      while (over() && k > 0.74) { k -= 0.04; box.style.zoom = String(k); }
    });
  }
  function mount(rec) {
    if (!rec || rec.mounted) return;
    rec.mounted = true;
    if (rec.def.mount) { try { rec.def.mount(rec.el, rec); } catch (e) { console.error(e); } }
  }
  function sync() {
    const list = defs(), keepId = order[cur];
    order = list.map((d) => d.id);
    list.forEach((def) => {
      let rec = recs.get(def.id);
      if (!rec) {
        const el = document.createElement("article");
        el.className = "pr-page";
        el.setAttribute("aria-roledescription", "slide");
        rec = { def, el, cleanup: [], views: [], reveal: [], mounted: false, entered: false, key: null };
        recs.set(def.id, rec);
      }
      deck.appendChild(rec.el);
      const changed = rec.key !== def.key;
      rec.def = def;
      if (changed) { rec.key = def.key; fill(rec); if (rec.el.classList.contains("on") || flow) { mount(rec); if (rec.el.classList.contains("on")) enter(rec); } }
    });
    [...recs.keys()].forEach((id) => { if (!order.includes(id)) { const r = recs.get(id); teardown(r); r.el.remove(); recs.delete(id); } });
    // the printed page numbers follow the new count
    recs.forEach((r) => { const i = order.indexOf(r.def.id), last = r.el.querySelector(".pr-print-foot span:last-child"); if (last) last.textContent = `Prepared with public records · ${i + 1} of ${order.length}`; });
    segs.innerHTML = list.map((d, i) => `<button type="button" class="pr-seg" data-go="${i}" aria-label="${esc(d.title)}" title="${esc(d.title)}"><i></i></button>`).join("");
    const keep = order.indexOf(keepId);
    cur = keep >= 0 ? keep : Math.min(cur, order.length - 1);
    if (flow) watchFlow();
    paintFoot();
    if (pendingSlide && order.includes(pendingSlide)) {
      const wanted = order.indexOf(pendingSlide), still = cur === 0;   // only if the presenter has not moved on
      pendingSlide = "";
      if (still) later(() => go(wanted), 0);
    }
  }
  function paintFoot() {
    segs.querySelectorAll(".pr-seg").forEach((b, i) => { b.classList.toggle("on", i === cur); b.classList.toggle("past", i < cur); b.setAttribute("aria-current", i === cur ? "step" : "false"); });
    const rec = recs.get(order[cur]);
    nowTitle.textContent = rec ? rec.def.title : "";
    counter.textContent = `${cur + 1} of ${order.length}`;
    root.querySelector("[data-prev]").disabled = cur === 0;
    root.querySelector("[data-next]").disabled = cur === order.length - 1;
  }
  function countUp(scope) {
    scope.querySelectorAll(".pr-n").forEach((el) => {
      const to = Number(el.dataset.to), d = Number(el.dataset.d) || 0, start = performance.now() + 200, dur = 1200;
      const step = (now) => {
        if (gone || !el.isConnected) return;
        const t = Math.max(0, Math.min(1, (now - start) / dur));
        el.textContent = num(to * (1 - Math.pow(1 - t, 3)), d);
        if (t < 1) requestAnimationFrame(step); else el.textContent = num(to, d);
      };
      el.textContent = num(0, d);
      requestAnimationFrame(step);
    });
  }
  function enter(rec) {
    rec.el.classList.remove("enter");
    void rec.el.offsetWidth;   // so the entrance plays again when the slide is shown again
    rec.el.classList.add("enter");
    rec.entered = true;
    if (motion) countUp(rec.el);
    if (rec.def.enter) { try { rec.def.enter(rec); } catch (e) { console.error(e); } }
  }
  function go(i) {
    i = Math.max(0, Math.min(order.length - 1, i));
    if (flow) { const rec = recs.get(order[i]); if (rec) rec.el.scrollIntoView({ behavior: motion ? "smooth" : "auto", block: "start" }); cur = i; return; }
    const before = recs.get(order[cur]);
    if (before && i !== cur) before.el.classList.remove("on", "enter");
    cur = i;
    const rec = recs.get(order[cur]);
    if (!rec) return;
    rec.el.classList.add("on");
    mount(rec);
    enter(rec);
    paintFoot();
    // the slides either side are made ready, so moving on is instant
    [cur + 1, cur - 1].forEach((j) => mount(recs.get(order[j])));
    try { history.replaceState(null, "", location.hash.split("?")[0] + "?slide=" + encodeURIComponent(order[cur])); } catch (e) { /* the address keeps its old slide */ }
  }

  // ---------------------------------------------------------------- the screen: one slide scaled, or slides down the page

  let flowWatch = null, lastFlowWidth = 0;
  function watchFlow() {
    if (flowWatch) flowWatch.disconnect();
    flowWatch = new IntersectionObserver((entries) => entries.forEach((e) => {
      if (!e.isIntersecting) return;
      const rec = [...recs.values()].find((r) => r.el === e.target);
      if (!rec) return;
      mount(rec);
      if (!rec.entered) enter(rec);
      cur = order.indexOf(rec.def.id);
    }), { threshold: 0.2 });
    recs.forEach((r) => flowWatch.observe(r.el));
  }
  function layout() {
    const vw = window.innerWidth, vh = window.innerHeight, s = Math.min(vw / DW, vh / DH);
    const nowFlow = vw < 760 || s < 0.4;
    scaleNow = s;
    if (nowFlow !== flow) {
      flow = nowFlow;
      root.classList.toggle("pr-flow", flow);
      recs.forEach((r) => { r.views.forEach((v) => { if (flow) v.map.dragging.disable(); else v.map.dragging.enable(); }); r.entered = false; });
      if (flow) { recs.forEach((r) => r.el.classList.remove("on", "enter")); watchFlow(); }
      else { if (flowWatch) flowWatch.disconnect(); flowWatch = null; window.scrollTo(0, 0); go(cur); }
      recs.forEach(drawCharts);
      recs.forEach(fit);
    } else if (flow && Math.abs(vw - lastFlowWidth) > 20) recs.forEach(drawCharts);
    lastFlowWidth = vw;
    canvas.style.transform = flow ? "" : `translate(-50%, -50%) scale(${s})`;
  }
  const onResize = () => { if (!gone) layout(); };
  window.addEventListener("resize", onResize);
  cleanups.push(() => window.removeEventListener("resize", onResize));

  // ---------------------------------------------------------------- moving

  function toggleFull() {
    try {
      if (document.fullscreenElement) document.exitFullscreen();
      else document.documentElement.requestFullscreen();
    } catch (e) { /* the browser said no */ }
  }
  function onKey(e) {
    if (gone || e.ctrlKey || e.metaKey || e.altKey) return;
    const t = e.target, typing = t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA" || t.isContentEditable);
    if (typing) return;
    const onControl = t && t.closest && t.closest("button, a");
    const k = e.key;
    if (k === "Escape") { if (!document.fullscreenElement) { e.preventDefault(); location.hash = backHref; } return; }
    if (k === "f" || k === "F") { e.preventDefault(); toggleFull(); return; }
    if (flow) return;
    if (k === "ArrowRight" || k === "ArrowDown" || k === "PageDown" || (k === " " && !onControl) || (k === "Enter" && !onControl)) { e.preventDefault(); go(cur + (e.shiftKey && k === " " ? -1 : 1)); }
    else if (k === "ArrowLeft" || k === "ArrowUp" || k === "PageUp" || k === "Backspace") { e.preventDefault(); go(cur - 1); }
    else if (k === "Home") { e.preventDefault(); go(0); }
    else if (k === "End") { e.preventDefault(); go(order.length - 1); }
  }
  document.addEventListener("keydown", onKey);
  cleanups.push(() => document.removeEventListener("keydown", onKey));

  const busyTarget = (t) => t.closest("a, button, input, label, select, .leaflet-container, .view3d");
  deck.addEventListener("click", (e) => {
    if (flow || busyTarget(e.target) || (window.getSelection && String(window.getSelection()))) return;
    const box = deck.getBoundingClientRect();
    go(cur + (e.clientX < box.left + box.width / 3 ? -1 : 1));
  });
  let touch = null;
  deck.addEventListener("touchstart", (e) => { touch = !flow && e.touches.length === 1 && !e.target.closest(".leaflet-container, .view3d") ? { x: e.touches[0].clientX, y: e.touches[0].clientY } : null; }, { passive: true });
  deck.addEventListener("touchend", (e) => {
    if (!touch) return;
    const p = e.changedTouches[0], dx = p.clientX - touch.x, dy = p.clientY - touch.y;
    touch = null;
    if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.3) go(cur + (dx < 0 ? 1 : -1));
  });
  root.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.go !== undefined) go(Number(b.dataset.go));
    else if (b.hasAttribute("data-prev")) go(cur - 1);
    else if (b.hasAttribute("data-next")) go(cur + 1);
    else if (b.hasAttribute("data-full")) toggleFull();
    else if (b.hasAttribute("data-print")) printAll();
    else if (b.hasAttribute("data-motion")) setMotion(!motion);
    else if (b.hasAttribute("data-outlook-again")) askOutlook();
    else if (b.hasAttribute("data-ground-again")) askGround();
  });
  function setMotion(on) {
    motion = on;
    try { localStorage.setItem(MOTION_KEY, on ? "on" : "off"); } catch (e) { /* remembered for this visit only */ }
    root.classList.toggle("pr-motion", on);
    const sw = root.querySelector("[data-motion]");
    sw.setAttribute("aria-checked", String(on));
    sw.querySelector("span").textContent = `Motion ${on ? "on" : "off"}`;
    if (on && !flow) { const rec = recs.get(order[cur]); if (rec) enter(rec); }
  }
  const onFull = () => root.querySelector("[data-full]").textContent = document.fullscreenElement ? "Leave full screen" : "Full screen";
  document.addEventListener("fullscreenchange", onFull);
  cleanups.push(() => { document.removeEventListener("fullscreenchange", onFull); if (document.fullscreenElement) document.exitFullscreen().catch(() => {}); });

  // ---------------------------------------------------------------- print: every slide on its own page

  function readyAll() {
    if (flow) { flow = false; root.classList.remove("pr-flow"); recs.forEach(drawCharts); recs.forEach(fit); root.dataset.printFlow = "1"; }
    recs.forEach((r) => { mount(r); r.views.forEach((v) => v.map.invalidateSize()); });
  }
  const beforePrint = () => { root.classList.add("pr-printing"); readyAll(); };
  const afterPrint = () => { root.classList.remove("pr-printing"); if (root.dataset.printFlow) { delete root.dataset.printFlow; layout(); } };
  window.addEventListener("beforeprint", beforePrint);
  window.addEventListener("afterprint", afterPrint);
  cleanups.push(() => { window.removeEventListener("beforeprint", beforePrint); window.removeEventListener("afterprint", afterPrint); });
  function printAll() {
    readyAll();
    const b = root.querySelector("[data-print]");
    b.textContent = "Getting the maps ready…";
    later(() => { b.textContent = "Print"; window.print(); }, 2500);
  }

  // ---------------------------------------------------------------- the slower answers

  function askOutlook() {
    S.Oerr = "";
    sync();
    api.outlook(cityId, apns).then((o) => {
      if (gone) return;
      S.O = o;
      sync();
    }, (e) => {
      if (gone) return;
      S.Oerr = e.message || "The city's records could not be read just now.";
      sync();
    });
  }
  function askGround() {
    S.Gerr = ""; S.G = null;
    sync();
    api.ground(cityId, apns).then((g) => {
      if (gone) return;
      S.G = g || {};
      sync();
    }, (e) => {
      if (gone) return;
      S.Gerr = e.message || "no answer";
      sync();
    });
  }

  // ---------------------------------------------------------------- start

  cleanups.push(() => { recs.forEach(teardown); if (flowWatch) flowWatch.disconnect(); });
  sync();
  layout();
  const start = order.indexOf(wantSlide);
  if (start < 0) pendingSlide = wantSlide;
  if (!flow) go(start >= 0 ? start : 0);
  else if (start > 0) later(() => go(start), 300);
  askOutlook();
  askGround();
  // the maps of the other slides are made one by one in the background, so printing has them and moving is instant
  let next = 0;
  const warm = () => { while (next < order.length && recs.get(order[next]) && recs.get(order[next]).mounted) next++; if (next < order.length) { mount(recs.get(order[next])); later(warm, 900); } };
  later(warm, 1800);
}

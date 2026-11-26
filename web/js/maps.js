// One way to make a map, used by every page that shows one. Leaflet is loaded by index.html (window.L).
// Backgrounds are the U.S. Geological Survey's public map tiles; outlines are drawn from the app's own data,
// so a map still shows its shapes when the background cannot load.
import { api } from "./api.js";
import { esc, num } from "./util.js";

const TILES = "https://basemap.nationalmap.gov/arcgis/rest/services/";
// USGS aerial tiles stop at zoom 16; closer than that the same survey's NAIP photo is asked for as pictures
const NAIP = "https://imagery.nationalmap.gov/arcgis/services/USGSNAIPImagery/ImageServer/WMSServer";
const DEEPEST = 19;
const BASES = {
  aerial: { label: "Aerial photo" },
  streets: { label: "Street map" },
};

// Leaflet 1.9.4 can leave a redraw queued that its own bookkeeping has lost track of: an "update" event redraws at once
// and forgets the queued one, the next change queues a second, and taking the map away cancels only the second. The
// first then runs against a drawing surface that is gone ("reading 'clearRect'"). Every map in the app is made by
// createMap below, so the one fix is here: a redraw done directly replaces the queued one, and a layer whose map has
// been removed draws nothing.
function mendCanvasRedraw(L) {
  const proto = L.Canvas && L.Canvas.prototype;
  if (!proto || proto._redrawMended) return;
  const redraw = proto._redraw;
  proto._redraw = function () {
    if (this._redrawRequest) L.Util.cancelAnimFrame(this._redrawRequest);
    if (!this._ctx) { this._redrawRequest = null; return; }
    return redraw.call(this);
  };
  proto._redrawMended = true;
}

export const ll = (rings) => rings.map((r) => r.map((p) => [p[1], p[0]]));

// How strongly zoning colours are filled in: lighter on the photo, so the ground can still be seen.
export function fillStrength(base, onStreets) { return base === "aerial" ? 0.34 : onStreets; }

function backgroundLayer(L, name) {
  if (name === "streets") {
    return L.tileLayer(TILES + "USGSTopo/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 16, maxZoom: DEEPEST, zIndex: 1, attribution: "Background: USGS The National Map" });
  }
  return L.layerGroup([
    L.tileLayer(TILES + "USGSImageryOnly/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 16, maxZoom: DEEPEST, zIndex: 1, attribution: "Aerial photo: USGS The National Map" }),
    L.tileLayer.wms(NAIP, { layers: "USGSNAIPImagery", format: "image/jpeg", transparent: false, minZoom: 17, maxZoom: DEEPEST, tileSize: 512, zIndex: 2, attribution: "Close-up photo: USDA NAIP, served by USGS" }),
  ]);
}

// ---- labels on pieces of land (shared by the Forecast site plan, the Plan page and the presentation)
// Each label sits at the piece's visual centre: the point farthest from every edge, which stays inside L-shaped and thin
// pieces where the average of the corners would not. Labels are kept from overlapping at the current zoom: a label that
// would collide is moved a little within its own piece, then given its shorter wording, and left off (its piece still
// has a tooltip) only when nothing fits. Larger pieces are placed first, so the smaller piece gives way.
export function visualCentre(ring) {
  const lat0 = ring.reduce((t, p) => t + p[1], 0) / ring.length, k = Math.cos(lat0 * Math.PI / 180);
  const pts = ring.map((p) => [p[0] * k, p[1]]), n = pts.length;
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const size = Math.max(maxX - minX, maxY - minY);
  if (!size) return ring[0];
  const dist = (x, y) => {   // how far inside the piece (negative outside) from the nearest edge
    let inside = false, near = Infinity;
    for (let i = 0, j = n - 1; i < n; j = i++) {
      const a = pts[i], b = pts[j];
      if ((a[1] > y) !== (b[1] > y) && x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]) inside = !inside;
      let dx = a[0], dy = a[1];
      const ex = b[0] - dx, ey = b[1] - dy;
      if (ex || ey) { const t = Math.max(0, Math.min(1, ((x - dx) * ex + (y - dy) * ey) / (ex * ex + ey * ey))); dx += ex * t; dy += ey * t; }
      near = Math.min(near, (x - dx) ** 2 + (y - dy) ** 2);
    }
    return (inside ? 1 : -1) * Math.sqrt(near);
  };
  const cell = (x, y, h) => { const d = dist(x, y); return { x, y, h, d, max: d + h * Math.SQRT2 }; };
  let h = Math.min(maxX - minX, maxY - minY) / 2 || size / 2;
  const queue = [];
  for (let x = minX; x < maxX; x += h * 2) for (let y = minY; y < maxY; y += h * 2) queue.push(cell(x + h, y + h, h));
  let best = cell((minX + maxX) / 2, (minY + maxY) / 2, 0);
  queue.forEach((c) => { if (c.d > best.d) best = c; });
  const precision = size / 300;
  for (let guard = 0; queue.length && guard < 4000; guard++) {
    let top = 0;
    queue.forEach((c, i) => { if (c.max > queue[top].max) top = i; });
    const c = queue.splice(top, 1)[0];
    if (c.d > best.d) best = c;
    if (c.max - best.d <= precision) continue;
    h = c.h / 2;
    [[-h, -h], [h, -h], [-h, h], [h, h]].forEach(([dx, dy]) => queue.push(cell(c.x + dx, c.y + dy, h)));
  }
  return [best.x / k, best.y];
}
function ringArea(ring) {
  let a = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) a += (ring[j][0] + ring[i][0]) * (ring[j][1] - ring[i][1]);
  return Math.abs(a / 2);
}
function pointIn(p, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const a = poly[i], b = poly[j];
    if ((a.y > p.y) !== (b.y > p.y) && p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x) inside = !inside;
  }
  return inside;
}
// One per map. set([{ ring: [[lon, lat]...], variants: [fullHtml, shorterHtml...], className }]) draws them (replacing
// the last set) and returns the markers in the same order.
export function pieceLabels(L, map) {
  const group = L.layerGroup().addTo(map);
  let entries = [];
  function place() {
    if (!map._loaded || !map.getSize().x) return;
    const placed = [];
    entries.slice().sort((a, b) => b.area - a.area).forEach((en) => {
      const holder = en.marker.getElement(), span = holder && holder.firstChild;
      if (!span) return;
      const poly = en.ring.map((p) => map.latLngToContainerPoint([p[1], p[0]]));
      const c = map.latLngToContainerPoint([en.centre[1], en.centre[0]]);
      let done = false;
      for (const html of en.variants) {
        span.style.display = ""; span.style.transform = ""; span.innerHTML = html;
        const w = span.offsetWidth, h = span.offsetHeight;
        const tries = [[0, 0]];
        for (let step = 1; step <= 3; step++) {
          tries.push([0, -step * h * 0.9], [0, step * h * 0.9], [-step * w * 0.35, 0], [step * w * 0.35, 0],
            [-step * w * 0.3, -step * h * 0.7], [step * w * 0.3, -step * h * 0.7], [-step * w * 0.3, step * h * 0.7], [step * w * 0.3, step * h * 0.7]);
        }
        for (const [dx, dy] of tries) {
          const at = { x: c.x + dx, y: c.y + dy };
          if ((dx || dy) && !pointIn(at, poly)) continue;
          const box = { l: at.x - w / 2 - 3, r: at.x + w / 2 + 3, t: at.y - h / 2 - 2, b: at.y + h / 2 + 2 };
          if (placed.some((o) => box.r > o.l && box.l < o.r && box.b > o.t && box.t < o.b)) continue;
          if (dx || dy) span.style.transform = `translate(calc(-50% + ${Math.round(dx)}px), calc(-50% + ${Math.round(dy)}px))`;
          placed.push(box);
          done = true;
          break;
        }
        if (done) break;
      }
      if (!done) span.style.display = "none";
    });
  }
  map.on("load moveend zoomend resize", place);
  return {
    set(specs) {
      group.clearLayers();
      entries = [];
      const markers = specs.map((spec) => {
        if (!spec.ring || spec.ring.length < 3) return null;
        const centre = visualCentre(spec.ring);
        const marker = L.marker([centre[1], centre[0]], { icon: L.divIcon({ className: spec.className || "", iconSize: [0, 0], html: "<span></span>" }), interactive: false, keyboard: false }).addTo(group);
        entries.push({ marker, centre, ring: spec.ring, variants: spec.variants, area: ringArea(spec.ring) });
        return marker;
      });
      place();
      return markers.filter(Boolean);
    },
  };
}

// el: the box to fill. base: "aerial" (the default) or "streets".
// city + at ({lat, lon}): when given, a line under the map says when its records and its photo were last updated.
// Returns { map, fit(bounds), release(), destroy(), base(), onBase(fn), note(html) }.
export function createMap(el, { base = "aerial", city = null, at = null } = {}) {
  const L = window.L;
  mendCanvasRedraw(L);
  const map = L.map(el, { scrollWheelZoom: true, preferCanvas: true, zoomSnap: 0.25, maxZoom: DEEPEST });
  map.attributionControl.setPrefix(false);
  let layer = null, current = base;
  const buttons = [], listeners = new Set();
  function setBase(name) {
    if (layer && name === current) return;
    if (layer) map.removeLayer(layer);
    current = name;
    layer = backgroundLayer(L, name).addTo(map);
    buttons.forEach((b) => { const on = b.dataset.base === name; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); });
    listeners.forEach((fn) => fn(name));
  }
  const Switch = L.Control.extend({
    options: { position: "topright" },
    onAdd() {
      const box = L.DomUtil.create("div", "map-switch");
      Object.entries(BASES).forEach(([name, b]) => {
        const button = L.DomUtil.create("button", "", box);
        button.type = "button"; button.textContent = b.label; button.dataset.base = name;
        button.addEventListener("click", () => setBase(name));
        buttons.push(button);
      });
      L.DomEvent.disableClickPropagation(box);
      return box;
    },
  });
  map.addControl(new Switch());
  L.control.scale({ metric: false }).addTo(map);
  setBase(current);

  // a small message on the map itself (bottom left, above the scale); note(null) hides it
  let noteBox = null;
  const Note = L.Control.extend({
    options: { position: "bottomleft" },
    onAdd() { noteBox = L.DomUtil.create("div", "map-note"); noteBox.setAttribute("role", "status"); noteBox.hidden = true; return noteBox; },
  });
  map.addControl(new Note());
  function note(html) {
    if (!noteBox) return;
    noteBox.hidden = !html;
    noteBox.innerHTML = html || "";
  }

  let wanted = null, gone = false;
  function fit(bounds, options) {
    wanted = [bounds, { ...options, animate: false }];
    if (!gone && el.clientWidth && el.clientHeight) map.fitBounds(wanted[0], wanted[1]);
  }
  // A map made while its box has no size shows the whole world: fit again whenever the box changes size.
  const watcher = window.ResizeObserver ? new ResizeObserver(() => {
    if (gone || !el.isConnected) return;
    map.invalidateSize();
    if (wanted) map.fitBounds(wanted[0], wanted[1]);
  }) : null;
  if (watcher) watcher.observe(el);

  if (city && at && Number.isFinite(at.lat) && Number.isFinite(at.lon)) {
    const line = document.createElement("p");
    line.className = "map-updated";
    line.textContent = "Checking when this map was last updated…";
    const frame = el.parentElement && el.parentElement.classList.contains("map-frame") ? el.parentElement : null;
    if (frame) frame.appendChild(line); else el.insertAdjacentElement("afterend", line);
    // the strip's height, for a page that lays the map's corner controls above it (the presentation does)
    const lift = () => { if (!gone && line.isConnected && line.offsetHeight) line.parentElement.style.setProperty("--updated-h", line.offsetHeight + "px"); };
    lift();
    map.on("resize", lift);
    api.updated(city, at.lat, at.lon)
      .then((d) => { if (!gone && line.isConnected) line.innerHTML = updatedWords(d); })
      .catch(() => { if (!gone && line.isConnected) line.textContent = "When this map was last updated could not be read just now."; })
      .then(lift);
  }

  let labels = null;
  return {
    map, fit, note,
    pieceLabels() { return labels || (labels = pieceLabels(L, map)); },
    base: () => current,
    onBase(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    release() { wanted = null; },   // stop re-fitting (after the person has moved the map themselves)
    destroy() {
      if (gone) return;
      gone = true;
      listeners.clear();
      if (watcher) watcher.disconnect();
      map.stop();
      // Leaflet finishes a zoom a moment after it starts; taking the map away in between makes it trip
      if (map._animatingZoom) map.once("zoomend", () => setTimeout(() => map.remove(), 0));
      else map.remove();
    },
  };
}

// "2026-10-28" as "Oct 28, 2026" (read as a calendar day, so it never slips a day by time zone)
function day(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ""));
  if (!m) return "";
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}
function monthYear(iso) {
  const m = /^(\d{4})-(\d{2})/.exec(String(iso || ""));
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, 1).toLocaleDateString("en-US", { month: "long", year: "numeric" }) : "";
}
const RECORD_NAMES = { parcels: "Parcel lines: city records", zoning: "Zoning: city records" };

function updatedWords(d) {
  const parts = [];
  const records = d && d.records;
  const said = records ? Object.keys(records).filter((k) => day(records[k])) : [];
  if (said.length) said.forEach((k) => parts.push(`${esc(RECORD_NAMES[k] || "City records (" + k + ")")} last changed <b>${esc(day(records[k]))}</b>`));
  else parts.push("Parcel lines: the city's map service did not answer just now about when its records last changed");
  const photo = d && d.photo;
  let after = "";
  if (photo && (day(photo.taken) || photo.year)) {
    const taken = day(photo.taken);
    const detail = Number(photo.detail_metres) > 0 ? ` (shows detail down to about ${esc(num(photo.detail_metres * 3.28084, photo.detail_metres * 3.28084 < 3 ? 1 : 0))} ft)` : "";
    parts.push(`Aerial photo taken <b>${esc(taken || "in " + photo.year)}</b>${detail}`);
    after = ` Anything built after ${esc(taken ? monthYear(photo.taken) : photo.year)} will not be in the photo.`;
  } else {
    parts.push("Aerial photo: the photo service did not answer just now about when it was taken");
  }
  return parts.join(" · ") + "." + after;
}

export function legend(kinds, shownIds) {
  const rows = kinds.filter((k) => shownIds.has(k.id));
  return rows.map((k) => `<span><i style="background:${k.colour}"></i>${k.label}</span>`).join("");
}
export function kindColour(kinds, id) {
  const k = kinds.find((x) => x.id === id);
  return k ? k.colour : "#9aa0a6";
}

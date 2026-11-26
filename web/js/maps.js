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

// el: the box to fill. base: "aerial" (the default) or "streets".
// city + at ({lat, lon}): when given, a line under the map says when its records and its photo were last updated.
// Returns { map, fit(bounds), release(), destroy(), base(), onBase(fn), note(html) }.
export function createMap(el, { base = "aerial", city = null, at = null } = {}) {
  const L = window.L;
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
    api.updated(city, at.lat, at.lon)
      .then((d) => { if (!gone && line.isConnected) line.innerHTML = updatedWords(d); })
      .catch(() => { if (!gone && line.isConnected) line.textContent = "When this map was last updated could not be read just now."; });
  }

  return {
    map, fit, note,
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

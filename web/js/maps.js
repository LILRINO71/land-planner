// One way to make a map, used by every page that shows one. Leaflet is loaded by index.html (window.L).
// Backgrounds are the U.S. Geological Survey's public map tiles; outlines are drawn from the app's own data,
// so a map still shows its shapes when the background cannot load.

const TILES = "https://basemap.nationalmap.gov/arcgis/rest/services/";
const BASES = {
  streets: { label: "Street map", url: TILES + "USGSTopo/MapServer/tile/{z}/{y}/{x}" },
  aerial: { label: "Aerial photo", url: TILES + "USGSImageryOnly/MapServer/tile/{z}/{y}/{x}" },
};

export const ll = (rings) => rings.map((r) => r.map((p) => [p[1], p[0]]));

// el: the box to fill. base: "streets" or "aerial". Returns { map, destroy(), fit(bounds) }.
export function createMap(el, { base = "streets" } = {}) {
  const L = window.L;
  const map = L.map(el, { scrollWheelZoom: false, preferCanvas: true, zoomSnap: 0.25 });
  map.attributionControl.setPrefix(false);
  let layer = null, current = base;
  function setBase(name) {
    if (layer) map.removeLayer(layer);
    current = name;
    layer = L.tileLayer(BASES[name].url, { maxNativeZoom: 16, maxZoom: 19, attribution: "Background: USGS The National Map" }).addTo(map);
    layer.bringToBack();
    buttons.forEach((b) => b.classList.toggle("on", b.dataset.base === name));
  }
  const buttons = [];
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
  // click the map to turn on wheel zoom, so scrolling the page never gets caught by the map
  map.on("click", () => map.scrollWheelZoom.enable());
  map.on("mouseout", () => map.scrollWheelZoom.disable());

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
  return {
    map, fit,
    release() { wanted = null; },   // stop re-fitting (after the person has moved the map themselves)
    destroy() {
      if (gone) return;
      gone = true;
      if (watcher) watcher.disconnect();
      map.stop();
      // Leaflet finishes a zoom a moment after it starts; taking the map away in between makes it trip
      if (map._animatingZoom) map.once("zoomend", () => setTimeout(() => map.remove(), 0));
      else map.remove();
    },
  };
}

export function legend(kinds, shownIds) {
  const rows = kinds.filter((k) => shownIds.has(k.id));
  return rows.map((k) => `<span><i style="background:${k.colour}"></i>${k.label}</span>`).join("");
}
export function kindColour(kinds, id) {
  const k = kinds.find((x) => x.id === id);
  return k ? k.colour : "#9aa0a6";
}

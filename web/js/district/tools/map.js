// Map and trade area: the project's GIS layers on the aerial photo (each layer switched on and off), parcels
// coloured by zoning, use or phase with a legend and a popup, and straight-line distance rings around the site.
// Rings are distances, not drive times.
import { esc, isNum, nFix, fold, page, leadHtml, calmBox, seg, wireSegKeys, acres, NK, entities, useLabel, phaseLabel, guarded, loadingHtml } from "./common.js";
import { createMap } from "../../maps.js";

const PALETTE = ["#f2b632", "#4fb3a9", "#e07b53", "#8fb5e8", "#c58fd6", "#9ccc65", "#f48fb1", "#ffd54f", "#80cbc4", "#bcaaa4", "#90a4ae", "#ffab91"];
const RINGS = [1, 3, 5, 10];
const MILE = 1609.344;
const digits = (s) => String(s || "").replace(/\D/g, "");

export async function render(el, ctx) {
  el.innerHTML = loadingHtml("Reading the map layers…");
  await guarded(el, ctx, async () => {
    const p = encodeURIComponent(ctx.project.id), aud = ctx.viewAs ? { audience: ctx.viewAs } : null;
    const list = ((await ctx.api.get(`/projects/${p}/gis`, aud)).layers || []).filter((l) => !l.removed);
    const layers = [];
    for (const l of list) {
      try { layers.push({ meta: l, fc: await ctx.api.get(`/projects/${p}/gis/${encodeURIComponent(l.id)}`, aud) }); }
      catch (e) { layers.push({ meta: l, fc: null, error: e.message }); }
    }
    if (ctx.alive && !ctx.alive()) return;
    draw(el, ctx, layers);
  });
}

// the dataset's parcel for a GIS feature (matched by APN digits)
function parcelFor(ctx, props) {
  const d = digits(props.apn || props.APN || props.parcel || props.id);
  return d ? (entities(ctx).parcels || []).find((x) => digits(x.apn || x.id) === d) || null : null;
}
function factsOf(ctx, f) {
  const pr = f.properties || {}, row = parcelFor(ctx, pr) || {};
  return {
    apn: pr.apn || pr.APN || row.apn || "", label: pr.label || pr.name || row.label || "",
    acres: isNum(pr.city_acres) ? pr.city_acres : isNum(pr.documents_gross_acres) ? pr.documents_gross_acres : isNum(pr.acres) ? pr.acres : row.acres,
    zoning: pr.city_zoning || pr.zoning || pr.documents_zoning || "", use: row.use ? useLabel(ctx, row.use) : pr.use || "",
    phase: row.phase ? phaseLabel(ctx, row.phase) : pr.phase || "", gp: pr.city_general_plan || "", differs: !!(pr.acres_differ || pr.zoning_differs),
  };
}
// a polygon's middle (the average of its first ring) for the rings' centre
function middle(fcs) {
  const pts = [];
  fcs.forEach((fc) => (fc.features || []).forEach((f) => {
    const g = f.geometry || {};
    if (g.type === "Point") pts.push(g.coordinates);
    else if (g.type === "Polygon") pts.push(...(g.coordinates[0] || []));
    else if (g.type === "MultiPolygon") (g.coordinates || []).forEach((poly) => pts.push(...(poly[0] || [])));
  }));
  if (!pts.length) return null;
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  return [(Math.min(...ys) + Math.max(...ys)) / 2, (Math.min(...xs) + Math.max(...xs)) / 2];
}

function draw(el, ctx, layers) {
  const P = page(el, ctx);
  const ok = layers.filter((l) => l.fc && (l.fc.features || []).length);
  const parcelLayers = ok.filter((l) => l.meta.kind === "parcels");
  const parcelFeatures = parcelLayers.flatMap((l) => l.fc.features);
  const totalAc = parcelFeatures.reduce((t, f) => { const a = factsOf(ctx, f).acres; return t + (isNum(a) ? Number(a) : 0); }, 0);
  const corridor = (ctx.modules || []).find((m) => m.id === "corridor" || String(m.group || "").toLowerCase() === "corridor");
  const state = { by: "zoning", rings: new Set(), custom: "" };

  const lead = ok.length
    ? leadHtml({ sentence: parcelFeatures.length ? `${parcelFeatures.length} parcels on ${esc(nFix(totalAc, 1))} acres, on the aerial photo with ${ok.length} ${ok.length === 1 ? "layer" : "layers"} from the package.` : `${ok.length} ${ok.length === 1 ? "layer" : "layers"} from the package on the aerial photo.`,
      big: parcelFeatures.length ? nFix(totalAc, 1) : "", bigLabel: parcelFeatures.length ? "Acres in the parcels layer" : "", aside: "Click a parcel for its facts. Switch layers on and off on the right; add distance rings to see what lies within a few miles." })
    : leadHtml({ sentence: layers.length ? "The map layers this view can see have no shapes to draw yet." : `The package has no map layers${ctx.viewAs ? " shared with this audience" : ""} yet.`, aside: "An administrator adds them under Data, Map layers (GeoJSON or a zipped shapefile)." });
  if (!ok.length) {
    P.set({ lead, parts: [["map", "Map", (corridor ? corridorBox(ctx, corridor) : "") + calmBox("Nothing to draw yet", "Upload a parcels, trade area or competitors layer and it appears here.")]] });
    return;
  }

  const side = `<div class="tl-map-side">
    ${parcelLayers.length ? `<section class="tl-box">${seg("by", [["zoning", "Zoning"], ["use", "Use"], ["phase", "Phase"]], state.by, "Colour parcels by")}<ul class="tl-legend" data-legend aria-label="Legend"></ul></section>` : ""}
    <section class="tl-box"><h3>Layers</h3>${ok.map((l, i) => `<label class="check"><input type="checkbox" data-layer="${i}" checked> ${esc(l.meta.label || l.meta.id)} <small class="muted">(${(l.fc.features || []).length})</small></label>`).join("")}
      ${layers.filter((l) => l.error).map((l) => `<p class="fine">${esc(l.meta.label || l.meta.id)} could not be read: ${esc(l.error)}</p>`).join("")}</section>
    <section class="tl-box"><h3>Distance rings</h3>
      <div class="tl-rings" role="group" aria-label="Rings around the site">${RINGS.map((m) => `<button type="button" data-ring="${m}" aria-pressed="false">${m} ${m === 1 ? "mile" : "miles"}</button>`).join("")}</div>
      <form class="dz-row" data-ring-form style="margin-top:8px"><label class="field" style="flex:1 1 120px"><span>Another distance (miles)</span><input type="number" min="0.1" max="50" step="0.1" inputmode="decimal" name="miles"></label><button type="submit" class="btn small">Add ring</button></form>
      <p class="fine">These are straight-line distance rings, not drive times. Drive-time trade areas need a consultant's study or an Esri licence.</p></section>
    ${corridor ? corridorBox(ctx, corridor) : ""}
  </div>`;
  const list = parcelFeatures.length ? fold("map-list", `List the ${parcelFeatures.length} parcels`, `<ul class="tl-mini">${parcelFeatures.map((f, i) => { const x = factsOf(ctx, f); return `<li><button type="button" class="link" data-zoom="${i}">${esc(x.apn || x.label || "Parcel " + (i + 1))}</button> ${esc(x.label && x.apn ? x.label : "")} · ${esc(acres(x.acres))} · ${esc(x.zoning || NK)}</li>`; }).join("")}</ul>`, P.openFolds) : "";
  P.set({ lead, parts: [["map", "Map", `<div class="tl-map-wrap"><div><div class="map-frame"><div class="map tl-map" role="region" aria-label="Map of the project"></div></div>${list}</div>${side}</div>`]] });
  wireSegKeys(el);

  const L = window.L, box = el.querySelector(".tl-map");
  const centre = middle(ok.map((l) => l.fc));
  const m = createMap(box, { base: "aerial", city: ctx.project.city || null, at: centre ? { lat: centre[0], lon: centre[1] } : null });
  if (ctx.alive && ctx.alive.onLeave) ctx.alive.onLeave(() => m.destroy());
  const legendEl = el.querySelector("[data-legend]");
  const colourOf = new Map();
  const keyOf = (x) => (state.by === "use" ? x.use : state.by === "phase" ? x.phase : x.zoning) || "Not given";
  const colour = (k) => { if (!colourOf.has(state.by + "|" + k)) colourOf.set(state.by + "|" + k, k === "Not given" ? "#bdbdbd" : PALETTE[[...colourOf.keys()].filter((c) => c.startsWith(state.by + "|")).length % PALETTE.length]); return colourOf.get(state.by + "|" + k); };
  const popup = (x) => `<div class="tl-pop"><b>${esc(x.label || "Parcel")}</b><dl>
    <dt>APN</dt><dd>${esc(x.apn || NK)}</dd><dt>Acres</dt><dd>${esc(isNum(x.acres) ? nFix(x.acres, 2) : NK)}</dd>
    <dt>Zoning</dt><dd>${esc(x.zoning || NK)}${x.gp ? ` <small>(general plan ${esc(x.gp)})</small>` : ""}</dd>
    <dt>Use</dt><dd>${esc(x.use || NK)}</dd><dt>Phase</dt><dd>${esc(x.phase || NK)}</dd></dl>
    ${x.differs ? '<p class="fine">The papers and the city record differ here: see Papers vs. city record.</p>' : ""}</div>`;
  const groups = [], parcelShapes = [];
  ok.forEach((l, i) => {
    const isParcels = l.meta.kind === "parcels";
    const g = L.geoJSON(l.fc, {
      style: (f) => (isParcels ? { color: "#ffffff", weight: 2, fillColor: colour(keyOf(factsOf(ctx, f))), fillOpacity: 0.55 }
        : l.meta.kind === "trade_area" ? { color: "#f2b632", weight: 3, dashArray: "8 6", fill: true, fillOpacity: 0.06 } : { color: "#8fb5e8", weight: 2, fillOpacity: 0.15 }),
      pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 7, color: "#fff", weight: 2, fillColor: l.meta.kind === "competitors" ? "#e07b53" : "#1f4436", fillOpacity: 0.95 }),
      onEachFeature: (f, lay) => {
        if (isParcels) { const x = factsOf(ctx, f); lay.bindPopup(popup(x)); lay.bindTooltip(x.apn || x.label || "Parcel"); parcelShapes.push(lay); }
        else { const pr = f.properties || {}; const nm = pr.name || pr.label || l.meta.label; lay.bindPopup(`<div class="tl-pop"><b>${esc(nm)}</b><dl>${Object.entries(pr).filter(([k, v]) => k !== "name" && (typeof v !== "object")).slice(0, 8).map(([k, v]) => `<dt>${esc(k.replace(/_/g, " "))}</dt><dd>${esc(v)}</dd>`).join("")}</dl></div>`); lay.bindTooltip(nm); }
      },
    }).addTo(m.map);
    groups[i] = g;
  });
  const all = L.featureGroup(groups.filter(Boolean));
  if (all.getLayers().length) m.fit(all.getBounds().pad(0.08));
  m.map.once("dragstart zoomstart", () => m.release());

  function legend() {
    if (!legendEl) return;
    const counts = new Map();
    parcelFeatures.forEach((f) => { const k = keyOf(factsOf(ctx, f)); counts.set(k, (counts.get(k) || 0) + 1); });
    legendEl.innerHTML = [...counts.entries()].map(([k, n]) => `<li><i style="background:${colour(k)}"></i><span>${esc(k)}</span><small class="muted">${n}</small></li>`).join("");
  }
  function recolour() {
    groups.forEach((g, i) => { if (ok[i].meta.kind === "parcels") g.setStyle((f) => ({ color: "#ffffff", weight: 2, fillColor: colour(keyOf(factsOf(ctx, f))), fillOpacity: 0.55 })); });
    legend();
  }
  legend();

  // distance rings around the middle of the site
  const ringLayer = L.layerGroup().addTo(m.map);
  const site = parcelLayers.length ? middle(parcelLayers.map((l) => l.fc)) : centre;
  function drawRings() {
    ringLayer.clearLayers();
    const miles = [...state.rings].sort((a, b) => a - b);
    let last = null;
    miles.forEach((mi) => {
      last = L.circle(site, { radius: mi * MILE, color: "#ffffff", weight: 2, dashArray: "6 6", fill: false, interactive: false }).addTo(ringLayer);
      const north = [site[0] + (mi * MILE) / 111320, site[1]];
      L.marker(north, { interactive: false, keyboard: false, icon: L.divIcon({ className: "", iconSize: [0, 0], html: `<span class="tl-ring-label">${esc(nFix(mi, mi % 1 ? 1 : 0))} ${mi === 1 ? "mile" : "miles"}</span>` }) }).addTo(ringLayer);
    });
    if (last) { m.release(); m.map.fitBounds(last.getBounds().pad(0.05), { animate: false }); }
    m.note(miles.length ? `Straight-line rings: ${miles.map((x) => nFix(x, x % 1 ? 1 : 0)).join(", ")} ${miles.length === 1 && miles[0] === 1 ? "mile" : "miles"}. Not drive times.` : null);
  }

  el.addEventListener("change", (e) => {
    const c = e.target.closest("[data-layer]");
    if (c) { const g = groups[Number(c.dataset.layer)]; if (c.checked) g.addTo(m.map); else m.map.removeLayer(g); }
  });
  el.addEventListener("click", (e) => {
    const r = e.target.closest("[data-ring]");
    if (r) { const mi = Number(r.dataset.ring); if (state.rings.has(mi)) state.rings.delete(mi); else state.rings.add(mi); r.setAttribute("aria-pressed", String(state.rings.has(mi))); drawRings(); return; }
    const b = e.target.closest('[data-seg="by"]');
    if (b) { state.by = b.dataset.val; el.querySelectorAll('[data-seg="by"]').forEach((x) => { const on = x === b; x.classList.toggle("on", on); x.setAttribute("aria-checked", String(on)); }); recolour(); return; }
    const z = e.target.closest("[data-zoom]");
    if (z) { const lay = parcelShapes[Number(z.dataset.zoom)]; if (lay) { m.release(); m.map.fitBounds(lay.getBounds().pad(0.6), { animate: false }); lay.openPopup(); box.scrollIntoView({ block: "nearest" }); } }
  });
  el.addEventListener("submit", (e) => {
    const f = e.target.closest("[data-ring-form]");
    if (!f) return;
    e.preventDefault();
    const mi = Number(f.elements.miles.value);
    if (isNum(mi) && mi > 0 && mi <= 50) { state.rings.add(Math.round(mi * 10) / 10); f.elements.miles.value = ""; drawRings(); }
  });
}

function corridorBox(ctx, mod) {
  return `<section class="tl-box"><h3>The corridor around the site</h3><p class="tl-note">${esc(mod.description || "The package's own page on the corridor: what is planned and built along it.")}</p>
    <p><a class="btn small" href="${esc(ctx.link(["m", mod.id]))}">Open ${esc(mod.label || "the corridor page")}</a></p></section>`;
}

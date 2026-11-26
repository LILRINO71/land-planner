// Cities: one card per city with a live count of its large parcels.
import { api, cities } from "../api.js";
import { esc, num, plural, when, icon, loading, problem } from "../util.js";
import { createMap, ll, kindColour, legend } from "../maps.js";

export async function render(el, params, alive) {
  el.innerHTML = `
    <header class="page-head">
      <p class="kicker">Land Planner</p>
      <h1>Cities</h1>
      <p class="lead">Pick a city to see its large parcels of land, on a map and in a list.</p>
    </header>
    <div class="cities-layout">
    <div class="city-grid" id="cityGrid">${loading("Getting the list of cities…")}</div>
    <section class="note-row">
      <div class="card soft">
        <h3>What you are looking at</h3>
        <p>The facts in Land Planner are read from public records: each city's own parcel, zoning, street and project maps, the U.S. Geological Survey for ground heights and aerial photos, Caltrans for highway traffic and the Census for people. Where a fact is not available it says “not covered yet”. Each land's Plan page then suggests how the land could be divided; it marks which of its numbers are measured and which are starting figures to replace with your own.</p>
      </div>
      <div class="card soft">
        <h3>What it is not</h3>
        <p>Parcel outlines are the assessor's drawings, <b>not a boundary survey</b>. Zoning and the general plan say what is allowed today; <b>any change goes through the city</b>. This is a starting point for the owner, the engineer and the city's planners, not a decision.</p>
      </div>
    </section>
    </div>`;
  const grid = el.querySelector("#cityGrid");
  let list;
  try {
    list = await cities();
  } catch (e) {
    if (!alive()) return;
    grid.innerHTML = problem(e.message);
    grid.querySelector("[data-retry]").addEventListener("click", () => render(el, params, alive));
    return;
  }
  if (!alive()) return;
  grid.innerHTML = list.map((c) => `
    <article class="card city" data-city="${esc(c.id)}">
      <div class="city-top">
        <div><h2>${esc(c.name)}</h2><p class="muted">${esc(c.region)}</p></div>
        <span class="chip">${icon("pin")} ${num(c.large_acres)} ${plural(c.large_acres, "acre")} and up</span>
      </div>
      <div class="city-body">
        <div class="city-facts">
          <div class="city-count" data-count>${loading("Counting large parcels…")}</div>
          <a class="btn primary" href="#/lands/${esc(c.id)}">See the lands ${icon("arrow")}</a>
        </div>
        <div class="city-map-box">
          <div class="map-frame"><div class="map city-map" data-map aria-label="Map of ${esc(c.name)}'s large parcels"></div></div>
          <div class="legend" data-legend></div>
        </div>
      </div>
    </article>`).join("") + `
    <article class="card city more">
      <h2>More cities</h2>
      <p class="muted">Menifee is the first city. Others can be added as their public parcel and zoning records are connected, and will appear here as cards.</p>
    </article>`;
  list.forEach((c) => {
    count(grid.querySelector(`[data-city="${c.id}"] [data-count]`), c, alive, false);
    preview(grid.querySelector(`[data-city="${c.id}"]`), c, alive);
  });
}

// The city's large parcels on a small map, coloured by zoning. Click a shape to open that land.
async function preview(card, c, alive) {
  const L = window.L, view = createMap(card.querySelector("[data-map]"), { base: "aerial", city: c.id, at: c.centre });
  alive.onLeave(view.destroy);
  view.fit(L.latLng(c.centre.lat, c.centre.lon).toBounds(16000));
  try {
    const [lands, shapes] = await Promise.all([api.lands(c.id, {}), api.shapes(c.id)]);
    if (!alive()) return;
    const kinds = new Set(), bounds = L.latLngBounds([]);
    lands.parcels.forEach((p) => {
      const rings = shapes.shapes[p.apn];
      if (!rings || !rings.length) return;
      kinds.add(p.zoning_kind);
      const colour = kindColour(c.zoning_kinds, p.zoning_kind);
      const shape = L.polygon(ll(rings), { color: colour, weight: 1.5, fillColor: colour, fillOpacity: 0.4 })
        .bindTooltip(`${esc(p.apn_formatted || p.apn)} · ${num(p.acres, 2)} ${plural(p.acres, "acre", "acres", 2)} · ${esc(p.zoning || "no zoning listed")}`, { sticky: true })
        .on("click", () => { location.hash = `#/land/${c.id}/${p.apn}`; })
        .addTo(view.map);
      bounds.extend(shape.getBounds());
    });
    if (bounds.isValid()) view.fit(bounds.pad(0.05));
    card.querySelector("[data-legend]").innerHTML = legend(c.zoning_kinds, kinds);
  } catch (e) {
    if (alive()) card.querySelector("[data-legend]").innerHTML = '<span class="missing">The parcel outlines could not be loaded just now.</span>';
  }
}

async function count(box, c, alive, fresh) {
  box.innerHTML = loading("Counting large parcels…");
  try {
    const s = await api.summary(c.id, fresh);
    if (!alive()) return;
    box.innerHTML = `
      <p class="big"><b>${num(s.large_parcels)}</b><span>parcels of ${num(c.large_acres)} ${plural(c.large_acres, "acre")} or more</span></p>
      <ul class="facts-line">
        <li><b>${num(s.look_vacant)}</b> with no buildings on the assessor's records</li>
        <li>Largest: <b>${num(s.largest_acres, 2)} ${plural(s.largest_acres, "acre", "acres", 2)}</b></li>
        <li><b>${num(s.total_acres)}</b> acres in all</li>
      </ul>
      <p class="fine">${s.stale ? "The city's map service did not answer just now. Showing the count from " + esc(when(s.fetched)) + "."
        : "Counted " + esc(when(s.fetched)) + " from " + esc(c.sources.parcel || "the city's public records") + "."}
        <button class="link" data-again>Count again</button></p>`;
    box.querySelector("[data-again]").addEventListener("click", () => count(box, c, alive, true));
  } catch (e) {
    if (!alive()) return;
    box.innerHTML = problem(e.message);
    box.querySelector("[data-retry]").addEventListener("click", () => count(box, c, alive, true));
  }
}

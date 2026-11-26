// Cities: one card per city with a live count of its large parcels.
import { api, cities } from "../api.js";
import { esc, num, when, icon, loading, problem } from "../util.js";

export async function render(el, params, alive) {
  el.innerHTML = `
    <header class="page-head">
      <p class="kicker">Land Planner</p>
      <h1>Cities</h1>
      <p class="lead">Pick a city to see its large parcels of land, on a map and in a list.</p>
    </header>
    <div class="city-grid" id="cityGrid">${loading("Getting the list of cities…")}</div>
    <section class="note-row">
      <div class="card soft">
        <h3>What you are looking at</h3>
        <p>Everything in Land Planner is read from public records: each city's own parcel and zoning maps, the U.S. Geological Survey for ground heights, and Caltrans for highway traffic. Nothing is estimated. Where a fact is not available it says “not covered yet”.</p>
      </div>
      <div class="card soft">
        <h3>What it is not</h3>
        <p>Parcel outlines are the assessor's drawings, <b>not a boundary survey</b>. Zoning and the general plan say what is allowed today; <b>any change goes through the city</b>. This is a starting point for the owner, the engineer and the city's planners, not a decision.</p>
      </div>
    </section>`;
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
        <span class="chip">${icon("pin")} ${num(c.large_acres)} acres and up</span>
      </div>
      <div class="city-count" data-count>${loading("Counting large parcels…")}</div>
      <a class="btn primary" href="#/lands/${esc(c.id)}">See the lands ${icon("arrow")}</a>
    </article>`).join("") + `
    <article class="card city more">
      <h2>More cities</h2>
      <p class="muted">Menifee is the first city. Others can be added as their public parcel and zoning records are connected, and will appear here as cards.</p>
    </article>`;
  list.forEach((c) => count(grid.querySelector(`[data-city="${c.id}"] [data-count]`), c, alive, false));
}

async function count(box, c, alive, fresh) {
  box.innerHTML = loading("Counting large parcels…");
  try {
    const s = await api.summary(c.id, fresh);
    if (!alive()) return;
    box.innerHTML = `
      <p class="big"><b>${num(s.large_parcels)}</b><span>parcels of ${num(c.large_acres)} acres or more</span></p>
      <ul class="facts-line">
        <li><b>${num(s.look_vacant)}</b> with no buildings on the assessor's records</li>
        <li>Largest: <b>${num(s.largest_acres, 2)} acres</b></li>
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

// Lands: a city's large parcels on a map and in a list that can be sorted, filtered and searched.
// The filtering and sorting themselves are done by the server (landplanner/lands.py), so the list and the
// command-line tool can never disagree; this page only asks and draws.
import { api, city as getCity, cities, saved } from "../api.js";
import { createMap, ll, legend, kindColour } from "../maps.js";
import { esc, has, num, money, when, icon, loading, problem, toast, debounce, apnText } from "../util.js";

const remembered = {};   // the filters last used in each city, kept while the app is open
const fresh = () => ({ min: "", max: "", zoning: "", vacant: false, q: "", sort: "acres", dir: "desc" });
const COLUMNS = [["apn", "Parcel number"], ["acres", "Acres"], ["zoning", "Zoning"], ["vacant", "Buildings"], ["land_value", "Assessed land value"]];

export async function render(el, params, alive) {
  let c, all;
  try {
    [c, all] = [await getCity(params.city), await cities()];
  } catch (e) {
    if (!alive()) return;
    el.innerHTML = `<header class="page-head"><h1>Lands</h1></header>` + problem(e.message, e.code === "no-such-city" ? "" : "Try again") +
      (e.code === "no-such-city" ? `<p><a class="btn" href="#/cities">Back to Cities</a></p>` : "");
    const retry = el.querySelector("[data-retry]");
    if (retry) retry.addEventListener("click", () => render(el, params, alive));
    return;
  }
  if (!alive()) return;
  const f = remembered[c.id] || (remembered[c.id] = fresh());
  const floor = c.large_acres;

  el.innerHTML = `
    <header class="page-head">
      <p class="kicker">${esc(c.name)}, ${esc(c.region)}</p>
      <h1>Lands in ${esc(c.name)}</h1>
      <p class="lead">Every parcel of ${num(floor)} acres or more on the city's records. Click a row or a shape to pick it out; open it to see the land's own pages.</p>
      ${all.length > 1 ? `<label class="field inline"><span>City</span><select id="cityPick">${all.map((x) => `<option value="${esc(x.id)}"${x.id === c.id ? " selected" : ""}>${esc(x.name)}</option>`).join("")}</select></label>` : ""}
    </header>
    <form class="filters card" id="filters" autocomplete="off">
      <label class="field grow"><span>Find a parcel number (APN)</span>
        <div class="input-icon">${icon("search")}<input type="search" name="q" placeholder="for example 372-100-001" value="${esc(f.q)}"></div></label>
      <div class="field"><span>Size, in acres</span>
        <div class="range"><input type="number" name="min" min="0" step="any" inputmode="decimal" placeholder="${num(floor)}" value="${esc(f.min)}" aria-label="Smallest size in acres">
          <i>to</i><input type="number" name="max" min="0" step="any" inputmode="decimal" placeholder="any" value="${esc(f.max)}" aria-label="Largest size in acres"></div>
        <div class="chips">${[20, 40, 80, 100].map((n) => `<button type="button" data-min="${n}">${n}+</button>`).join("")}</div></div>
      <label class="field"><span>Zoning</span><select name="zoning"><option value="">Any zoning</option></select></label>
      <label class="check"><input type="checkbox" name="vacant"${f.vacant ? " checked" : ""}><span>Only land with no buildings on record</span></label>
    </form>
    <div class="lands-split">
      <section class="lands-list card flush">
        <div class="list-head"><p id="countLine" class="count-line">&nbsp;</p><button type="button" class="btn small" id="clearAll" hidden>Clear filters</button></div>
        <div id="notice"></div>
        <div id="list">${loading("Asking " + c.name + "'s public map service for its large parcels…")}</div>
      </section>
      <section class="lands-map">
        <div class="map-frame"><div id="landsMap" class="map"></div><div id="picked" class="picked" hidden></div></div>
        <div id="mapLegend" class="legend"></div>
        <p class="fine">Shapes are the large parcels in the list, coloured by zoning. Outlines are the assessor's drawings, simplified for this map; they are not a survey. Click the map, then scroll, to zoom.</p>
      </section>
    </div>
    <p class="fine foot" id="sourceLine"></p>`;

  const form = el.querySelector("#filters"), list = el.querySelector("#list"), notice = el.querySelector("#notice");
  const countLine = el.querySelector("#countLine"), picked = el.querySelector("#picked"), sourceLine = el.querySelector("#sourceLine");
  const L = window.L, view = createMap(el.querySelector("#landsMap"), { base: "streets" });
  const drawn = L.layerGroup().addTo(view.map);
  view.fit(L.latLng(c.centre.lat, c.centre.lon).toBounds(16000));
  let shapes = null, data = null, selected = null, ticket = 0, fitted = "", polygons = {}, offSaved = () => {};
  alive.onLeave(() => { offSaved(); view.destroy(); });

  const pick = el.querySelector("#cityPick");
  if (pick) pick.addEventListener("change", () => { location.hash = "#/lands/" + pick.value; });

  // ---- asking the server
  function asked() {
    const [type, value] = f.zoning.split(/:(.*)/);
    return { min_acres: f.min, max_acres: f.max, zoning: type === "zone" ? value : "", kind: type === "kind" ? value : "",
      vacant: f.vacant, q: f.q.trim(), sort: f.sort, dir: f.dir };
  }
  async function load(again = false) {
    const mine = ++ticket;
    list.classList.add("busy");
    try {
      const answer = await api.lands(c.id, { ...asked(), fresh: again });
      if (!alive() || mine !== ticket) return;
      data = answer;
      drawList();
      drawMap();
    } catch (e) {
      if (!alive() || mine !== ticket) return;
      data = null;
      countLine.innerHTML = "&nbsp;";
      notice.innerHTML = "";
      list.innerHTML = problem(e.message);
      list.querySelector("[data-retry]").addEventListener("click", () => { list.innerHTML = loading("Trying again…"); load(true); });
    }
    list.classList.remove("busy");
  }

  // ---- the list
  function saveButton(apn) {
    const on = saved.has(c.id, apn);
    return `<button type="button" class="btn small save${on ? " on" : ""}" data-save="${esc(apn)}" aria-pressed="${on}" title="${on ? "Saved. Click to take it off My lands." : "Keep this parcel in My lands"}">${icon(on ? "check" : "saved")}<span>${on ? "Saved" : "Save to My lands"}</span></button>`;
  }
  function row(p) {
    const where = p.address || (p.subdivision ? "Map " + p.subdivision : "");
    return `<tr data-apn="${esc(p.apn)}"${p.apn === selected ? ' class="selected"' : ""}>
      <td><a class="apn" href="#/land/${esc(c.id)}/${esc(p.apn)}">${esc(apnText(p))}</a>${where ? `<small>${esc(where)}</small>` : ""}</td>
      <td class="num">${num(p.acres, 2)}</td>
      <td><span class="swatch" style="background:${kindColour(c.zoning_kinds, p.zoning_kind)}"></span><b>${esc(p.zoning || "None listed")}</b>${p.zoning_name && p.zoning_name !== p.zoning ? `<small>${esc(p.zoning_name)}</small>` : ""}</td>
      <td>${p.looks_vacant ? "None on record" : "Yes"}</td>
      <td class="num wide-only">${has(p.assessed_land_usd) ? money(p.assessed_land_usd) : '<span class="missing">not covered yet</span>'}</td>
      <td class="actions">${saveButton(p.apn)}</td></tr>`;
  }
  function drawList() {
    fillZoning();
    const filtered = data.count !== data.total;
    countLine.innerHTML = filtered
      ? `<b>${num(data.count)}</b> of ${num(data.total)} large parcels match`
      : `<b>${num(data.total)}</b> large parcels`;
    sourceLine.innerHTML = (data.stale ? `${esc(c.name)}'s map service did not answer just now. Showing the list as it was read ${esc(when(data.fetched))}. `
      : `Read from ${esc(c.sources.parcel || "the city's public records")} ${esc(when(data.fetched))}. `) +
      `“Buildings” is what the county assessor lists, not a site visit. Assessed values are for property tax; they are not market prices. <button class="link" data-again>Read the list again</button>`;
    sourceLine.querySelector("[data-again]").addEventListener("click", () => { list.innerHTML = loading("Reading the list again…"); load(true); });

    notice.innerHTML = "";
    if (data.direct) {
      const p = data.direct;
      notice.innerHTML = `<div class="notice">
        <p><b>${esc(apnText(p))}</b> is ${num(p.acres, 2)} acres, zoned ${esc(p.zoning || "none listed")}. It is smaller than the ${num(floor)} acres this list starts at, so it is shown here on its own.</p>
        <p class="row"><a class="btn small primary" href="#/land/${esc(c.id)}/${esc(p.apn)}">Open this parcel</a> ${saveButton(p.apn)}</p></div>`;
    } else if (data.direct_missing) {
      notice.innerHTML = `<div class="notice warn"><p>No parcel in ${esc(c.name)} has the number <b>${esc(f.q.trim())}</b>. Check the digits; a parcel number has nine, for example 372-100-001.</p></div>`;
    }
    if (!data.count) {
      list.innerHTML = data.direct || data.direct_missing ? "" :
        `<div class="state"><p>No large parcels match these filters.</p><button type="button" class="btn" data-clear>Clear filters</button></div>`;
      const clear = list.querySelector("[data-clear]");
      if (clear) clear.addEventListener("click", clearAll);
      return;
    }
    const head = COLUMNS.map(([key, label]) => {
      const on = f.sort === key;
      return `<th${key === "acres" || key === "land_value" ? ' class="num' + (key === "land_value" ? " wide-only" : "") + '"' : ""} aria-sort="${on ? (f.dir === "asc" ? "ascending" : "descending") : "none"}"><button type="button" class="sort${on ? " on" : ""}" data-sort="${key}" title="Sort by ${label.toLowerCase()}">${label}<i>${on ? (f.dir === "asc" ? "▲" : "▼") : ""}</i></button></th>`;
    }).join("") + "<th></th>";
    list.innerHTML = `<div class="scroll tall"><table class="data lands"><thead><tr>${head}</tr></thead><tbody>${data.parcels.map(row).join("")}</tbody></table></div>`;
  }
  list.addEventListener("click", (e) => {
    const sort = e.target.closest("[data-sort]");
    if (sort) {
      const key = sort.dataset.sort;
      if (f.sort === key) f.dir = f.dir === "asc" ? "desc" : "asc";
      else { f.sort = key; f.dir = key === "apn" || key === "zoning" ? "asc" : "desc"; }
      return load();
    }
    if (e.target.closest("[data-save]") || e.target.closest("a")) return;
    const tr = e.target.closest("tr[data-apn]");
    if (tr) select(tr.dataset.apn, { fromList: true });
  });
  // Save buttons live in the list, the notice and the map's picked bar
  el.addEventListener("click", async (e) => {
    const button = e.target.closest("[data-save]");
    if (!button) return;
    const apn = button.dataset.save, was = saved.has(c.id, apn);
    button.disabled = true;
    try {
      await (was ? saved.remove(c.id, apn) : saved.add(c.id, apn));
      toast(was ? "Taken off My lands." : "Saved to My lands.");
    } catch (err) {
      toast(err.message);
      button.disabled = false;
    }
  });
  offSaved = saved.onChange(() => {
    el.querySelectorAll("[data-save]").forEach((b) => { b.outerHTML = saveButton(b.dataset.save); });
  });

  // ---- the map
  function everyone() { return data ? data.parcels.concat(data.direct ? [data.direct] : []) : []; }
  function style(p, on) {
    return { color: on ? "#1d2a24" : "#33443b", opacity: on ? 1 : 0.65, weight: on ? 3.5 : 1, fillColor: kindColour(c.zoning_kinds, p.zoning_kind), fillOpacity: on ? 0.85 : 0.7 };
  }
  function drawMap() {
    if (!data || !shapes) return;
    drawn.clearLayers();
    polygons = {};
    const kinds = new Set(), bounds = L.latLngBounds([]);
    everyone().forEach((p) => {
      const rings = p.rings || shapes[p.apn];
      if (!rings || !rings.length) return;
      kinds.add(p.zoning_kind);
      const shape = L.polygon(ll(rings), style(p, p.apn === selected))
        .bindTooltip(`${esc(apnText(p))} · ${num(p.acres, 2)} acres · ${esc(p.zoning || "no zoning listed")}`, { sticky: true })
        .on("click", (ev) => { L.DomEvent.stopPropagation(ev); select(p.apn, { fromMap: true }); });
      shape.addTo(drawn);
      polygons[p.apn] = shape;
      bounds.extend(shape.getBounds());
    });
    el.querySelector("#mapLegend").innerHTML = legend(c.zoning_kinds, kinds);
    if (selected && !polygons[selected]) select(null);
    else if (selected) polygons[selected].bringToFront();
    // move the map only when the set of parcels changed, not on a re-sort
    const key = JSON.stringify([f.min, f.max, f.zoning, f.vacant, f.q.trim(), !!data.direct]);
    if (key !== fitted && bounds.isValid()) { fitted = key; view.fit(bounds.pad(0.08), { maxZoom: 16 }); }
  }
  function select(apn, { fromMap = false, fromList = false } = {}) {
    const before = selected;
    selected = apn === before && fromList ? null : apn;
    const find = (a) => everyone().find((p) => p.apn === a);
    if (before && polygons[before] && find(before)) polygons[before].setStyle(style(find(before), false));
    list.querySelectorAll("tr.selected").forEach((tr) => tr.classList.remove("selected"));
    const p = selected && find(selected);
    if (!p) { selected = null; picked.hidden = true; return; }
    const tr = list.querySelector(`tr[data-apn="${p.apn}"]`);
    if (tr) { tr.classList.add("selected"); if (fromMap) tr.scrollIntoView({ block: "nearest" }); }
    if (polygons[p.apn]) {
      polygons[p.apn].setStyle(style(p, true)).bringToFront();
      if (fromList) { view.release(); view.map.flyToBounds(polygons[p.apn].getBounds().pad(1.2), { maxZoom: 16, duration: 0.6 }); }
    }
    picked.hidden = false;
    picked.innerHTML = `<div><b>${esc(apnText(p))}</b><span>${num(p.acres, 2)} acres · ${esc(p.zoning || "no zoning listed")}${p.zoning_name && p.zoning_name !== p.zoning ? " · " + esc(p.zoning_name) : ""}</span></div>
      <div class="picked-actions"><a class="btn small primary" href="#/land/${esc(c.id)}/${esc(p.apn)}">Open ${icon("arrow")}</a>${saveButton(p.apn)}</div>`;
  }
  api.shapes(c.id).then((d) => { if (alive()) { shapes = d.shapes; drawMap(); } })
    .catch(() => { if (alive()) { shapes = {}; el.querySelector("#mapLegend").innerHTML = '<span class="missing">The parcel outlines could not be loaded just now; the list still works.</span>'; } });

  // ---- the filters
  function fillZoning() {
    const select = form.elements.zoning, o = data.zoning_options;
    if (select.options.length > 1) return;
    select.innerHTML = '<option value="">Any zoning</option>' +
      `<optgroup label="By kind of zoning">${o.kinds.map((k) => `<option value="kind:${esc(k.id)}">${esc(k.label)} (${k.count})</option>`).join("")}</optgroup>` +
      `<optgroup label="By zone">${o.zones.map((z) => `<option value="zone:${esc(z.code)}">${esc(z.code)}${z.name && z.name !== z.code ? " – " + esc(z.name) : ""} (${z.count})</option>`).join("")}</optgroup>`;
    select.value = f.zoning;
  }
  function chips() {
    form.querySelectorAll("[data-min]").forEach((b) => b.classList.toggle("on", String(f.min) === b.dataset.min));
    el.querySelector("#clearAll").hidden = !(f.q.trim() || f.min || f.max || f.zoning || f.vacant);
  }
  function read() {
    f.q = form.elements.q.value; f.min = form.elements.min.value; f.max = form.elements.max.value;
    f.zoning = form.elements.zoning.value; f.vacant = form.elements.vacant.checked;
    chips();
  }
  function clearAll() {
    Object.assign(f, fresh(), { sort: f.sort, dir: f.dir });
    form.elements.q.value = ""; form.elements.min.value = ""; form.elements.max.value = "";
    form.elements.zoning.value = ""; form.elements.vacant.checked = false;
    chips();
    load();
  }
  const typed = debounce(() => { read(); load(); }, 280);
  form.addEventListener("input", (e) => { if (e.target.matches("input[type=search],input[type=number]")) typed(); });
  form.addEventListener("change", (e) => { if (e.target.matches("select,input[type=checkbox]")) { read(); load(); } });
  form.addEventListener("submit", (e) => { e.preventDefault(); read(); load(); });
  form.addEventListener("click", (e) => {
    const chip = e.target.closest("[data-min]");
    if (chip) {
      form.elements.min.value = String(f.min) === chip.dataset.min ? "" : chip.dataset.min;
      read(); load();
    }
  });
  const clearButton = el.querySelector("#clearAll");
  clearButton.addEventListener("click", clearAll);
  chips();

  await load();
}

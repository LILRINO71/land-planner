// One land's pages: Overview, Zoning, Surroundings, Terrain 3D, Traffic and Plan.
// Every value on these pages comes from the server's answer for this parcel. Nothing is typed in here: a value
// the public records do not give reads "not covered yet".
import { land as getLand, city as getCity, saved } from "../api.js";
import { createMap, ll, legend, kindColour } from "../maps.js";
import { mountTerrain } from "../terrain3d.js";
import { NONE, esc, has, show, num, money, cap, placeName, when, table, icon, loading, problem, missing, toast, apnText } from "../util.js";

export const PAGES = [
  ["overview", "Overview"], ["zoning", "Zoning"], ["surroundings", "Surroundings"],
  ["terrain", "Terrain 3D"], ["traffic", "Traffic"], ["plan", "Plan"],
];
const PART_NAMES = {
  parcel: "Parcel outline and facts", zoning: "Zoning", general_plan: "General plan", surroundings: "Zoning around the parcel",
  neighbour_shapes: "Neighbouring outlines", state_highway_traffic: "Highway traffic", terrain: "Five spot heights",
  surface: "Ground heights for the 3D view",
};
const STATE_WORDS = { ok: "Yes", "nothing found there": "Answered, with nothing for this spot", "did not answer": "Did not answer just now" };

export async function render(el, params, alive) {
  const page = PAGES.some((p) => p[0] === params.page) ? params.page : "overview";
  el.innerHTML = `<header class="page-head"><p class="kicker">Parcel ${esc(params.apn)}</p><h1>Opening this land…</h1></header>` +
    loading("Gathering this parcel's facts from the public records. The first time takes a few seconds.");
  let c, quick, entry;
  try {
    c = await getCity(params.city);
    entry = getLand(params.city, params.apn);
    quick = await entry.quick;
  } catch (e) {
    if (!alive()) return;
    const gone = e.status === 404;
    el.innerHTML = `<header class="page-head"><p class="kicker">Parcel ${esc(params.apn)}</p><h1>${gone ? "No such land" : "This land could not be opened"}</h1></header>` +
      problem(e.message, gone ? "" : "Try again") + `<p><a class="btn" href="#/lands">Back to Lands</a></p>`;
    const retry = el.querySelector("[data-retry]");
    if (retry) retry.addEventListener("click", () => render(el, params, alive));
    return;
  }
  if (!alive()) return;
  const P = quick.parcel, number = apnText(P);
  document.title = `${number} · ${PAGES.find((p) => p[0] === page)[1]} · Land Planner`;
  document.dispatchEvent(new CustomEvent("land-open", { detail: { city: c.id, apn: P.apn, number, acres: P.acres } }));
  const ctx = { c, P, quick, parts: quick.parts, entry, alive, number, link: (p) => `#/land/${c.id}/${P.apn}/${p}` };

  el.innerHTML = `
    <header class="page-head land-head">
      <p class="kicker"><a href="#/lands/${esc(c.id)}">${esc(c.name)}, ${esc(c.region)}</a></p>
      <div class="head-row">
        <div>
          <h1>${has(P.acres) ? num(P.acres, 2) + " acres" : "Parcel " + esc(number)}</h1>
          <p class="lead">Parcel ${esc(number)} · ${P.address ? esc(P.address) : "no street address listed"}</p>
        </div>
        <div class="head-actions"><span id="saveSlot"></span>
          <button type="button" class="btn" id="again" title="Ask the public records again for this parcel">${icon("refresh")} Read the facts again</button></div>
      </div>
      <nav class="tabs" aria-label="This land's pages">${PAGES.map(([id, label]) =>
        `<a href="${ctx.link(id)}"${id === page ? ' class="on" aria-current="page"' : ""}>${icon(id)}${label}</a>`).join("")}</nav>
    </header>
    ${quick.parcel_stale ? `<div class="notice warn"><p>${esc(c.name)}'s map service did not answer just now. These are the parcel's facts as they were read ${esc(when(quick.parcel_fetched))}.</p></div>` : ""}
    <div id="pageBody" class="page-body"></div>`;

  const slot = el.querySelector("#saveSlot");
  function drawSave() {
    const on = saved.has(c.id, P.apn);
    slot.innerHTML = `<button type="button" class="btn save${on ? " on" : " primary"}" aria-pressed="${on}" title="${on ? "Saved. Click to take it off My lands." : "Keep this parcel in My lands"}">${icon(on ? "check" : "saved")}<span>${on ? "Saved in My lands" : "Save to My lands"}</span></button>`;
    slot.firstChild.addEventListener("click", async (e) => {
      e.currentTarget.disabled = true;
      try {
        await (on ? saved.remove(c.id, P.apn) : saved.add(c.id, P.apn));
        toast(on ? "Taken off My lands." : "Saved to My lands.");
      } catch (err) { toast(err.message); drawSave(); }
    });
  }
  drawSave();
  alive.onLeave(saved.onChange(() => { if (alive()) drawSave(); }));
  el.querySelector("#again").addEventListener("click", () => {
    getLand(c.id, P.apn, { fresh: true });
    window.dispatchEvent(new HashChangeEvent("hashchange"));   // draw this page again from the top
  });

  ({ overview, zoning, surroundings, terrain, traffic, plan })[page](el.querySelector("#pageBody"), ctx);
}

// ---------------------------------------------------------------- shared pieces

function busiest(s) {
  const v = [s.vehicles_per_day_behind, s.vehicles_per_day_ahead].filter(has).map(Number).filter((n) => !isNaN(n));
  if (!v.length) return NONE;
  const lo = Math.min(...v), hi = Math.max(...v);
  return lo === hi ? num(hi) : num(lo) + "–" + num(hi);
}
function sourceNote(ctx, part) {
  const at = ctx.quick.fetched[part];
  return `${esc(ctx.c.sources[part] || "Public records")}${at ? ", read " + esc(when(at)) : ""}`;
}
function unanswered(ctx, part, what) {
  // a part that is empty: either the source did not answer (say so, offer to ask again) or it has nothing here
  const state = ctx.quick.sources[part];
  if (state === "did not answer") {
    return `<div class="state problem">${icon("alert")}<p>${esc(what)}: ${esc(ctx.c.sources[part] || "the source")} did not answer just now.</p><button type="button" class="btn" data-reload>Ask again</button></div>`;
  }
  return missing(`${what}: not covered yet.`);
}
function wireReload(box, ctx) {
  box.querySelectorAll("[data-reload]").forEach((b) => b.addEventListener("click", () => document.getElementById("again").click()));
}

// The ground heights arrive after the page: draw a waiting line, then the real thing (or a plain failure).
function withGround(ctx, box, waiting, draw) {
  box.innerHTML = loading(waiting);
  const ask = (again) => ctx.entry.loadGround(again).then((g) => { if (ctx.alive()) draw(g); }).catch((e) => {
    if (!ctx.alive()) return;
    box.innerHTML = problem(e.message);
    box.querySelector("[data-retry]").addEventListener("click", () => { box.innerHTML = loading(waiting); ask(true); });
  });
  ask(false);
  return (again) => { box.innerHTML = loading(waiting); ask(again); };
}

// A map of the parcel. neighbours: colour the surrounding parcels by zoning. stations: show highway count points.
function siteMap(box, ctx, { neighbours = false, stations = false, base = "aerial", legendBox = null } = {}) {
  const L = window.L, { P, c, parts } = ctx;
  const view = createMap(box, { base });
  ctx.alive.onLeave(view.destroy);
  const shown = new Set();
  if (neighbours) {
    (parts.neighbour_shapes || []).forEach((n) => {
      if (n.apn === P.apn) return;
      const kind = n.zoning_kind || "other";
      shown.add(kind);
      L.polygon(ll(n.rings), { color: "#fff", weight: 0.6, fillColor: kindColour(c.zoning_kinds, kind), fillOpacity: 0.45 })
        .bindTooltip(`${esc(n.zoning)}${n.zoning_name && n.zoning_name !== n.zoning ? " · " + esc(n.zoning_name) : ""}${has(n.acres) ? " · " + num(n.acres, 2) + " acres" : ""}`, { sticky: true })
        .addTo(view.map);
    });
  }
  const rings = ll(P.outline.coordinates);
  L.polygon(rings, { color: "#1d2a24", weight: 7, fill: false, interactive: false }).addTo(view.map);
  const site = L.polygon(rings, { color: "#f2b632", weight: 4, fillColor: "#f2b632", fillOpacity: neighbours ? 0.1 : 0.16 })
    .bindTooltip("This parcel · " + esc(ctx.number), { sticky: true }).addTo(view.map);
  const bounds = site.getBounds().pad(neighbours ? 0.9 : 0.6);
  const traffic = parts.state_highway_traffic;
  if (stations && traffic) {
    traffic.stations.forEach((s, i) => {
      if (!has(s.lat)) return;
      L.circleMarker([s.lat, s.lon], { radius: 8, color: "#fff", weight: 2, fillColor: "#1f4436", fillOpacity: 1 })
        .bindTooltip(`Route ${esc(s.route)} at ${esc(placeName(s.where))}: ${busiest(s)} vehicles a day`).addTo(view.map);
      if (stations === "all" || i === 0) bounds.extend([s.lat, s.lon]);
    });
  }
  view.fit(bounds);
  if (legendBox) {
    legendBox.innerHTML = shown.size ? legend(c.zoning_kinds, shown)
      : neighbours ? `<span class="missing">Neighbouring parcels: ${ctx.quick.sources.neighbour_shapes === "did not answer" ? "the city's map service did not answer just now" : "not covered yet"}.</span>` : "";
  }
  return view;
}
function groundReading(g) {
  // what the ground heights say, as one line for the Overview card
  const inside = g.parts.surface && g.parts.surface.inside, five = g.parts.terrain;
  if (inside && has(inside.typical_slope_pct)) {
    return [cap(inside.reading), `typical slope about ${inside.typical_slope_pct}%; ${num(inside.range_ft)} ft between the lowest and highest ground`];
  }
  if (inside) return [num(inside.range_ft) + " ft", "between the lowest and highest ground inside the outline"];
  if (five) return [cap(five.reading), `about ${five.rough_slope_pct}% across five spot heights only (rough)`];
  return [NONE, g.sources.surface === "did not answer" ? "the elevation service did not answer just now" : "ground heights"];
}

function limitsCard() {
  return `<div class="card"><h2>Limits of these pages</h2>
    <ul class="plain">
      <li>Parcel outlines are the assessor's drawings, <b>not a boundary survey</b>.</li>
      <li>Zoning and the general plan say what is allowed today. <b>Any change goes through the city</b> (general plan amendment, zone change or specific plan, with public hearings).</li>
      <li>The ground view is not a topographic survey and is not for grading design.</li>
      <li>This is a starting point for the owner, the engineer and the city's planners, not a decision.</li>
    </ul></div>`;
}

// ---------------------------------------------------------------- Overview

function overview(box, ctx) {
  const { P, c, parts, quick } = ctx, Z = parts.zoning, traffic = parts.state_highway_traffic, near = traffic && traffic.stations[0];
  box.innerHTML = `
    <section class="stats">
      <a class="stat" href="${ctx.link("overview")}"><span class="label">Size</span><b>${show(P.acres, " acres")}</b>
        <span>${P.size_feet ? "about " + num(P.size_feet.east_west) + " ft east–west by " + num(P.size_feet.north_south) + " ft north–south" : "extent " + NONE}</span></a>
      <a class="stat" href="${ctx.link("zoning")}"><span class="label">Zoning</span><b>${esc(P.zoning || "None listed")}</b>
        <span>${Z ? esc(Z.what_it_allows) : esc(P.zoning_name || NONE)}</span></a>
      <a class="stat" href="${ctx.link("terrain")}" id="groundStat"><span class="label">Ground</span><b class="wait">…</b><span>reading the ground heights</span></a>
      <a class="stat" href="${ctx.link("traffic")}"><span class="label">Nearest state highway</span><b>${near ? busiest(near) : NONE}</b>
        <span>${near ? "vehicles a day on route " + esc(near.route) + " at " + esc(placeName(near.where)) + ", " + near.miles_away + " mi away" : traffic ? "no count point within " + traffic.within_miles + " miles" : "highway traffic"}</span></a>
    </section>
    <section class="two wide-left">
      <div>
        <h2>Where it is</h2>
        <div class="map-frame"><div class="map" id="siteMap"></div></div>
        <p class="fine">Gold outline: this parcel, as the assessor draws it. Dark dot: the nearest Caltrans count point, when it is close enough to show. Click the map, then scroll, to zoom. The background picture needs an internet connection; the outline does not.</p>
      </div>
      <div class="card"><h2>Size and assessor facts</h2>
        <dl class="facts">${[
          ["Parcel number (APN)", esc(ctx.number)], ["Size", show(P.acres, " acres")],
          ["Extent", P.size_feet ? num(P.size_feet.east_west) + " × " + num(P.size_feet.north_south) + " ft (east–west × north–south)" : NONE],
          ["Street address", P.address ? esc(P.address) : "None listed"],
          ["Recorded map", P.subdivision ? esc(P.subdivision) : "None listed"],
          ["Assessor's description", show(P.assessor_class)],
          ["Buildings", P.looks_vacant ? "None on the assessor's records" : "The assessor's records list buildings"],
          ["Assessed land value", money(P.assessed_land_usd)], ["Assessed buildings", money(P.assessed_structures_usd)],
          ["Fire hazard zone", show(cap(P.fire_hazard_zone || ""))], ["Council district", show(P.council_district)],
          ["Centre point", P.centre.lat.toFixed(5) + ", " + P.centre.lon.toFixed(5)],
        ].map((r) => `<dt>${r[0]}</dt><dd>${r[1]}</dd>`).join("")}</dl>
        <p class="fine">Assessed values are for property tax. They are not market prices. ${esc(c.sources.parcel || "Public records")}, read ${esc(when(quick.parcel_fetched))}.</p>
      </div>
    </section>
    <section class="two">
      <div class="card"><h2>Not covered yet</h2><ul class="plain">${c.not_covered.map((m) => `<li>${esc(m)}</li>`).join("")}</ul></div>
      ${limitsCard()}
    </section>
    <section>
      <h2>Where the information comes from</h2>
      <div id="sources"></div>
    </section>`;
  siteMap(box.querySelector("#siteMap"), ctx, { stations: "nearest", base: "aerial" });

  const stat = box.querySelector("#groundStat"), sources = box.querySelector("#sources");
  function drawSources(g) {
    const rows = [["parcel", "ok", quick.parcel_fetched]]
      .concat(Object.keys(quick.sources).map((k) => [k, quick.sources[k], quick.fetched[k]]))
      .concat(g ? Object.keys(g.sources).map((k) => [k, g.sources[k], g.fetched[k]]) : [["terrain", "…", null], ["surface", "…", null]]);
    sources.innerHTML = table(["What", "Source", "Answered", "Read"], rows.map(([part, state, at]) =>
      [esc(PART_NAMES[part] || part), esc(c.sources[part] || "Public records"), esc(state === "…" ? "Asking now…" : STATE_WORDS[state] || state), at ? esc(when(at)) : "–"]));
  }
  drawSources(null);
  ctx.entry.loadGround().then((g) => {
    if (!ctx.alive()) return;
    const [big, small] = groundReading(g);
    stat.innerHTML = `<span class="label">Ground</span><b>${esc(big)}</b><span>${esc(small)}</span>`;
    drawSources(g);
  }).catch(() => {
    if (!ctx.alive()) return;
    stat.innerHTML = `<span class="label">Ground</span><b>${NONE}</b><span>the ground heights could not be read just now; open Terrain 3D to try again</span>`;
  });
}

// ---------------------------------------------------------------- Zoning

function zoning(box, ctx) {
  const { P, c, parts, quick } = ctx, Z = parts.zoning, G = parts.general_plan;
  let html = '<section class="two">';
  html += '<div class="card"><p class="kicker dark">The rulebook today</p>';
  if (Z) {
    html += `<h2>Zoning: ${esc(Z.abbrev || Z.zone)}</h2><p>The city calls this zone <b>${esc(Z.what_it_allows)}</b>. Zoning is the rulebook for what may be built on the land now.</p>
      <p class="fine">${sourceNote(ctx, "zoning")}.</p>`;
  } else html += "<h2>Zoning</h2>" + unanswered(ctx, "zoning", "The zone at this spot") + (P.zoning ? `<p>The parcel record itself lists <b>${esc(P.zoning)}</b> (${esc(P.zoning_name)}).</p>` : "");
  html += '</div><div class="card"><p class="kicker dark">The long-range picture</p>';
  if (G) {
    html += `<h2>General plan: ${esc(G.label || G.land_use)}</h2><p>The city's long-range plan marks this land as <b>${esc(G.description)}</b>${G.specific_plan ? ", inside the " + esc(G.specific_plan) + " specific plan" : ""}. The general plan is the city's picture of what this area should become.</p>
      <p class="fine">${sourceNote(ctx, "general_plan")}.</p>`;
  } else html += "<h2>General plan</h2>" + unanswered(ctx, "general_plan", "The general plan at this spot");
  html += "</div></section>";
  (quick.zoning_notes || []).forEach((n) => {
    html += `<section class="card"><h2>${esc(n.title)}</h2><blockquote>“${esc(n.quote)}”</blockquote>
      <p class="fine">${n.source_url ? `<a href="${esc(n.source_url)}" target="_blank" rel="noopener">${esc(n.source_name)}</a>` : esc(n.source_name)}.</p>
      <p><b>In plain words:</b> ${esc(n.plain)}</p></section>`;
  });
  const split = String(P.zoning || "").includes("&");
  html += `<section class="two">
    <div class="card"><h2>On the parcel record</h2>
      <dl class="facts"><dt>Zoning code</dt><dd>${esc(P.zoning || "None listed")}</dd><dt>In words</dt><dd>${esc(P.zoning_name || NONE)}</dd>
      <dt>General plan code</dt><dd>${show(P.general_plan)}</dd></dl>
      ${split ? '<p class="fine">This parcel carries more than one zone. The “zoning today” above is the zone at the parcel\'s centre point; the other parts of the parcel follow the other zones.</p>' : '<p class="fine">The “zoning today” above is read at the parcel\'s centre point.</p>'}
    </div>
    <div class="card"><h2>What the zone allows, use by use</h2>
      <p class="missing">Which uses are allowed outright, need a permit or are not allowed: not covered yet.</p>
      ${c.links.development_code ? `<p>The rules themselves are in the <a href="${esc(c.links.development_code)}" target="_blank" rel="noopener">city development code</a>.</p>` : ""}
      <p class="fine">Changing what is allowed goes through the city: a general plan amendment, a zone change or a specific plan, each with public hearings.</p>
    </div></section>`;
  box.innerHTML = html;
  wireReload(box, ctx);
}

// ---------------------------------------------------------------- Surroundings

function surroundings(box, ctx) {
  const { c, parts } = ctx, A = parts.surroundings;
  box.innerHTML = `
    <section>
      <h2>What surrounds it</h2>
      <div class="map-frame"><div class="map tall" id="aroundMap"></div></div>
      <div class="legend" id="aroundLegend"></div>
      <p class="fine">Gold outline: this parcel. Coloured shapes: the parcels within ${num(c.site_miles, 1)} mile of its centre, by zoning (point at one to read it). This is zoning, not what is built there today.</p>
    </section>
    <section><h2>Zoning within ${num(c.site_miles, 1)} mile</h2><div id="aroundTable"></div></section>`;
  siteMap(box.querySelector("#aroundMap"), ctx, { neighbours: true, base: "aerial", legendBox: box.querySelector("#aroundLegend") });
  const t = box.querySelector("#aroundTable");
  if (!A) { t.innerHTML = unanswered(ctx, "surroundings", "Zoning around the parcel"); wireReload(t, ctx); return; }
  const listed = A.by_zoning.reduce((sum, r) => sum + r.acres, 0), rest = A.total_acres - listed;
  const rows = A.by_zoning.map((r) => [
    `<span class="swatch" style="background:${kindColour(c.zoning_kinds, r.zoning_kind)}"></span>${esc(r.zoning)}`, esc(r.zoning_name || r.zoning),
    num(r.acres, 1), num(r.parcels), r.share_pct + "%"]);
  if (rest > 0.5) rows.push(["Other", "Smaller zoning groups", num(rest, 1), "–", "–"]);
  t.innerHTML = `<p>Parcels within <b>${num(A.within_miles, 1)} mile</b> of the centre add up to <b>${num(A.total_acres)} acres</b>. By zoning:</p>` +
    table(["Code", "Meaning", "Acres", "Parcels", "Share"], rows) +
    `<p class="fine">Includes this parcel. A parcel the circle only touches is counted whole. Roads and other land outside parcels are not counted. ${sourceNote(ctx, "surroundings")}.</p>`;
}

// ---------------------------------------------------------------- Terrain 3D

function terrain(box, ctx) {
  box.innerHTML = '<div id="ground"></div>';
  const ground = box.querySelector("#ground");
  let unmount = null;
  ctx.alive.onLeave(() => { if (unmount) unmount(); });
  const reload = withGround(ctx, ground, "Reading the ground heights from the U.S. Geological Survey. This is the slowest source: it can take up to a minute.", (g) => {
    const H = g.parts.surface, T = g.parts.terrain, inside = H && H.inside;
    const source = esc(ctx.c.sources.surface || "U.S. Geological Survey");
    let html = "";
    if (inside) {
      html += `<section class="stats">
        <div class="stat"><span class="label">Lowest ground</span><b>${num(inside.low_ft)} ft</b><span>above sea level, inside the outline</span></div>
        <div class="stat"><span class="label">Highest ground</span><b>${num(inside.high_ft)} ft</b><span>above sea level, inside the outline</span></div>
        <div class="stat"><span class="label">Difference</span><b>${num(inside.range_ft)} ft</b><span>between the lowest and highest of ${num(inside.samples_inside)} height samples</span></div>
        <div class="stat"><span class="label">Typical slope</span><b>${has(inside.typical_slope_pct) ? inside.typical_slope_pct + "%" : NONE}</b><span>${has(inside.typical_slope_pct) ? esc(inside.reading) + "; half the ground is flatter than this, half steeper" : "too few samples to say"}</span></div>
      </section>`;
    }
    html += '<section><h2>The shape of the ground</h2>';
    if (H) {
      const known = H.feet.filter((v) => v !== null).length;
      html += `<div class="view3d" id="view3d"></div>
        <p class="fine">Approximate ground surface drawn from ${num(known)} height samples (${source}), one about every ${num(H.spacing_ft)} ft. Ditches, mounds and anything smaller than that can be missed. Heights are stretched so gentle slopes can be seen; set the slider to 1× for true proportions. Gold line: parcel outline. Paler ground: outside the parcel. N: north. Read ${esc(when(g.fetched.surface))}.</p>`;
    } else {
      html += g.sources.surface === "did not answer"
        ? `<div class="state problem">${icon("alert")}<p>The U.S. Geological Survey's elevation service did not answer just now, so the 3D view cannot be drawn. It is often slow; trying again usually works.</p><button type="button" class="btn" data-ground>Ask again</button></div>`
        : missing("3D ground view: not covered yet for this parcel.");
    }
    html += "</section>";
    if (inside) {
      html += `<section class="card"><h2>What the heights say</h2>
        <ul class="plain">
          <li>Inside the outline the ground runs from <b>${num(inside.low_ft)} ft</b> to <b>${num(inside.high_ft)} ft</b> above sea level: a difference of <b>${num(inside.range_ft)} ft</b>. Both points are marked on the 3D view.</li>
          ${has(inside.typical_slope_pct) ? `<li>Between neighbouring samples the typical slope is about <b>${inside.typical_slope_pct}%</b> (${esc(inside.reading)}). The steepest tenth of the ground is over <b>${inside.steepest_tenth_pct}%</b>.</li>` : ""}
          <li>These figures are measured from the samples and are approximate. Small bumps, furrows and plants picked up by the survey count toward the slope figures. This is not a topographic survey and is not for grading design.</li>
        </ul></section>`;
    }
    html += '<section><h2>Five spot heights</h2>';
    if (T) {
      const f = T.feet_above_sea_level;
      html += `<p>A quick first check from five points only: ${T.fall_across_site_ft} ft between the highest and lowest of them, about ${T.rough_slope_pct}% across the parcel (${esc(T.reading)}).${inside && Math.abs(inside.range_ft - T.fall_across_site_ft) >= 3 ? ` The ${num(inside.samples_inside)} samples above find a larger difference (${num(inside.range_ft)} ft) because five points miss the highest and lowest ground.` : ""}</p>` +
        table(["Point", "Feet above sea level"], Object.keys(f).map((k) => [k === "centre" ? "Centre" : cap(k) + "-most point of the outline", num(f[k], 1)]));
    } else {
      html += g.sources.terrain === "did not answer" ? missing("The elevation service did not answer for the five points just now.") : missing();
    }
    html += "</section>";
    ground.innerHTML = html;
    const again = ground.querySelector("[data-ground]");
    if (again) again.addEventListener("click", () => reload(true));
    if (H) unmount = mountTerrain(ground.querySelector("#view3d"), ctx.P, H);
  });
}

// ---------------------------------------------------------------- Traffic

function traffic(box, ctx) {
  const t = ctx.parts.state_highway_traffic, near = t && t.stations[0];
  if (!t) {
    box.innerHTML = `<section><h2>Traffic on the nearest state highways</h2>${unanswered(ctx, "state_highway_traffic", "Highway traffic")}</section>`;
    wireReload(box, ctx);
    return;
  }
  if (!near) {
    box.innerHTML = `<section><h2>Traffic on the nearest state highways</h2><p>No state highway count point within ${num(t.within_miles)} miles of this parcel.</p>
      <p class="missing">Traffic on city streets: not covered yet.</p></section>`;
    return;
  }
  box.innerHTML = `
    <section class="stats">
      <div class="stat"><span class="label">Nearest count point</span><b>Route ${esc(near.route)}</b><span>at ${esc(placeName(near.where))}, ${near.miles_away} mi from the parcel's centre in a straight line</span></div>
      <div class="stat"><span class="label">Vehicles a day there</span><b>${busiest(near)}</b><span>the two stretches of highway either side of the count point</span></div>
      <div class="stat"><span class="label">Busiest hour</span><b>${num(near.peak_hour_ahead)}</b><span>vehicles in the peak hour, on the stretch just past the count point</span></div>
      <div class="stat"><span class="label">City streets</span><b class="small">${cap(NONE)}</b><span>only state highways are counted here; the city publishes its own street counts</span></div>
    </section>
    <section>
      <h2>Count points near the parcel</h2>
      <div class="map-frame"><div class="map" id="trafficMap"></div></div>
      <p class="fine">Gold outline: this parcel. Dark dots: Caltrans count points within ${num(t.within_miles)} miles (point at one to read it).</p>
    </section>
    <section>
      <h2>The counts</h2>
      ${table(["Count point", "Miles away", "Vehicles a day, before the point", "Vehicles a day, past the point", "Peak hour, past the point"],
        t.stations.map((s) => ["Route " + esc(s.route) + " at " + esc(placeName(s.where)), num(s.miles_away, 2), num(s.vehicles_per_day_behind), num(s.vehicles_per_day_ahead), num(s.peak_hour_ahead)]))}
      <p class="fine">Caltrans annual average daily traffic: the average over a year, both directions together. Caltrans counts the stretch of highway on each side of a count point separately (“back” and “ahead” in its tables). Distances are straight lines from the parcel's centre, not driving distances. ${sourceNote(ctx, "state_highway_traffic")}.</p>
    </section>`;
  siteMap(box.querySelector("#trafficMap"), ctx, { stations: "all", base: "streets" });
}

// ---------------------------------------------------------------- Plan (placeholder)

function plan(box, ctx) {
  const { P, parts } = ctx, near = parts.state_highway_traffic && parts.state_highway_traffic.stations[0];
  box.innerHTML = `
    <section class="card placeholder">
      <p class="tag">Not built yet</p>
      <h2>The land-use plan comes next</h2>
      <p>This page is a placeholder. <b>No plan has been drawn for this land, and nothing here is a proposal.</b></p>
      <p>The next step for Land Planner is a first split of the land into uses, from rules a planner would recognise: shops want traffic and a corner, homes want quiet edges, and every plan needs roads, parks and drainage. Each piece will be shown with its reason and its acres, and every piece will be adjustable by hand.</p>
    </section>
    <section class="two">
      <div class="card"><h2>What the plan will start from</h2>
        <p>The facts already on this land's other pages:</p>
        <dl class="facts">
          <dt>Size</dt><dd><a href="${ctx.link("overview")}">${show(P.acres, " acres")}</a></dd>
          <dt>Zoning today</dt><dd><a href="${ctx.link("zoning")}">${esc(P.zoning || "None listed")}</a></dd>
          <dt>Around it</dt><dd><a href="${ctx.link("surroundings")}">${parts.surroundings ? num(parts.surroundings.total_acres) + " acres of parcels within " + num(parts.surroundings.within_miles, 1) + " mile, by zoning" : cap(NONE)}</a></dd>
          <dt>Ground</dt><dd><a href="${ctx.link("terrain")}" id="planGround">see Terrain 3D</a></dd>
          <dt>Nearest highway traffic</dt><dd><a href="${ctx.link("traffic")}">${near ? busiest(near) + " vehicles a day, " + near.miles_away + " mi away" : cap(NONE)}</a></dd>
        </dl>
      </div>
      <div class="card"><h2>What it will still need</h2>
        <ul class="plain">
          <li>The owner's own numbers for costs and prices.</li>
          <li>Traffic on the city streets beside the land, utilities, flood zones and other limits on what can be built: not covered yet.</li>
          <li>The city. Zoning and the general plan say what is allowed today; any change goes through the city.</li>
        </ul>
        <p class="fine">Whatever the plan page suggests will be a starting point for the owner, the engineer and the city's planners, not a decision.</p>
      </div>
    </section>`;
}

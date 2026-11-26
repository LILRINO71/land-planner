// The Plan page of one land: a first suggestion of how to divide it into uses, drawn on the land, with the reasons,
// who builds that kind of project nearby, traffic, costs, money, and every figure it rests on (all editable).
// Every value shown comes from the server's plan answer. A value the answer does not give reads "not covered yet".
import { createMap, ll } from "../maps.js";
import { ApiError } from "../api.js";
import { mountTerrain } from "../terrain3d.js";
import { balance, readCostSheet, applyCostSheet, costSheet, money as readNumber } from "../planmath.js";
import { NONE, esc, has, num, cap, table, icon, loading, problem, missing, toast, debounce } from "../util.js";

// ---------------------------------------------------------------- talking to the server (as api.js does)

async function call(method, path, body) {
  let response;
  try {
    response = await fetch(path, {
      method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    throw new ApiError("Land Planner is not running. Start it again with “Start Land Planner”, then reload this page.", "stopped", 0);
  }
  let data = null;
  try { data = await response.json(); } catch (e) { /* handled below */ }
  if (!response.ok || !data) {
    const err = data && data.error;
    throw new ApiError((err && err.message) || "Something went wrong. Try again.", (err && err.code) || "unknown", response.status);
  }
  return data;
}

// ---------------------------------------------------------------- words and numbers

const ac = (v) => num(v, 1);
const usd = (v) => (has(v) && !isNaN(Number(v)) ? (Number(v) < 0 ? "-$" + num(-Number(v)) : "$" + num(v)) : NONE);
const colourOf = (c) => (/^#[0-9a-f]{3,8}$/i.test(String(c || "")) ? c : "#9aa0a6");
const clone = (o) => JSON.parse(JSON.stringify(o));
const LOW = { retail: "shops", office: "offices", apartments: "apartments", homes: "houses", business: "business park", park: "parks" };
const FIT_CLASS = { fits: "fits", review: "review", change: "change", unknown: "unknown" };
const KIND_WORDS = { measured: "Measured here", assumption: "Starting figure", yours: "Your figure" };
const SIGNAL_WORDS = { existing: "Uses a signal that is already there", study: "A new signal is worth studying", none: "No signal likely needed",
  unknown: "Not known whether a signal already stands there" };
// the letter on each entrance marker, so the colour is never the only signal
const SIGNAL_MARK = { existing: "S", study: "N", none: "E", unknown: "?" };

// "$/acre" as "per acre"; other units as they are
function per(unit) {
  const u = String(unit || "");
  const words = { "$/acre": "per acre", "$/ft": "per foot", "$ each": "each", "$/lot": "per house lot", "$/apartment": "per apartment",
    "$/sq ft": "per sq ft", "$": "", "ratio": "of the land area", "%": "%" };
  return u in words ? words[u] : u;
}
const isMoneyUnit = (unit) => String(unit || "").startsWith("$");
function inputValue(v, unit) {
  if (!has(v) || isNaN(Number(v))) return "";
  return isMoneyUnit(unit) ? Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 }) : String(Number(Number(v).toFixed(4)));
}
// "2025-08-04" as "Aug 4, 2025", read as a calendar day
function day(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ""));
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "";
}
function listWords(items) {
  if (items.length <= 1) return items.join("");
  return items.slice(0, -1).join(", ") + " and " + items[items.length - 1];
}
function amountWords(u) {
  if (!u.acres) return "none in this mix";
  if (u.id === "homes") return `${num(u.homes)} houses, about ${num(u.people)} people`;
  if (u.id === "apartments") return `${num(u.homes)} apartments, about ${num(u.people)} people`;
  if (has(u.sq_ft)) return `${num(u.sq_ft)} sq ft of floor space, about ${num(u.jobs)} jobs`;
  if (u.id === "park") return "parks, open space and drainage basins";
  return "";
}
function fitChip(u) {
  return `<span class="chip plan-fit plan-fit-${FIT_CLASS[u.fit] || "unknown"}">${esc(u.fit_words || NONE)}</span>`;
}
function effect(e) {
  const n = Number(e) || 0;
  if (n > 0) return `<span class="plan-eff plus" aria-label="adds ${n} points">+${n}</span>`;
  if (n < 0) return `<span class="plan-eff minus" aria-label="takes away ${-n} points">−${-n}</span>`;
  return '<span class="plan-eff zero" aria-label="no points either way">0</span>';
}

// ---------------------------------------------------------------- the page

export function plan(box, ctx) {
  const { P } = ctx;
  const base = `/api/cities/${encodeURIComponent(ctx.c.id)}/lands/${encodeURIComponent(P.apn)}/plan`;
  let data = null, settings = null, mixAcres = null, seq = 0, touched = false;
  let ground = null, groundProblem = "", show3d = false, mapView = null, layers = null, fitted = false, unmount3d = null, shown3dKey = "";
  let sheetRead = null;
  ctx.alive.onLeave(() => {
    if (mapView) mapView.destroy();
    if (unmount3d) unmount3d();
    mapView = null; unmount3d = null;
  });

  function first() {
    box.innerHTML = loading("Working out a plan for this land from its public records…");
    call("GET", base).then((answer) => {
      if (!ctx.alive()) return;
      take(answer);
      build();
    }).catch((e) => {
      if (!ctx.alive()) return;
      box.innerHTML = problem(e.message);
      box.querySelector("[data-retry]").addEventListener("click", first);
    });
  }
  function take(answer) {
    data = answer;
    settings = clone(answer.settings || { mode: "zoning", acres: null, assumptions: {}, extra_costs: [], land_cost: null });
    settings.assumptions = settings.assumptions || {};
    settings.extra_costs = settings.extra_costs || [];
    mixAcres = Object.fromEntries(data.uses.map((u) => [u.id, Number(u.acres) || 0]));
  }

  // ---------------------------------------------------------------- asking again

  const status = (html, kind = "") => {
    const el = box.querySelector("#planStatus");
    if (el) { el.className = "plan-status " + kind; el.innerHTML = html; }
  };
  // every change bumps seq at once, so an answer already on its way for older settings is ignored
  function changed() { touched = true; seq++; status("Waiting for you to finish typing…", "busy"); later(); }
  const later = debounce(() => send(), 400);
  function send(method = "POST") {
    const my = ++seq;
    status(method === "DELETE" ? "Going back to the suggestion…" : "Working out the plan with your change…", "busy");
    const asking = method === "GET" ? call("GET", base) : method === "DELETE" ? call("DELETE", base) : call("POST", base, settings);
    asking.then((answer) => {
      if (!ctx.alive() || my !== seq) return;
      take(answer);
      drawAll();
      status(answer.kept ? "Your changes are kept on this computer." : "This is the suggested plan.", "ok");
    }).catch((e) => {
      if (!ctx.alive() || my !== seq) return;
      status(`${esc(e.message)} <button type="button" class="btn small" data-again>Try again</button>`, "bad");
      const again = box.querySelector("[data-again]");
      if (again) again.addEventListener("click", () => send(method));
    });
  }
  // the ground heights arrived after the plan: ask for the plan again (with the person's changes, if any)
  function refresh() { send(touched ? "POST" : "GET"); }

  function watchGround(again) {
    groundProblem = "";
    ctx.entry.loadGround(again).then((g) => {
      if (!ctx.alive()) return;
      ground = g;
      if (data && !data.ground_read) refresh();
      else { drawGroundNote(); if (show3d) draw3d(true); }
    }).catch((e) => {
      if (!ctx.alive()) return;
      groundProblem = e.message;
      drawGroundNote();
      if (show3d) draw3d(true);
    });
  }

  // ---------------------------------------------------------------- the frame (drawn once)

  function build() {
    box.innerHTML = `
      <div class="plan">
        <header class="plan-head">
          <div class="plan-headline" id="planHeadline"></div>
          <div class="plan-actions">
            <div class="plan-switch" role="group" aria-label="What the plan follows">
              <button type="button" data-mode="zoning">Follow today's zoning</button>
              <button type="button" data-mode="best">Best use (may need a zoning change)</button>
            </div>
            <button type="button" class="btn" id="planBack" title="Forget your changes to this plan (sizes, figures, costs and land price) and show the suggestion again">${icon("refresh")} Back to the suggestion</button>
            <button type="button" class="btn" id="planPrint">Print</button>
          </div>
          <p class="plan-status" id="planStatus" role="status" aria-live="polite"></p>
        </header>
        <div id="planGround"></div>
        <div id="planAdvice"></div>
        <section class="stats plan-stats" id="planStats" aria-label="The plan in numbers"></section>

        <div class="plan-top">
          <section class="plan-view">
            <div class="plan-view-head">
              <h2>The plan on the land</h2>
              <div class="plan-switch small" role="group" aria-label="How to show the plan">
                <button type="button" data-show="map">Map</button><button type="button" data-show="3d">3D</button>
              </div>
            </div>
            <div id="planMapBox"><div class="map-frame"><div class="map tall" id="planMap"></div></div><div class="legend" id="planLegend"></div></div>
            <div id="plan3d" hidden></div>
            <div id="planLaid"></div>
          </section>
          <section class="card plan-mix" id="planMix" aria-labelledby="mixTitle"></section>
        </div>

        <section id="planWhy"></section>
        <section id="planBuyers"></section>
        <div class="plan-three">
          <section id="planTraffic"></section>
          <section id="planMarket"></section>
          <section id="planEconomy"></section>
        </div>
        <div class="plan-money">
          <section id="planCosts"></section>
          <section id="planMoney"></section>
        </div>
        <section id="planFigures"></section>
        <section id="planLimits"></section>
      </div>`;

    box.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => {
      if (settings.mode === b.dataset.mode) return;
      settings.mode = b.dataset.mode;
      settings.acres = null;              // the new choice starts from its own suggested sizes; figures and costs stay
      touched = true;
      send();
    }));
    box.querySelector("#planBack").addEventListener("click", () => { touched = false; send("DELETE"); });
    box.querySelector("#planPrint").addEventListener("click", () => window.print());
    box.querySelectorAll("[data-show]").forEach((b) => b.addEventListener("click", () => {
      show3d = b.dataset.show === "3d";
      try { localStorage.setItem("plan-show", show3d ? "3d" : "map"); } catch (e) { /* only a convenience */ }
      drawShow();
    }));
    try { show3d = localStorage.getItem("plan-show") === "3d"; } catch (e) { show3d = false; }

    // one listener for every edit box on the page; each says what it changes in data-k
    box.addEventListener("input", onInput);
    box.addEventListener("change", onChange);
    box.addEventListener("click", onClick);

    const L = window.L;
    mapView = createMap(box.querySelector("#planMap"), { base: "aerial" });
    layers = L.layerGroup().addTo(mapView.map);
    drawAll();
    drawShow();
    if (data.kept) status("Your earlier changes to this plan are kept on this computer.", "ok");
    watchGround(false);
  }

  // ---------------------------------------------------------------- drawing everything, keeping the person's place

  function drawAll() {
    const active = document.activeElement;
    const key = active && box.contains(active) && active.dataset ? active.dataset.k : null;
    let typed = null, from = null, to = null;
    if (key && "value" in active) {
      typed = active.value;
      try { from = active.selectionStart; to = active.selectionEnd; } catch (e) { from = to = null; }
    }
    // open "Show the reasons" and import panels stay open
    const open = new Set([...box.querySelectorAll("details[data-open-k]")].filter((d) => d.open).map((d) => d.dataset.openK));
    drawHead(); drawGroundNote(); drawAdvice(); drawStats(); drawMapLayers(); drawLaid(); drawMix();
    drawWhy(); drawBuyers(); drawTraffic(); drawMarket(); drawEconomy(); drawCosts(); drawMoney(); drawFigures(); drawLimits();
    box.querySelectorAll("details[data-open-k]").forEach((d) => { if (open.has(d.dataset.openK)) d.open = true; });
    if (show3d) draw3d(false);
    if (key) {
      const again = box.querySelector(`[data-k="${CSS.escape(key)}"]`);
      if (again && again !== active) {
        if (typed !== null && again.type !== "range" && again.type !== "file") again.value = typed;
        again.focus({ preventScroll: true });
        if (from !== null && again.setSelectionRange && again.type === "text") { try { again.setSelectionRange(from, to); } catch (e) { /* not a text box */ } }
      }
    }
  }

  const built = () => data.uses.filter((u) => u.id !== "park" && u.acres > 0);
  const nothing = () => built().length === 0;

  function drawHead() {
    const parts = data.uses.filter((u) => u.acres > 0).sort((a, b) => b.acres - a.acres);
    let sentence;
    if (nothing()) {
      sentence = data.nothing_to_build && !data.edited && settings.mode === "zoning"
        ? `Under today's zoning there is nothing to build on these ${ac(data.acres)} acres: all of it stays parks and open space.`
        : `This mix has no buildings: all ${ac(data.acres)} acres are parks and open space.`;
    } else {
      const words = parts.map((u, i) => `${ac(u.acres)}${i ? "" : " acres"} of ${LOW[u.id] || esc(u.label).toLowerCase()}`);
      sentence = `${data.edited ? "Your mix" : "Suggested"} for these ${ac(data.acres)} acres: ${listWords(words)}.`;
    }
    box.querySelector("#planHeadline").innerHTML = `<p class="kicker dark">${settings.mode === "best" ? "Best use for the location, today's zoning left aside" : "Following today's zoning"}${data.facts && data.facts.zoning ? " · zoned " + esc(data.facts.zoning) + (data.facts.zoning_name && data.facts.zoning_name !== data.facts.zoning ? " (" + esc(data.facts.zoning_name) + ")" : "") : ""}</p>
      <h2 class="plan-sentence">${sentence}</h2>`;
    box.querySelectorAll("[data-mode]").forEach((b) => { const on = b.dataset.mode === settings.mode; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); });
    box.querySelector("#planBack").hidden = !(data.kept || data.edited);
  }

  function drawGroundNote() {
    const el = box.querySelector("#planGround");
    if (!el || !data) return;
    if (data.ground_read) { el.innerHTML = ""; return; }
    if (ground && !groundProblem) {
      el.innerHTML = `<p class="fine">The ground heights have been read, but this plan was worked out without them. Reload the page to use them.</p>`;
      return;
    }
    if (groundProblem) {
      el.innerHTML = `<div class="notice warn"><div class="row"><p>The ground heights could not be read just now (${esc(groundProblem)}), so this plan is worked out without them. <button type="button" class="btn small" data-ground-again>Try again</button></p></div></div>`;
      el.querySelector("[data-ground-again]").addEventListener("click", () => { el.innerHTML = notice(); watchGround(true); });
    } else el.innerHTML = notice();
    function notice() {
      return `<p class="plan-wait"><span class="spinner" aria-hidden="true"></span> The ground heights are still being read. Scores, where parks go and the cost of shaping the ground will update when they arrive.</p>`;
    }
  }

  function drawAdvice() {
    const items = (data.advice || []).map((a) => `<div class="notice plan-advice"><p>${esc(a)}</p></div>`);
    box.querySelector("#planAdvice").innerHTML = items.join("");
  }

  function drawStats() {
    const e = data.economy || {}, t = data.traffic || {}, m = data.money || {};
    const houses = (data.uses.find((u) => u.id === "homes") || {}).homes || 0, flats = (data.uses.find((u) => u.id === "apartments") || {}).homes || 0;
    const stat = (label, big, small) => `<div class="stat"><span class="label">${label}</span><b>${big}</b><span>${small}</span></div>`;
    box.querySelector("#planStats").innerHTML = [
      stat("Homes", num(e.homes), `${num(houses)} houses and ${num(flats)} apartments`),
      stat("Floor space", has(e.floor_space_sq_ft) ? num(e.floor_space_sq_ft) + " sq ft" : NONE, "for shops, offices and the business park"),
      stat("Jobs", num(e.jobs), "in the shops, offices and business park, by rule of thumb"),
      stat("Trips a day", num(t.per_day), `about ${num(t.peak_hour)} in the busiest hour`),
      stat("Land sales", usd(m.revenue), "at the starting prices: replace them with real quotes"),
      stat("Profit", usd(m.profit), has(m.margin_pct) ? `${num(m.margin_pct, 1)}% of sales, before interest, sales costs and taxes` : "before interest, sales costs and taxes"),
    ].join("");
  }

  // ---------------------------------------------------------------- the map

  function drawMapLayers() {
    const L = window.L;
    if (!layers || !L) return;
    layers.clearLayers();
    const colours = Object.fromEntries(data.uses.map((u) => [u.id, colourOf(u.colour)]));
    const names = Object.fromEntries(data.uses.map((u) => [u.id, u]));
    (data.street_lines || []).forEach((s) => {
      if (!s.path || s.path.length < 2) return;
      const line = s.path.map((p) => [p[1], p[0]]), weight = 1.5 + 1.4 * (Number(s.rank) || 1);
      L.polyline(line, { color: "#1d2a24", weight: weight + 3, opacity: 0.55, interactive: false }).addTo(layers);
      L.polyline(line, { color: "#8fc3ff", weight, opacity: 0.95 })
        .bindTooltip(`${esc(s.name)}: ${esc(s.class)} (the city's planned street network)`, { sticky: true }).addTo(layers);
    });
    const outline = ll(P.outline.coordinates);
    L.polygon(outline, { color: "#1d2a24", weight: 6, fill: false, interactive: false }).addTo(layers);
    const site = L.polygon(outline, { color: "#f2b632", weight: 3, fill: false, interactive: false }).addTo(layers);
    const d = data.drawing;
    if (d) {
      d.pieces.forEach((p) => {
        const u = names[p.use] || { label: p.use, short: p.use };
        L.polygon(ll([p.ring]), { color: "#fff", weight: 2, opacity: 0.95, fillColor: colours[p.use], fillOpacity: 0.5 })
          .bindTooltip(`${esc(u.label)}: ${ac(p.acres)} acres`, { sticky: true }).addTo(layers);
        if (p.label_at) {
          L.marker([p.label_at[1], p.label_at[0]], {
            icon: L.divIcon({ className: "plan-label", iconSize: [0, 0], html: `<span><b>${esc(u.short)}</b> ${ac(p.acres)} ac</span>` }),
            interactive: false, keyboard: false,
          }).addTo(layers);
        }
      });
      d.streets.forEach((s) => {
        const line = s.line.map((p) => [p[1], p[0]]);
        L.polyline(line, { color: "#1d2a24", weight: 9, opacity: 0.5, interactive: false }).addTo(layers);
        L.polyline(line, { color: "#ffffff", weight: 5, opacity: 1 })
          .bindTooltip(`A main street this plan draws inside the land, about ${num(s.feet)} ft long`, { sticky: true }).addTo(layers);
      });
    }
    const t = data.traffic || {};
    (t.existing_signals || []).forEach((s) => {
      if (!has(s.lat)) return;
      L.circleMarker([s.lat, s.lon], { radius: 5, color: "#fff", weight: 2, fillColor: "#1d2a24", fillOpacity: 1 })
        .bindTooltip(`Traffic signal today at ${esc(s.street)} and ${esc(s.cross_street)}, ${num(s.miles_away, 2)} mi away`).addTo(layers);
    });
    const hw = t.highway;
    if (hw && has(hw.lat)) {
      L.circleMarker([hw.lat, hw.lon], { radius: 8, color: "#fff", weight: 2, fillColor: "#1f4436", fillOpacity: 1 })
        .bindTooltip(`Route ${esc(hw.route)} at ${esc(hw.where)}: about ${num(hw.per_day)} vehicles a day (state count point, ${num(hw.miles, 2)} mi away)`).addTo(layers);
    }
    (t.entrances || []).forEach((e) => {
      if (!has(e.lat)) return;
      const kind = SIGNAL_MARK[e.signal] ? e.signal : "none";
      L.marker([e.lat, e.lon], {
        icon: L.divIcon({ className: "plan-pin", iconSize: [26, 26], iconAnchor: [13, 13], html: `<span class="plan-ent plan-ent-${kind}">${SIGNAL_MARK[kind]}</span>` }),
        title: `Entrance onto ${e.street}: ${SIGNAL_WORDS[kind]}`, alt: `Entrance onto ${e.street}`,
      }).bindTooltip(`<b>Entrance onto ${esc(e.street)}</b> (${esc(e.class)}): about ${num(e.trips)} trips a day. ${esc(e.text)}`).addTo(layers);
    });
    if (!fitted && mapView) { mapView.fit(site.getBounds().pad(0.25)); fitted = true; }

    const shownUses = data.uses.filter((u) => u.acres > 0);
    box.querySelector("#planLegend").innerHTML =
      shownUses.map((u) => `<span><i style="background:${colourOf(u.colour)}"></i>${esc(u.short)}</span>`).join("") +
      `<span><i class="plan-key-road"></i>Streets this plan draws</span>
       <span><i class="plan-key-city"></i>The city's planned streets (thicker: bigger street)</span>
       <span><b class="plan-ent plan-ent-existing small">S</b>Entrance at a signal already there</span>
       <span><b class="plan-ent plan-ent-study small">N</b>Entrance where a new signal is worth studying</span>
       <span><b class="plan-ent plan-ent-none small">E</b>Entrance, no signal likely</span>
       ${(t.entrances || []).some((e) => e.signal === "unknown") ? '<span><b class="plan-ent plan-ent-unknown small">?</b>Entrance; not known whether a signal stands there</span>' : ""}
       <span><i class="plan-key-dot"></i>Traffic signal today</span>
       <span><i class="plan-key-dot hw"></i>State highway count point</span>`;
  }

  function drawLaid() {
    const d = data.drawing, el = box.querySelector("#planLaid");
    if (!d) { el.innerHTML = missing("The plan could not be drawn on this parcel's outline, so the map shows the outline only."); return; }
    const gap = has(d.drawn_acres) && Math.abs(d.drawn_acres - data.acres) > Math.max(1, data.acres * 0.05);
    el.innerHTML = `<div class="card soft plan-laid"><h3>Why it is laid out this way</h3>
      <ul class="plain">${(d.why || []).map((w) => `<li>${esc(w)}</li>`).join("")}</ul>
      ${d.note ? `<p>${esc(d.note)}</p>` : ""}
      ${gap ? `<p class="notice warn">The outline on the map covers about <b>${ac(d.drawn_acres)} acres</b>, but the parcel record says <b>${ac(data.acres)} acres</b>. The plan's numbers use the record; the drawing can only use the outline. Check the parcel's real boundary.</p>` : ""}
      <p class="fine">The pieces are a first sketch of where each use could go, cut from the assessor's outline. They are not lot lines and not a site plan.</p></div>`;
  }

  // ---------------------------------------------------------------- the 3D view

  function drawShow() {
    box.querySelectorAll("[data-show]").forEach((b) => { const on = (b.dataset.show === "3d") === show3d; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); });
    box.querySelector("#planMapBox").hidden = show3d;
    box.querySelector("#plan3d").hidden = !show3d;
    if (show3d) draw3d(false);
  }
  function draw3d(force) {
    const el = box.querySelector("#plan3d"), d = data.drawing;
    const H = ground && ground.parts && ground.parts.surface;
    const key = JSON.stringify([!!H, groundProblem, d && d.pieces, d && d.streets, data.uses.map((u) => [u.homes, u.sq_ft])]);
    if (!force && key === shown3dKey && el.firstChild) return;
    shown3dKey = key;
    let keep = null;
    if (unmount3d) { keep = unmount3d.getView ? unmount3d.getView() : null; unmount3d(); unmount3d = null; }
    if (!d) { el.innerHTML = missing("The plan could not be drawn on this parcel's outline, so there is no 3D view of it."); return; }
    if (!H) {
      if (groundProblem) {
        el.innerHTML = problem("The ground heights could not be read just now, so the 3D view cannot be drawn. " + groundProblem);
        el.querySelector("[data-retry]").addEventListener("click", () => { el.innerHTML = loading("Reading the ground heights…"); watchGround(true); });
      } else if (!ground) el.innerHTML = loading("The ground heights are still being read. The 3D view appears when they arrive (up to a minute).");
      else el.innerHTML = missing("3D view: the ground heights are not covered yet for this parcel.");
      return;
    }
    el.innerHTML = `<div class="view3d plan-3d" id="plan3dView"></div>
      <p class="fine">The ground in the plan's colours, the streets this plan draws as light lines, and simple boxes for buildings: about as many and as large as the plan's figures make, standing on the ground. The boxes are <b>a picture of scale, not a site plan</b>; trees mark the parks. Only the ground's height is stretched by the slider; the buildings keep their true height. At most about 1,500 boxes are drawn, so a large housing area shows its houses spaced further apart than they would be.</p>`;
    const colours = Object.fromEntries(data.uses.map((u) => [u.id, colourOf(u.colour)]));
    const amounts = Object.fromEntries(data.uses.map((u) => [u.id, { homes: u.homes, sq_ft: u.sq_ft }]));
    unmount3d = mountTerrain(el.querySelector("#plan3dView"), P, H, {
      pieces: d.pieces, streets: d.streets.map((s) => s.line), colours, front: d.front, amounts, cap: 1500, view: keep,
    });
  }

  // ---------------------------------------------------------------- the mix

  function drawMix() {
    const el = box.querySelector("#planMix");
    const rows = el.querySelectorAll(".plan-row");
    const same = rows.length === data.uses.length && data.uses.every((u, i) => rows[i].dataset.use === u.id);
    if (!same) {
      el.innerHTML = `<h2 id="mixTitle">The mix</h2>
        <p class="fine plan-mix-help">Move a slider or type acres. The other uses give up or take the difference in proportion, so the total stays ${ac(data.acres)} acres.</p>
        <div class="plan-rows">${data.uses.map((u) => `
          <div class="plan-row" data-use="${esc(u.id)}">
            <div class="plan-row-top"><span class="swatch" style="background:${colourOf(u.colour)}"></span><label for="planAc-${esc(u.id)}"><b>${esc(u.label)}</b></label><span class="plan-fit-slot"></span></div>
            <div class="plan-row-ctl">
              <input type="range" min="0" max="${Number(data.acres) || 0}" step="0.1" data-k="slide:${esc(u.id)}" aria-label="Acres of ${esc(u.label.toLowerCase())}">
              <span class="plan-acre"><input id="planAc-${esc(u.id)}" class="plan-num" type="text" inputmode="decimal" autocomplete="off" data-k="ac:${esc(u.id)}"> acres</span>
              <span class="plan-share"></span>
            </div>
            <div class="plan-row-sub"><span class="plan-what"></span><span class="plan-sugg"></span></div>
          </div>`).join("")}</div>
        <div class="plan-mix-foot"><span id="planTotal"></span><button type="button" class="btn small" id="planSuggested">Use the suggested sizes</button></div>
        <div id="planNotes"></div>`;
    }
    updateMix(true);
    const notes = data.notes || [];
    el.querySelector("#planNotes").innerHTML = notes.length ? `<ul class="plain plan-notes">${notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : "";
    el.querySelector("#planSuggested").hidden = !settings.acres;
  }
  // put the current acres in the rows; the box or slider the person is using is left alone
  function updateMix(fromAnswer) {
    const el = box.querySelector("#planMix"), active = document.activeElement, total = Number(data.acres) || 0;
    const left = new Map((data.left_out || []).map((x) => [x.use, x]));
    data.uses.forEach((u) => {
      const row = el.querySelector(`.plan-row[data-use="${CSS.escape(u.id)}"]`);
      if (!row) return;
      const a = mixAcres[u.id] || 0;
      const slide = row.querySelector('input[type="range"]'), text = row.querySelector(".plan-num");
      if (slide !== active) slide.value = String(a);
      if (text !== active) text.value = ac(a);
      row.querySelector(".plan-share").textContent = total ? num(100 * a / total, 1) + "%" : "";
      row.classList.toggle("zero", a === 0);
      if (fromAnswer) {
        row.querySelector(".plan-fit-slot").innerHTML = fitChip(u);
        row.querySelector(".plan-what").textContent = amountWords(u);
      } else if (Math.abs(a - u.acres) >= 0.05) row.querySelector(".plan-what").textContent = "working it out…";
      const lo = left.get(u.id);
      const sugg = lo ? `Left out of the suggestion (score ${num(lo.score)}). You can raise it.`
        : Math.abs(a - (u.suggested_acres || 0)) >= 0.05 ? `Suggested: ${ac(u.suggested_acres)} acres` : "";
      row.querySelector(".plan-sugg").textContent = sugg;
    });
    const sum = Object.values(mixAcres).reduce((t, v) => t + v, 0);
    el.querySelector("#planTotal").textContent = `Total: ${ac(sum)} of ${ac(total)} acres`;
  }
  function setAcres(use, value) {
    mixAcres = balance(mixAcres, use, value, Number(data.acres) || 0, data.uses.map((u) => u.id), "park");
    settings.acres = { ...mixAcres };
    updateMix(false);
    changed();
  }

  // ---------------------------------------------------------------- why

  function drawWhy() {
    const kept = data.uses.filter((u) => u.acres > 0).sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
    const out = data.uses.filter((u) => !(u.acres > 0));
    const reasons = (u) => `<ul class="plan-reasons">${u.reasons.map((r) => `<li>${effect(r.effect)}<span>${esc(r.text)} <span class="plan-src">${esc(r.source)}</span></span></li>`).join("")}</ul>`;
    const bar = (u) => has(u.score)
      ? `<div class="plan-score"><div class="plan-bar" role="img" aria-label="Score ${num(u.score)} out of 100"><i style="width:${Math.max(0, Math.min(100, Number(u.score)))}%;background:${colourOf(u.colour)}"></i></div><b>${num(u.score)}</b><span>out of 100</span></div>`
      : `<p class="fine">Not scored: its size comes from the parks and drainage rules under the mix.</p>`;
    box.querySelector("#planWhy").innerHTML = `<h2>Why</h2>
      <p class="plan-lead">Each use gets a score out of 100 from the facts of this land. Each fact adds or takes away points; the source of each fact is in the small tag.${settings.mode === "best" ? " In Best use the zoning is left out of the score, so the zoning line counts 0." : ""}</p>
      <div class="plan-cards">${kept.map((u) => `
        <article class="card plan-why">
          <h3><span class="swatch" style="background:${colourOf(u.colour)}"></span>${esc(u.label)} <span class="plan-acres">${ac(u.acres)} acres</span></h3>
          ${bar(u)} ${fitChip(u)}
          ${u.reasons.length ? reasons(u) : ""}
        </article>`).join("")}
        ${out.map((u) => `
        <article class="card plan-why plan-left">
          <h3><span class="swatch" style="background:${colourOf(u.colour)}"></span>${esc(u.label)} <span class="plan-acres">left out</span></h3>
          <p>Score ${has(u.score) ? num(u.score) + " out of 100" : NONE} · ${esc(u.fit_words || NONE)}.${(data.left_out || []).some((x) => x.use === u.id) ? " Too low a score, or too little room, to make the suggestion." : ""}</p>
          ${u.reasons.length ? `<details data-open-k="why:${esc(u.id)}"><summary>Show the reasons</summary>${reasons(u)}</details>` : ""}
        </article>`).join("")}
      </div>`;
  }

  // ---------------------------------------------------------------- who might buy

  function listsLine() {
    const lu = (data.market || {}).lists_updated || {};
    const names = Object.keys(lu);
    return names.length ? "The city's lists used: " + names.map((n) => `${esc(n)} (updated ${esc(day(lu[n]) || lu[n])})`).join("; ") + "." : "When the city's lists were last updated: " + NONE + ".";
  }
  function drawBuyers() {
    const el = box.querySelector("#planBuyers");
    if (nothing()) { el.innerHTML = `<h2>Who might buy each piece</h2><p class="missing">Nothing to sell in this mix, so no buyers are listed.</p>`; return; }
    const names = Object.fromEntries(data.uses.map((u) => [u.id, u]));
    const buyers = data.buyers || [];
    el.innerHTML = `<h2>Who might buy each piece</h2>
      <div class="notice"><p>These are companies the city's own project lists show <b>building this kind of project near here</b>. It is not a statement that any of them wants this land. ${listsLine()}</p></div>
      ${buyers.length ? `<div class="plan-buyers">${buyers.map((b) => {
        const u = names[b.use] || { label: b.use, colour: "" };
        return `<article class="card plan-buyer">
          <h3><span class="swatch" style="background:${colourOf(u.colour)}"></span>${esc(u.label)}</h3>
          <p>${esc(b.who)}</p>
          <p class="plan-chips">${b.named.length ? b.named.map((n) => `<span class="chip">${esc(n)}</span>`).join("") : '<span class="missing">No builder is named on the city\'s lists for this kind of project nearby.</span>'}</p>
          ${b.projects.length ? table(["Project", "Builder", "Status", "Miles away", "What it is"], b.projects.map((p) => [
            `<b>${esc(p.title)}</b>${p.number ? `<small>${esc(p.number)} · ${esc(p.list || "")}</small>` : ""}`,
            p.builder ? esc(p.builder) : '<span class="missing">not named</span>', esc(p.status || NONE), num(p.miles_away, 2), `<small class="plan-desc">${esc(p.description || "")}</small>`]))
            : missing("No projects of this kind on the city's lists nearby.")}
        </article>`;
      }).join("")}</div>` : missing("No buyers found on the city's lists: not covered yet.")}`;
  }

  // ---------------------------------------------------------------- traffic, market, economy

  function drawTraffic() {
    const el = box.querySelector("#planTraffic"), t = data.traffic || {};
    if (nothing()) { el.innerHTML = `<h2>Traffic</h2><p class="missing">No buildings in this mix, so no new trips.</p>`; return; }
    const names = Object.fromEntries(data.uses.map((u) => [u.id, u]));
    const uses = Object.keys(t.by_use || {}), most = Math.max(1, ...uses.map((u) => t.by_use[u]));
    el.innerHTML = `<h2>Traffic</h2><div class="card">
      <p>About <b>${num(t.per_day)} trips a day</b> in and out, and about <b>${num(t.peak_hour)}</b> in the busiest hour.</p>
      ${uses.length ? table(["Use", "Trips a day", ""], uses.map((u) => [esc((names[u] || {}).label || u), num(t.by_use[u]),
        `<span class="plan-tbar" aria-hidden="true"><i style="width:${(100 * t.by_use[u] / most).toFixed(1)}%;background:${colourOf((names[u] || {}).colour)}"></i></span>`])) : ""}
      <h3 class="plan-sub">Entrances</h3>
      ${(t.entrances || []).length ? `<ul class="plan-ents">${t.entrances.map((e) => {
        const kind = SIGNAL_MARK[e.signal] ? e.signal : "none";
        return `<li><b class="plan-ent plan-ent-${kind} small" aria-hidden="true">${SIGNAL_MARK[kind]}</b><span><b>${esc(e.street)}</b> (${esc(e.class)}), about ${num(e.trips)} trips a day. <b>${SIGNAL_WORDS[kind]}.</b> ${esc(e.text)}</span></li>`;
      }).join("")}</ul>` : missing("Where the entrances go: not covered yet (see the note below).")}
      <h3 class="plan-sub">Traffic signals today, nearest first</h3>
      ${(t.existing_signals || []).length ? table(["Where", "Miles away"], t.existing_signals.map((s) => [`${esc(s.street)} and ${esc(s.cross_street)}`, num(s.miles_away, 2)])) : missing("Traffic signals nearby: not covered yet.")}
      ${(t.notes || []).length ? `<ul class="plain plan-notes">${t.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
      <p class="fine">Trips come from the trip rates under “Every figure”, which are starting figures. They are not a traffic study.</p></div>`;
  }

  function drawMarket() {
    const el = box.querySelector("#planMarket"), m = data.market || {}, pl = m.pipeline || {};
    el.innerHTML = `<h2>The market around it</h2><div class="card">
      <h3 class="plan-sub">People and homes nearby <span class="plan-tag measured">2020 Census</span></h3>
      ${m.people ? table(["Within", "People", "Homes"], m.people.map((r) => [`${num(r.miles)} mile${Number(r.miles) === 1 ? "" : "s"}`, num(r.people), num(r.homes)])) : missing("The census count of people nearby: not covered yet.")}
      <h3 class="plan-sub">Already on the city's lists within ${num(pl.within_miles, 1)} miles <span class="plan-tag measured">City project lists</span></h3>
      ${has(pl.projects) ? `<dl class="facts">
        <dt>Projects</dt><dd>${num(pl.projects)}</dd>
        <dt>Housing projects</dt><dd>${num(pl.housing_projects)}, with ${num(pl.homes_stated)} homes stated</dd>
        <dt>Shops and offices projects</dt><dd>${num(pl.commercial_projects)}</dd>
        <dt>Industrial projects</dt><dd>${num(pl.industrial_projects)}</dd>
        <dt>Building space stated</dt><dd>${num(pl.building_sq_ft_stated)} sq ft (shops, offices and industry)</dd></dl>` : missing()}
      <h3 class="plan-sub">Schools nearby</h3>
      ${(m.schools || []).length ? table(["School", "Grades", "Public or private", "Miles away"], m.schools.map((s) => [esc(s.name), esc(s.grades), esc(s.kind), num(s.miles_away, 2)])) : missing("Schools nearby: not covered yet.")}
      <p class="fine">${listsLine()}</p></div>`;
  }

  function drawEconomy() {
    const e = data.economy || {};
    const rows = [
      ["New residents", num(e.residents)], ["Homes", num(e.homes)], ["Jobs", num(e.jobs)],
      ["Floor space for shops and jobs", has(e.floor_space_sq_ft) ? num(e.floor_space_sq_ft) + " sq ft" : NONE],
      ["Value once built", usd(e.built_value)], ["Property tax a year", usd(e.property_tax_year)],
      ["Shop sales a year", usd(e.retail_sales_year)], ["The city's share of sales tax a year", usd(e.city_sales_tax_year)],
    ];
    box.querySelector("#planEconomy").innerHTML = `<h2>Jobs, people and taxes</h2><div class="card">
      <dl class="facts plan-econ">${rows.map((r) => `<dt>${r[0]}</dt><dd>${r[1]}</dd>`).join("")}</dl>
      <p class="fine">Worked out from the plan's homes and floor space with the starting figures under “Jobs and taxes” in “Every figure”. Change them there.</p></div>`;
  }

  // ---------------------------------------------------------------- costs and money

  const figure = (id) => (data.figures || []).find((f) => f.id === id);
  function figureBox(id, k, label, { wide = false } = {}) {
    const f = figure(id);
    if (!f) return NONE;
    const unit = per(f.unit);
    return `<span class="plan-in${wide ? " wide" : ""}">${isMoneyUnit(f.unit) ? "<i>$</i>" : ""}<input class="plan-num" type="text" inputmode="decimal" autocomplete="off" data-k="${esc(k)}" data-fig="${esc(id)}" value="${esc(inputValue(f.value, f.unit))}" aria-label="${esc(label || f.label)}${unit ? ", " + esc(unit) : ""}">${unit ? `<i>${esc(unit)}</i>` : ""}</span>`;
  }

  function drawCosts() {
    const el = box.querySelector("#planCosts"), c = data.costs || {};
    if (nothing()) { el.innerHTML = `<h2>Costs</h2><p class="missing">Nothing is built in this mix, so there are no costs to work out.</p>`; return; }
    const rows = (c.lines || []).map((l) => [
      esc(l.label), figureBox(l.id, "cost:" + l.id, l.label),
      `${num(l.quantity, 1)} ${esc(l.quantity_unit)}<small>${esc(l.quantity_from)}</small>`, usd(l.amount)]);
    rows.push(["<b>Before the allowance</b>", "", "", `<b>${usd(c.subtotal)}</b>`]);
    rows.push(["Allowance for surprises", figureBox("contingency_pct", "cost:contingency_pct", "Allowance for surprises, percent of costs"), "", usd(c.contingency)]);
    rows.push(["City and agency fees", figureBox("fees_total", "cost:fees_total", "City and agency fees, in dollars"), '<small>not covered yet: type your figure</small>', usd(c.fees)]);
    (settings.extra_costs || []).forEach((x, i) => rows.push([`${esc(x.name)} <small>added by you</small>`, "", "",
      `${usd(x.amount)} <button type="button" class="btn small plan-x" data-remove-extra="${i}" aria-label="Remove ${esc(x.name)}">Remove</button>`]));
    rows.push(["<b>Total costs</b>", "", "", `<b>${usd(c.total)}</b>`]);
    el.innerHTML = `<h2>Costs</h2><div class="card">
      <p class="plan-calc"><b>Starting figures, not quotes.</b> Every cost per unit is a common planning figure. Replace them with your engineer's and contractors' numbers.</p>
      ${table(["What", "Cost per unit", "How much", "Amount"], rows)}
      <form class="plan-add" id="planAddExtra">
        <label class="field"><span>Another cost</span><input type="text" name="name" maxlength="80" placeholder="For example: soil report" data-k="extra-name"></label>
        <label class="field"><span>Amount ($)</span><input type="text" name="amount" inputmode="decimal" placeholder="45,000" data-k="extra-amount"></label>
        <button type="submit" class="btn">${icon("plus")} Add</button>
      </form>
      <h3 class="plan-sub">Not counted</h3>
      <ul class="plain">${(c.not_counted || []).map((n) => `<li>${esc(n)}</li>`).join("")}</ul>
      <details class="plan-import" data-open-k="import" ${sheetRead ? "open" : ""}><summary>Import costs from a file, or download this cost sheet</summary>
        <p>Each row is <b>a name, then an amount</b>. A header row and $ and , signs are fine. A row named exactly like a cost or figure on this page (for example “Drainage basins” or <code>cost_basin_per_acre</code>) sets that figure; any other row becomes a cost line of its own.</p>
        <div class="plan-import-row">
          <label class="field"><span>Pick a .csv file</span><input type="file" accept=".csv,text/csv,text/plain" id="planFile" data-k="file"></label>
          <button type="button" class="btn" id="planDownload">Download this cost sheet</button>
        </div>
        <label class="field"><span>Or paste the rows here</span><textarea id="planPaste" rows="5" data-k="paste" placeholder="Soil report, $45,000&#10;Drainage basins, 175000"></textarea></label>
        <p><button type="button" class="btn" id="planReadPaste">Read the pasted rows</button></p>
        <div id="planSheet">${sheetHtml()}</div>
      </details></div>`;
  }
  function sheetHtml() {
    const r = sheetRead;
    if (!r) return "";
    const total = r.figures.length + r.extra.length;
    return `<div class="notice">
      <p>Read <b>${num(r.rows)}</b> row${r.rows === 1 ? "" : "s"}${r.header ? " (and a header row)" : ""}: <b>${num(r.figures.length)}</b> set a figure, <b>${num(r.extra.length)}</b> become cost lines, <b>${num(r.skipped.length)}</b> skipped.</p>
      ${r.figures.length ? `<p>Figures: ${r.figures.map((f) => `${esc(f.label)} = ${esc(num(f.value, 2))}`).join("; ")}.</p>` : ""}
      ${r.extra.length ? `<p>New cost lines: ${r.extra.map((x) => `${esc(x.name)} ${usd(x.amount)}`).join("; ")}.</p>` : ""}
      ${r.skipped.length ? `<p>Skipped: ${r.skipped.map((s) => `row ${s.row} (“${esc(s.text)}”): ${esc(s.why)}`).join("; ")}.</p>` : ""}
      <div class="row">${total ? '<button type="button" class="btn primary" id="planApply">Apply these</button>' : ""}<button type="button" class="btn" id="planCancelSheet">Cancel</button></div></div>`;
  }
  function readSheet(text) {
    sheetRead = readCostSheet(text, data.figures || []);
    const el = box.querySelector("#planSheet");
    if (el) el.innerHTML = sheetHtml();
  }

  function drawMoney() {
    const el = box.querySelector("#planMoney"), m = data.money || {};
    if (nothing()) { el.innerHTML = `<h2>Money</h2><p class="missing">Nothing to sell in this mix, so there are no sales or profit to work out.</p>`; return; }
    const names = Object.fromEntries(data.uses.map((u) => [u.id, u]));
    const priced = m.priced || [];
    const rows = priced.map((p) => [
      `<span class="swatch" style="background:${colourOf((names[p.use] || {}).colour)}"></span>${esc((names[p.use] || {}).label || p.use)}`,
      figureBox(p.figure, "price:" + p.figure, (figure(p.figure) || {}).label),
      `${num(p.quantity, p.quantity_unit === "acres" ? 1 : 0)} ${esc(p.quantity_unit)}`, usd(p.amount)]);
    const landBox = `<span class="plan-in wide"><i>$</i><input class="plan-num" type="text" inputmode="decimal" autocomplete="off" data-k="land" value="${esc(has(settings.land_cost) ? inputValue(settings.land_cost, "$") : "")}" placeholder="type what the land costs" aria-label="What the land cost, in dollars"></span>`;
    const stand = m.land_is_stand_in
      ? (has(m.assessed_land)
        ? `<p class="notice warn">Until you type the real price, the county's <b>assessed value (${usd(m.assessed_land)})</b> stands in for what the land cost. The assessed value is for property tax; it is not a market price.</p>`
        : `<p class="notice warn">The county's assessed value is not covered yet for this parcel, so the land counts as $0 until you type its price.</p>`)
      : "";
    el.innerHTML = `<h2>Money</h2><div class="card">
      <p class="plan-calc"><b>This is a calculator, not an appraisal.</b> The sale prices are starting figures to replace with real quotes from brokers and builders. The answer is only as good as the prices and costs in it.</p>
      ${priced.length ? table(["Piece", "Sale price", "How many", "Sales"], rows) : missing("Sales: not covered yet.")}
      <dl class="facts plan-sum">
        <dt>Total sales</dt><dd>${usd(m.revenue)}</dd>
        <dt>Costs</dt><dd>${usd(m.costs)} <small>(from Costs)</small></dd>
        <dt><label for="planLand">What the land cost</label></dt><dd>${landBox.replace('data-k="land"', 'id="planLand" data-k="land"')} <small>counted as ${usd(m.land)}</small></dd>
        <dt>Profit</dt><dd class="plan-profit">${usd(m.profit)}</dd>
        <dt>Profit per acre</dt><dd>${usd(m.per_acre)}</dd>
        <dt>Margin</dt><dd>${has(m.margin_pct) ? num(m.margin_pct, 1) + "% of sales" : NONE}</dd>
      </dl>
      ${stand}
      <p class="fine">Houses are priced per approved house lot and apartments per apartment the land is approved for; other land per acre. Profit is before interest, sales costs and taxes.</p></div>`;
  }

  // ---------------------------------------------------------------- every figure

  function drawFigures() {
    const groups = [];
    (data.figures || []).forEach((f) => {
      let g = groups.find((x) => x.name === f.group);
      if (!g) { g = { name: f.group, items: [] }; groups.push(g); }
      g.items.push(f);
    });
    box.querySelector("#planFigures").innerHTML = `<h2>Every figure this plan rests on</h2>
      <p class="plan-lead">Change any of them and the whole plan is worked out again. <span class="plan-tag measured">Measured here</span> figures come from this land's own records; <span class="plan-tag assumption">Starting figure</span> is a common planning figure to replace; <span class="plan-tag yours">Your figure</span> is one you typed.</p>
      <div class="plan-fig-groups">${groups.map((g) => `
        <article class="card plan-fig-group"><h3>${esc(g.name)}</h3>
          <div class="plan-figs">${g.items.map((f) => {
            const changedFig = Math.abs(Number(f.value) - Number(f.start)) > 1e-9;
            return `<div class="plan-fig">
              <div class="plan-fig-top"><label for="planFig-${esc(f.id)}">${esc(f.label)}</label><span class="plan-tag ${esc(f.kind)}">${esc(KIND_WORDS[f.kind] || f.kind)}</span></div>
              <div class="plan-fig-ctl">${figureBox(f.id, "fig:" + f.id, f.label).replace("<input ", `<input id="planFig-${esc(f.id)}" `)}
                ${changedFig ? `<button type="button" class="btn small" data-reset="${esc(f.id)}" data-k="reset:${esc(f.id)}" aria-label="Back to the starting figure for ${esc(f.label)}">Back to ${esc(inputValue(f.start, f.unit))}</button>` : ""}</div>
              <p class="fine">${esc(f.basis)}</p>
            </div>`;
          }).join("")}</div>
        </article>`).join("")}</div>`;
  }

  function drawLimits() {
    const missingFacts = (data.facts || {}).missing || [];
    box.querySelector("#planLimits").innerHTML = `<div class="card plan-limits"><h2>Limits of this plan</h2>
      <ul class="plain">
        <li>This is a <b>first suggestion</b> worked out from public records and rules of thumb. It is not the city's decision, not an appraisal and not a traffic study.</li>
        ${missingFacts.length ? `<li>Records that did not answer, so the rules that need them were skipped: <b>${esc(listWords(missingFacts))}</b>.</li>` : ""}
        <li>Not covered yet: water, sewer and power capacity, flood zones, protected plants and animals, and soil.</li>
        <li>Your changes to this plan are kept on this computer in <span class="path">${esc(data.kept_in || NONE)}</span>.</li>
      </ul></div>`;
  }

  // ---------------------------------------------------------------- what the person does

  function setFigure(id, text, el) {
    const f = figure(id);
    const v = readNumber(text);
    const bad = v === null || v < 0 || v > 1e10;
    el.setAttribute("aria-invalid", String(bad));
    if (bad) { status("That is not a number this figure can take. Type a number of zero or more.", "bad"); return; }
    if (f && Math.abs(v - Number(f.start)) < 1e-9) delete settings.assumptions[id]; else settings.assumptions[id] = v;
    changed();
  }
  function onInput(e) {
    const el = e.target, k = el.dataset ? el.dataset.k || "" : "";
    if (k.startsWith("slide:")) { setAcres(k.slice(6), Number(el.value)); return; }
    if (k.startsWith("ac:")) {
      const v = readNumber(el.value);
      el.setAttribute("aria-invalid", String(v === null || v < 0));
      if (v === null || v < 0) return;
      setAcres(k.slice(3), v);
      return;
    }
    if (el.dataset.fig) { setFigure(el.dataset.fig, el.value, el); return; }
    if (k === "land") {
      const t = el.value.trim(), v = t ? readNumber(t) : null;
      const bad = t !== "" && (v === null || v < 0);
      el.setAttribute("aria-invalid", String(bad));
      if (bad) return;
      settings.land_cost = v;
      changed();
    }
  }
  function onChange(e) {
    const el = e.target, k = el.dataset ? el.dataset.k || "" : "";
    if (k.startsWith("ac:")) el.value = ac(mixAcres[k.slice(3)] || 0);   // tidy the box once the person leaves it
    if (k === "file" && el.files && el.files[0]) {
      const file = el.files[0];
      if (file.size > 2e6) { toast("That file is larger than a cost sheet should be (over 2 MB)."); return; }
      file.text().then((text) => { if (ctx.alive()) readSheet(text); }).catch(() => toast("That file could not be read."));
    }
  }
  function onClick(e) {
    const t = e.target.closest ? e.target.closest("button") : null;
    if (!t || !box.contains(t)) return;
    if (t.dataset.reset) { delete settings.assumptions[t.dataset.reset]; touched = true; send(); return; }
    if (t.dataset.removeExtra !== undefined) {
      settings.extra_costs.splice(Number(t.dataset.removeExtra), 1); touched = true; send(); return;
    }
    if (t.id === "planSuggested") { settings.acres = null; touched = true; send(); return; }
    if (t.id === "planReadPaste") { readSheet(box.querySelector("#planPaste").value); return; }
    if (t.id === "planCancelSheet") { sheetRead = null; box.querySelector("#planSheet").innerHTML = ""; return; }
    if (t.id === "planApply" && sheetRead) {
      const read = sheetRead;
      settings = applyCostSheet(settings, read);
      sheetRead = null;
      touched = true;
      toast(`Applied ${read.figures.length} figure${read.figures.length === 1 ? "" : "s"} and ${read.extra.length} cost line${read.extra.length === 1 ? "" : "s"}.`);
      send();
      return;
    }
    if (t.id === "planDownload") {
      const csv = costSheet(data.costs, data.figures || []);
      const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
      const a = document.createElement("a");
      a.href = url; a.download = `cost-sheet-${P.apn}.csv`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  }
  box.addEventListener("submit", (e) => {
    if (e.target.id !== "planAddExtra") return;
    e.preventDefault();
    const form = e.target, name = form.elements.name.value.trim(), amount = readNumber(form.elements.amount.value);
    if (!name || amount === null) { toast(!name ? "Give the cost a name." : "Type the amount as a number."); return; }
    settings.extra_costs.push({ name: name.slice(0, 80), amount });
    touched = true;
    send();
  });

  first();
}

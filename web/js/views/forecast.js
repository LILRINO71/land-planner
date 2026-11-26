// The Forecast page: year by year for the next ten years (the first five in focus, last year as background), the
// people, homes, income areas, shops, jobs and traffic around a site, and how fast the site's own land could be
// taken up. A site is one parcel, or several parcels treated as one. Address: #/forecast/<city>/<apn+apn+...>
// Every value shown comes from the server's forecast answer. A value the answer does not give reads "not covered yet".
import { createMap, ll } from "../maps.js";
import { api } from "../api.js";
import { PAGES, FORECAST_ICON } from "./land.js";
import { money as readNumber } from "../planmath.js";
import { mountTerrain } from "../terrain3d.js";
import { NONE, esc, has, num, plural, cap, icon, loading, problem, missing, debounce, dateOnly, when, noAnswer, whyNoAnswer } from "../util.js";
import { chapters, fold, watchFolds, watchMotion, printEverything, drawIn, countUp, motionOn } from "../calm.js";

// ---------------------------------------------------------------- words and numbers

const colourOf = (c) => (/^#[0-9a-f]{3,8}$/i.test(String(c || "")) ? c : "#9aa0a6");
const isNum = (v) => has(v) && !isNaN(Number(v));
const mi = (m) => `${num(m)} ${Number(m) === 1 ? "mile" : "miles"}`;
function range(o, d = 0) {
  if (!o || !isNum(o.low) || !isNum(o.high)) return NONE;
  return Number(o.low) === Number(o.high) ? num(o.low, d) : `${num(o.low, d)} to ${num(o.high, d)}`;
}
function amount(v, unit) {
  if (!isNum(v)) return NONE;
  if (unit === "$") return "$" + num(v);
  return num(v) + (unit ? " " + esc(unit) : "");
}
// What to say of the sources that are not simply answering: which did not answer, which answered in a form the app could not read,
// and which are shown from the copy read earlier. "" when every one of them is answering.
function stateSentences(names, answered, wordOf) {
  const said = (state, tail) => {
    const hit = names.filter((p) => answered[p] === state).map(wordOf);
    return hit.length ? `${cap(listWords(hit))} ${tail}.` : "";
  };
  return [said("did not answer", "did not answer just now"), said("could not be read", "answered in a form this app could not read"),
    said("older copy", "did not answer just now, so the copy read earlier is used")].filter(Boolean).join(" ");
}
function listWords(items) {
  if (items.length <= 1) return items.join("");
  return items.slice(0, -1).join(", ") + " and " + items[items.length - 1];
}
// "2023-09-14" as "Sep 14, 2023", read as a calendar day
function day(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ""));
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : dateOnly(iso);
}
// what each part the forecast reads is called on screen (the parts are the server's FORECAST_PARTS)
const PART_WORDS = {
  people: "the 2020 Census", people_before: "the 2010 Census", regional_plan: "the regional plan (SCAG)",
  tracts: "the census survey", projects: "the city's project lists", state_highway_traffic: "Caltrans' highway counts",
};
const PARTS_FOR = {
  rings: ["people", "people_before", "regional_plan"], income: ["tracts"], homes: ["people", "people_before", "regional_plan", "projects"],
  shops: ["people", "people_before", "regional_plan", "tracts", "projects"], jobs: ["regional_plan", "projects"],
  traffic: ["state_highway_traffic", "people", "people_before", "regional_plan"], projects: ["projects"],
};
// which of the owner's figures each part of the page rests on (the figures' own groups)
const GROUPS_FOR = {
  homes: ["Projects on the city's list"], shops: ["Shops", "Projects on the city's list"], jobs: ["Jobs", "Projects on the city's list"],
  traffic: ["Traffic", "The site"], programme: ["The site"],
};
// the page's chapters, one on screen at a time (print shows them all, in the order of the page)
const CHAPTERS = [["summary", "Summary"], ["market", "People and market"], ["site", "This site"], ["city", "The city around it"],
  ["todo", "What needs to be done"], ["figures", "Figures and sources"]];
// the findings shown on the Summary before "Show the other findings"
const FIRST_FINDINGS = 4;
// the outlook's sources: [name on screen, what it gives]
const OUTLOOK_WORDS = {
  population: ["State population estimates", "People and homes in the city, by year"], permits: ["Building permits (Census Bureau)", "Homes permitted, by year"],
  sales: ["State taxable sales", "Shop and restaurant sales, by year"], work: ["State employment figures", "Unemployment and people working"],
  borrowing: ["Freddie Mac home-loan survey", "The 30-year home-loan rate"], prices: ["Consumer prices (Bureau of Labor Statistics)", "How much prices rose"],
  climate: ["NASA weather grids", "Weather since 1985"], hazards: ["Hazard maps (FEMA, state, city)", "Flood, fire, faults, ground, water, habitat"],
  nearby: ["City and federal place lists", "Parks, stops, stations, schools, hospitals"], residents: ["Census survey", "Who lives nearby"],
  housing: ["State housing department progress reports", "The city's state housing target, and permits toward it"],
};
// an entrance by the signal it would use: a letter on the marker as well as a colour (as on the Plan page)
const SIGNAL_MARK = { existing: "S", study: "N", none: "E", unknown: "?" };
const SIGNAL_WORDS = { existing: "Uses a signal that is already there", study: "A new signal is worth studying", none: "No signal likely needed",
  unknown: "Not known whether a signal already stands there" };
// hazard levels: words and a mark, never colour alone
const LEVELS = { clear: { words: "Clear", mark: "✓" }, note: { words: "Know about it", mark: "!" }, work: { words: "Adds work", mark: "+" } };
// kinds of nearby places: a letter and a shape each, so the map does not rely on colour
const PLACE_KINDS = {
  park: { letter: "P", shape: "round", colour: "#2f8a57", words: "Parks", one: "park" },
  "transit stop": { letter: "B", shape: "square", colour: "#2a6fb0", words: "Bus and transit stops", one: "bus stop" },
  "fire station": { letter: "F", shape: "diamond", colour: "#c0392b", words: "Fire stations", one: "fire station" },
  police: { letter: "PD", shape: "square", colour: "#22313f", words: "Police", one: "police station" },
  hospital: { letter: "H", shape: "round", colour: "#b0306b", words: "Hospitals", one: "hospital" },
  library: { letter: "L", shape: "round", colour: "#6d4c9f", words: "Libraries", one: "library" },
  college: { letter: "C", shape: "square", colour: "#1f6f8b", words: "Colleges", one: "college" },
  school: { letter: "K", shape: "round", colour: "#a5641a", words: "Schools", one: "school" },
};
const KIND_ORDER = Object.keys(PLACE_KINDS);
const TODO_KINDS = [["city", "With the city", "meetings and applications"], ["study", "Studies", "reports by specialists"],
  ["check", "Checks", "letters and confirmations"], ["sell", "Offering the land", "to builders, as the forecast supports"]];

// ---------------------------------------------------------------- charts (inline SVG, drawn at the width of their box)

function niceStep(span, count) {
  const raw = span / Math.max(1, count), mag = Math.pow(10, Math.floor(Math.log10(raw || 1))), r = raw / mag;
  return (r <= 1 ? 1 : r <= 2 ? 2 : r <= 2.5 ? 2.5 : r <= 5 ? 5 : 10) * mag;
}
function axis(values, count, zero) {
  const v = values.filter(isNum).map(Number);
  let lo = v.length ? Math.min(...v) : 0, hi = v.length ? Math.max(...v) : 1;
  if (zero) { lo = Math.min(0, lo); hi = hi * 1.04; } else { const pad = (hi - lo) * 0.08 || Math.abs(hi) * 0.05 || 1; lo = Math.max(0, lo - pad); hi += pad; }
  if (!(hi > lo)) hi = lo + 1;
  const step = niceStep(hi - lo, count);
  const a = Math.floor(lo / step + 1e-9) * step, b = Math.ceil(hi / step - 1e-9) * step;
  const list = [];
  for (let t = a; t <= b + step / 2; t += step) list.push(Math.round(t / step) * step);
  return { lo: a, hi: b, list, digits: step < 1 ? 2 : step % 1 ? 1 : 0 };
}
const pathOf = (pts) => pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join("");

// o: { width, height, xMin, xMax, values, zero, unit, label, draw(s), hover: [{x, text}] }
function chart(o) {
  const W = Math.max(260, Math.round(o.width || 600)), H = o.height || 260;
  const t = axis(o.values, H >= 240 ? 5 : 4, o.zero);
  const labels = t.list.map((v) => num(v, t.digits));
  const left = 12 + Math.max(...labels.map((s) => s.length)) * 7.1, right = 12, top = 24, bottom = 26;
  const pw = Math.max(40, W - left - right), ph = H - top - bottom, n = o.xMax - o.xMin + 1, slot = pw / n;
  const x = (v) => left + (v - o.xMin + 0.5) * slot;
  const y = (v) => top + ph - (Number(v) - t.lo) / (t.hi - t.lo) * ph;
  const s = { x, y, slot, top, bottom: top + ph, left, right: W - right, W, H };
  let out = `<svg class="fc-svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${esc(o.label)}">`;
  t.list.forEach((v, i) => {
    const yy = y(v).toFixed(1);
    out += `<line class="fc-grid${v === 0 ? " zero" : ""}" x1="${left.toFixed(1)}" x2="${s.right}" y1="${yy}" y2="${yy}"/><text class="fc-ylab" x="${(left - 6).toFixed(1)}" y="${yy}" dy="4" text-anchor="end">${labels[i]}</text>`;
  });
  out += `<text class="fc-unit" x="${left.toFixed(1)}" y="13">${esc(o.unit)}</text>`;
  // o.xLabel(v) names a position (months); otherwise it is a year
  const step = o.xLabel ? ([1, 2, 3].find((k) => slot * k >= 30) || 3) : ([1, 2, 5, 10].find((k) => slot * k >= 42) || 10);
  for (let v = o.xMin; v <= o.xMax; v++) {
    if (!o.xLabel && step >= 5 ? v % step !== 0 : (v - o.xMin) % step !== 0) continue;
    out += `<text class="fc-xlab" x="${x(v).toFixed(1)}" y="${H - 7}" text-anchor="middle">${esc(o.xLabel ? o.xLabel(v) : v)}</text>`;
  }
  out += `<g class="calm-data">${o.draw(s)}</g>`;   // what draws in, left to right, the first time the chart is seen
  (o.hover || []).forEach((h) => {
    out += `<rect class="fc-hit" x="${(x(h.x) - slot / 2).toFixed(1)}" y="${top}" width="${slot.toFixed(1)}" height="${ph}"><title>${esc(h.text)}</title></rect>`;
  });
  return out + "</svg>";
}
function shade(s, from, to, words) {
  const a = s.x(from) - s.slot / 2, b = s.x(to) + s.slot / 2;
  return `<rect class="fc-focus" x="${a.toFixed(1)}" y="${s.top}" width="${(b - a).toFixed(1)}" height="${s.bottom - s.top}"/>` +
    (b - a > 80 ? `<text class="fc-focus-lab" x="${((a + b) / 2).toFixed(1)}" y="${s.top + 13}" text-anchor="middle">${esc(words)}</text>` : "");
}
function nowLine(s, year) {
  const xx = s.x(year).toFixed(1);
  return `<line class="fc-now" x1="${xx}" x2="${xx}" y1="${s.top}" y2="${s.bottom}"/>`;
}
// pts: [x, low, high]
function band(s, pts, cls = "fc-band") {
  const ok = pts.filter((p) => isNum(p[1]) && isNum(p[2]));
  if (ok.length < 2) return "";
  const upper = ok.map((p) => [s.x(p[0]), s.y(p[2])]), lower = ok.slice().reverse().map((p) => [s.x(p[0]), s.y(p[1])]);
  return `<path class="${cls}" d="${pathOf(upper.concat(lower))}Z"/>`;
}
// pts: [x, value]; a missing value breaks the line
function line(s, pts, cls = "fc-line", style = "") {
  let d = "", run = [];
  const flush = () => { if (run.length > 1) d += pathOf(run); run = []; };
  pts.forEach((p) => { if (isNum(p[1])) run.push([s.x(p[0]), s.y(p[1])]); else flush(); });
  flush();
  return d ? `<path class="${cls}" d="${d}"${style ? ` style="${style}"` : ""}/>` : "";
}
function dots(s, pts, cls = "fc-dot", r = 3.2, style = "") {
  if (s.slot < 14) return "";   // years too close together: the line alone reads better
  return pts.filter((p) => isNum(p[1])).map((p) => `<circle class="${cls}" cx="${s.x(p[0]).toFixed(1)}" cy="${s.y(p[1]).toFixed(1)}" r="${r}"${style ? ` style="${style}"` : ""}/>`).join("");
}
// bars stand on zero: only charts that start at zero draw them
function bars(s, pts, cls = "fc-bar", share = 0.56) {
  const base = s.y(0);
  return pts.filter((p) => isNum(p[1]) && Number(p[1]) > 0).map((p) => {
    const top = s.y(p[1]), w = s.slot * share;
    return `<rect class="${cls}" x="${(s.x(p[0]) - w / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${w.toFixed(1)}" height="${Math.max(0, base - top).toFixed(1)}"/>`;
  }).join("");
}
const key = (cls, words, style = "") => `<span><i class="fc-key ${cls}"${style ? ` style="${style}"` : ""}></i>${words}</span>`;

// ---------------------------------------------------------------- the page

export async function render(main, route, alive) {
  // everything lives in a box of its own, so the listeners below go away with the page
  main.innerHTML = '<div class="fc-root"></div>';
  const el = main.firstChild;
  const cityId = route.city, apns = route.apns || [];
  let data = null, values = {}, seq = 0, ringMiles = null, mapView = null, mapDrawn = false, lastWidth = 0, observer = null;
  // the wider picture (outlook) arrives after the forecast; its own maps are made once and redrawn in place
  let outlook = null, outlookProblem = "", outlookSeq = 0, planView = "uses";
  let planMap = null, planLayers = null, planFitted = false, nearMap = null, nearLayers = null, nearFitted = false;
  let roadMap = null, roadLayers = null, roadFitted = false;
  // the site plan in 3D: asked for only when chosen (the ground heights can be slow the first time)
  let ground = null, groundProblem = "", groundAsking = false, unmount3d = null;
  const charts = {};
  // calm: the open chapter, the disclosures the reader opened (kept through every redraw), the charts already drawn in
  const folds = new Set(), seenCharts = new Set();
  let counted = false;
  const book = chapters({ root: el, list: CHAPTERS, onShow: (id) => {
    paintCharts();
    if (id === "summary") countStats();
  } });
  const stopFolds = watchFolds(el, folds, () => paintCharts());
  const stopMotion = watchMotion(el);
  const stopPrint = printEverything(el, () => paintCharts());
  alive.onLeave(() => { stopFolds(); stopMotion(); stopPrint(); });
  const folded = (key, summary, body, cls) => fold(key, summary, body, folds, cls);
  function dropMaps() {
    [mapView, planMap, nearMap].forEach((m) => { if (m) m.destroy(); });
    mapView = planMap = nearMap = null; planLayers = nearLayers = null; planFitted = nearFitted = false;
    if (roadMap) roadMap.destroy();
    roadMap = roadLayers = null; roadFitted = false;
    if (unmount3d) unmount3d();
    unmount3d = null;
  }
  alive.onLeave(() => {
    dropMaps();
    if (observer) observer.disconnect();
    observer = null;
  });
  el.addEventListener("input", onInput);
  el.addEventListener("change", onChange);
  el.addEventListener("click", onClick);

  function first() {
    dropMaps();
    mapDrawn = false; outlook = null; outlookProblem = ""; outlookSeq++; ground = null; groundProblem = "";
    el.innerHTML = `<header class="page-head"><p class="kicker">Forecast</p><h1>Working out the forecast…</h1></header>` +
      loading("Reading the Census, the regional plan, the census survey, the city's project lists and the highway counts around this site. The first time takes several seconds.");
    if (!apns.length) {
      el.innerHTML = `<header class="page-head"><p class="kicker">Forecast</p><h1>No parcels to forecast</h1></header>` +
        problem("This address does not name any parcel numbers. Open a land and press Forecast, or tick lands on My lands.", "") + `<p><a class="btn" href="#/my-lands">Go to My lands</a></p>`;
      return;
    }
    api.forecast(cityId, apns).then((answer) => {
      if (!alive()) return;
      take(answer);
      try { build(); } catch (e) {
        console.error(e);
        el.innerHTML = `<header class="page-head"><p class="kicker">Forecast</p><h1>The forecast could not be shown</h1></header>` +
          problem("The forecast was worked out, but this page could not draw it. Reload the page; if it keeps happening, close Land Planner and start it again.", "");
      }
    }, (e) => {
      if (!alive()) return;
      // a parcel that does not exist will not appear by asking again; anything else might
      const gone = e.status === 404 || e.status === 400;
      el.innerHTML = `<header class="page-head"><p class="kicker">Forecast</p><h1>The forecast could not be worked out</h1></header>` +
        problem(e.message, gone ? "" : "Try again") + `<p><a class="btn" href="#/my-lands">Go to My lands</a></p>`;
      const retry = el.querySelector("[data-retry]");
      if (retry) retry.addEventListener("click", first);
    });
  }
  function take(answer) {
    data = answer;
    values = Object.fromEntries((data.figures || []).map((f) => [f.id, Number(f.value)]));
    if (ringMiles === null || !(data.rings || []).some((r) => r.miles === ringMiles)) ringMiles = data.market_miles;
  }

  // ---------------------------------------------------------------- asking again with the owner's figures

  const status = (html, kind = "") => {
    const s = el.querySelector("#fcStatus");
    if (s) { s.className = "fc-status " + kind; s.innerHTML = html; }
  };
  const later = debounce(() => send("POST"), 600);
  function send(method) {
    const my = ++seq;
    status(method === "DELETE" ? "Going back to the starting figures…" : "Working out the forecast with your figures…", "busy");
    const asking = method === "DELETE" ? api.forecastReset(cityId, data.apns) : api.forecastSet(cityId, data.apns, { ...values });
    asking.then((answer) => {
      if (!alive() || my !== seq) return;
      take(answer);
      drawAll();
      loadOutlook(false, true);   // its steps and shop sales ahead follow the owner's figures too
      status(method === "DELETE" ? "Back to the starting figures. Every number on this page is worked out again."
        : answer.kept ? "Worked out again with your figures. Every number on this page is updated, and your figures are kept on this computer."
          : "Worked out again. These are the starting figures.", "ok");
    }).catch((e) => {
      if (!alive() || my !== seq) return;
      status(`${esc(e.message)} <button type="button" class="btn small" data-again>Try again</button>`, "bad");
      const again = el.querySelector("[data-again]");
      if (again) again.addEventListener("click", () => send(method));
    });
  }

  // ---------------------------------------------------------------- the frame (drawn once)

  function build() {
    const single = data.apns.length === 1;
    const P0 = (data.site.parcels || [])[0] || {};
    document.title = `Forecast · ${single ? P0.apn_formatted || P0.apn : data.apns.length + " parcels"} · Land Planner`;
    if (single) document.dispatchEvent(new CustomEvent("land-open", { detail: { city: data.city, apn: P0.apn, number: P0.apn_formatted || P0.apn, acres: P0.acres } }));
    // the parts stay in their printed order; on screen only the open chapter's parts show (data-part), each in the
    // order its chapter reads best (--o)
    el.innerHTML = `
      <div class="fc">
        <header class="page-head fc-head" id="fcHead"></header>
        ${book.tabs()}
        <div id="fcEdited"></div>
        <div class="fc-top" id="fcTop" data-part="summary" style="--o:1">
          <div class="fc-about" id="fcAbout"></div>
          <section class="stats fc-stats" id="fcStats" aria-label="The forecast in numbers"></section><section class="card fc-advice" id="fcAdvice"></section></div>
        <section id="fcPeople" data-part="market" style="--o:1" aria-labelledby="fcPeopleTitle"></section>
        <section id="fcIncome" data-part="market" style="--o:3" aria-labelledby="fcIncomeTitle">
          <h2 id="fcIncomeTitle">Income areas</h2>
          <div class="fc-income">
            <div class="fc-income-map">
              <div class="map-frame"><div class="map fc-map" id="fcMap"></div></div>
              <div class="legend" id="fcMapLegend"></div>
            </div>
            <div class="fc-income-text" id="fcIncomeText"></div>
          </div>
          <div class="fc-income-tracts" id="fcTracts"></div>
        </section>
        <section id="fcNeeds" data-part="market" style="--o:2" aria-labelledby="fcNeedsTitle"></section>
        <section id="fcTraffic" data-part="site" style="--o:3" aria-labelledby="fcTrafficTitle">
          <div id="fcTrafficBody"></div>
          <div class="fc-entr">
            <div class="fc-entr-map"><div class="map-frame"><div class="map fc-map" id="fcRoadMap"></div></div><div class="legend" id="fcRoadLegend"></div></div>
            <div id="fcEntrText"></div>
          </div>
        </section>
        <section id="fcLand" data-part="site" style="--o:1" aria-labelledby="fcLandTitle"></section>
        <section id="fcPlan" data-part="site" style="--o:2" aria-labelledby="fcPlanTitle">
          <div class="fc-sec-head"><h2 id="fcPlanTitle">Site plan</h2>
            <div class="plan-switch small" role="group" aria-label="What the site plan shows">
              <button type="button" data-planview="uses">The uses</button><button type="button" data-planview="when">When each part is offered</button><button type="button" data-planview="3d">In 3D on the real ground</button></div></div>
          <div class="fc-plan">
            <div class="fc-plan-map"><div class="map-frame" id="fcPlanFrame"><div class="map fc-map" id="fcPlanMap"></div></div><div id="fcPlan3d" hidden></div><div class="legend" id="fcPlanLegend"></div></div>
            <div id="fcPlanText"></div>
          </div>
        </section>
        <section id="fcEconomy" data-part="city" style="--o:1" aria-labelledby="fcEconomyTitle"></section>
        <section id="fcHousing" data-part="city" style="--o:2" aria-labelledby="fcHousingTitle"></section>
        <section id="fcWeather" data-part="city" style="--o:4" aria-labelledby="fcWeatherTitle"></section>
        <section id="fcHazards" data-part="site" style="--o:4" aria-labelledby="fcHazardsTitle"></section>
        <section id="fcNearby" data-part="city" style="--o:3" aria-labelledby="fcNearbyTitle">
          <h2 id="fcNearbyTitle">What is close by</h2>
          <div class="fc-nearby">
            <div class="fc-nearby-map"><div class="map-frame"><div class="map fc-map" id="fcNearMap"></div></div><div class="legend" id="fcNearLegend"></div></div>
            <div><div id="fcNearSummary"></div><div id="fcNearText"></div></div>
          </div>
        </section>
        <section id="fcResident" data-part="market" style="--o:4" aria-labelledby="fcResidentTitle"></section>
        <section id="fcTodo" data-part="todo" style="--o:1" aria-labelledby="fcTodoTitle"></section>
        <section id="fcFigures" data-part="figures" style="--o:1" aria-labelledby="fcFiguresTitle"></section>
        <section class="two fc-last" id="fcSources" data-part="figures" style="--o:2"></section>
        <div class="fc-pager-box" data-calm-pager></div>
      </div>`;
    drawAll(false);
    drawMap();
    book.open(book.current(), { write: false, first: true });
    loadOutlook(false);
    if (data.kept) status("Your own figures for this site are kept on this computer and used below.", "ok");
    if (window.ResizeObserver && !observer) {
      observer = new ResizeObserver(() => {
        const w = el.clientWidth;
        if (Math.abs(w - lastWidth) < 2) return;
        lastWidth = w;
        requestAnimationFrame(() => { if (alive()) paintCharts(); });
      });
      observer.observe(el);
    }
  }

  // ---------------------------------------------------------------- drawing everything, keeping the person's place

  function drawAll(keepPlace = true) {
    const active = document.activeElement;
    const k = active && el.contains(active) && active.dataset ? active.dataset.k : null;
    let typed = null, from = null, to = null;
    if (k && "value" in active) {
      typed = active.value;
      try { from = active.selectionStart; to = active.selectionEnd; } catch (e) { from = to = null; }
    }
    // keep whatever the person is looking at in the same place on the screen
    const anchor = (k && active) || el.querySelector("#fcFigures");
    const before = anchor ? anchor.getBoundingClientRect().top : 0;

    drawHead(); drawEdited(); drawStats(); drawAdvice(); drawPeople(); drawIncomeText(); drawNeeds(); drawTraffic(); drawLand();
    drawSitePlan(); drawOutlook();
    drawFigures(); drawSources();
    paintCharts();

    if (k) {
      const again = el.querySelector(`[data-k="${CSS.escape(k)}"]`);
      if (again) {
        if (typed !== null && again.type === "text") again.value = typed;
        again.focus({ preventScroll: true });
        if (from !== null && again.setSelectionRange && again.type === "text") { try { again.setSelectionRange(from, to); } catch (e) { /* not a text box */ } }
      }
    }
    const now = k ? el.querySelector(`[data-k="${CSS.escape(k)}"]`) : el.querySelector("#fcFigures");
    if (keepPlace && now && anchor) {
      const shift = now.getBoundingClientRect().top - before;
      if (Math.abs(shift) > 1) window.scrollBy(0, shift);
    }
  }
  // a chart is drawn at the width of its box; a box out of sight (another chapter, a closed disclosure) has no width
  // and is drawn when it is shown. The first time a chart is drawn on screen its lines draw in.
  function paintCharts() {
    el.querySelectorAll("[data-chart]").forEach((box) => {
      const fn = charts[box.dataset.chart], w = box.clientWidth;
      if (!fn || !w) return;
      box.innerHTML = fn(w);
      if (!seenCharts.has(box.dataset.chart)) { seenCharts.add(box.dataset.chart); drawIn(box); }
    });
  }
  // the headline numbers count up once, the first time the Summary is on screen
  function countStats() {
    if (counted || !data || !el.querySelector("#fcStats [data-to]")) return;
    counted = true;
    el.querySelectorAll("#fcStats [data-to]").forEach((b) => countUp(b, Number(b.dataset.to), (v) => amount(Math.round(v), b.dataset.unit || "")));
  }

  // ---------------------------------------------------------------- shared pieces

  const now = () => data.year;
  function yearKind(y) {
    if (y < now()) return "bg";
    if (y === now()) return "now";
    return y - now() <= 5 ? "focus" : "later";
  }
  function yearCell(y) {
    const k = yearKind(y);
    const words = k === "bg" ? "last year" : k === "now" ? "this year" : `year ${y - now()}`;
    return `<b>${esc(y)}</b><small>${words}</small>`;
  }
  // rows: [{year, cells}] ; the first column is the year, the others are numbers lined up on the right
  function yearTable(head, rows, cls = "") {
    return `<div class="scroll"><table class="data fc-years ${cls}"><thead><tr>${head.map((h, i) => `<th${i ? ' class="num"' : ""}>${h}</th>`).join("")}</tr></thead><tbody>` +
      rows.map((r) => `<tr class="fc-y-${yearKind(r.year)}"><td>${yearCell(r.year)}</td>${r.cells.map((c) => `<td class="num">${c}</td>`).join("")}</tr>`).join("") +
      "</tbody></table></div>";
  }
  function plainTable(head, rows, numeric = []) {
    return `<div class="scroll"><table class="data"><thead><tr>${head.map((h, i) => `<th${numeric.includes(i) ? ' class="num"' : ""}>${h}</th>`).join("")}</tr></thead><tbody>` +
      rows.map((r) => `<tr${r.cls ? ` class="${r.cls}"` : ""}>${(r.cells || r).map((c, i) => `<td${numeric.includes(i) ? ' class="num"' : ""}>${c}</td>`).join("")}</tr>`).join("") +
      "</tbody></table></div>";
  }
  function notCovered(what, partsKey, reason) {
    let text = `${what}: not covered yet.`;
    if (reason) text += " " + reason;
    else {
      const answered = data.answered || {};
      const silent = (PARTS_FOR[partsKey] || []).filter((p) => answered[p] && answered[p] !== "ok" && answered[p] !== "older copy");
      if (silent.length) text += " " + cap(listWords(silent.map((p) => `${PART_WORDS[p] || p} ${noAnswer(answered[p]) ? whyNoAnswer(answered[p]) : "had nothing for this spot"}`))) + ".";
    }
    return missing(text);
  }
  function figureTag(f) {
    return f.yours ? '<span class="fc-tag yours">Your figure</span>' : '<span class="fc-tag start">Starting figure</span>';
  }
  function figureValue(f) {
    const u = String(f.unit || "");
    if (u === "%") return num(f.value, 2) + "%";
    if (u.startsWith("$")) return "$" + num(f.value, 2) + (u.slice(1).trim() ? " " + esc(u.slice(1).trim()) : "");
    return num(f.value, 2) + (u ? " " + esc(u) : "");
  }
  // "Rests on: [Starting figure] Floor space for each new job, 400 sq ft. Change"
  function restsOn(part) {
    const groups = GROUPS_FOR[part] || [];
    const figs = (data.figures || []).filter((f) => groups.includes(f.group));
    if (!figs.length) return "";
    return `<p class="fc-rests"><b>Rests on figures you can change:</b> ${figs.map((f) => `${figureTag(f)} ${esc(f.label)}: <b>${figureValue(f)}</b>`).join("; ")}. <button type="button" class="link" data-jump="fcFigures">Change them</button></p>`;
  }

  // ---------------------------------------------------------------- the head

  function drawHead() {
    const site = data.site || {}, parcels = site.parcels || [], single = data.apns.length === 1, P0 = parcels[0] || {};
    const zones = [];
    parcels.forEach((p) => {
      const words = p.zoning ? p.zoning + (p.zoning_name && p.zoning_name !== p.zoning ? ` (${p.zoning_name})` : "") : "no zoning listed";
      if (!zones.includes(words)) zones.push(words);
    });
    const parcelLinks = parcels.map((p) => `<a href="#/land/${esc(data.city)}/${esc(p.apn)}">${esc(p.apn_formatted || p.apn)}</a>${isNum(p.acres) ? ` <span class="muted">(${num(p.acres, 2)} ${plural(p.acres, "acre", "acres", 2)})</span>` : ""}`);
    let together = "";
    if (!single) {
      together = `<p class="fc-together">These ${parcels.length} parcels are forecast <b>as one site</b>: the people, homes, shops, jobs and traffic around the point between them, and the land of all of them together.` +
        (site.together ? (isNum(site.spread_miles) ? ` They lie together, within about ${num(site.spread_miles, 2)} ${plural(site.spread_miles, "mile", "miles", 2)} of each other.` : " They lie together.")
          : " <b>They are not next to each other</b>, so the forecast fits each one less well than a forecast of its own.") + "</p>";
    }
    const tabs = single ? `<nav class="tabs" aria-label="This land's pages">${PAGES.map(([id, label]) =>
      `<a href="#/land/${esc(data.city)}/${esc(P0.apn)}/${id}">${icon(id)}${label}</a>`).join("")}<a href="#/forecast/${esc(data.city)}/${esc(P0.apn)}" class="on" aria-current="page">${FORECAST_ICON}Forecast</a></nav>` : "";
    el.querySelector("#fcHead").innerHTML = `
      <p class="kicker"><a href="#/lands/${esc(data.city)}">${esc(data.city_name || data.city)}</a> · Forecast, ${esc(now())} to ${esc(now() + 10)}</p>
      <div class="head-row">
        <div>
          <h1>${isNum(site.acres) ? num(site.acres, 2) + " " + plural(site.acres, "acre", "acres", 2) : "This site"}${single ? "" : `, ${parcels.length} parcels as one site`}</h1>
          <p class="lead">${single ? "Parcel" : "Parcels"} ${parcelLinks.join(", ")} · zoned ${esc(listWords(zones))}</p>
        </div>
        <div class="head-actions">
          ${single ? "" : `<a class="btn" href="#/my-lands">${icon("saved")} My lands</a>`}
          <button type="button" class="btn" id="fcPrint">Print</button>
          <a class="btn" href="#/handout/${esc(encodeURIComponent(data.city))}/${data.apns.map((a) => esc(a)).join("+")}" title="The whole site on one printed page, to leave with the people in the room">One-page summary</a>
          <a class="btn primary" href="#/present/${esc(encodeURIComponent(data.city))}/${data.apns.map((a) => esc(a)).join("+")}">${icon("cities")} Present to the city</a>
        </div>
      </div>
      ${tabs}`;
    // what the site is and how the years are shown: read once, on the Summary
    el.querySelector("#fcAbout").innerHTML = `${together}
      <p class="fc-years-line">Next ten years, year by year: <b>${esc(now() + 1)} to ${esc(now() + 5)}</b> in focus, ${esc(now() + 6)} to ${esc(now() + 10)} lighter, and ${esc(data.background_year)} as background. Low, expected and high lines come from the real readings of growth; nothing is filled in where a source gives nothing.</p>`;
  }
  function drawEdited() {
    const box = el.querySelector("#fcEdited"), mine = (data.figures || []).filter((f) => f.yours);
    let html = "";
    if (!data.available) {
      html += `<div class="notice warn"><p><b>There is no year-by-year forecast for this site yet.</b> ${esc((data.limits || [])[0] || "")}</p></div>`;
    }
    if (mine.length) {
      html += `<div class="notice"><div class="row"><p>This forecast uses <b>your own figures</b> for ${esc(listWords(mine.map((f) => f.label.toLowerCase())))}. They are marked “Your figure” below.</p>
        <button type="button" class="btn small" data-reset-all>Back to starting figures</button></div></div>`;
    }
    box.innerHTML = html;
  }
  function drawStats() {
    const list = data.headline || [];
    el.querySelector("#fcStats").innerHTML = list.length ? list.map((h) => {
      const bare = (v) => (h.unit === "$" ? amount(v, "$") : num(v));
      const spread = isNum(h.low) && isNum(h.high) ? `<span>low ${bare(h.low)} to high ${bare(h.high)}</span>` : "";
      const to = isNum(h.value) ? ` data-to="${Number(h.value)}" data-unit="${esc(h.unit || "")}"` : "";
      return `<div class="stat"><span class="label">${esc(h.label)}</span><b${to}>${amount(h.value, h.unit)}</b>${spread}${h.note ? `<span>${esc(h.note)}</span>` : ""}</div>`;
    }).join("") : `<div class="stat"><span class="label">Forecast</span><b class="small">${cap(NONE)}</b><span>no reading of growth answered for this site</span></div>`;
  }
  function drawAdvice() {
    const items = data.advice || [];
    // the first findings, then the rest on request
    const list = (some) => `<ul class="plain fc-advice-list">${some.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>`;
    const rest = items.slice(FIRST_FINDINGS);
    el.querySelector("#fcAdvice").innerHTML = `<h2>What this says</h2>` +
      (items.length ? list(items.slice(0, FIRST_FINDINGS)) + (rest.length ? folded("advice", `Show the other ${rest.length === 1 ? "finding" : rest.length + " findings"}`, list(rest)) : "")
        : missing("Nothing to say yet: the forecast is not covered for this site."));
  }

  // ---------------------------------------------------------------- people and homes

  function drawPeople() {
    const box = el.querySelector("#fcPeople"), rings = data.rings || [];
    const ring = rings.find((r) => r.miles === ringMiles) || rings[0];
    const sw = `<div class="plan-switch small" role="group" aria-label="How far around the site">${rings.map((r) =>
      `<button type="button" data-ring="${r.miles}" class="${r === ring ? "on" : ""}" aria-pressed="${r === ring}">${esc(mi(r.miles))}</button>`).join("")}</div>`;
    const head = `<div class="fc-sec-head"><h2 id="fcPeopleTitle">People and homes</h2>${sw}</div>`;
    if (!ring) { box.innerHTML = head + notCovered("People and homes around the site", "rings"); return; }
    const counted = ring.counted || {}, cYears = Object.keys(counted).map(Number).filter(Number.isFinite).sort();
    const countedLine = cYears.length ? cYears.map((y) => `<b>${num(counted[y].people)}</b> people in <b>${num(counted[y].homes)}</b> homes in ${y}`).join(", ") : "";
    if (!ring.available) {
      box.innerHTML = head + (countedLine ? `<p>Within ${esc(mi(ring.miles))} the Census counted ${countedLine}.</p>` : "") + notCovered(`The forecast within ${mi(ring.miles)}`, "rings");
      return;
    }
    const r = ring.rates_pct || {};
    const intro = `<p class="fc-intro">Within ${esc(mi(ring.miles))} of the site the Census counted ${countedLine || NONE}${isNum(ring.people_per_home) ? `, about ${num(ring.people_per_home, 2)} ${plural(ring.people_per_home, "person", "people", 2)} a home` : ""}. ` +
      (ring.one_reading ? `Only one reading of growth answered (${num(r.expected, 2)}% a year), so the low and high lines are the same as the expected line.`
        : `The expected line grows homes by <b>${num(r.expected, 2)}% a year</b>, the middle reading; the band runs from the lowest reading (${num(r.low, 2)}%) to the highest (${num(r.high, 2)}%).`) + "</p>";
    const rows = ring.rows || [];
    charts.people = (w) => {
      const xs = rows.map((x) => x.year).concat(cYears);
      const vals = [];
      rows.forEach((x) => vals.push(x.people.low, x.people.high));
      cYears.forEach((y) => vals.push(counted[y].people));
      const bg = rows.filter((x) => x.year <= now()), fwd = rows.filter((x) => x.year >= now());
      return chart({
        width: w, height: 300, xMin: Math.min(...xs), xMax: Math.max(...xs), values: vals, zero: false, unit: `People within ${mi(ring.miles)}`,
        label: `Chart of people within ${mi(ring.miles)} of the site, counted in ${cYears.join(" and ")} and forecast from ${rows[0] ? rows[0].year : ""} to ${rows.length ? rows[rows.length - 1].year : ""}. The table gives the same figures.`,
        draw: (s) => shade(s, now() + 1, now() + 5, "Next five years") +
          band(s, bg.map((x) => [x.year, x.people.low, x.people.high]), "fc-band bg") + band(s, fwd.map((x) => [x.year, x.people.low, x.people.high])) +
          line(s, bg.map((x) => [x.year, x.people.expected]), "fc-line bg") + line(s, fwd.map((x) => [x.year, x.people.expected])) +
          dots(s, fwd.map((x) => [x.year, x.people.expected]), "fc-dot") + nowLine(s, now()) +
          cYears.map((y) => `<circle class="fc-counted" cx="${s.x(y).toFixed(1)}" cy="${s.y(counted[y].people).toFixed(1)}" r="5.5"/>` +
            `<text class="fc-pt-lab" x="${s.x(y).toFixed(1)}" y="${(s.y(counted[y].people) - 10).toFixed(1)}" text-anchor="middle">${num(counted[y].people)}</text>`).join(""),
        hover: rows.map((x) => ({ x: x.year, text: `${x.year}: about ${num(x.people.expected)} ${plural(x.people.expected, "person", "people")} expected (${range(x.people)})` }))
          .concat(cYears.map((y) => ({ x: y, text: `${y}: ${num(counted[y].people)} ${plural(counted[y].people, "person", "people")} counted by the Census` }))),
      });
    };
    const readings = (ring.readings || []).map((g) => {
      const used = [];
      if (Number(g.rate_pct) === Number(r.expected)) used.push("expected line");
      if (!ring.one_reading && Number(g.rate_pct) === Number(r.low)) used.push("low line");
      if (!ring.one_reading && Number(g.rate_pct) === Number(r.high)) used.push("high line");
      const tag = (g.kind === "measured" ? '<span class="fc-tag measured">measured</span>' : '<span class="fc-tag official">official forecast</span>') +
        (g.whole_city ? ' <span class="fc-tag city">whole city</span>' : "");
      return [`<b>${esc(g.label)}</b> ${tag}<small>${esc(g.source || NONE)}</small>${used.length ? `<small><b>Used for the ${esc(listWords(used))}</b></small>` : ""}`,
        `${num(g.rate_pct, 2)}% a year`,
        g.from ? `${num(g.from.homes)} ${plural(g.from.homes, "home")}<small>in ${esc(g.from.year)}</small>` : NONE,
        g.to ? `${num(g.to.homes)} ${plural(g.to.homes, "home")}<small>in ${esc(g.to.year)}</small>` : NONE];
    });
    box.innerHTML = head + intro + `
      <div class="card fc-people-chart">
        <div class="fc-chart" data-chart="people"></div>
        <div class="legend fc-legend">${key("band", "Low to high")}${key("line", "Expected")}${key("counted", "Counted by the Census")}${key("focus", "Next five years")}${key("now", "This year")}</div>
      </div>
      <div class="fc-folds">
        ${folded("people-years", "Show the year-by-year figures", `<h3>Year by year, within ${esc(mi(ring.miles))}</h3>
          ${yearTable(["Year", "People<small>expected, then low to high</small>", "Homes<small>expected, then low to high</small>"],
            rows.map((x) => ({ year: x.year, cells: [cellRange(x.people), cellRange(x.homes)] })))}
          ${allRings()}`)}
        ${folded("people-how", "How this was worked out", `<h3>The readings of growth</h3>
          ${readings.length ? plainTable(["What it is, and its source", "A year", "From", "To"], readings, [1, 2, 3]) : missing("Readings of growth: not covered yet.")}
          <p class="fine">Each reading is a steady yearly growth rate in homes. People are homes times the people a home counted in ${esc(cYears[cYears.length - 1] || "the last Census")}.</p>
          ${ring.today_from && ring.today_from.words ? `<p class="fine">Where “this year” (${esc(ring.today_from.year || now())}) comes from: ${esc(ring.today_from.words)}</p>` : ""}`)}
      </div>`;
  }

  // the three distances side by side: counted, this year, five and ten years on (expected), and the yearly rate
  function allRings() {
    const rings = data.rings || [], marks = [now(), now() + 5, now() + 10];
    if (rings.length < 2) return "";
    const rows = rings.map((g) => {
      const c = g.counted || {}, last = Object.keys(c).map(Number).filter(Number.isFinite).sort().pop();
      const at = (y) => { const x = (g.rows || []).find((row) => row.year === y); return x ? num(x.people.expected) : NONE; };
      return { cls: g.miles === ringMiles ? "fc-ring-on" : "", cells: [`<b>${esc(mi(g.miles))}</b>`, last ? `${num(c[last].people)}<small>in ${last}</small>` : NONE]
        .concat(g.available ? marks.map(at).concat([`${num((g.rates_pct || {}).expected, 2)}%<small>${num((g.rates_pct || {}).low, 2)} to ${num((g.rates_pct || {}).high, 2)}%</small>`])
          : [NONE, NONE, NONE, NONE]) };
    });
    return `<h3 class="fc-gap">People at each distance</h3>` +
      plainTable(["Within", "Counted", `${marks[0]}`, `${marks[1]}`, `${marks[2]}`, "Homes grow<small>a year, expected</small>"], rows, [1, 2, 3, 4, 5]) +
      `<p class="fine">${esc(marks.join(", "))}: expected people. The switch above picks the distance the chart and the year table show.</p>`;
  }

  // ---------------------------------------------------------------- income areas

  function incomeBands() {
    const inc = data.income || {};
    if (!inc.available || !isNum(inc.lowest) || !isNum(inc.highest)) return null;
    const colours = ["#fff2c4", "#f8c26a", "#e9814b", "#c4434f", "#7b1f5c"];
    const lo = Number(inc.lowest), hi = Number(inc.highest), step = (hi - lo) / colours.length || 1;
    const cuts = colours.map((c, i) => ({ colour: c, from: Math.round((lo + i * step) / 1000) * 1000, to: Math.round((lo + (i + 1) * step) / 1000) * 1000 }));
    cuts[0].from = lo; cuts[cuts.length - 1].to = hi;
    return { cuts, colourOf: (v) => cuts[Math.min(cuts.length - 1, Math.max(0, Math.floor((Number(v) - lo) / step)))].colour };
  }
  function drawMap() {
    if (mapDrawn) return;
    mapDrawn = true;
    const L = window.L, site = data.site || {}, inc = data.income || {};
    const at = site.centre && isNum(site.centre.lat) ? { lat: Number(site.centre.lat), lon: Number(site.centre.lon) } : null;
    mapView = createMap(el.querySelector("#fcMap"), { base: "aerial", city: data.city, at });
    const m = mapView.map;
    const rings = (data.rings || []).map((r) => r.miles).filter(isNum);
    let bounds = null;
    if (at) {
      rings.forEach((miles) => {
        L.circle([at.lat, at.lon], { radius: miles * 1609.344, color: "#ffffff", weight: 2, opacity: 0.95, dashArray: "6 6", fill: false, interactive: false }).addTo(m);
        // the widest circle's box (a circle has no bounds until the map has a view)
        const north = at.lat + miles / 69.05, east = miles / (69.17 * Math.cos(at.lat * Math.PI / 180));
        if (miles === Math.max(...rings)) bounds = L.latLngBounds([at.lat - miles / 69.05, at.lon - east], [north, at.lon + east]);
        L.marker([north, at.lon], { icon: L.divIcon({ className: "fc-ring-label", iconSize: [0, 0], html: `<span>${esc(mi(miles))}</span>` }), interactive: false, keyboard: false }).addTo(m);
      });
    }
    (site.parcels || []).forEach((p) => {
      if (!p.outline || !p.outline.coordinates) return;
      const shape = ll(p.outline.type === "MultiPolygon" ? p.outline.coordinates.flat() : p.outline.coordinates);
      L.polygon(shape, { color: "#1d2a24", weight: 6, fill: false, interactive: false }).addTo(m);
      const g = L.polygon(shape, { color: "#f2b632", weight: 3, fillColor: "#f2b632", fillOpacity: 0.25 }).bindTooltip(`Parcel ${esc(p.apn_formatted || p.apn)}${isNum(p.acres) ? ", " + num(p.acres, 2) + " " + plural(p.acres, "acre", "acres", 2) : ""}`, { sticky: true }).addTo(m);
      if (!bounds) bounds = g.getBounds();
    });
    const scale = incomeBands();
    if (scale) {
      (inc.tracts || []).forEach((t) => {
        if (!isNum(t.lat) || !isNum(t.lon)) return;
        L.circleMarker([Number(t.lat), Number(t.lon)], { radius: 8, color: "#1d2a24", weight: 1.5, fillColor: scale.colourOf(t.income), fillOpacity: 0.95 })
          .bindTooltip(`<b>${esc(t.name)}</b><br>Typical household income $${num(t.income)} a year<br>${num(t.households)} ${plural(t.households, "household")} · ${num(t.miles_away, 2)} ${plural(t.miles_away, "mile", "miles", 2)} ${esc(t.direction || "")}`).addTo(m);
      });
    }
    if (bounds) mapView.fit(bounds.pad(0.04));
    el.querySelector("#fcMapLegend").innerHTML = (scale ? scale.cuts.map((c) => `<span><i style="background:${c.colour}"></i>$${num(c.from)} to $${num(c.to)}</span>`).join("") + "<span class=\"muted\">typical household income of each census tract (dot at its middle)</span>"
      : `<span class="missing">Income by census tract: not covered yet.</span>`) +
      `<span><i class="fc-key site"></i>The site</span><span><i class="fc-key ring"></i>${esc(listWords(rings.map(mi)))} around it</span>`;
  }
  function drawIncomeText() {
    const inc = data.income || {}, textBox = el.querySelector("#fcIncomeText"), tracts = el.querySelector("#fcTracts");
    if (!inc.available) {
      textBox.innerHTML = notCovered("Household income around the site", "income");
      tracts.innerHTML = "";
      return;
    }
    const scale = incomeBands();
    const dirs = inc.by_direction || [], far = (data.rings || []).map((r) => r.miles).filter(isNum);
    textBox.innerHTML = `<div class="card fc-income-card">
      <p class="fc-summary">${esc(inc.summary || "")}</p>
      ${dirs.length ? `<div class="fc-dirs">${dirs.map((d) => `<div><span class="label">${esc(cap(d.direction))}</span><b>$${num(d.income)}</b><span>${num(d.households)} ${plural(d.households, "household")} in ${num(d.tracts)} ${plural(d.tracts, "tract")}</span></div>`).join("")}</div>` : ""}
      ${folded("income-facts", "Show the figures and how they were read", `<dl class="facts">
        <dt>Typical household income within ${esc(mi(data.market_miles))}</dt><dd>${amount(inc.typical, "$")} a year</dd>
        <dt>${esc(inc.county_name || "The county")}</dt><dd>${amount(inc.county, "$")} a year</dd>
        <dt>Households that rent</dt><dd>${isNum(inc.renters_pct) ? `about ${num(inc.renters_pct, 1)}%` : NONE}</dd>
        <dt>Homes built in 2020 or later, within ${esc(mi(data.market_miles))}</dt><dd>${isNum(inc.built_since_2020) ? "about " + num(inc.built_since_2020) : NONE}${inc.homes_survey ? ` <small class="muted">(survey ${esc(inc.homes_survey)})</small>` : ""}</dd>
      </dl>
      ${dirs.length ? `<p class="fine">By direction: the households' typical income in the tracts on that side${far.length ? `, within ${esc(mi(Math.max(...far)))}` : ""}. A tract to the north-east counts toward both north and east.</p>` : ""}
      <p class="fine">${esc(inc.source || "Census survey")}${inc.survey ? `, ${esc(inc.survey)}` : ""}. Survey dollars, not adjusted for inflation.</p>`)}</div>`;
    const rows = (inc.tracts || []).map((t) => [
      `<span class="swatch" style="background:${scale ? scale.colourOf(t.income) : "#ccc"}"></span>${esc(String(t.name || NONE).replace(/^Census Tract /, "Tract "))}`,
      `${num(t.miles_away, 2)} mi<small>${esc(t.direction || NONE)}</small>`, amount(t.income, "$"), num(t.households),
      isNum(t.share_in_market) ? num(100 * t.share_in_market) + "%" : NONE,
      t.against_county ? `<span class="fc-against ${esc(t.against_county.replace(/\s+/g, "-"))}">${esc(t.against_county)}</span>` : NONE]);
    tracts.innerHTML = `<div class="fc-folds">${folded("income-tracts", `Show the census tracts, nearest first${rows.length ? ` (${num(rows.length)})` : ""}`,
      `${rows.length ? `<div class="fc-tracts">${plainTable(["Census tract", "Away", "Typical income", "Households", `Inside ${esc(mi(data.market_miles))}`, `Against ${esc(inc.county_name || "the county")}`], rows, [1, 2, 3, 4])}</div>` : missing("Census tracts: not covered yet.")}
      <p class="fine">“Inside ${esc(mi(data.market_miles))}” is the share of the tract's area within that distance; the typical income above weighs each tract by its households inside. “Higher” and “lower” mean 15% or more above or below ${esc(inc.county_name || "the county")}.</p>`)}</div>`;
  }

  // ---------------------------------------------------------------- homes needed, shops, jobs

  // spec: { name, rows, need(r) -> {low,expected,high}, list(r), needSoFar(r), listSoFar(r), unit, what }
  function needCharts(spec) {
    const rows = spec.rows, xs = rows.map((r) => r.year), xMin = Math.min(...xs), xMax = Math.max(...xs);
    charts[spec.name + "-year"] = (w) => {
      const vals = [];
      rows.forEach((r) => { const n = spec.need(r) || {}; vals.push(n.low, n.high, spec.list(r)); });
      return chart({
        width: w, height: 230, xMin, xMax, values: vals, zero: true, unit: `${spec.unit} a year`,
        label: `Chart of ${spec.what} each year, ${xMin} to ${xMax}: the need as a low to high band and an expected line, and what is already on the city's lists as bars. The table gives the same figures.`,
        draw: (s) => shade(s, now() + 1, now() + 5, "Next five years") + bars(s, rows.map((r) => [r.year, spec.list(r)])) +
          band(s, rows.map((r) => { const n = spec.need(r) || {}; return [r.year, n.low, n.high]; })) +
          line(s, rows.map((r) => [r.year, (spec.need(r) || {}).expected])) + dots(s, rows.map((r) => [r.year, (spec.need(r) || {}).expected])),
        hover: rows.map((r) => ({ x: r.year, text: `${r.year}: need about ${num((spec.need(r) || {}).expected)} ${spec.unit} (${range(spec.need(r))}); on the city's lists ${num(spec.list(r))}` })),
      });
    };
    const sum = rows.filter((r) => spec.needSoFar(r));
    if (sum.length > 1) {
      const sMin = Math.min(...sum.map((r) => r.year));
      charts[spec.name + "-sum"] = (w) => {
        const vals = [];
        sum.forEach((r) => vals.push(spec.needSoFar(r).low, spec.needSoFar(r).high, spec.listSoFar(r)));
        return chart({
          width: w, height: 200, xMin: sMin, xMax, values: vals, zero: true, unit: `${spec.unit} added up from ${sMin}`,
          label: `Chart of ${spec.what} added up year by year from ${sMin}: the need as a band and line, and what is on the city's lists as a dashed line.`,
          draw: (s) => band(s, sum.map((r) => [r.year, spec.needSoFar(r).low, spec.needSoFar(r).high])) +
            line(s, sum.map((r) => [r.year, spec.needSoFar(r).expected])) + line(s, sum.map((r) => [r.year, spec.listSoFar(r)]), "fc-line lists") +
            dots(s, sum.map((r) => [r.year, spec.listSoFar(r)]), "fc-dot lists"),
          hover: sum.map((r) => ({ x: r.year, text: `${r.year}, added up: need about ${num(spec.needSoFar(r).expected)} ${spec.unit} (${range(spec.needSoFar(r))}); on the city's lists ${num(spec.listSoFar(r))}` })),
        });
      };
    } else delete charts[spec.name + "-sum"];
    // the year chart leads; the added-up chart goes with the year-by-year figures
    return {
      year: `<div class="fc-chart" data-chart="${spec.name}-year"></div>
      <div class="legend fc-legend">${key("band", "Needed, low to high")}${key("line", "Needed, expected")}${key("bar", "Already on the city's lists")}</div>`,
      sum: sum.length > 1 ? `<h4 class="fc-sub">Added up</h4><div class="fc-chart" data-chart="${spec.name}-sum"></div>
      <div class="legend fc-legend">${key("band", "Needed so far, low to high")}${key("line", "Needed so far, expected")}${key("lists", "On the city's lists so far")}</div>` : "",
    };
  }
  // the expected figure, with low to high under it (left out when all three are the same)
  const cellRange = (o) => `${num(o && o.expected)}${o && Number(o.low) === Number(o.high) && Number(o.low) === Number(o.expected) ? "" : `<small>${range(o)}</small>`}`;

  function drawNeeds() {
    const box = el.querySelector("#fcNeeds"), H = data.homes || {}, S = data.shops || {}, J = data.jobs || {};
    const mm = esc(mi(data.market_miles));
    let homes;
    if (!H.available) homes = notCovered("Homes needed", "homes");
    else {
      const c = needCharts({
        name: "homes", rows: H.rows || [], need: (r) => r.need, list: (r) => r.pipeline, needSoFar: (r) => r.need_so_far, listSoFar: (r) => r.pipeline_so_far,
        unit: "homes", what: `new homes needed within ${mi(data.market_miles)}`,
      });
      homes = `<p class="fc-summary">${esc(H.summary || "")}</p>` + c.year +
        `<dl class="facts fc-totals"><dt>Needed over ten years</dt><dd>${cellRange(H.need_10_years)}</dd><dt>On the city's lists over ten years</dt><dd>${num(H.pipeline_10_years)}</dd>
          <dt>Years of the expected need the lists cover</dt><dd>${isNum(H.pipeline_covers_years) ? num(H.pipeline_covers_years, 1) : NONE}</dd></dl>` +
        folded("homes-years", "Show the year-by-year figures", c.sum + yearTable(["Year", "Needed a year", "On the city's lists", "Needed so far", "On the lists so far", "To rent / to own"],
          (H.rows || []).map((r) => ({ year: r.year, cells: [cellRange(r.need), num(r.pipeline), r.need_so_far ? cellRange(r.need_so_far) : "", has(r.pipeline_so_far) ? num(r.pipeline_so_far) : "",
            has(r.rented) ? `${num(r.rented)} / ${num(r.owned)}` : ""] })), "fc-compact") +
          `<p class="fine">To rent and to own splits the expected need by today's share of renters (census survey).</p>`) +
        folded("homes-how", "How this was worked out", restsOn("homes"));
    }
    let shops;
    if (!S.available) shops = notCovered("Shop space", "shops");
    else {
      const c = needCharts({
        name: "shops", rows: S.rows || [], need: (r) => r.new_sq_ft, list: (r) => r.pipeline_sq_ft, needSoFar: (r) => r.new_so_far, listSoFar: (r) => r.pipeline_so_far,
        unit: "sq ft", what: `new shop space that growth within ${mi(data.market_miles)} supports`,
      });
      shops = `<p class="fc-summary">${esc(S.summary || "")}</p>` + c.year +
        `<dl class="facts fc-totals"><dt>New over ten years</dt><dd>${cellRange(S.new_10_years_sq_ft)} sq ft</dd><dt>On the city's lists over ten years</dt><dd>${num(S.pipeline_10_years_sq_ft)} sq ft</dd></dl>` +
        folded("shops-years", "Show the year-by-year figures", c.sum + yearTable(["Year", "Supported a year (sq ft)", "On the city's lists", "Supported so far", "On the lists so far"],
          (S.rows || []).map((r) => ({ year: r.year, cells: [cellRange(r.new_sq_ft), num(r.pipeline_sq_ft), cellRange(r.new_so_far), num(r.pipeline_so_far)] })), "fc-compact")) +
        folded("shops-how", "How this was worked out", `<dl class="facts fc-totals"><dt>Shop space a household supports</dt><dd>${isNum(S.sq_ft_per_home) ? num(S.sq_ft_per_home, 1) + " sq ft" : NONE}</dd>
          <dt>What homes within ${mm} support today</dt><dd>${cellRange(S.supported_today_sq_ft)} sq ft</dd></dl>` + restsOn("shops"));
    }
    let jobs;
    if (!J.available) jobs = notCovered("Jobs and work space", "jobs");
    else {
      const readings = (J.readings || []).map((g) => [`<b>${esc(g.label)}</b> <span class="fc-tag official">official forecast</span><small>${esc(g.source || NONE)}</small>`, num(g.jobs_per_year),
        g.from ? `${num(g.from.jobs)}<small>in ${esc(g.from.year)}</small>` : NONE, g.to ? `${num(g.to.jobs)}<small>in ${esc(g.to.year)}</small>` : NONE]);
      const c = needCharts({
        name: "jobs", rows: J.rows || [], need: (r) => r.space_sq_ft, list: (r) => r.pipeline_sq_ft, needSoFar: (r) => r.space_so_far, listSoFar: (r) => r.pipeline_so_far,
        unit: "sq ft", what: `work space new jobs within ${mi(data.market_miles)} need`,
      });
      jobs = `<p class="fc-summary">${esc(J.summary || "")}</p>` + c.year +
        folded("jobs-years", "Show the year-by-year figures", c.sum + yearTable(["Year", "New jobs", "Space a year (sq ft)", "On the city's lists", "Space so far", "On the lists so far"],
          (J.rows || []).map((r) => ({ year: r.year, cells: [cellRange(r.new_jobs), cellRange(r.space_sq_ft), num(r.pipeline_sq_ft), cellRange(r.space_so_far), num(r.pipeline_so_far)] })), "fc-compact")) +
        folded("jobs-how", "How this was worked out", (readings.length ? `<h4 class="fc-sub">The readings of jobs</h4>${plainTable(["What it is, and its source", "New jobs a year", "From", "To"], readings, [1, 2, 3])}` : "") + restsOn("jobs"));
    }
    box.innerHTML = `<h2 id="fcNeedsTitle">Homes needed, shops, jobs and work space</h2>
      <p class="fc-intro">What growth within ${mm} needs each year, beside what is already on the city's lists. The band is low to high, the line expected; the bars are projects already on the city's lists, spread over the years they are likely to open.</p>
      <div class="fc-needs">
        <article class="card fc-need"><h3>Homes needed</h3>${homes}</article>
        <article class="card fc-need"><h3>Shops and restaurants</h3>${shops}</article>
        <article class="card fc-need"><h3>Jobs and work space</h3>${jobs}</article>
        <article class="card fc-need fc-stages">${stagesHtml()}</article>
      </div>`;
  }
  function stagesHtml() {
    const pipe = ((data.homes || {}).pipeline) || {}, counted = pipe.stages || [];
    const head = `<h3>Already on the city's lists, by stage</h3>`;
    if (!pipe.available) return head + notCovered("The city's project lists", "projects");
    return head + `<p class="fc-summary">Counted: <b>${num(pipe.projects_counted)}</b> ${plural(pipe.projects_counted, "project")} within ${esc(mi(data.market_miles))} that state a number of homes or a building size.</p>` +
      folded("stages", "Show the projects by stage, and the lists used", stagesBody(pipe, counted));
  }
  function stagesBody(pipe, counted) {
    const review = (data.figures || []).find((f) => f.id === "built_review_pct");
    // a stage with no project counted in it has nothing to show, so it is left out
    const rows = (data.stages || []).filter((st) => { const c = counted.find((x) => x.label === st.label); return c && Number(c.projects) > 0; }).map((st) => {
      const c = counted.find((x) => x.label === st.label);
      return { cls: st.uncertain ? "fc-unsure" : "", cells: [
        `<b>${esc(st.label)}</b>${st.uncertain ? ' <span class="fc-tag unsure">may not all be built</span>' : ""}`,
        `${esc(st.from_year)} to ${esc(st.to_year)}`, num(c.projects), num(c.homes), num(c.shops_sq_ft), num(c.work_sq_ft)] };
    });
    const lists = Object.entries(pipe.lists_updated || {});
    return (rows.length ? plainTable(["Stage", "Likely to open", "Projects", "Homes", "Shop space (sq ft)", "Work space (sq ft)"], rows, [2, 3, 4, 5]) : missing("No project on the city's lists is counted in any stage yet.")) +
      `<p class="fine">Counted: <b>${num(pipe.projects_counted)}</b> projects within ${esc(mi(data.market_miles))} that state a number of homes or a building size.${isNum(pipe.projects_without_sizes) && pipe.projects_without_sizes ? ` ${num(pipe.projects_without_sizes)} more within that distance state neither, so they are left out.` : ""}${Number(pipe.projects_other_kinds) > 0 ? ` ${num(pipe.projects_other_kinds)} are not homes, shops or work space, so they are not counted.` : ""}${Number(pipe.projects_dropped) > 0 ? ` ${num(pipe.projects_dropped)} were withdrawn, denied, expired or cancelled, so they are not counted as coming.` : ""} The lists hold ${num(pipe.projects_listed)} ${plural(pipe.projects_listed, "project")} in all.
        ${review ? ` Stages marked “may not all be built” count ${figureValue(review)} of their homes and floor space (${esc(review.label.toLowerCase())}, ${review.yours ? "your figure" : "a starting figure"}).` : ""}</p>
      ${lists.length ? `<p class="fine">The city's lists used: ${lists.map(([name, d]) => `${esc(name)} (updated ${esc(day(d) || d)})`).join("; ")}.</p>` : ""}`;
  }

  // ---------------------------------------------------------------- traffic

  function drawTraffic() {
    const box = el.querySelector("#fcTrafficBody"), T = data.traffic || {};
    const head = `<h2 id="fcTrafficTitle">Traffic</h2>`;
    drawRoads();
    if (!T.available) { box.innerHTML = head + notCovered("Highway traffic by year", "traffic"); return; }
    const rows = T.rows || [], xs = rows.map((r) => r.year), hw = T.highway || {};
    const where = `Route ${hw.route || ""} at ${hw.where || ""}`;
    charts.highway = (w) => {
      const vals = [];
      rows.forEach((r) => vals.push(r.highway.low, r.highway.high));
      return chart({
        width: w, height: 250, xMin: Math.min(...xs), xMax: Math.max(...xs), values: vals, zero: false, unit: `Vehicles a day, ${where}`,
        label: `Chart of vehicles a day on ${where} by year, ${xs[0]} to ${xs[xs.length - 1]}, low to high band and expected line. The table gives the same figures.`,
        draw: (s) => shade(s, now() + 1, now() + 5, "Next five years") + band(s, rows.map((r) => [r.year, r.highway.low, r.highway.high])) +
          line(s, rows.map((r) => [r.year, r.highway.expected])) + dots(s, rows.map((r) => [r.year, r.highway.expected])),
        hover: rows.map((r) => ({ x: r.year, text: `${r.year}: about ${num(r.highway.expected)} vehicles a day (${range(r.highway)})` })),
      });
    };
    charts.trips = (w) => chart({
      width: w, height: 190, xMin: Math.min(...xs), xMax: Math.max(...xs), values: rows.map((r) => r.site_trips), zero: true, unit: "The site's own trips a day",
      label: `Chart of the trips a day the site itself adds, by year, as its land is taken up.`,
      draw: (s) => bars(s, rows.map((r) => [r.year, r.site_trips]), "fc-bar site"),
      hover: rows.map((r) => ({ x: r.year, text: `${r.year}: about ${num(r.site_trips)} ${plural(r.site_trips, "trip")} a day from the site` })),
    });
    box.innerHTML = head + `
      <p class="fc-summary">${esc(T.summary || "")}</p>
      <div class="fc-traffic">
        <div class="card"><h3>${esc(where)}${isNum(hw.miles_away) ? `, ${num(hw.miles_away, 2)} ${plural(hw.miles_away, "mile", "miles", 2)} away` : ""}</h3>
          <div class="fc-chart" data-chart="highway"></div>
          <div class="legend fc-legend">${key("band", "Low to high")}${key("line", "Expected")}${key("focus", "Next five years")}</div></div>
        <div class="card"><h3>The site's own trips</h3>
          <div class="fc-chart" data-chart="trips"></div>
          <div class="legend fc-legend">${key("bar site", "Trips a day the site adds as its land is taken up")}</div>
        </div>
      </div>
      <div class="fc-folds">
        ${folded("traffic-years", "Show the year-by-year figures", yearTable(["Year", "Vehicles a day<small>expected, then low to high</small>", "The site's trips a day"],
          rows.map((r) => ({ year: r.year, cells: [cellRange(r.highway), num(r.site_trips)] }))))}
        ${folded("traffic-how", "How this was worked out", `<p class="fine">Today's count is Caltrans' latest (${isNum(hw.today) ? num(hw.today) + " vehicles a day" : NONE}), both directions together. It grows with the homes around it; trips from the site follow how fast its own land is taken up.</p>
          ${restsOn("traffic")}`)}
      </div>`;
  }

  // the site's entrances (marked by what kind of signal they would use) and the signals standing nearby today
  function drawRoads() {
    const L = window.L, T = data.traffic || {}, entrances = (T.entrances || []).filter((e) => isNum(e.lat) && isNum(e.lon));
    const signals = (T.existing_signals || []).filter((s) => isNum(s.lat) && isNum(s.lon));
    if (!roadMap) {
      roadMap = createMap(el.querySelector("#fcRoadMap"), { base: "aerial" });
      roadLayers = L.layerGroup().addTo(roadMap.map);
    }
    roadLayers.clearLayers();
    let bounds = null;
    const grow = (ll2) => { bounds = bounds ? bounds.extend(ll2) : L.latLngBounds([ll2, ll2]); };
    ((data.site || {}).parcels || []).forEach((p) => {
      if (!p.outline || !p.outline.coordinates) return;
      const shape = ll(p.outline.type === "MultiPolygon" ? p.outline.coordinates.flat() : p.outline.coordinates);
      L.polygon(shape, { color: "#1d2a24", weight: 6, fill: false, interactive: false }).addTo(roadLayers);
      const g = L.polygon(shape, { color: "#f2b632", weight: 3, fillColor: "#f2b632", fillOpacity: 0.2 }).bindTooltip("The site", { sticky: true }).addTo(roadLayers);
      grow(g.getBounds().getSouthWest()); grow(g.getBounds().getNorthEast());
    });
    signals.forEach((s) => {
      L.circleMarker([Number(s.lat), Number(s.lon)], { radius: 6, color: "#fff", weight: 2, fillColor: "#1d2a24", fillOpacity: 1 })
        .bindTooltip(`Traffic signal today at ${esc(s.street)} and ${esc(s.cross_street)}, ${num(s.miles_away, 2)} ${plural(s.miles_away, "mile", "miles", 2)} away`).addTo(roadLayers);
      grow([Number(s.lat), Number(s.lon)]);
    });
    entrances.forEach((e) => {
      const kind = SIGNAL_MARK[e.signal] ? e.signal : "unknown";
      L.marker([Number(e.lat), Number(e.lon)], {
        icon: L.divIcon({ className: "plan-pin", iconSize: [26, 26], iconAnchor: [13, 13], html: `<span class="plan-ent plan-ent-${kind}">${SIGNAL_MARK[kind]}</span>` }),
        title: `Entrance onto ${e.street}: ${SIGNAL_WORDS[kind]}`, alt: `Entrance onto ${e.street}`,
      }).bindTooltip(`<b>Entrance onto ${esc(e.street)}</b> (${esc(e.class || "")}): about ${num(e.trips)} ${plural(e.trips, "trip")} a day. ${esc(e.text || "")}`).addTo(roadLayers);
      grow([Number(e.lat), Number(e.lon)]);
    });
    if (bounds && !roadFitted) { roadMap.fit(bounds.pad(0.12)); roadFitted = true; }
    const kinds = [...new Set(entrances.map((e) => (SIGNAL_MARK[e.signal] ? e.signal : "unknown")))];
    el.querySelector("#fcRoadLegend").innerHTML = '<span><i class="fc-key site"></i>The site</span>' +
      kinds.map((k) => `<span><b class="plan-ent plan-ent-${k} small">${SIGNAL_MARK[k]}</b>Entrance: ${esc(SIGNAL_WORDS[k].toLowerCase())}</span>`).join("") +
      (signals.length ? '<span><i class="fc-key signal"></i>Traffic signal today</span>' : "");
    const box = el.querySelector("#fcEntrText");
    if (!entrances.length && !signals.length) {
      box.innerHTML = `<h3>Entrances and signals</h3>` + missing("Where the site's entrances go, and the traffic signals nearby: not covered yet.");
      return;
    }
    box.innerHTML = `<div class="card"><h3>The site's entrances</h3>
        ${entrances.length ? `<ul class="plan-ents fc-ents">${entrances.map((e) => {
          const kind = SIGNAL_MARK[e.signal] ? e.signal : "unknown";
          return `<li><b class="plan-ent plan-ent-${kind} small" aria-hidden="true">${SIGNAL_MARK[kind]}</b><span><b>${esc(e.street)}</b>${e.class ? ` (${esc(e.class)})` : ""}, about ${num(e.trips)} ${plural(e.trips, "trip")} a day. <b>${esc(SIGNAL_WORDS[kind])}.</b> ${esc(e.text || "")}</span></li>`;
        }).join("")}</ul>` : missing("Where the entrances go: not covered yet.")}
        ${isNum(T.signals_to_study) ? `<p>${Number(T.signals_to_study) ? `<b>${num(T.signals_to_study)}</b> new ${Number(T.signals_to_study) === 1 ? "signal is" : "signals are"} worth studying at the entrances.` : "No new signal is likely to be needed at the entrances."}</p>` : ""}
        <p class="fine">The entrances come from the site plan and the trip rates under each parcel's Plan page, which are starting figures. This is not a traffic study.</p>
        ${folded("signals", `Show the traffic signals today, nearest first${signals.length ? ` (${num(signals.length)})` : ""}`,
          signals.length ? plainTable(["Where", "Miles away"], signals.slice().sort((a, b) => a.miles_away - b.miles_away).map((s) => [`${esc(s.street)} and ${esc(s.cross_street)}`, num(s.miles_away, 2)]), [1]) : missing("Traffic signals nearby: not covered yet."))}</div>`;
  }

  // ---------------------------------------------------------------- the site's own land

  function drawLand() {
    const box = el.querySelector("#fcLand"), G = data.programme || {}, uses = G.uses || [];
    const parcels = (data.site || {}).parcels || [];
    const planLinks = `<p class="fc-links">${parcels.map((p) => `<a class="btn small" href="#/land/${esc(data.city)}/${esc(p.apn)}/plan">${icon("plan")} Plan page of ${esc(p.apn_formatted || p.apn)}</a>`).join("")}</p>`;
    const head = `<h2 id="fcLandTitle">This site's land, year by year</h2>`;
    const notForecast = (G.not_forecast || []).length ? `<h3>Not forecast</h3><ul class="plain">${G.not_forecast.map((n) =>
      `<li><b>${esc(n.label)}</b>${isNum(n.acres) ? ` (${num(n.acres, 1)} ${plural(n.acres, "acre", "acres", 1)})` : ""}: ${esc(n.why || NONE)}</li>`).join("")}</ul>` : "";
    if (!G.available) {
      box.innerHTML = head + (G.basis ? `<p class="fc-intro">${esc(G.basis)}</p>` : "") + notCovered("How fast this site's land is taken up", "homes") +
        (notForecast ? `<div class="card">${notForecast}</div>` : "") + planLinks;
      return;
    }
    const years = (uses[0] && uses[0].by_year || []).map((r) => r.year);
    charts.land = (w) => {
      const vals = [0];
      uses.forEach((u) => (u.by_year || []).forEach((r) => vals.push(r.acres_so_far)));
      return chart({
        width: w, height: 290, xMin: Math.min(...years), xMax: Math.max(...years), values: vals, zero: true, unit: "Acres taken up so far",
        label: `Chart of the acres of this site taken up so far by year, one line for each use. The table gives the same figures.`,
        draw: (s) => shade(s, now() + 1, now() + 5, "Next five years") + uses.map((u) => {
          const c = colourOf(u.colour), pts = (u.by_year || []).map((r) => [r.year, r.acres_so_far]);
          return line(s, pts, "fc-line use", `stroke:${c}`) + dots(s, pts, "fc-dot use", 3.4, `fill:${c}`);
        }).join(""),
        hover: years.map((y) => ({ x: y, text: `${y}: ` + uses.map((u) => { const r = (u.by_year || []).find((x) => x.year === y); return `${u.short || u.label} ${r ? num(r.acres_so_far, 1) : NONE} acres`; }).join(", ") })),
      });
    };
    // when the use is filled on the expected line, then on the high and low lines (absent: not within the ten years)
    const spans = (u) => {
      if (!("filled_in_if_high" in u) && !("filled_in_if_low" in u)) return "";
      const hi = u.filled_in_if_high ? `by ${u.filled_in_if_high} if growth runs high` : "not within the ten years even if growth runs high";
      const lo = u.filled_in_if_low ? `by ${u.filled_in_if_low} if it runs low` : "not within the ten years if it runs low";
      return ` (${hi}; ${lo})`;
    };
    const when = (u) => (u.filled_in ? `all taken up by about ${u.filled_in}` : u.filled_later_in ? `filled around ${u.filled_later_in} at this pace` : u.never_at_this_pace ? "not filled at this pace" : "") + spans(u);
    const legend = uses.map((u) => `<li><i style="background:${colourOf(u.colour)}"></i><span><b>${esc(u.label)}</b>: ${num(u.acres, 1)} ${plural(u.acres, "acre", "acres", 1)} (${num(u.amount)} ${esc(u.unit)}). ${num(u.acres_by_year_5, 1)} ${plural(u.acres_by_year_5, "acre", "acres", 1)} by ${now() + 5}, ${num(u.acres_by_year_10, 1)} by ${now() + 10} (${num(u.pct_by_year_10)}%)${when(u) ? "; " + esc(when(u)) : ""}.${u.fit_words ? ` <em class="fc-zoning">Today's zoning: ${esc(u.fit_words.toLowerCase())}.</em>` : ""}</span></li>`).join("");
    const table = yearTable(["Year"].concat(uses.map((u) => `${esc(u.short || u.label)} (acres)`)),
      years.map((y) => ({ year: y, cells: uses.map((u) => { const r = (u.by_year || []).find((x) => x.year === y); return r ? `${num(r.acres_so_far, 1)}<small>${num(r.so_far)} ${esc(u.unit)}</small>` : NONE; }) })), "fc-compact");
    const steps = (G.steps || []).map((st) => `<article class="card fc-step"><p class="kicker dark">${esc(st.label)}</p><h3>${esc(st.title)}</h3><ul class="plain">${(st.lines || []).map((l) => `<li>${esc(l)}</li>`).join("")}</ul></article>`).join("");
    box.innerHTML = head + `
      <p class="fc-intro">${esc(G.basis || "")} The site wins a share of each year's new need of its kind (homes, shop space, work space), once its first land is ready.${isNum(G.acres) ? ` ${num(G.acres, 1)} ${plural(G.acres, "acre", "acres", 1)} in the plan` : ""}${isNum(G.trips_at_build_out) ? `, about ${num(G.trips_at_build_out)} ${plural(G.trips_at_build_out, "trip")} a day once everything is built` : ""}.</p>
      <div class="card fc-land-card"><div class="fc-chart" data-chart="land"></div><ul class="fc-uses">${legend}</ul></div>
      <div class="fc-folds">
        ${folded("land-years", "Show the year-by-year figures", table)}
        ${steps ? folded("land-steps", "Show the steps the land is offered in", `<div class="fc-steps">${steps}</div>`) : ""}
        ${folded("land-after", "After ten years, and what is not forecast", `<div class="fc-after">
          <div><h3>After ten years</h3>${(G.after || []).length ? `<ul class="plain">${G.after.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : "<p>All of the land is taken up within the ten years at this pace.</p>"}</div>
          <div>${notForecast || "<h3>Not forecast</h3><p>Every use on this site has a forecast.</p>"}</div></div>`)}
        ${folded("land-how", "How this was worked out", restsOn("programme"))}
      </div>
      ${planLinks}`;
  }

  // ---------------------------------------------------------------- going to a part of the page

  // a jump to a part (or a box inside it): its chapter opens first, then it is brought into view
  function goTo(id, focusBox) {
    const target = el.querySelector("#" + CSS.escape(id));
    if (!target) return;
    const part = book.partOf(target);
    if (part && part !== book.current()) book.open(part);
    target.scrollIntoView({ behavior: motionOn() ? "smooth" : "auto", block: "start" });
    const box = focusBox ? target.querySelector("input") : null;
    if (box) box.focus({ preventScroll: true });
  }
  // redraw something without moving what the person is reading: the first section at the top of the screen stays put
  // (sections of the other chapters are not on screen, so they are passed over)
  function keepScreen(fn) {
    const top = [...el.querySelectorAll(".fc > section, .fc > .fc-top")].find((s) => s.getBoundingClientRect().bottom > 60);
    const before = top ? top.getBoundingClientRect().top : 0;
    fn();
    if (top && top.isConnected) {
      const shift = top.getBoundingClientRect().top - before;
      if (Math.abs(shift) > 1) window.scrollBy(0, shift);
    }
  }

  // ---------------------------------------------------------------- site plan (from the forecast: where each use sits)

  // a use's name and colour: each drawn piece carries its own; the forecast's uses carry them too
  function useInfo(id) {
    const G = data.programme || {}, u = (G.uses || []).find((x) => x.id === id);
    const p = (G.drawings || []).flatMap((d) => d.pieces || []).find((x) => x.use === id) || {};
    return { label: p.label || (u && u.label) || cap(String(id)), short: p.short || (u && u.short) || cap(String(id)), colour: colourOf(p.colour || (u && u.colour)), taken: u || null };
  }
  const firstYear = (u) => { const r = (u.by_year || []).find((x) => Number(x.taken) > 0); return r ? r.year : null; };
  // the shade of a piece in "When each part is offered": its use's first year, or why it has none
  function phaseOf(id) {
    const G = data.programme || {}, info = useInfo(id);
    if ((G.not_forecast || []).some((n) => n.id === id)) return { key: "nf", words: "Not forecast", colour: "#b9b4a6" };
    if (!info.taken) return { key: "with", words: "Built along with the uses around it", colour: "#e6dfc6" };
    const y = firstYear(info.taken);
    if (!y) return { key: "never", words: "Not within the ten years", colour: "#8c8c8c" };
    const t = Math.max(0, Math.min(1, (y - now() - 1) / 9));
    const mix = (a, b) => Math.round(a + (b - a) * t);
    return { key: String(y), year: y, words: `From ${y}`, colour: `rgb(${mix(15, 222)},${mix(92, 236)},${mix(69, 200)})` };
  }
  function drawSitePlan() {
    const L = window.L, G = data.programme || {}, drawings = G.drawings || [], parcels = (data.site || {}).parcels || [];
    const pieces = drawings.flatMap((d) => d.pieces || []);
    el.querySelectorAll("[data-planview]").forEach((b) => { const on = b.dataset.planview === planView; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); });
    if (!planMap) {
      planMap = createMap(el.querySelector("#fcPlanMap"), { base: "aerial" });
      planLayers = L.layerGroup().addTo(planMap.map);
    }
    planLayers.clearLayers();
    const seenStreets = new Set();
    drawings.forEach((d) => (d.street_lines || []).forEach((s) => {
      if (!s.path || s.path.length < 2) return;
      const id = s.name + JSON.stringify(s.path[0]);
      if (seenStreets.has(id)) return;
      seenStreets.add(id);
      const line = s.path.map((p) => [p[1], p[0]]), weight = 1.5 + 1.4 * (Number(s.rank) || 1);
      L.polyline(line, { color: "#1d2a24", weight: weight + 3, opacity: 0.55, interactive: false }).addTo(planLayers);
      L.polyline(line, { color: "#8fc3ff", weight, opacity: 0.95 }).bindTooltip(`${esc(s.name)}: ${esc(s.class)} (the city's planned street network)`, { sticky: true }).addTo(planLayers);
    }));
    const shades = new Map(), labelSpecs = [];
    pieces.forEach((p) => {
      if (!p.ring || p.ring.length < 3) return;
      const info = useInfo(p.use), phase = phaseOf(p.use);
      const fill = planView === "when" ? phase.colour : info.colour;
      if (planView === "when") shades.set(phase.key, phase);
      L.polygon(ll([p.ring]), { color: "#fff", weight: 2, opacity: 0.95, fillColor: fill, fillOpacity: planView === "when" ? 0.78 : 0.55 })
        .bindTooltip(`${esc(info.label)}: ${num(p.acres, 1)} ${plural(p.acres, "acre", "acres", 1)}${planView === "when" ? " · " + esc(phase.words.toLowerCase()) : ""}`, { sticky: true }).addTo(planLayers);
      labelSpecs.push({
        ring: p.ring, className: "plan-label",
        variants: [`<b>${esc(info.short)}</b> ${planView === "when" ? esc(phase.year ? "from " + phase.year : phase.key === "never" ? "after ten years" : phase.key === "with" ? "with the rest" : "not forecast") : num(p.acres, 1) + " ac"}`, `<b>${esc(info.short)}</b>`],
      });
    });
    planMap.pieceLabels().set(labelSpecs);
    drawings.forEach((d) => (d.streets || []).forEach((s) => {
      const line = (s.line || []).map((p) => [p[1], p[0]]);
      if (line.length < 2) return;
      L.polyline(line, { color: "#1d2a24", weight: 9, opacity: 0.5, interactive: false }).addTo(planLayers);
      L.polyline(line, { color: "#ffffff", weight: 5, opacity: 1 }).bindTooltip(`A new street inside the site, about ${num(s.feet)} ft long`, { sticky: true }).addTo(planLayers);
    }));
    let bounds = null;
    parcels.forEach((p) => {
      if (!p.outline || !p.outline.coordinates) return;
      const shape = ll(p.outline.type === "MultiPolygon" ? p.outline.coordinates.flat() : p.outline.coordinates);
      L.polygon(shape, { color: "#1d2a24", weight: 6, fill: false, interactive: false }).addTo(planLayers);
      const g = L.polygon(shape, { color: "#f2b632", weight: 3, fill: false, interactive: false }).addTo(planLayers);
      bounds = bounds ? bounds.extend(g.getBounds()) : g.getBounds();
    });
    if (bounds && !planFitted) { planMap.fit(bounds.pad(0.12)); planFitted = true; }

    const ids = [...new Set(pieces.map((p) => p.use))];
    const legend = planView === "when"
      ? [...shades.values()].sort((a, b) => (a.year || 9999) - (b.year || 9999)).map((p) => `<span><i style="background:${p.colour}"></i>${esc(p.words)}</span>`).join("")
      : ids.map((id) => `<span><i style="background:${useInfo(id).colour}"></i>${esc(useInfo(id).label)}</span>`).join("");
    el.querySelector("#fcPlanLegend").innerHTML = !pieces.length ? "" : planView === "3d"
      ? legend + '<span><i class="fc-key street"></i>New streets inside the site</span><span><i class="fc-key site"></i>Site outline</span>'
      : legend + '<span><i class="fc-key street"></i>New streets inside the site</span><span><i class="fc-key city-street"></i>The city\'s planned streets</span><span><i class="fc-key site"></i>Parcel outlines</span>';
    el.querySelector("#fcPlanFrame").hidden = planView === "3d";
    el.querySelector("#fcPlan3d").hidden = planView !== "3d";
    if (planView === "3d") draw3d();

    const box = el.querySelector("#fcPlanText");
    if (!pieces.length) {
      box.innerHTML = missing("Where each use sits on the land: not covered yet. The plan could not be drawn on the parcel outlines, so the map shows the outlines only.");
      return;
    }
    const byParcel = drawings.length > 1 && drawings.length === parcels.length && !(data.site || {}).one_plan;
    const why = drawings.map((d, i) => (d.why || []).length ? `${byParcel ? `<h4 class="fc-sub">Parcel ${esc(parcels[i].apn_formatted || parcels[i].apn)}</h4>` : ""}<ul class="plain">${d.why.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : "").join("");
    const totals = new Map();
    pieces.forEach((p) => totals.set(p.use, (totals.get(p.use) || 0) + (Number(p.acres) || 0)));
    const rows = [...totals.entries()].map(([id, acres]) => {
      const info = useInfo(id), phase = phaseOf(id), u = info.taken;
      const filled = u ? (u.filled_in ? `by ${u.filled_in}` : u.filled_later_in ? `around ${u.filled_later_in}` : "not at this pace") : "";
      return [`<span class="swatch" style="background:${info.colour}"></span>${esc(info.short)}`, num(acres, 1),
        `<span class="swatch" style="background:${phase.colour}"></span>${esc(phase.year ? String(phase.year) : phase.words)}`, filled || '<span class="muted">with the rest</span>'];
    });
    box.innerHTML = `<div class="card fc-plan-card">
        <h3>The pieces</h3>
        ${plainTable(["Use", "Acres", "First offered", "All taken up"], rows, [1])}
        <p class="fine">“First offered” is the first year the forecast takes up any of that use (expected line, your figures if you changed them). The pieces are a first sketch cut from the assessor's outlines: not lot lines and not a site plan the city has seen.</p>
        ${why ? folded("plan-why", "Why it is laid out this way", why) : ""}
      </div>`;
  }

  function askGround(fresh) {
    groundAsking = true;
    api.ground(cityId, data.apns, fresh).then((g) => {
      groundAsking = false;
      if (!alive()) return;
      ground = g;
      if (planView === "3d") draw3d();
    }, (e) => {
      groundAsking = false;
      if (!alive()) return;
      groundProblem = e.message;
      if (planView === "3d") draw3d();
    });
  }
  // the site plan on the real ground: asked for the first time "In 3D" is chosen, then kept
  function draw3d() {
    const box = el.querySelector("#fcPlan3d");
    if (!ground && !groundProblem) {
      if (!box.querySelector(".plan-wait")) {
        box.innerHTML = '<p class="plan-wait fc-3d-wait"><span class="spinner" aria-hidden="true"></span> Reading the ground heights under the site. The first time can take up to a minute; after that it is quick.</p>';
      }
      if (!groundAsking) askGround(false);
      return;
    }
    if (groundProblem) {
      box.innerHTML = `<div class="state problem">${icon("alert")}<p>The ground heights could not be read just now: ${esc(groundProblem)}</p><button type="button" class="btn" data-ground-again>Try again</button></div>`;
      return;
    }
    const H = ground.surface, plan = ground.plan, P = ground.parcel;
    if (!H || !plan || !P || !P.outline || !(H.feet || []).some((v) => v !== null)) {
      const why = !H ? `the ground heights ${noAnswer(ground.answered) ? whyNoAnswer(ground.answered) : "are not covered for this site"}`
        : !plan || !P ? "no plan could be drawn on this land" : "the ground heights came back empty";
      box.innerHTML = missing(`The 3D view is not available for this site: ${why}.`) +
        (!H ? '<p><button type="button" class="btn small" data-ground-again>Ask again</button></p>' : "");
      return;
    }
    if (unmount3d && box.querySelector("canvas")) return;   // already on screen; it does not change with the figures
    const d = plan.drawing || {};
    if (!(d.pieces || []).length) {
      box.innerHTML = missing("The 3D view is not available for this site: the plan could not be drawn on the outline.");
      return;
    }
    const colours = Object.fromEntries((plan.uses || []).map((u) => [u.id, colourOf(u.colour)]));
    const amounts = Object.fromEntries((plan.uses || []).map((u) => [u.id, { homes: u.homes, sq_ft: u.sq_ft }]));
    box.innerHTML = `<div class="view3d fc-3d" id="fcPlan3dView"></div>
      <p class="fine">The ground in the plan's colours, the new streets as light lines, and simple boxes for buildings: about as many and as large as the plan's figures make, standing on the ground. The boxes are <b>a picture of scale, not a site plan</b>; trees mark the parks. Only the ground's height is stretched by the slider. ${ground.one_plan === false ? "These parcels are not planned as one block, so the 3D view shows the plan worked out for the site as a whole." : ""}${H.source ? ` Ground heights: ${esc(H.source)}.` : ""}</p>`;
    unmount3d = mountTerrain(box.querySelector("#fcPlan3dView"), P, H, {
      pieces: d.pieces, streets: (d.streets || []).map((s) => s.line), colours, front: d.front, amounts, cap: 1500,
    });
  }

  // ---------------------------------------------------------------- the wider picture (the outlook answer)

  function loadOutlook(fresh, quiet = false) {
    const my = ++outlookSeq;
    if (!quiet) {
      outlookProblem = "";
      if (fresh) outlook = null;
      if (el.querySelector("#fcEconomy")) keepScreen(() => { drawOutlook(); drawSources(); paintCharts(); });
    }
    api.outlook(cityId, data.apns, fresh).then((o) => {
      if (!alive() || my !== outlookSeq) return;
      outlook = o; outlookProblem = "";
      keepScreen(() => { drawOutlook(); drawSources(); paintCharts(); });
    }, (e) => {
      if (!alive() || my !== outlookSeq) return;
      if (!outlook) outlookProblem = e.message;   // a quiet refresh that fails keeps what is already shown
      keepScreen(() => { drawOutlook(); drawSources(); paintCharts(); });
    });
  }
  // the heading, then either a quiet waiting line, the problem, or null when the answer is here
  function outlookWait(id, title) {
    const head = `<h2 id="${id}">${esc(title)}</h2>`;
    if (outlookProblem) {
      return head + `<div class="state problem fc-wait-problem">${icon("alert")}<p>The wider picture could not be read just now: ${esc(outlookProblem)}</p><button type="button" class="btn" data-outlook-again>Try again</button></div>`;
    }
    if (!outlook) return head + `<p class="plan-wait fc-wait"><span class="spinner" aria-hidden="true"></span> Reading the wider picture… The forecast above is complete; this part arrives on its own.</p>`;
    return null;
  }
  function outlookMissing(what, silent) {
    const says = stateSentences(silent || [], (outlook || {}).answered || {}, (p) => (OUTLOOK_WORDS[p] || [p])[0]);
    return missing(`${what}: not covered yet.${says ? " " + says : ""}`);
  }
  function drawOutlook() {
    drawEconomy(); drawHousing(); drawWeather(); drawHazards(); drawNearby(); drawResident(); drawTodo();
  }

  // ---- the city's economy, year by year
  const millions = (v) => (isNum(v) ? "$" + num(Number(v) / 1e6, Number(v) >= 1e8 ? 0 : 1) + " million" : null);
  const notGiven = '<span class="muted">not given</span>';
  const given = (v, text) => (isNum(v) ? text : notGiven);
  function drawEconomy() {
    const box = el.querySelector("#fcEconomy"), title = "The city's economy, year by year";
    const wait = outlookWait("fcEconomyTitle", title);
    if (wait) { box.innerHTML = wait; return; }
    const E = outlook.economy || {};
    if (!E.available) { box.innerHTML = `<h2 id="fcEconomyTitle">${title}</h2>` + outlookMissing("The city's economy", E.did_not_answer); return; }
    const rows = E.rows || [], ahead = E.sales_ahead || [], place = E.place || outlook.city_name || "The city";
    const xs = rows.map((r) => r.year), xMin = Math.min(...xs), xMax = Math.max(...xs);
    const partialSales = (r) => isNum(r.sales_quarters) && Number(r.sales_quarters) < 4;
    const partialPermits = (r) => isNum(r.permit_months) && Number(r.permit_months) < 12;
    const partialLoan = (r) => isNum(r.mortgage_weeks) && Number(r.mortgage_weeks) < 50;
    charts["eco-people"] = (w) => chart({
      width: w, height: 210, xMin, xMax, values: rows.flatMap((r) => [r.people, r.homes]), zero: true, unit: `People and homes in ${place}`,
      label: `Chart of people and homes in ${place} by year. The table gives the same figures.`,
      draw: (s) => line(s, rows.map((r) => [r.year, r.people])) + dots(s, rows.map((r) => [r.year, r.people])) +
        line(s, rows.map((r) => [r.year, r.homes]), "fc-line alt") + dots(s, rows.map((r) => [r.year, r.homes]), "fc-dot alt"),
      hover: rows.map((r) => ({ x: r.year, text: `${r.year}: ${isNum(r.people) ? num(r.people) + " " + plural(r.people, "person", "people") : "people not given"}, ${isNum(r.homes) ? num(r.homes) + " " + plural(r.homes, "home", "homes") : "homes not given"}` })),
    });
    charts["eco-permits"] = (w) => chart({
      width: w, height: 210, xMin, xMax, values: rows.map((r) => r.homes_permitted), zero: true, unit: "Homes permitted a year",
      label: `Chart of homes permitted in ${place} each year; years not complete are drawn paler and marked.`,
      draw: (s) => bars(s, rows.filter((r) => !partialPermits(r)).map((r) => [r.year, r.homes_permitted])) +
        bars(s, rows.filter(partialPermits).map((r) => [r.year, r.homes_permitted]), "fc-bar partial") +
        rows.filter((r) => partialPermits(r) && isNum(r.homes_permitted)).map((r) => `<text class="fc-pt-lab small" x="${s.x(r.year).toFixed(1)}" y="${(s.y(r.homes_permitted) - 5).toFixed(1)}" text-anchor="middle">${esc(r.permit_months)} mo</text>`).join(""),
      hover: rows.map((r) => ({ x: r.year, text: `${r.year}: ${isNum(r.homes_permitted) ? num(r.homes_permitted) + " " + plural(r.homes_permitted, "home", "homes") + " permitted" : "not given"}${partialPermits(r) ? ` (${r.permit_months} ${plural(r.permit_months, "month")} reported)` : ""}` })),
    });
    const aheadX = ahead.map((a) => a.year);
    charts["eco-sales"] = (w) => {
      const vals = rows.map((r) => r.shop_sales_usd / 1e6).concat(ahead.flatMap((a) => [a.shop_sales_usd.low / 1e6, a.shop_sales_usd.high / 1e6]));
      return chart({
        width: w, height: 210, xMin, xMax: Math.max(xMax, ...aheadX), values: vals, zero: true, unit: "Shop and restaurant sales, $ millions",
        label: `Chart of shop and restaurant sales in ${place}: measured years as bars, a part year paler, and the years ahead as a low to high band and an expected line.`,
        draw: (s) => bars(s, rows.filter((r) => isNum(r.shop_sales_usd) && !partialSales(r)).map((r) => [r.year, r.shop_sales_usd / 1e6])) +
          bars(s, rows.filter((r) => isNum(r.shop_sales_usd) && partialSales(r)).map((r) => [r.year, r.shop_sales_usd / 1e6]), "fc-bar partial") +
          rows.filter((r) => isNum(r.shop_sales_usd) && partialSales(r)).map((r) => `<text class="fc-pt-lab small" x="${s.x(r.year).toFixed(1)}" y="${(s.y(r.shop_sales_usd / 1e6) - 5).toFixed(1)}" text-anchor="middle">${esc(r.sales_quarters)} of 4</text>`).join("") +
          band(s, ahead.map((a) => [a.year, a.shop_sales_usd.low / 1e6, a.shop_sales_usd.high / 1e6])) + line(s, ahead.map((a) => [a.year, a.shop_sales_usd.expected / 1e6])) + nowLine(s, now()),
        hover: rows.map((r) => ({ x: r.year, text: `${r.year}: ${millions(r.shop_sales_usd) || "not given"}${partialSales(r) ? ` (${r.sales_quarters} of 4 quarters only)` : ""}` }))
          .concat(ahead.filter((a) => !xs.includes(a.year)).map((a) => ({ x: a.year, text: `${a.year}: about ${millions(a.shop_sales_usd.expected)} expected (${millions(a.shop_sales_usd.low)} to ${millions(a.shop_sales_usd.high)})` }))),
      });
    };
    charts["eco-rates"] = (w) => chart({
      width: w, height: 210, xMin, xMax, values: rows.flatMap((r) => [r.unemployment_pct, r.mortgage_pct]), zero: true, unit: "Percent",
      label: `Chart of unemployment in ${place} and the 30-year home-loan rate, by year.`,
      draw: (s) => line(s, rows.map((r) => [r.year, r.unemployment_pct]), "fc-line jobless") + dots(s, rows.map((r) => [r.year, r.unemployment_pct]), "fc-dot jobless") +
        line(s, rows.map((r) => [r.year, r.mortgage_pct]), "fc-line loan") + dots(s, rows.filter((r) => !partialLoan(r)).map((r) => [r.year, r.mortgage_pct]), "fc-dot loan") +
        dots(s, rows.filter((r) => partialLoan(r)).map((r) => [r.year, r.mortgage_pct]), "fc-dot loan partial", 4) +
        rows.filter((r) => partialLoan(r) && isNum(r.mortgage_pct)).map((r) => `<text class="fc-pt-lab small" x="${s.x(r.year).toFixed(1)}" y="${(s.y(r.mortgage_pct) - 8).toFixed(1)}" text-anchor="middle">${esc(r.mortgage_weeks)} wk</text>`).join(""),
      hover: rows.map((r) => ({ x: r.year, text: `${r.year}: unemployment ${isNum(r.unemployment_pct) ? num(r.unemployment_pct, 1) + "%" : "not given"}, home loans ${isNum(r.mortgage_pct) ? num(r.mortgage_pct, 2) + "%" : "not given"}${partialLoan(r) ? ` (${r.mortgage_weeks} weeks so far)` : ""}` })),
    });
    const tableRows = rows.map((r) => [
      `<b>${esc(r.year)}</b>${r.year === outlook.year ? "<small>this year, so far</small>" : ""}`,
      given(r.people, num(r.people)) + (isNum(r.homes) ? `<small>${num(r.homes)} ${plural(r.homes, "home")}</small>` : ""),
      given(r.homes_permitted, num(r.homes_permitted) + (partialPermits(r) ? `<small>${esc(r.permit_months)} ${plural(r.permit_months, "month")}</small>` : "")),
      given(r.shop_sales_usd, millions(r.shop_sales_usd) + (partialSales(r) ? `<small>${esc(r.sales_quarters)} of 4 quarters</small>` : "")),
      given(r.sales_per_home_usd, "$" + num(r.sales_per_home_usd)),
      given(r.unemployment_pct, num(r.unemployment_pct, 1) + "%") + (isNum(r.labour_force) ? `<small>of ${num(r.labour_force)}</small>` : ""),
      given(r.mortgage_pct, num(r.mortgage_pct, 2) + "%" + (partialLoan(r) ? `<small>${esc(r.mortgage_weeks)} of 52 weeks</small>` : "")), given(r.prices_change_pct, num(r.prices_change_pct, 1) + "%")]);
    box.innerHTML = `<h2 id="fcEconomyTitle">${title}</h2>
      <p class="fc-intro">${esc(place)} as a whole, as measured by state and federal agencies. A year not yet complete is marked.</p>
      <div class="card fc-says"><h3>What it says</h3>${(E.facts || []).length ? `<ul class="plain">${E.facts.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>` : missing("Nothing to say yet.")}
        ${(E.did_not_answer || []).length ? `<p class="fine fc-no">${esc(stateSentences(E.did_not_answer, outlook.answered || {}, (p) => (OUTLOOK_WORDS[p] || [p])[0]))}</p>` : ""}</div>
      <div class="fc-eco-charts">
        <div class="card"><h3>People and homes</h3><div class="fc-chart" data-chart="eco-people"></div><div class="legend fc-legend">${key("line", "People")}${key("line alt", "Homes")}</div></div>
        <div class="card"><h3>Homes permitted</h3><div class="fc-chart" data-chart="eco-permits"></div><div class="legend fc-legend">${key("bar", "Homes permitted")}${key("bar partial", "Year not complete (months marked)")}</div></div>
        <div class="card"><h3>Shop and restaurant sales</h3><div class="fc-chart" data-chart="eco-sales"></div><div class="legend fc-legend">${key("bar", "Measured")}${key("bar partial", "Part of the year only")}${ahead.length ? key("band", "Ahead, low to high") + key("line", "Ahead, expected") : ""}</div>
          ${!ahead.length && E.sales_ahead_note ? `<p class="fine fc-ahead-note"><b>Years ahead:</b> ${esc(E.sales_ahead_note)}</p>` : ""}</div>
        <div class="card"><h3>Unemployment and home loans</h3><div class="fc-chart" data-chart="eco-rates"></div><div class="legend fc-legend">${key("line jobless", "Unemployment")}${key("line loan", "30-year home-loan rate")}${rows.some(partialLoan) ? key("dot-partial", "Year not complete (weeks marked)") : ""}</div></div>
      </div>
      <div class="fc-folds">
        ${folded("eco-years", "Show the year-by-year figures", `<div class="fc-eco-table">${plainTable(["Year", "People<small>and homes</small>", "Homes permitted", "Shop and restaurant sales", "Sales a household", "Unemployment<small>of those working or looking</small>", "Home-loan rate<small>30-year, average</small>", "Prices rose"], tableRows, [1, 2, 3, 4, 5, 6, 7])}</div>`)}
        ${folded("eco-how", "How this was worked out", `${E.sales_ahead_basis ? `<p class="fine"><b>Sales ahead:</b> ${esc(E.sales_ahead_basis)}</p>` : ""}
          <p class="fine">Sources: ${(E.sources || []).map((s) => `${esc(s.source || (OUTLOOK_WORDS[s.name] || [s.name])[0])}${s.answered ? "" : " (did not answer)"}`).join("; ")}.</p>`)}
      </div>`;
  }

  // ---- weather and how it is changing
  function drawWeather() {
    const box = el.querySelector("#fcWeather"), title = "Weather and how it is changing";
    const wait = outlookWait("fcWeatherTitle", title);
    if (wait) { box.innerHTML = wait; return; }
    const C = outlook.climate || {};
    if (!C.available) { box.innerHTML = `<h2 id="fcWeatherTitle">${title}</h2>` + outlookMissing("The weather", ["climate"]); return; }
    const months = C.months || [], years = (C.by_year || []).filter((y) => isNum(y.mean_f)), t = C.typical_year || {}, trend = C.trend || {}, ahead = C.ahead;
    charts["wx-temp"] = (w) => chart({
      width: w, height: 220, xMin: 1, xMax: months.length || 12, xLabel: (v) => (months[v - 1] || {}).month || v,
      values: months.flatMap((m) => [m.high_f, m.low_f]), zero: false, unit: "°F, a typical month",
      label: "Chart of each month's typical high, average and low temperature. The table under the facts gives the decades.",
      draw: (s) => line(s, months.map((m, i) => [i + 1, m.high_f]), "fc-line hot") + dots(s, months.map((m, i) => [i + 1, m.high_f]), "fc-dot hot") +
        line(s, months.map((m, i) => [i + 1, m.mean_f]), "fc-line") + line(s, months.map((m, i) => [i + 1, m.low_f]), "fc-line cold") + dots(s, months.map((m, i) => [i + 1, m.low_f]), "fc-dot cold"),
      hover: months.map((m, i) => ({ x: i + 1, text: `${m.month}: high ${num(m.high_f, 1)}, average ${num(m.mean_f, 1)}, low ${num(m.low_f, 1)} °F; ${num(m.rain_in, 2)} in of rain` })),
    });
    charts["wx-rain"] = (w) => chart({
      width: w, height: 150, xMin: 1, xMax: months.length || 12, xLabel: (v) => (months[v - 1] || {}).month || v,
      values: months.map((m) => m.rain_in), zero: true, unit: "Rain, inches a month",
      label: "Chart of typical rain each month.", draw: (s) => bars(s, months.map((m, i) => [i + 1, m.rain_in]), "fc-bar rain"),
      hover: months.map((m, i) => ({ x: i + 1, text: `${m.month}: ${num(m.rain_in, 2)} inches of rain` })),
    });
    // the trend line: the slope the answer gives, through the middle of the measured years (where a straight-line fit passes)
    const slope = isNum(trend.mean_f_per_decade) ? Number(trend.mean_f_per_decade) / 10 : null;
    const mx = years.length ? years.reduce((a, y) => a + y.year, 0) / years.length : 0, my = years.length ? years.reduce((a, y) => a + Number(y.mean_f), 0) / years.length : 0;
    const at = (y) => my + slope * (y - mx);
    const endYear = ahead && isNum(ahead.year) ? Number(ahead.year) : (years.length ? years[years.length - 1].year : now());
    charts["wx-years"] = (w) => {
      if (!years.length) return "";
      const first = years[0].year, last = years[years.length - 1].year;
      const vals = years.map((y) => y.mean_f).concat(slope !== null ? [at(first), at(endYear)] : []);
      return chart({
        width: w, height: 240, xMin: first, xMax: endYear, values: vals, zero: false, unit: "Yearly average, °F",
        label: `Chart of the yearly average temperature from ${first} to ${last}${slope !== null ? `, with its straight-line trend carried on to ${endYear}` : ""}.`,
        draw: (s) => line(s, years.map((y) => [y.year, y.mean_f]), "fc-line thin") + dots(s, years.map((y) => [y.year, y.mean_f]), "fc-dot small") +
          (slope !== null ? line(s, [[first, at(first)], [last, at(last)]], "fc-line trend") + line(s, [[last, at(last)], [endYear, at(endYear)]], "fc-line trend ahead") : "") + nowLine(s, now()),
        hover: years.map((y) => ({ x: y.year, text: `${y.year}: average ${num(y.mean_f, 1)} °F, ${num(y.rain_in, 1)} in of rain` })),
      });
    };
    const stat = (label, big, small = "") => `<div class="stat"><span class="label">${label}</span><b>${big}</b>${small ? `<span>${small}</span>` : ""}</div>`;
    box.innerHTML = `<h2 id="fcWeatherTitle">${title}</h2>
      ${(C.facts || []).length ? `<div class="card fc-says"><h3>What it says</h3><ul class="plain">${C.facts.map((f) => `<li>${esc(f)}</li>`).join("")}</ul></div>` : ""}
      <section class="stats fc-wx-stats" aria-label="A typical year">
        ${stat("Typical year", isNum(t.mean_f) ? num(t.mean_f, 1) + " °F" : NONE, "average of day and night")}
        ${stat("Rain", isNum(t.rain_in) ? num(t.rain_in, 1) + " in" : NONE, "in a typical year")}
        ${stat("Wind", isNum(t.wind_mph) ? num(t.wind_mph, 1) + " mph" : NONE, "typical speed")}
        ${stat("Sunshine", isNum(t.sun_kwh_m2_day) ? num(t.sun_kwh_m2_day, 2) + " kWh" : NONE, "a square metre a day")}
        ${stat("Change each ten years", isNum(trend.mean_f_per_decade) ? (trend.mean_f_per_decade > 0 ? "+" : "") + num(trend.mean_f_per_decade, 2) + " °F" : NONE, isNum(trend.rain_in_per_decade) ? `rain ${trend.rain_in_per_decade > 0 ? "+" : ""}${num(trend.rain_in_per_decade, 2)} in; ${esc(trend.from_year)} to ${esc(trend.to_year)}` : "")}
      </section>
      <div class="fc-wx">
        <div class="card"><h3>A typical year, month by month</h3><div class="fc-chart" data-chart="wx-temp"></div>
          <div class="legend fc-legend">${key("line hot", "Highs")}${key("line", "Average")}${key("line cold", "Lows")}</div>
          <div class="fc-chart" data-chart="wx-rain"></div><div class="legend fc-legend">${key("bar rain", "Rain")}</div></div>
        <div class="card"><h3>The yearly average since ${esc(years.length ? years[0].year : trend.from_year || "")}</h3><div class="fc-chart" data-chart="wx-years"></div>
          <div class="legend fc-legend">${key("line thin", "Each year")}${slope !== null ? key("line trend", "Straight-line trend") + key("line trend ahead", `Trend carried on to ${endYear}`) : ""}${key("now", "This year")}</div>
          ${ahead && ahead.basis ? `<p class="fine">${esc(ahead.basis)}${isNum(ahead.mean_f_change) ? ` About ${ahead.mean_f_change > 0 ? "+" : ""}${num(ahead.mean_f_change, 1)} °F by ${esc(ahead.year)}.` : ""} This is where the past trend points, not a climate forecast.</p>` : ""}</div>
      </div>
      <div class="fc-folds">
        ${folded("wx-decades", "Show the figures by decade", plainTable(["Years", "Average", "Summer high", "Rain a year"], (C.by_decade || []).map((d) => [esc(d.years), given(d.mean_f, num(d.mean_f, 1) + " °F"), given(d.summer_high_f, num(d.summer_high_f, 1) + " °F"), given(d.rain_in, num(d.rain_in, 2) + " in")]), [1, 2, 3]))}
        ${folded("wx-how", "How this was worked out", `${C.note ? `<p class="fine">${esc(C.note)}</p>` : ""}<p class="fine">${esc(C.source || "")}</p>`)}
      </div>`;
  }

  // ---- hazards and limits on building
  function drawHazards() {
    const box = el.querySelector("#fcHazards"), title = "Hazards and limits on building";
    const wait = outlookWait("fcHazardsTitle", title);
    if (wait) { box.innerHTML = wait; return; }
    const H = outlook.hazards || {};
    if (!H.available) { box.innerHTML = `<h2 id="fcHazardsTitle">${title}</h2>` + outlookMissing("Hazards and limits on building", ["hazards"]); return; }
    const order = { work: 0, note: 1, clear: 2 };
    const found = (H.findings || []).slice().sort((a, b) => (order[a.level] ?? 3) - (order[b.level] ?? 3));
    const count = (lv) => found.filter((f) => f.level === lv).length;
    const card = (f) => {
      const lv = LEVELS[f.level] || { words: f.level, mark: "?" };
      return `<article class="card fc-haz ${esc(f.level)}"><div class="fc-haz-top"><h3>${esc(f.topic)}</h3><span class="fc-level ${esc(f.level)}"><b aria-hidden="true">${lv.mark}</b>${esc(lv.words)}</span></div>
        <p>${esc(f.text)}</p><p class="fine">${esc(f.source || "")}</p></article>`;
    };
    // what adds work or is worth knowing leads; the clear findings and the gaps are there on request
    const lead = found.filter((f) => f.level !== "clear"), clear = found.filter((f) => f.level === "clear");
    const gaps = `<ul class="plain">${(H.not_covered || []).map((n) => `<li>${esc(n)}</li>`).join("")}</ul>
      ${(H.did_not_answer || []).length ? `<h3 class="fc-gap">Did not answer just now</h3><ul class="plain">${H.did_not_answer.map((n) => `<li>${esc(String(n).replace(/_/g, " "))}</li>`).join("")}</ul>` : ""}`;
    box.innerHTML = `<h2 id="fcHazardsTitle">${title}</h2>
      <p class="fc-intro"><b>${num(count("work"))}</b> ${count("work") === 1 ? "finding adds" : "findings add"} work (a study, a permit or a cost), <b>${num(count("note"))}</b> to know about, <b>${num(count("clear"))}</b> clear.${H.evacuation_zone ? ` Evacuation zone: <b>${esc(H.evacuation_zone)}</b>.` : ""}</p>
      ${lead.length ? `<div class="fc-haz-grid">${lead.map(card).join("")}</div>` : ""}
      <p class="fine">Maps say where to look; the studies under “What needs to be done” settle it on the ground.</p>
      <div class="fc-folds">
        ${clear.length ? folded("haz-clear", `Show the ${clear.length === 1 ? "clear finding" : num(clear.length) + " clear findings"}`, `<div class="fc-haz-grid">${clear.map(card).join("")}</div>`) : ""}
        ${folded("haz-gaps", (H.did_not_answer || []).length ? "Not covered yet, and what did not answer" : "Not covered yet", gaps)}
      </div>`;
  }

  // ---- what is close by
  function placeKind(kind) {
    const k = PLACE_KINDS[kind];
    return k || { letter: String(kind || "?").charAt(0).toUpperCase(), shape: "round", colour: "#4d5b54", words: cap(String(kind || "other")) };
  }
  function placePin(kind, small) {
    const k = placeKind(kind);
    return `<span class="fc-pin ${k.shape}${small ? " sm" : ""}" style="background:${k.colour}" aria-hidden="true"><b>${esc(k.letter)}</b></span>`;
  }
  function drawNearby() {
    const L = window.L, text = el.querySelector("#fcNearText");
    if (!nearMap) {
      nearMap = createMap(el.querySelector("#fcNearMap"), { base: "aerial" });
      nearLayers = L.layerGroup().addTo(nearMap.map);
    }
    nearLayers.clearLayers();
    let bounds = null;
    ((data.site || {}).parcels || []).forEach((p) => {
      if (!p.outline || !p.outline.coordinates) return;
      const shape = ll(p.outline.type === "MultiPolygon" ? p.outline.coordinates.flat() : p.outline.coordinates);
      L.polygon(shape, { color: "#1d2a24", weight: 6, fill: false, interactive: false }).addTo(nearLayers);
      const g = L.polygon(shape, { color: "#f2b632", weight: 3, fillColor: "#f2b632", fillOpacity: 0.3 }).bindTooltip("The site", { sticky: true }).addTo(nearLayers);
      bounds = bounds ? bounds.extend(g.getBounds()) : g.getBounds();
    });
    const N = outlook && outlook.nearby;
    const places = N && N.available ? (N.places || []).filter((p) => isNum(p.lat) && isNum(p.lon)) : [];
    places.forEach((p) => {
      const k = placeKind(p.kind);
      L.marker([Number(p.lat), Number(p.lon)], { icon: L.divIcon({ className: "fc-pin-icon", html: placePin(p.kind), iconSize: [24, 24], iconAnchor: [12, 12] }), keyboard: false, title: `${k.words}: ${p.name}` })
        .bindTooltip(`<b>${esc(p.name)}</b><br>${esc(k.words)} · ${num(p.miles_away, 2)} ${plural(p.miles_away, "mile", "miles", 2)}${p.detail ? "<br>" + esc(p.detail) : ""}`).addTo(nearLayers);
      bounds = bounds ? bounds.extend([Number(p.lat), Number(p.lon)]) : L.latLngBounds([[Number(p.lat), Number(p.lon)], [Number(p.lat), Number(p.lon)]]);
    });
    if (bounds && !nearFitted) { nearMap.fit(bounds.pad(0.15)); if (places.length || (outlook && !(N && N.available))) nearFitted = true; }
    const kinds = [...new Set(places.map((p) => p.kind))].sort((a, b) => KIND_ORDER.indexOf(a) - KIND_ORDER.indexOf(b));
    el.querySelector("#fcNearLegend").innerHTML = '<span><i class="fc-key site"></i>The site</span>' + kinds.map((k) => `<span>${placePin(k, true)}${esc(placeKind(k).words)}</span>`).join("");

    const summary = el.querySelector("#fcNearSummary");
    summary.innerHTML = "";
    const wait = outlookWait("fcNearbyWait", "");
    if (wait) { text.innerHTML = wait.replace('<h2 id="fcNearbyWait"></h2>', ""); return; }
    if (!N || !N.available) { text.innerHTML = outlookMissing("What is close by", ["nearby"]); return; }
    const nearest = Object.values(N.nearest || {}).sort((a, b) => Number(a.miles_away) - Number(b.miles_away));
    const rows = places.slice().sort((a, b) => (KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind)) || (Number(a.miles_away) - Number(b.miles_away)))
      .map((p) => [`<span class="fc-kind">${placePin(p.kind, true)}${esc(placeKind(p.kind).words)}</span>`, `<b>${esc(p.name)}</b>${p.detail ? `<small>${esc(p.detail)}</small>` : ""}`, num(p.miles_away, 2)]);
    summary.innerHTML = `${nearest.length ? `<h3 class="fc-gap">The nearest of each kind</h3><div class="fc-nearest">${nearest.map((p) => `<div>${placePin(p.kind, true)}<span><span class="label">Nearest ${esc(placeKind(p.kind).one)}</span><b>${esc(p.name)}</b><span class="muted">${num(p.miles_away, 2)} ${plural(p.miles_away, "mile", "miles", 2)}</span></span></div>`).join("")}</div>` : ""}
      ${(N.not_covered || []).length ? `<p class="fine"><b>Not covered yet:</b> ${esc(N.not_covered.join("; "))}.</p>` : ""}
      ${(N.did_not_answer || []).length ? `<p class="fine fc-no">Did not answer just now: ${esc(N.did_not_answer.join(", "))}.</p>` : ""}`;
    text.innerHTML = `<div class="fc-folds">${folded("near-all", `Show everything found, by kind${rows.length ? ` (${num(rows.length)})` : ""}`,
      `${rows.length ? plainTable(["Kind", "Place", "Miles away"], rows, [2]) : missing("No places found nearby.")}
      <p class="fine">Straight-line miles from the middle of the site. Sources: ${esc([...new Set(places.map((p) => p.source).filter(Boolean))].join("; "))}.</p>`)}</div>`;
  }

  // ---- who lives nearby
  function drawResident() {
    const box = el.querySelector("#fcResident"), title = "Who lives nearby";
    const wait = outlookWait("fcResidentTitle", title);
    if (wait) { box.innerHTML = wait; return; }
    const R = outlook.resident || {};
    if (!R.available) { box.innerHTML = `<h2 id="fcResidentTitle">${title}</h2>` + outlookMissing("Who lives nearby", ["residents"]); return; }
    const t = R.typical || {}, then = R.earlier || {};
    const pct = (v) => (isNum(v) ? num(v, 1) + "%" : NONE);
    const stat = (label, big, small = "") => `<div class="stat"><span class="label">${label}</span><b>${big}</b>${small ? `<span>${small}</span>` : ""}</div>`;
    const usd = (v) => (isNum(v) ? "$" + num(v) : NONE);
    // the middle of a survey's years ("2019-2023" is 2021); the rate a year is the steady yearly change from the earlier value to the later one
    const middle = (text) => { const y = String(text || "").match(/\d{4}/g); return y ? (Number(y[0]) + Number(y[y.length - 1])) / 2 : null; };
    const yearly = (was, now, given) => {
      if (isNum(given)) return `about ${num(given, 1)}%`;
      const gap = middle(R.survey) - middle(then.years);
      if (!isNum(was) || !isNum(now) || Number(was) <= 0 || Number(now) <= 0) return `<span title="Not worked out: one of the two figures is not covered yet.">–</span>`;
      if (!isFinite(gap) || gap <= 0) return `<span title="Not worked out: the years of the two surveys are not both known, so the years between them are not known.">–</span>`;
      return `about ${num((Math.pow(Number(now) / Number(was), 1 / gap) - 1) * 100, 1)}%`;
    };
    box.innerHTML = `<h2 id="fcResidentTitle">${title}</h2>
      <p class="fc-intro">The typical figures of the census tracts within ${esc(mi(data.market_miles))} of the site, census survey ${esc(R.survey || "")}.</p>
      ${(R.facts || []).length ? `<div class="card fc-says"><h3>What it says</h3><ul class="plain">${R.facts.map((f) => `<li>${esc(f)}</li>`).join("")}</ul></div>` : ""}
      <section class="stats fc-res-stats" aria-label="The typical resident nearby">
        ${stat("Typical age", isNum(t.median_age) ? num(t.median_age, 1) : NONE, "years, half older and half younger")}
        ${stat("Household", isNum(t.household_size) ? num(t.household_size, 2) : NONE, "people in a typical household")}
        ${stat("Home value", usd(t.home_value_usd), "typical, as owners report it")}
        ${stat("Rent", usd(t.rent_usd), "typical, a month")}
      </section>
      <div class="fc-folds">
        ${folded("res-more", "Show more about who lives nearby", `<section class="stats fc-res-stats" aria-label="More about the people nearby">
          ${stat("Under 18", pct(t.under_18_pct))}
          ${stat("65 or older", pct(t.over_65_pct))}
          ${stat("College degree", pct(t.bachelors_pct), "of adults")}
          ${stat("Drive alone to work", pct(t.drive_alone_pct))}
          ${stat("Work from home", pct(t.work_from_home_pct))}
          ${stat("An hour or more to work", pct(t.long_commute_pct), "of workers")}
          ${stat("Spanish at home", pct(t.spanish_at_home_pct))}
        </section>`)}
        ${folded("res-then", "Show then and now: home values and rents", `<div class="fc-res">
          ${plainTable(["", `Survey ${esc(then.years || "earlier")}`, `Survey ${esc(R.survey || "now")}`, "A year"], [
            ["Typical home value", usd(then.home_value_usd), usd(t.home_value_usd), yearly(then.home_value_usd, t.home_value_usd, R.home_value_rise_pct_a_year)],
            ["Typical rent a month", usd(then.rent_usd), usd(t.rent_usd), yearly(then.rent_usd, t.rent_usd)]], [1, 2, 3])}
          <p class="fine">${isNum(then.tracts_matched) ? `The earlier figures come from the ${num(then.tracts_matched)} ${plural(then.tracts_matched, "tract")} that match between the two surveys. ` : ""}Survey dollars, not adjusted for inflation.</p></div>`)}
        ${folded("res-how", "How this was worked out", `<p class="fine">${esc(R.source || "")}${(R.tracts || []).length ? `; ${num(R.tracts.length)} census tracts` : ""}.</p>`)}
      </div>`;
  }

  // ---- the homes the state requires the city to plan for, and this site's homes beside what is left
  function drawHousing() {
    const box = el.querySelector("#fcHousing"), title = "The city's state housing target";
    const wait = outlookWait("fcHousingTitle", title);
    if (wait) { box.innerHTML = wait; return; }
    const H = outlook.housing || {};
    if (!H.available) { box.innerHTML = `<h2 id="fcHousingTitle">${title}</h2>` + outlookMissing("The city's state housing target", ["housing"]); return; }
    const stat = (label, big, small = "") => `<div class="stat"><span class="label">${label}</span><b>${big}</b>${small ? `<span>${small}</span>` : ""}</div>`;
    const n = (v) => (isNum(v) ? num(v) : NONE);
    const site = H.site, lower = H.lower || {};
    const bar = (l) => {
      const share = isNum(l.target) && Number(l.target) > 0 && isNum(l.permitted) ? 100 * Number(l.permitted) / Number(l.target) : null;
      return `<div class="fc-goal"><span>${esc(l.label)}</span><i aria-hidden="true"><b style="width:${share === null ? 0 : Math.min(100, share).toFixed(1)}%"></b></i>
        <em>${n(l.permitted)} of ${n(l.target)}${share === null ? "" : ` <small>${num(share, share < 10 ? 1 : 0)}%</small>`}</em></div>`;
    };
    const years = H.by_year || [];
    box.innerHTML = `<h2 id="fcHousingTitle">${title}</h2>
      <p class="fc-intro">The state gives every California city a number of homes to plan for, split by the income they are meant for, and the city reports its building permits toward it each year.${isNum(H.from_year) && isNum(H.to_year) ? ` This count runs from ${esc(H.from_year)} to ${esc(H.to_year)}.` : ""}</p>
      <section class="stats fc-res-stats fc-goal-stats" aria-label="The housing target in figures">
        ${stat("Homes to plan for", n(H.target), isNum(H.to_year) ? `by ${esc(H.to_year)}` : "")}
        ${stat("Permitted so far", n(H.permitted), isNum(H.share_pct) ? `${num(H.share_pct, 1)}% of the target${isNum(H.through_year) ? `, through ${esc(H.through_year)}` : ""}` : "")}
        ${stat("Still to come", n(H.left), isNum(lower.left) ? `${num(lower.left)} of them for very low, low and moderate incomes` : "")}
        ${stat("In this site's plan", site ? n(site.homes) : "0", site ? `${plural(site.homes, "home")}${isNum(site.pct_of_left) ? `, ${num(site.pct_of_left, 1)}% of what is still to come` : ""}` : "no homes in this plan")}
      </section>
      <div class="card fc-goals"><h3>Permits so far, beside the target for each income level</h3>
        ${(H.levels || []).map(bar).join("")}
        <p class="fine">The whole track is the target; the dark part is the permits the state has counted. A level past its target shows a full track.</p></div>
      ${(H.facts || []).length ? `<div class="card fc-says"><h3>What it says</h3><ul class="plain">${H.facts.map((f) => `<li>${esc(f)}</li>`).join("")}</ul></div>` : ""}
      <div class="fc-folds">
        ${years.length ? folded("house-years", "Show the permits reported each year", plainTable(["Year", "Very low", "Low", "Moderate", "Above moderate", "All"],
          years.map((r) => [esc(r.year), n(r.very_low), n(r.low), n(r.moderate), n(r.above_moderate), n(r.total)]), [1, 2, 3, 4, 5])) : ""}
        ${folded("house-how", "How this was worked out", `<p class="fine">${esc(H.source || "")}${H.as_of ? `; ${esc(H.as_of)}` : ""}.</p>
          ${(H.notes || []).length ? `<ul class="plain fine">${H.notes.map((t) => `<li>${esc(cap(t))}.</li>`).join("")}</ul>` : ""}
          <p class="fine">The site's homes are the ones in its plan. This page does not say which income level they would count toward.</p>`)}
      </div>`;
  }

  // ---- what needs to be done (the part the owner shows the city)
  function drawTodo() {
    const box = el.querySelector("#fcTodo"), title = "What needs to be done";
    const wait = outlookWait("fcTodoTitle", title);
    if (wait) { box.innerHTML = wait; return; }
    const T = outlook.todo || {}, steps = T.steps || [];
    if (!steps.length) { box.innerHTML = `<h2 id="fcTodoTitle">${title}</h2>` + missing("The list of steps: not covered yet."); return; }
    const y0 = Math.min(...steps.map((s) => s.from_year)), y1 = Math.max(...steps.map((s) => s.to_year)), n = y1 - y0 + 1;
    const cols = `grid-template-columns:repeat(${n},minmax(0,1fr));--n:${n}`;
    const years = Array.from({ length: n }, (_, i) => y0 + i);
    const what = (s) => {
      const i = s.kind === "sell" ? String(s.what).indexOf(": ") : -1;
      return i > 0 ? `<b>${esc(s.what.slice(0, i))}</b>: ${esc(s.what.slice(i + 2))}` : `<b>${esc(s.what)}</b>`;
    };
    const groups = TODO_KINDS.map(([k, words, help]) => ({ k, words, help, list: steps.filter((s) => s.kind === k) }))
      .concat([{ k: "other", words: "Other steps", help: "", list: steps.filter((s) => !TODO_KINDS.some(([k]) => k === s.kind)) }]).filter((g) => g.list.length);
    box.innerHTML = `<h2 id="fcTodoTitle">${title}</h2>
      <p class="fc-intro">In order, year by year: who to see, which studies, which checks, and when each part of the land is offered. Open a step to read why it is on the list and who does it.</p>
      <div class="card fc-todo">
        <div class="fc-tl-row fc-tl-head" aria-hidden="true"><div>Step</div><div class="fc-tl-years" style="${cols}">${years.map((y) => `<span>${y}</span>`).join("")}</div></div>
        ${groups.map((g) => `
          <h3 class="fc-tl-kind"><span class="fc-tl-dot k-${g.k}" aria-hidden="true"></span>${esc(g.words)} <span class="muted">${num(g.list.length)} ${g.list.length === 1 ? "step" : "steps"}${g.help ? ", " + esc(g.help) : ""}</span></h3>
          <ol class="fc-tl-list">${g.list.map((s, i) => {
            const span = s.from_year === s.to_year ? String(s.from_year) : `${s.from_year} to ${s.to_year}`, k = `step-${g.k}-${i}`;
            return `
            <li><details class="fc-tl-step" data-fold="${k}"${folds.has(k) ? " open" : ""}>
              <summary class="fc-tl-row">
                <div class="fc-tl-text"><span class="fc-tl-when k-${g.k}">${esc(span)}</span>${what(s)}</div>
                <div class="fc-tl-bar" style="${cols}" aria-hidden="true"><span class="fc-tl-span k-${g.k}" style="grid-column:${s.from_year - y0 + 1} / ${s.to_year - y0 + 2}" title="${esc(span)}"></span></div>
              </summary>
              <div class="fc-tl-more"><p>${esc(s.why || "")}</p><p class="fc-tl-who"><span>Who:</span> ${esc(s.who || NONE)}</p></div>
            </details></li>`;
          }).join("")}</ol>`).join("")}
      </div>
      ${T.note ? `<div class="notice warn fc-todo-note"><p><b>A starting list, not the city's list.</b> ${esc(T.note)}</p></div>` : ""}`;
  }

  // ---------------------------------------------------------------- figures you can change

  function unitParts(unit) {
    const u = String(unit || "");
    if (u.startsWith("$")) return { before: "$", after: u.slice(1).trim() };
    return { before: "", after: u };
  }
  const boxValue = (v) => (isNum(v) ? Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 }) : "");
  function drawFigures() {
    const groups = [];
    (data.figures || []).forEach((f) => {
      let g = groups.find((x) => x.name === f.group);
      if (!g) { g = { name: f.group, items: [] }; groups.push(g); }
      g.items.push(f);
    });
    const mine = (data.figures || []).some((f) => f.yours);
    const keep = el.querySelector("#fcStatus");
    const kept = keep ? { html: keep.innerHTML, cls: keep.className } : null;
    el.querySelector("#fcFigures").innerHTML = `
      <div class="fc-sec-head"><h2 id="fcFiguresTitle">Figures you can change</h2>
        <button type="button" class="btn" data-reset-all ${mine || data.kept ? "" : "disabled"} title="Forget your figures for this site and use the starting figures again">${icon("refresh")} Back to starting figures</button></div>
      <p class="fc-intro">These are not measured. They are <span class="fc-tag start">Starting figure</span> common planning rules of thumb; type your own and every number on this page is worked out again. A figure you changed is marked <span class="fc-tag yours">Your figure</span>.</p>
      <p class="fc-status" id="fcStatus" role="status" aria-live="polite"></p>
      <div class="fc-fig-groups">${groups.map((g) => `
        <article class="card"><h3>${esc(g.name)}</h3>${g.items.map((f) => {
          const u = unitParts(f.unit);
          return `<div class="fc-fig">
            <div class="fc-fig-top"><label for="fcFig-${esc(f.id)}">${esc(f.label)}</label>${figureTag(f)}</div>
            <div class="fc-fig-ctl"><span class="plan-in">${u.before ? `<i>${esc(u.before)}</i>` : ""}<input class="plan-num" id="fcFig-${esc(f.id)}" type="text" inputmode="decimal" autocomplete="off" data-k="fig:${esc(f.id)}" data-fig="${esc(f.id)}" value="${esc(boxValue(values[f.id]))}" aria-describedby="fcFigHelp-${esc(f.id)}">${u.after ? `<i>${esc(u.after)}</i>` : ""}</span>
              ${f.yours ? `<button type="button" class="btn small" data-reset="${esc(f.id)}" aria-label="Back to the starting figure for ${esc(f.label)}">Back to ${esc(boxValue(f.start))}</button>` : ""}</div>
            <p class="fine" id="fcFigHelp-${esc(f.id)}">Starting figure ${esc(u.before)}${esc(boxValue(f.start))}${u.after === "%" ? "%" : u.after ? " " + esc(u.after) : ""}. Any number from ${esc(boxValue(f.lowest))} to ${esc(boxValue(f.highest))}.</p>
          </div>`;
        }).join("")}</article>`).join("")}</div>
      <p class="fine">${data.kept ? "Your figures for this site are kept" : "Figures you change are kept"} on this computer, in <span class="path">${esc(data.kept_in || NONE)}</span>. They are kept for this exact set of parcels.</p>`;
    if (kept) { const s = el.querySelector("#fcStatus"); s.innerHTML = kept.html; s.className = kept.cls; }
  }

  // ---------------------------------------------------------------- what answered, and the limits

  function drawSources() {
    const answered = data.answered || {};
    const says = stateSentences(Object.keys(answered), answered, (p) => PART_WORDS[p] || p);
    el.querySelector("#fcSources").innerHTML = `
      <div class="card"><h2>What answered</h2>
        ${says ? `<p class="fc-again">${esc(says)} <button type="button" class="btn small" data-ask-again>Ask again</button></p>` : `<p>${num((data.sources || []).filter((s) => s.answered).length)} of ${num((data.sources || []).length)} sources of the forecast answered.</p>`}
        ${folded("sources-forecast", "Show the forecast's sources", plainTable(["Source", "What it gives", "Answered"], (data.sources || []).map((s) => [esc(s.name), esc(s.what), s.answered ? "Yes" : '<b class="fc-no">No</b>'])))}
        ${folded("sources-wider", "Show the wider picture's sources", outlookSources())}
      </div>
      <div class="card fc-limits"><h2>Limits of this forecast</h2>
        <ul class="plain">${(data.limits || []).map((l) => `<li>${esc(l)}</li>`).join("")}
          <li>This is a forecast from public records and stated figures, not a market study or an appraisal.</li></ul>
      </div>`;
  }

  function outlookSources() {
    if (outlookProblem) return `<p class="fc-again fc-no">The wider picture could not be read just now. <button type="button" class="btn small" data-outlook-again>Ask again</button></p>`;
    if (!outlook) return '<p class="plan-wait"><span class="spinner" aria-hidden="true"></span> Asking these sources now…</p>';
    const answered = outlook.answered || {}, names = Object.keys(answered);
    const words = { ok: "Yes", "did not answer": '<b class="fc-no">Did not answer just now</b>', "nothing found there": "Answered, nothing for this spot",
      "could not be read": '<b class="fc-no">Answered in a form this app could not read</b>',
      "older copy": '<b class="fc-no">Did not answer just now</b>: this is the copy read earlier',
      "not published": "The city does not publish this" };
    const says = stateSentences(names, answered, (p) => (OUTLOOK_WORDS[p] || [p])[0]);
    return plainTable(["Source", "What it gives", "Answered", "Read"], names.map((p) => [esc((OUTLOOK_WORDS[p] || [p])[0]), esc((OUTLOOK_WORDS[p] || ["", ""])[1]),
      words[answered[p]] || esc(answered[p]), (outlook.fetched || {})[p] ? esc(when((outlook.fetched || {})[p])) : ""])) +
      `<p class="fc-again">${says ? esc(says) + " " : "Saved answers are reused for a while. "}<button type="button" class="btn small" data-outlook-again>Ask these sources again</button></p>`;
  }

  // ---------------------------------------------------------------- what the person does

  function onInput(e) {
    const t = e.target;
    if (!t.dataset || !t.dataset.fig) return;
    const f = (data.figures || []).find((x) => x.id === t.dataset.fig);
    if (!f) return;
    const v = readNumber(t.value);
    const bad = v === null || v < Number(f.lowest) || v > Number(f.highest);
    t.setAttribute("aria-invalid", String(bad));
    if (bad) {
      seq++;   // an answer on its way for an older figure no longer applies
      status(`Type a number from ${esc(boxValue(f.lowest))} to ${esc(boxValue(f.highest))} for “${esc(f.label)}”.`, "bad");
      return;
    }
    values[f.id] = v;
    seq++;
    status("Waiting for you to finish typing…", "busy");
    later();
  }
  function onChange(e) {
    const t = e.target;
    if (t.dataset && t.dataset.fig && t.getAttribute("aria-invalid") !== "true") t.value = boxValue(values[t.dataset.fig]);
  }
  function onClick(e) {
    const b = e.target.closest ? e.target.closest("button") : null;
    if (!b || !el.contains(b)) return;
    if (b.dataset.jump) { goTo(b.dataset.jump, true); return; }
    if (b.dataset.goto) { goTo(b.dataset.goto, false); return; }
    if (b.dataset.planview) {
      planView = b.dataset.planview;
      drawSitePlan();
      return;
    }
    if (b.dataset.outlookAgain !== undefined) { loadOutlook(true); return; }
    if (b.dataset.groundAgain !== undefined) {
      groundProblem = ""; ground = null;
      if (unmount3d) { unmount3d(); unmount3d = null; }
      el.querySelector("#fcPlan3d").innerHTML = "";
      askGround(true);
      draw3d();
      return;
    }
    if (b.dataset.ring) {
      ringMiles = Number(b.dataset.ring);
      drawPeople();
      paintCharts();
      const again = el.querySelector(`[data-ring="${ringMiles}"]`);
      if (again) again.focus({ preventScroll: true });
      return;
    }
    if (b.dataset.resetAll !== undefined) { send("DELETE"); return; }
    if (b.dataset.reset) {
      const f = (data.figures || []).find((x) => x.id === b.dataset.reset);
      if (f) { values[f.id] = Number(f.start); send("POST"); }
      return;
    }
    if (b.dataset.askAgain !== undefined) { first(); return; }
    if (b.id === "fcPrint") window.print();
  }

  first();
}

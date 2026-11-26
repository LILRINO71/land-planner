// The Forecast page: year by year for the next ten years (the first five in focus, last year as background), the
// people, homes, income areas, shops, jobs and traffic around a site, and how fast the site's own land could be
// taken up. A site is one parcel, or several parcels treated as one. Address: #/forecast/<city>/<apn+apn+...>
// Every value shown comes from the server's forecast answer. A value the answer does not give reads "not covered yet".
import { createMap, ll } from "../maps.js";
import { api } from "../api.js";
import { PAGES, FORECAST_ICON } from "./land.js";
import { money as readNumber } from "../planmath.js";
import { NONE, esc, has, num, cap, icon, loading, problem, missing, debounce, dateOnly } from "../util.js";

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
  const step = [1, 2, 5, 10].find((k) => slot * k >= 42) || 10;
  for (let v = o.xMin; v <= o.xMax; v++) {
    if (step >= 5 ? v % step !== 0 : (v - o.xMin) % step !== 0) continue;
    out += `<text class="fc-xlab" x="${x(v).toFixed(1)}" y="${H - 7}" text-anchor="middle">${v}</text>`;
  }
  out += o.draw(s);
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
  const charts = {};
  alive.onLeave(() => {
    if (mapView) mapView.destroy();
    if (observer) observer.disconnect();
    mapView = null; observer = null;
  });
  el.addEventListener("input", onInput);
  el.addEventListener("change", onChange);
  el.addEventListener("click", onClick);

  function first() {
    if (mapView) mapView.destroy();
    mapView = null; mapDrawn = false;
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
    el.innerHTML = `
      <div class="fc">
        <header class="page-head fc-head" id="fcHead"></header>
        <div id="fcEdited"></div>
        <div class="fc-top"><section class="stats fc-stats" id="fcStats" aria-label="The forecast in numbers"></section><section class="card fc-advice" id="fcAdvice"></section></div>
        <section id="fcPeople" aria-labelledby="fcPeopleTitle"></section>
        <section id="fcIncome" aria-labelledby="fcIncomeTitle">
          <h2 id="fcIncomeTitle">Income areas</h2>
          <div class="fc-income">
            <div class="fc-income-map">
              <div class="map-frame"><div class="map fc-map" id="fcMap"></div></div>
              <div class="legend" id="fcMapLegend"></div>
            </div>
            <div class="fc-income-text" id="fcIncomeText"></div>
            <div class="fc-income-tracts" id="fcTracts"></div>
          </div>
        </section>
        <section id="fcNeeds" aria-labelledby="fcNeedsTitle"></section>
        <section id="fcTraffic" aria-labelledby="fcTrafficTitle"></section>
        <section id="fcLand" aria-labelledby="fcLandTitle"></section>
        <section id="fcFigures" aria-labelledby="fcFiguresTitle"></section>
        <section class="two fc-last" id="fcSources"></section>
      </div>`;
    drawAll(false);
    drawMap();
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
  function paintCharts() {
    el.querySelectorAll("[data-chart]").forEach((box) => {
      const fn = charts[box.dataset.chart];
      if (fn) box.innerHTML = fn(box.clientWidth);
    });
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
      const silent = (PARTS_FOR[partsKey] || []).filter((p) => answered[p] && answered[p] !== "ok");
      if (silent.length) text += " " + cap(listWords(silent.map((p) => `${PART_WORDS[p] || p} ${answered[p] === "did not answer" ? "did not answer just now" : "had nothing for this spot"}`))) + ".";
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
    const parcelLinks = parcels.map((p) => `<a href="#/land/${esc(data.city)}/${esc(p.apn)}">${esc(p.apn_formatted || p.apn)}</a>${isNum(p.acres) ? ` <span class="muted">(${num(p.acres, 2)} acres)</span>` : ""}`);
    let together = "";
    if (!single) {
      together = `<p class="fc-together">These ${parcels.length} parcels are forecast <b>as one site</b>: the people, homes, shops, jobs and traffic around the point between them, and the land of all of them together.` +
        (site.together ? (isNum(site.spread_miles) ? ` They lie together, within about ${num(site.spread_miles, 2)} miles of each other.` : " They lie together.")
          : " <b>They are not next to each other</b>, so the forecast fits each one less well than a forecast of its own.") + "</p>";
    }
    const tabs = single ? `<nav class="tabs" aria-label="This land's pages">${PAGES.map(([id, label]) =>
      `<a href="#/land/${esc(data.city)}/${esc(P0.apn)}/${id}">${icon(id)}${label}</a>`).join("")}<a href="#/forecast/${esc(data.city)}/${esc(P0.apn)}" class="on" aria-current="page">${FORECAST_ICON}Forecast</a></nav>` : "";
    el.querySelector("#fcHead").innerHTML = `
      <p class="kicker"><a href="#/lands/${esc(data.city)}">${esc(data.city_name || data.city)}</a> · Forecast, ${esc(now())} to ${esc(now() + 10)}</p>
      <div class="head-row">
        <div>
          <h1>${isNum(site.acres) ? num(site.acres, 2) + " acres" : "This site"}${single ? "" : `, ${parcels.length} parcels as one site`}</h1>
          <p class="lead">${single ? "Parcel" : "Parcels"} ${parcelLinks.join(", ")} · zoned ${esc(listWords(zones))}</p>
        </div>
        <div class="head-actions">
          ${single ? "" : `<a class="btn" href="#/my-lands">${icon("saved")} My lands</a>`}
          <button type="button" class="btn" id="fcPrint">Print</button>
        </div>
      </div>
      ${together}
      <p class="fc-years-line">Next ten years, year by year: <b>${esc(now() + 1)} to ${esc(now() + 5)}</b> in focus, ${esc(now() + 6)} to ${esc(now() + 10)} lighter, and ${esc(data.background_year)} as background. Low, expected and high lines come from the real readings of growth below; nothing is filled in where a source gives nothing.</p>
      ${tabs}`;
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
      return `<div class="stat"><span class="label">${esc(h.label)}</span><b>${amount(h.value, h.unit)}</b>${spread}${h.note ? `<span>${esc(h.note)}</span>` : ""}</div>`;
    }).join("") : `<div class="stat"><span class="label">Forecast</span><b class="small">${cap(NONE)}</b><span>no reading of growth answered for this site</span></div>`;
  }
  function drawAdvice() {
    const items = data.advice || [];
    el.querySelector("#fcAdvice").innerHTML = `<h2>What this says</h2>` +
      (items.length ? `<ul class="plain fc-advice-list">${items.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : missing("Nothing to say yet: the forecast is not covered for this site."));
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
    const intro = `<p class="fc-intro">Within ${esc(mi(ring.miles))} of the site the Census counted ${countedLine || NONE}${isNum(ring.people_per_home) ? `, about ${num(ring.people_per_home, 2)} people a home` : ""}. ` +
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
        hover: rows.map((x) => ({ x: x.year, text: `${x.year}: about ${num(x.people.expected)} people expected (${range(x.people)})` }))
          .concat(cYears.map((y) => ({ x: y, text: `${y}: ${num(counted[y].people)} people counted by the Census` }))),
      });
    };
    const readings = (ring.readings || []).map((g) => {
      const used = [];
      if (Number(g.rate_pct) === Number(r.expected)) used.push("expected line");
      if (!ring.one_reading && Number(g.rate_pct) === Number(r.low)) used.push("low line");
      if (!ring.one_reading && Number(g.rate_pct) === Number(r.high)) used.push("high line");
      const tag = g.kind === "measured" ? '<span class="fc-tag measured">measured</span>' : '<span class="fc-tag official">official forecast</span>';
      return [`<b>${esc(g.label)}</b> ${tag}<small>${esc(g.source || NONE)}</small>${used.length ? `<small><b>Used for the ${esc(listWords(used))}</b></small>` : ""}`,
        `${num(g.rate_pct, 2)}% a year`,
        g.from ? `${num(g.from.homes)} homes<small>in ${esc(g.from.year)}</small>` : NONE,
        g.to ? `${num(g.to.homes)} homes<small>in ${esc(g.to.year)}</small>` : NONE];
    });
    box.innerHTML = head + intro + `
      <div class="fc-people">
        <div class="card fc-people-chart">
          <div class="fc-chart" data-chart="people"></div>
          <div class="legend fc-legend">${key("band", "Low to high")}${key("line", "Expected")}${key("counted", "Counted by the Census")}${key("focus", "Next five years")}${key("now", "This year")}</div>
        </div>
        <div class="fc-people-table"><h3>Year by year, within ${esc(mi(ring.miles))}</h3>
          ${yearTable(["Year", "People<small>expected, then low to high</small>", "Homes<small>expected, then low to high</small>"],
            rows.map((x) => ({ year: x.year, cells: [cellRange(x.people), cellRange(x.homes)] })))}
        </div>
        <div class="fc-people-readings"><h3>The readings of growth</h3>
          ${readings.length ? plainTable(["What it is, and its source", "A year", "From", "To"], readings, [1, 2, 3]) : missing("Readings of growth: not covered yet.")}
          <p class="fine">Each reading is a steady yearly growth rate in homes. People are homes times the people a home counted in ${esc(cYears[cYears.length - 1] || "the last Census")}.</p>
          ${allRings()}
        </div>
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
      const g = L.polygon(shape, { color: "#f2b632", weight: 3, fillColor: "#f2b632", fillOpacity: 0.25 }).bindTooltip(`Parcel ${esc(p.apn_formatted || p.apn)}${isNum(p.acres) ? ", " + num(p.acres, 2) + " acres" : ""}`, { sticky: true }).addTo(m);
      if (!bounds) bounds = g.getBounds();
    });
    const scale = incomeBands();
    if (scale) {
      (inc.tracts || []).forEach((t) => {
        if (!isNum(t.lat) || !isNum(t.lon)) return;
        L.circleMarker([Number(t.lat), Number(t.lon)], { radius: 8, color: "#1d2a24", weight: 1.5, fillColor: scale.colourOf(t.income), fillOpacity: 0.95 })
          .bindTooltip(`<b>${esc(t.name)}</b><br>Typical household income $${num(t.income)} a year<br>${num(t.households)} households · ${num(t.miles_away, 2)} miles ${esc(t.direction || "")}`).addTo(m);
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
      ${dirs.length ? `<div class="fc-dirs">${dirs.map((d) => `<div><span class="label">${esc(cap(d.direction))}</span><b>$${num(d.income)}</b><span>${num(d.households)} households in ${num(d.tracts)} tracts</span></div>`).join("")}</div>
        <p class="fine">By direction: the households' typical income in the tracts on that side${far.length ? `, within ${esc(mi(Math.max(...far)))}` : ""}. A tract to the north-east counts toward both north and east.</p>` : ""}
      <dl class="facts">
        <dt>Typical household income within ${esc(mi(data.market_miles))}</dt><dd>${amount(inc.typical, "$")} a year</dd>
        <dt>${esc(inc.county_name || "The county")}</dt><dd>${amount(inc.county, "$")} a year</dd>
        <dt>Households that rent</dt><dd>${isNum(inc.renters_pct) ? `about ${num(inc.renters_pct, 1)}%` : NONE}</dd>
        <dt>Homes built in 2020 or later, within ${esc(mi(data.market_miles))}</dt><dd>${isNum(inc.built_since_2020) ? "about " + num(inc.built_since_2020) : NONE}${inc.homes_survey ? ` <small class="muted">(survey ${esc(inc.homes_survey)})</small>` : ""}</dd>
      </dl>
      <p class="fine">${esc(inc.source || "Census survey")}${inc.survey ? `, ${esc(inc.survey)}` : ""}. Survey dollars, not adjusted for inflation.</p></div>`;
    const rows = (inc.tracts || []).map((t) => [
      `<span class="swatch" style="background:${scale ? scale.colourOf(t.income) : "#ccc"}"></span>${esc(String(t.name || NONE).replace(/^Census Tract /, "Tract "))}`,
      `${num(t.miles_away, 2)} mi<small>${esc(t.direction || NONE)}</small>`, amount(t.income, "$"), num(t.households),
      isNum(t.share_in_market) ? num(100 * t.share_in_market) + "%" : NONE,
      t.against_county ? `<span class="fc-against ${esc(t.against_county.replace(/\s+/g, "-"))}">${esc(t.against_county)}</span>` : NONE]);
    tracts.innerHTML = `<h3>Census tracts, nearest first</h3>
      ${rows.length ? `<div class="fc-tracts">${plainTable(["Census tract", "Away", "Typical income", "Households", `Inside ${esc(mi(data.market_miles))}`, `Against ${esc(inc.county_name || "the county")}`], rows, [1, 2, 3, 4])}</div>` : missing("Census tracts: not covered yet.")}
      <p class="fine">“Inside ${esc(mi(data.market_miles))}” is the share of the tract's area within that distance; the typical income above weighs each tract by its households inside. “Higher” and “lower” mean 15% or more above or below ${esc(inc.county_name || "the county")}.</p>`;
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
    return `<div class="fc-chart" data-chart="${spec.name}-year"></div>
      <div class="legend fc-legend">${key("band", "Needed, low to high")}${key("line", "Needed, expected")}${key("bar", "Already on the city's lists")}</div>
      ${sum.length > 1 ? `<h4 class="fc-sub">Added up</h4><div class="fc-chart" data-chart="${spec.name}-sum"></div>
      <div class="legend fc-legend">${key("band", "Needed so far, low to high")}${key("line", "Needed so far, expected")}${key("lists", "On the city's lists so far")}</div>` : ""}`;
  }
  // the expected figure, with low to high under it (left out when all three are the same)
  const cellRange = (o) => `${num(o && o.expected)}${o && Number(o.low) === Number(o.high) && Number(o.low) === Number(o.expected) ? "" : `<small>${range(o)}</small>`}`;

  function drawNeeds() {
    const box = el.querySelector("#fcNeeds"), H = data.homes || {}, S = data.shops || {}, J = data.jobs || {};
    const mm = esc(mi(data.market_miles));
    let homes;
    if (!H.available) homes = notCovered("Homes needed", "homes");
    else {
      homes = `<p class="fc-summary">${esc(H.summary || "")}</p><div class="fc-need-body"><div>` + needCharts({
        name: "homes", rows: H.rows || [], need: (r) => r.need, list: (r) => r.pipeline, needSoFar: (r) => r.need_so_far, listSoFar: (r) => r.pipeline_so_far,
        unit: "homes", what: `new homes needed within ${mi(data.market_miles)}`,
      }) + "</div><div>" + yearTable(["Year", "Needed a year", "On the city's lists", "Needed so far", "On the lists so far", "To rent / to own"],
        (H.rows || []).map((r) => ({ year: r.year, cells: [cellRange(r.need), num(r.pipeline), r.need_so_far ? cellRange(r.need_so_far) : "", has(r.pipeline_so_far) ? num(r.pipeline_so_far) : "",
          has(r.rented) ? `${num(r.rented)} / ${num(r.owned)}` : ""] })), "fc-compact") +
        `<dl class="facts fc-totals"><dt>Needed over ten years</dt><dd>${cellRange(H.need_10_years)}</dd><dt>On the city's lists over ten years</dt><dd>${num(H.pipeline_10_years)}</dd>
          <dt>Years of the expected need the lists cover</dt><dd>${isNum(H.pipeline_covers_years) ? num(H.pipeline_covers_years, 1) : NONE}</dd></dl>
        <p class="fine">To rent and to own splits the expected need by today's share of renters (census survey).</p>` + restsOn("homes") + "</div></div>";
    }
    let shops;
    if (!S.available) shops = notCovered("Shop space", "shops");
    else {
      shops = `<p class="fc-summary">${esc(S.summary || "")}</p><div class="fc-need-body"><div>` + needCharts({
        name: "shops", rows: S.rows || [], need: (r) => r.new_sq_ft, list: (r) => r.pipeline_sq_ft, needSoFar: (r) => r.new_so_far, listSoFar: (r) => r.pipeline_so_far,
        unit: "sq ft", what: `new shop space that growth within ${mi(data.market_miles)} supports`,
      }) + "</div><div>" + yearTable(["Year", "Supported a year (sq ft)", "On the city's lists", "Supported so far", "On the lists so far"],
        (S.rows || []).map((r) => ({ year: r.year, cells: [cellRange(r.new_sq_ft), num(r.pipeline_sq_ft), cellRange(r.new_so_far), num(r.pipeline_so_far)] })), "fc-compact") +
        `<dl class="facts fc-totals"><dt>Shop space a household supports</dt><dd>${isNum(S.sq_ft_per_home) ? num(S.sq_ft_per_home, 1) + " sq ft" : NONE}</dd>
          <dt>What homes within ${mm} support today</dt><dd>${cellRange(S.supported_today_sq_ft)} sq ft</dd>
          <dt>New over ten years</dt><dd>${cellRange(S.new_10_years_sq_ft)} sq ft</dd><dt>On the city's lists over ten years</dt><dd>${num(S.pipeline_10_years_sq_ft)} sq ft</dd></dl>` + restsOn("shops") + "</div></div>";
    }
    let jobs;
    if (!J.available) jobs = notCovered("Jobs and work space", "jobs");
    else {
      const readings = (J.readings || []).map((g) => [`<b>${esc(g.label)}</b> <span class="fc-tag official">official forecast</span><small>${esc(g.source || NONE)}</small>`, num(g.jobs_per_year),
        g.from ? `${num(g.from.jobs)}<small>in ${esc(g.from.year)}</small>` : NONE, g.to ? `${num(g.to.jobs)}<small>in ${esc(g.to.year)}</small>` : NONE]);
      jobs = `<p class="fc-summary">${esc(J.summary || "")}</p><div class="fc-need-body"><div>` + needCharts({
        name: "jobs", rows: J.rows || [], need: (r) => r.space_sq_ft, list: (r) => r.pipeline_sq_ft, needSoFar: (r) => r.space_so_far, listSoFar: (r) => r.pipeline_so_far,
        unit: "sq ft", what: `work space new jobs within ${mi(data.market_miles)} need`,
      }) + "</div><div>" + yearTable(["Year", "New jobs", "Space a year (sq ft)", "On the city's lists", "Space so far", "On the lists so far"],
        (J.rows || []).map((r) => ({ year: r.year, cells: [cellRange(r.new_jobs), cellRange(r.space_sq_ft), num(r.pipeline_sq_ft), cellRange(r.space_so_far), num(r.pipeline_so_far)] })), "fc-compact") +
        (readings.length ? `<h4 class="fc-sub">The readings of jobs</h4>${plainTable(["What it is, and its source", "New jobs a year", "From", "To"], readings, [1, 2, 3])}` : "") + restsOn("jobs") + "</div></div>";
    }
    box.innerHTML = `<h2 id="fcNeedsTitle">Homes needed, shops, jobs and work space</h2>
      <p class="fc-intro">What growth within ${mm} needs each year, beside what is already on the city's lists. The band is low to high, the line expected; the bars are projects already on the city's lists, spread over the years they are likely to open.</p>
      <div class="fc-needs">
        <article class="card fc-need"><h3>Homes needed</h3>${homes}</article>
        <article class="card fc-need"><h3>Shops and restaurants</h3>${shops}</article>
        <article class="card fc-need fc-wide"><h3>Jobs and work space</h3>${jobs}</article>
        <article class="card fc-need fc-stages">${stagesHtml()}</article>
      </div>`;
  }
  function stagesHtml() {
    const pipe = ((data.homes || {}).pipeline) || {}, counted = pipe.stages || [];
    const head = `<h3>Already on the city's lists, by stage</h3>`;
    if (!pipe.available) return head + notCovered("The city's project lists", "projects");
    const review = (data.figures || []).find((f) => f.id === "built_review_pct");
    const rows = (data.stages || []).map((st) => {
      const c = counted.find((x) => x.label === st.label);
      return { cls: st.uncertain ? "fc-unsure" : "", cells: [
        `<b>${esc(st.label)}</b>${st.uncertain ? ' <span class="fc-tag unsure">may not all be built</span>' : ""}`,
        `${esc(st.from_year)} to ${esc(st.to_year)}`, c ? num(c.projects) : "none", c ? num(c.homes) : "", c ? num(c.shops_sq_ft) : "", c ? num(c.work_sq_ft) : ""] };
    });
    const lists = Object.entries(pipe.lists_updated || {});
    return head + plainTable(["Stage", "Likely to open", "Projects", "Homes", "Shop space (sq ft)", "Work space (sq ft)"], rows, [2, 3, 4, 5]) +
      `<p class="fine">Counted: <b>${num(pipe.projects_counted)}</b> projects within ${esc(mi(data.market_miles))} that state a number of homes or a building size.${isNum(pipe.projects_without_sizes) && pipe.projects_without_sizes ? ` ${num(pipe.projects_without_sizes)} more within that distance state neither, so they are left out.` : ""} The lists hold ${num(pipe.projects_listed)} projects in all.
        ${review ? ` Stages marked “may not all be built” count ${figureValue(review)} of their homes and floor space (${esc(review.label.toLowerCase())}, ${review.yours ? "your figure" : "a starting figure"}).` : ""}</p>
      ${lists.length ? `<p class="fine">The city's lists used: ${lists.map(([name, d]) => `${esc(name)} (updated ${esc(day(d) || d)})`).join("; ")}.</p>` : ""}`;
  }

  // ---------------------------------------------------------------- traffic

  function drawTraffic() {
    const box = el.querySelector("#fcTraffic"), T = data.traffic || {};
    const head = `<h2 id="fcTrafficTitle">Traffic</h2>`;
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
      hover: rows.map((r) => ({ x: r.year, text: `${r.year}: about ${num(r.site_trips)} trips a day from the site` })),
    });
    box.innerHTML = head + `
      <p class="fc-summary">${esc(T.summary || "")}</p>
      <div class="fc-traffic">
        <div class="card"><h3>${esc(where)}${isNum(hw.miles_away) ? `, ${num(hw.miles_away, 2)} miles away` : ""}</h3>
          <div class="fc-chart" data-chart="highway"></div>
          <div class="legend fc-legend">${key("band", "Low to high")}${key("line", "Expected")}${key("focus", "Next five years")}</div>
          <h4 class="fc-sub">The site's own trips</h4>
          <div class="fc-chart" data-chart="trips"></div>
          <div class="legend fc-legend">${key("bar site", "Trips a day the site adds as its land is taken up")}</div>
        </div>
        <div>${yearTable(["Year", "Vehicles a day<small>expected, then low to high</small>", "The site's trips a day"],
          rows.map((r) => ({ year: r.year, cells: [cellRange(r.highway), num(r.site_trips)] })))}
          <p class="fine">Today's count is Caltrans' latest (${isNum(hw.today) ? num(hw.today) + " vehicles a day" : NONE}), both directions together. It grows with the homes around it; trips from the site follow its own take-up below.</p>
          ${restsOn("traffic")}</div>
      </div>`;
  }

  // ---------------------------------------------------------------- the site's own land

  function drawLand() {
    const box = el.querySelector("#fcLand"), G = data.programme || {}, uses = G.uses || [];
    const parcels = (data.site || {}).parcels || [];
    const planLinks = `<p class="fc-links">${parcels.map((p) => `<a class="btn small" href="#/land/${esc(data.city)}/${esc(p.apn)}/plan">${icon("plan")} Plan page of ${esc(p.apn_formatted || p.apn)}</a>`).join("")}</p>`;
    const head = `<h2 id="fcLandTitle">This site's land, year by year</h2>`;
    const notForecast = (G.not_forecast || []).length ? `<h3>Not forecast</h3><ul class="plain">${G.not_forecast.map((n) =>
      `<li><b>${esc(n.label)}</b>${isNum(n.acres) ? ` (${num(n.acres, 1)} acres)` : ""}: ${esc(n.why || NONE)}</li>`).join("")}</ul>` : "";
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
    const when = (u) => u.filled_in ? `all taken up by about ${u.filled_in}` : u.filled_later_in ? `filled around ${u.filled_later_in} at this pace` : u.never_at_this_pace ? "not filled at this pace" : "";
    const legend = uses.map((u) => `<li><i style="background:${colourOf(u.colour)}"></i><span><b>${esc(u.label)}</b>: ${num(u.acres, 1)} acres (${num(u.amount)} ${esc(u.unit)}). ${num(u.acres_by_year_5, 1)} acres by ${now() + 5}, ${num(u.acres_by_year_10, 1)} by ${now() + 10} (${num(u.pct_by_year_10)}%)${when(u) ? "; " + esc(when(u)) : ""}.</span></li>`).join("");
    const table = yearTable(["Year"].concat(uses.map((u) => `${esc(u.short || u.label)} (acres)`)),
      years.map((y) => ({ year: y, cells: uses.map((u) => { const r = (u.by_year || []).find((x) => x.year === y); return r ? `${num(r.acres_so_far, 1)}<small>${num(r.so_far)} ${esc(u.unit)}</small>` : NONE; }) })), "fc-compact");
    const steps = (G.steps || []).map((st) => `<article class="card fc-step"><p class="kicker dark">${esc(st.label)}</p><h3>${esc(st.title)}</h3><ul class="plain">${(st.lines || []).map((l) => `<li>${esc(l)}</li>`).join("")}</ul></article>`).join("");
    box.innerHTML = head + `
      <p class="fc-intro">${esc(G.basis || "")} The site wins a share of each year's new need of its kind (homes, shop space, work space), once its first land is ready.${isNum(G.acres) ? ` ${num(G.acres, 1)} acres in the plan` : ""}${isNum(G.trips_at_build_out) ? `, about ${num(G.trips_at_build_out)} trips a day once everything is built` : ""}.</p>
      <div class="fc-landgrid">
        <div class="card"><div class="fc-chart" data-chart="land"></div><ul class="fc-uses">${legend}</ul></div>
        <div>${table}</div>
      </div>
      ${steps ? `<div class="fc-steps">${steps}</div>` : ""}
      <div class="card fc-after">
        <div><h3>After ten years</h3>${(G.after || []).length ? `<ul class="plain">${G.after.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : "<p>All of the land is taken up within the ten years at this pace.</p>"}</div>
        <div>${notForecast || "<h3>Not forecast</h3><p>Every use on this site has a forecast.</p>"}${restsOn("programme")}${planLinks}</div>
      </div>`;
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
    const silent = Object.keys(answered).filter((p) => answered[p] === "did not answer");
    el.querySelector("#fcSources").innerHTML = `
      <div class="card"><h2>What answered</h2>
        ${plainTable(["Source", "What it gives", "Answered"], (data.sources || []).map((s) => [esc(s.name), esc(s.what), s.answered ? "Yes" : '<b class="fc-no">No</b>']))}
        ${silent.length ? `<p class="fc-again">${esc(cap(listWords(silent.map((p) => PART_WORDS[p] || p))))} did not answer just now. <button type="button" class="btn small" data-ask-again>Ask again</button></p>` : ""}
      </div>
      <div class="card fc-limits"><h2>Limits of this forecast</h2>
        <ul class="plain">${(data.limits || []).map((l) => `<li>${esc(l)}</li>`).join("")}
          <li>This is a forecast from public records and stated figures, not a market study or an appraisal.</li></ul>
      </div>`;
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
    if (b.dataset.jump) {
      const target = el.querySelector("#" + b.dataset.jump);
      if (target) { target.scrollIntoView({ behavior: "smooth", block: "start" }); const box = target.querySelector("input"); if (box) box.focus({ preventScroll: true }); }
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

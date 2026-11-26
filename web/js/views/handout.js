// The one-page summary: the site, the plan drawn on the land, its mix, the key numbers around it, what adds work and the
// first steps, on one US Letter page to leave with each person at a city meeting.
// Address: #/handout/<city>/<apn+apn+...>
// The sheet is drawn as soon as the forecast answers; hazards and steps come from the slower outlook answer and fill
// their blocks when it arrives. Every value comes from those two answers; a value they do not give reads "not covered yet".
// The drawing of the plan is inline SVG built from the plan's own pieces, so it prints crisply with no map tiles.
import { api } from "../api.js";
import { NONE, esc, has, num, plural, icon, loading, problem } from "../util.js";

const PARK = { id: "park", label: "Parks, open space and drainage", short: "Parks", colour: "#3f9d68" };
const WORDS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"];
const countWord = (n) => WORDS[n] || String(n);
const FT_PER_DEGREE_LAT = 69.05 * 5280;
// the drawing's box, in CSS pixels (96 to the inch): the same on screen and on paper
const DRAW_W = 307, DRAW_H = 218;
// how far the sheet may be tightened to stay on one page (each level keeps text at about 9pt or more)
const MOST_TIGHT = 5;

const isNum = (v) => has(v) && !isNaN(Number(v)) && isFinite(Number(v));
const colourOf = (c) => (/^#[0-9a-f]{3,8}$/i.test(String(c || "")) ? c : "#9aa0a6");
const miles = (m) => (isNum(m) ? `${num(m, 2)} ${Number(m) === 1 ? "mile" : "miles"}` : NONE);
const money = (v) => (isNum(v) ? "$" + num(v) : NONE);
const pct = (v, d = 0) => (isNum(v) ? num(v, d) + "%" : NONE);
function range(o, d = 0) {
  if (!o || !isNum(o.low) || !isNum(o.high)) return NONE;
  return Number(o.low) === Number(o.high) ? num(o.low, d) : `${num(o.low, d)} to ${num(o.high, d)}`;
}
function listWords(items) {
  if (items.length <= 1) return items.join("");
  return items.slice(0, -1).join(", ") + " and " + items[items.length - 1];
}
const dayWords = (d) => d.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
const years = (a, b) => (a === b ? String(a) : `${a} to ${b}`);
const lower = (s) => String(s || "").charAt(0).toLowerCase() + String(s || "").slice(1);
// a starting figure with its unit, as people say it: "30%", "$400 per sq ft", "2 years"
function figureWords(f) {
  const u = String(f.unit || ""), v = num(f.value, 2);
  if (u === "%") return v + "%";
  if (u.startsWith("$ ")) return "$" + v + " " + u.slice(2);
  return v + (u ? " " + u : "");
}
// when a use's land is all sold, at the forecast's expected pace
const filledWords = (u) => (u.filled_in ? `filled by about ${u.filled_in}` : u.filled_later_in ? `filled around ${u.filled_later_in}`
  : u.never_at_this_pace ? "not filled at this pace" : `when it fills: ${NONE}`);
const soldBy = (u) => (u.filled_in ? `about ${u.filled_in}` : u.filled_later_in ? `around ${u.filled_later_in}` : u.never_at_this_pace ? "not at this pace" : NONE);
// a starting figure's name up to its first comma or bracket: "Share of the need left each year"
const shortLabel = (s) => String(s || "").split(/[,(]/)[0].trim();
const gap = (what) => `<p class="ho-missing">${esc(what)}: ${NONE}.</p>`;

// ---------------------------------------------------------------- the drawing of the plan on the land

// rings of [lon, lat] from a parcel's outline (Polygon or MultiPolygon)
function outlineRings(p) {
  const o = p && p.outline;
  if (!o || !o.coordinates) return [];
  return o.type === "MultiPolygon" ? o.coordinates.flat() : o.coordinates;
}

function drawing(parcels, drawings) {
  const pieces = drawings.flatMap((d) => d.pieces || []).filter((p) => (p.ring || []).length >= 3);
  const parcelRings = parcels.flatMap(outlineRings).filter((r) => r.length >= 3);
  const fit = parcelRings.length ? parcelRings : pieces.map((p) => p.ring);
  const pts = fit.flat().filter((q) => isNum(q[0]) && isNum(q[1]));
  if (pts.length < 3) return { svg: "", drawn: false };
  const lat0 = pts.reduce((t, q) => t + Number(q[1]), 0) / pts.length, k = Math.cos(lat0 * Math.PI / 180);
  const xs = pts.map((q) => q[0] * k), ys = pts.map((q) => Number(q[1]));
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  // the box keeps its width; a wide, low site gets a lower box so the sheet keeps its room
  const pad = 30, W = DRAW_W;
  const aspect = ((maxY - minY) || 1e-6) / ((maxX - minX) || 1e-6);
  const H = Math.round(Math.max(190, Math.min(DRAW_H, (W - 2 * pad) * aspect + 2 * pad)));
  const s = Math.min((W - 2 * pad) / ((maxX - minX) || 1e-6), (H - 2 * pad) / ((maxY - minY) || 1e-6));
  const ox = (W - (maxX - minX) * s) / 2, oy = (H - (maxY - minY) * s) / 2;
  const P = (q) => [ox + (q[0] * k - minX) * s, oy + (maxY - q[1]) * s];
  const d = (ring, close = true) => ring.map((q, i) => { const [x, y] = P(q); return (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1); }).join("") + (close ? "Z" : "");
  const site = { x0: ox, y0: oy, x1: W - ox, y1: H - oy };

  let out = `<svg class="ho-draw" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Drawing of the plan on the land, north at the top">
    <defs><clipPath id="hoClip"><rect x="0" y="0" width="${W}" height="${H}"/></clipPath></defs><g clip-path="url(#hoClip)">`;

  // the city's planned streets around the site, thin, with their names
  const streetLines = drawings.flatMap((g) => g.street_lines || []).filter((l) => (l.path || []).length >= 2);
  streetLines.forEach((l) => {
    out += `<path class="ho-cityst" d="${d(l.path, false)}" style="stroke-width:${(1.2 + 0.9 * (Number(l.rank) || 1)).toFixed(1)}px"/>`;
  });
  // the uses on the land
  pieces.forEach((p) => {
    out += `<path class="ho-piece" d="${d(p.ring)}" style="fill:${colourOf(p.colour || (p.use === "park" ? PARK.colour : ""))}"/>`;
  });
  // streets inside the plan
  drawings.flatMap((g) => g.streets || []).filter((st) => (st.line || []).length >= 2).forEach((st) => {
    out += `<path class="ho-st-case" d="${d(st.line, false)}"/><path class="ho-st" d="${d(st.line, false)}"/>`;
  });
  // parcel lines on top
  if (parcelRings.length) out += `<path class="ho-parcel${pieces.length ? "" : " alone"}" d="${parcelRings.map((r) => d(r)).join("")}"/>`;

  // labels: each piece's short name and acres where they fit, the name alone where only that fits
  const placed = [];
  pieces.forEach((p) => {
    if (!p.label_at || !isNum(p.label_at[0])) return;
    const [x, y] = P(p.label_at), box = p.ring.map(P);
    const bw = Math.max(...box.map((q) => q[0])) - Math.min(...box.map((q) => q[0]));
    const bh = Math.max(...box.map((q) => q[1])) - Math.min(...box.map((q) => q[1]));
    const name = String(p.short || p.label || p.use || ""), ac = isNum(p.acres) ? `${num(p.acres, 1)} ac` : "";
    const wide = (t) => t.length * 6.9 + 4;
    if (bw >= Math.max(wide(name), wide(ac)) && bh >= 32 && ac) {
      out += `<text class="ho-lab" x="${x.toFixed(1)}" y="${(y - 3).toFixed(1)}" text-anchor="middle"><tspan x="${x.toFixed(1)}" font-weight="650">${esc(name)}</tspan><tspan x="${x.toFixed(1)}" dy="14">${esc(ac)}</tspan></text>`;
      placed.push([x, y]);
    } else if (bw >= wide(name) && bh >= 17) {
      out += `<text class="ho-lab" x="${x.toFixed(1)}" y="${(y + 4).toFixed(1)}" text-anchor="middle" font-weight="650">${esc(name)}</text>`;
      placed.push([x, y]);
    } else if (bh >= wide(name) && bw >= 17) {
      // a tall, narrow piece: its name runs up the piece
      out += `<text class="ho-lab" x="${x.toFixed(1)}" y="${y.toFixed(1)}" dy="4" text-anchor="middle" font-weight="650" transform="rotate(-90 ${x.toFixed(1)} ${y.toFixed(1)})">${esc(name)}</text>`;
      placed.push([x, y]);
    }
  });
  // one name per street, on its stretch nearest the site, outside the site and inside the drawing
  const byName = new Map();
  streetLines.forEach((l) => { if (l.name) byName.set(l.name, (byName.get(l.name) || []).concat([l.path.map(P)])); });
  const toSite = (x, y) => Math.hypot(Math.max(site.x0 - x, 0, x - site.x1), Math.max(site.y0 - y, 0, y - site.y1));
  byName.forEach((paths, name) => {
    let best = null;
    paths.forEach((pp) => {
      for (let i = 0; i < pp.length - 1; i++) {
        const [ax, ay] = pp[i], [bx, by] = pp[i + 1], len = Math.hypot(bx - ax, by - ay), n = Math.max(1, Math.ceil(len / 4));
        for (let j = 0; j <= n; j++) {
          const x = ax + (bx - ax) * j / n, y = ay + (by - ay) * j / n, half = name.length * 3.4 + 4;
          if (x < half || x > W - half || y < 14 || y > H - 10) continue;
          const dist = toSite(x, y);
          if (dist < 5) continue;
          if (placed.some((q) => Math.hypot(q[0] - x, q[1] - y) < 44)) continue;
          if (!best || dist < best.dist) best = { x, y, dist, angle: Math.atan2(by - ay, bx - ax) * 180 / Math.PI };
        }
      }
    });
    if (!best) return;
    let a = best.angle;
    if (a > 90) a -= 180;
    if (a < -90) a += 180;
    out += `<text class="ho-stname" x="${best.x.toFixed(1)}" y="${best.y.toFixed(1)}" dy="-4" text-anchor="middle" transform="rotate(${a.toFixed(1)} ${best.x.toFixed(1)} ${best.y.toFixed(1)})">${esc(name)}</text>`;
    placed.push([best.x, best.y]);
  });
  out += `</g>`;

  // north and a scale, since a planner will read distances off it
  out += `<g class="ho-north" transform="translate(${W - 16} 16)"><path d="M0 -9 L5 5 L0 2 L-5 5 Z"/><text y="17" text-anchor="middle">N</text></g>`;
  const ftPerPx = FT_PER_DEGREE_LAT / s, want = 80 * ftPerPx;
  const nice = [50, 100, 200, 250, 500, 1000, 1500, 2000, 2500, 5000, 10000].filter((f) => f <= want * 1.25).pop();
  if (nice) {
    const len = nice / ftPerPx;
    out += `<g class="ho-scale" transform="translate(10 ${H - 12})"><path d="M0 -4V0H${len.toFixed(1)}V-4"/><text x="${(len + 6).toFixed(1)}" y="1">${esc(num(nice))} ft</text></g>`;
  }
  if (pieces.length) out += `<text class="ho-sketch" x="${W - 8}" y="${H - 8}" text-anchor="end">A first sketch: not lot lines</text>`;
  return { svg: out + `</svg>`, drawn: pieces.length > 0 };
}

// ---------------------------------------------------------------- the page

export async function render(main, route, alive) {
  const cityId = route.city, apns = route.apns || [];
  const pathApns = apns.map(encodeURIComponent).join("+");
  const backHref = `#/forecast/${encodeURIComponent(cityId)}/${pathApns}`;
  const presentHref = `#/present/${encodeURIComponent(cityId)}/${pathApns}`;
  const cleanups = [];
  let gone = false;
  alive.onLeave(() => { gone = true; cleanups.splice(0).forEach((fn) => { try { fn(); } catch (e) { console.error(e); } }); });

  if (!apns.length) {
    main.innerHTML = problem("This address does not name any parcel numbers. Open a land's forecast and choose the one-page summary from there.", "") +
      `<p class="ho-back-row"><a class="btn" href="#/my-lands">Go to My lands</a></p>`;
    return;
  }
  main.innerHTML = loading("Preparing the one-page summary from the public records around this site. The first time takes several seconds.");
  let F;
  try {
    F = await api.forecast(cityId, apns);
  } catch (e) {
    if (!alive()) return;
    // a parcel that does not exist will not appear by asking again; anything else might
    if (e.status === 404 || e.status === 400) {
      main.innerHTML = problem(e.message, "") + `<p class="ho-back-row"><a class="btn" href="#/lands/${encodeURIComponent(cityId)}">Back to the lands</a></p>`;
      return;
    }
    main.innerHTML = problem(e.message) + `<p class="ho-back-row"><a class="btn" href="${esc(backHref)}">Back to the forecast</a></p>`;
    main.querySelector("[data-retry]").addEventListener("click", () => render(main, route, alive));
    return;
  }
  if (!alive()) return;
  F = F || {};

  // ---------------------------------------------------------------- facts the sheet uses

  const S = { O: null, Oerr: "", tight: 0 };
  const site = F.site || {}, parcels = site.parcels || [], G = F.programme || {};
  const forecastOk = F.available !== false;
  const market = F.market_miles;
  const R = (F.rings || []).find((r) => r.miles === market) || null;
  const rowAt = (rows, y) => (rows || []).find((r) => r.year === y);
  const lastRow = (rows) => (rows || [])[(rows || []).length - 1];
  const headlineItem = (start) => (F.headline || []).find((h) => String(h.label || "").startsWith(start));
  const drawings = (G.drawings || []).filter((g) => g && ((g.pieces || []).length || (g.street_lines || []).length));
  const pieces = drawings.flatMap((g) => g.pieces || []);
  const uses = (G.uses || []).filter((u) => Number(u.acres) > 0);
  const zones = [...new Set(parcels.map((p) => p.zoning_name ? `${p.zoning_name}${p.zoning ? ` (${p.zoning})` : ""}` : p.zoning).filter(Boolean))];
  const cityName = F.city_name || cityId;
  const siteName = `${isNum(site.acres) ? num(site.acres, 2) + " " + plural(site.acres, "acre", "acres", 2) : "The site"} in ${cityName}`;
  const prepared = dayWords(new Date());

  // ---------------------------------------------------------------- the blocks

  function header() {
    const count = parcels.length;
    const lead = `${count === 1 ? "One parcel" : count ? `${countWord(count)} ${site.together ? "neighbouring " : ""}parcels` : "Parcels"}.` +
      `${count > 1 && site.together === false ? " The parcels are not next to each other." : ""}` +
      `${G.basis ? " " + G.basis : ""}`;
    const shown = parcels.slice(0, 6);
    const more = parcels.length - shown.length;
    return `<header class="ho-head">
      <div class="ho-headrow">
        <div><p class="ho-kicker">Summary for the City of ${esc(cityName)}</p><h1>${esc(siteName)}</h1><p class="ho-lead">${esc(lead)}</p></div>
        <dl class="ho-facts">
          <div class="ho-apns"><dt>${count === 1 ? "Parcel number" : "Parcel numbers"}</dt><dd>${shown.length ? `<ul>${shown.map((p) => `<li><span>${esc(p.apn_formatted || p.apn)}</span><span class="ho-num">${isNum(p.acres) ? num(p.acres, 2) + " ac" : ""}</span></li>`).join("")}</ul>${more > 0 ? `<span class="ho-more">and ${more} more</span>` : ""}` : NONE}</dd></div>
          <div><dt>Acres</dt><dd class="ho-num">${isNum(site.acres) ? num(site.acres, 2) : NONE}</dd></div>
          <div><dt>${zones.length > 1 ? "Zones" : "Zone"}</dt><dd>${zones.length ? zones.map(esc).join("<br>") : NONE}</dd></div>
          <div><dt>Prepared</dt><dd>${esc(prepared)}</dd></div>
        </dl>
      </div>
    </header>`;
  }

  function plan() {
    const pic = drawing(parcels, drawings);
    let caption;
    if (!pic.svg) caption = `<p class="ho-missing">The outline of the land and the plan on it: ${NONE}.</p>`;
    else if (!pic.drawn) caption = `<p class="ho-note">The parcel lines only: where each use sits is ${NONE} for this site.</p>`;
    else caption = "";
    return `<section class="ho-plan" aria-labelledby="hoPlanH"><h2 id="hoPlanH">The plan on the land</h2>
      ${pic.svg ? `<div class="ho-drawbox">${pic.svg}</div>` : ""}${caption}</section>`;
  }

  function mix() {
    const parkAcres = pieces.filter((p) => p.use === "park").reduce((t, p) => t + (Number(p.acres) || 0), 0);
    let rows = uses.map((u) => ({
      colour: u.colour, label: u.label, acres: u.acres,
      amount: isNum(u.amount) ? `${num(u.amount)} ${esc(u.unit || "")}` : NONE, when: soldBy(u),
    }));
    // uses the plan holds but the forecast could not size (no reading for their kind)
    (G.not_forecast || []).forEach((n) => {
      if (typeof n !== "object" || !(Number(n.acres) > 0)) return;
      const look = pieces.find((p) => p.use === n.id) || {};
      rows.push({ colour: look.colour, label: n.label || look.label || n.id, acres: n.acres, amount: NONE, when: "not forecast", why: n.why || "" });
    });
    // no forecast of the uses at all: the drawing still says how much land each takes
    if (!rows.length && pieces.length) {
      const sums = new Map();
      pieces.filter((p) => p.use !== "park").forEach((p) => {
        const r = sums.get(p.use) || { colour: p.colour, label: p.label || p.short || p.use, acres: 0, amount: NONE, when: NONE };
        r.acres += Number(p.acres) || 0;
        sums.set(p.use, r);
      });
      rows = [...sums.values()];
    }
    if (parkAcres) rows.push({ colour: PARK.colour, label: PARK.label, acres: parkAcres, amount: "", when: "", span: "built with the uses around them" });
    const homes = uses.filter((u) => u.kind === "homes").reduce((t, u) => t + (Number(u.amount) || 0), 0);
    const feet = uses.filter((u) => u.kind !== "homes" && u.unit === "sq ft").reduce((t, u) => t + (Number(u.amount) || 0), 0);
    const total = isNum(G.acres) ? G.acres : rows.reduce((t, r) => t + (Number(r.acres) || 0), 0);
    const totalWhat = [homes ? `${num(homes)} ${plural(homes, "home")}` : "", feet ? `${num(feet)} sq ft` : ""].filter(Boolean).join(", ");
    const body = rows.length ? `<table class="ho-mix">
        <colgroup><col><col class="ho-c-ac"><col class="ho-c-amt"><col class="ho-c-sold"></colgroup>
        <thead><tr><th scope="col">Use</th><th scope="col" class="num">Acres</th><th scope="col" class="num">Size</th><th scope="col" class="num">Sold by*</th></tr></thead>
        <tbody>${rows.map((r) => `<tr><th scope="row"><div class="ho-use"><i class="ho-sw" style="background:${colourOf(r.colour)}"></i><span>${esc(r.label)}${r.why ? `<small>${esc(r.why)}</small>` : ""}</span></div></th>
          <td class="num">${isNum(r.acres) ? num(r.acres, 1) : NONE}</td>${r.span ? `<td class="num ho-sold ho-wrap" colspan="2">${esc(r.span)}</td>` : `<td class="num">${r.amount}</td><td class="num ho-sold">${esc(r.when)}</td>`}</tr>`).join("")}</tbody>
        <tfoot><tr><th scope="row">The whole plan</th><td class="num">${isNum(total) && total > 0 ? num(total, 1) : NONE}</td><td class="num ho-wrap" colspan="2">${totalWhat || (uses.length ? "" : NONE)}</td></tr></tfoot>
      </table>` : gap("The uses of the land");
    const trips = isNum(G.trips_at_build_out) && G.trips_at_build_out > 0
      ? `<p class="ho-note">About ${num(G.trips_at_build_out)} ${plural(G.trips_at_build_out, "trip")} a day once everything is built.</p>` : "";
    return `<section class="ho-mixbox" aria-labelledby="hoMixH"><h2 id="hoMixH">The plan's mix</h2>${body}${trips}</section>`;
  }

  const fig = (label, value, note, cls = "") => `<div class="ho-fig ${cls}"><p class="ho-fig-label">${label}</p><p class="ho-fig-num">${value}</p>${note ? `<p class="ho-fig-note">${note}</p>` : ""}</div>`;

  function numbers() {
    const mi = esc(miles(market));
    // people now, in five years and in ten
    const now = R && R.available ? rowAt(R.rows, F.year) : null;
    const mid = R && R.available ? rowAt(R.rows, F.year + 5) : null;
    const end = R && R.available ? lastRow(R.rows) : null;
    const c = (R && R.counted) || {}, counted = Object.keys(c).sort().pop();
    const peopleOf = (row) => (row && row.people && isNum(row.people.expected) ? num(row.people.expected) : NONE);
    const lowHigh = (o) => (o && isNum(o.low) && isNum(o.high) ? `Low to high: ${range(o)}.` : "");
    const rates = (R && R.rates_pct) || {};
    const growth = isNum(rates.expected) ? ` Homes growing ${pct(rates.expected, 2)} a year.` : "";
    const tiles = [
      fig(`People within ${mi}`, peopleOf(now),
        now ? `${esc(now.year)} estimate${counted && c[counted] && isNum(c[counted].people) ? `; ${num(c[counted].people)} counted in the ${esc(counted)} Census` : ""}.` : ""),
      fig(`By ${esc(mid ? mid.year : F.year + 5)}`, peopleOf(mid), `${lowHigh(mid && mid.people)}${growth}`),
      fig(`By ${esc(end ? end.year : F.year + 10)}`, peopleOf(end), lowHigh(end && end.people)),
    ];

    // new homes needed a year nearby
    const H = F.homes || {}, need = headlineItem("New homes needed");
    tiles.push(need && isNum(need.value)
      ? fig("New homes needed a year", num(need.value),
        `Within ${mi}. ${lowHigh(need)}${isNum(H.pipeline_covers_years) && S.tight < 1 ? ` The city's lists cover ${num(H.pipeline_covers_years, 1)} ${plural(H.pipeline_covers_years, "year", "years", 1)}.` : ""}`)
      : fig("New homes needed a year", NONE, `Within ${mi}.`));

    // when this site's land first goes to builders, and when its homes are all sold
    const firstSale = Math.min(...uses.flatMap((u) => (u.by_year || []).filter((y) => Number(y.taken) > 0).map((y) => y.year)));
    const homeUses = uses.filter((u) => u.kind === "homes");
    tiles.push(uses.length
      ? fig("Site first offered to builders*", isFinite(firstSale) ? esc(firstSale) : NONE,
        homeUses.length ? esc(`Its homes ${homeUses.map((u) => filledWords(u)).join("; ")}.`) : "")
      : fig("Site first offered to builders", NONE, (G.not_forecast || []).length ? "The uses could not be forecast." : ""));

    // typical household income nearby
    const inc = F.income || {};
    tiles.push(inc.available
      ? fig("Typical household income", money(inc.typical),
        `Within ${mi}. ${esc(inc.county_name || "The county")}: ${money(inc.county)}.${inc.survey ? ` Survey ${esc(inc.survey)}.` : ""}`)
      : fig("Typical household income", NONE, `Within ${mi}.`));

    // highway traffic now and later
    const T = F.traffic || {}, hw = T.highway || {}, tEnd = lastRow(T.rows);
    tiles.push(T.available && isNum(hw.today)
      ? fig(`Route ${esc(hw.route)}, vehicles a day`, num(hw.today), `At ${esc(hw.where)}, ${esc(miles(hw.miles_away))} away. Caltrans' latest count.`)
      : fig("Highway, vehicles a day", NONE, ""));
    tiles.push(T.available && tEnd && tEnd.highway
      ? fig(`By ${esc(tEnd.year)}`, num(tEnd.highway.expected), `${lowHigh(tEnd.highway)} Grown with the homes around it.`)
      : fig("Highway traffic later", NONE, ""));

    const banner = forecastOk ? "" : `<p class="ho-missing ho-wide">The forecast for this site is ${NONE}: no reading of growth answered, so the figures that follow from it are left blank.</p>`;
    return `<section class="ho-numbers" aria-labelledby="hoNumH"><h2 id="hoNumH">The numbers around it</h2>${banner}
      <div class="ho-figs">${tiles.join("")}</div></section>`;
  }

  const waitingFor = (what) => S.Oerr
    ? `<div class="ho-wait"><p class="ho-missing">${esc(what)} could not be read just now (${esc(S.Oerr)}).</p><button type="button" class="btn small ho-screen" data-outlook-again>Try again</button></div>`
    : `<div class="ho-wait"><span class="spinner" aria-hidden="true"></span><p>Reading the city's records for ${esc(lower(what))}. This fills in by itself in a moment.</p></div>`;

  // the city's state housing target, when the state's figures answered: one line, with this plan's homes beside it
  function housingLine() {
    const G = S.O && S.O.housing;
    if (!G || !G.available || !isNum(G.target) || !isNum(G.permitted)) return "";
    const lower = G.lower || {}, mine = G.site;
    return `<p class="ho-goal"><b>The city's state housing target.</b> The state requires ${esc(cityName)} to plan for ${num(G.target)} homes${isNum(G.to_year) ? ` by ${esc(G.to_year)}` : ""}; it has permitted ${num(G.permitted)}${isNum(G.through_year) ? ` through ${esc(G.through_year)}` : ""}.${isNum(lower.left) && Number(lower.left) > 0 ? ` ${num(lower.left)} are still to come for very low, low and moderate incomes.` : ""}${mine ? ` This plan holds ${num(mine.homes)} ${plural(mine.homes, "home")}; which income level they count toward is agreed with the city.` : ""}</p>`;
  }

  function hazards() {
    let body;
    if (!S.O) body = waitingFor("The hazard records");
    else {
      const Z = S.O.hazards || {};
      if (!Z.available) body = gap("Hazards on the site");
      else {
        const f = Z.findings || [], work = f.filter((x) => x.level === "work"), clear = f.filter((x) => x.level === "clear");
        const firstSentence = (t) => { const m = /^(.+?[.!?])(\s|$)/.exec(String(t || "")); return m ? m[1] : String(t || ""); };
        body = (work.length
          ? `<ul class="ho-haz">${work.map((x) => `<li>${icon("alert")}<p><b>${esc(x.topic)}.</b> ${esc(S.tight >= 5 ? firstSentence(x.text) : x.text)}</p></li>`).join("")}</ul>`
          : `<p class="ho-plain">No finding adds work.</p>`) +
          `<p class="ho-clear">${icon("check")}<span><b>Clear:</b> ${clear.length ? esc(listWords(clear.map((x) => lower(x.topic)))) + "." : "no finding is clear outright."}` +
          `</span></p>` +
          ((Z.did_not_answer || []).length ? `<p class="ho-note">Did not answer just now: ${esc(Z.did_not_answer.join(", "))}.</p>` : "");
      }
    }
    return `<section class="ho-hazards" aria-labelledby="hoHazH"><h2 id="hoHazH">What adds work</h2>${body}</section>`;
  }

  function steps() {
    let body;
    if (!S.O) body = waitingFor("The steps to take");
    else {
      const st = ((S.O.todo || {}).steps || []);
      if (!st.length) body = gap("The steps to take");
      else {
        const shown = st.slice(0, S.tight >= 3 ? 4 : 5), rest = st.length - shown.length;
        const when = (s) => (isNum(s.from_year) && isNum(s.to_year) ? years(s.from_year, s.to_year) : isNum(s.from_year) ? String(s.from_year) : NONE);
        body = `<ol class="ho-steps">${shown.map((s) => `<li><p><span class="ho-num ho-yr">${esc(when(s))}</span> <b>${esc(s.what || NONE)}</b></p>
            ${s.who && S.tight < 4 ? `<p class="ho-who">${esc(s.who)}</p>` : ""}</li>`).join("")}</ol>` +
          (rest > 0 ? `<p class="ho-note">And ${rest} more ${plural(rest, "step")} on the forecast page.</p>` : "");
      }
    }
    return `<section class="ho-stepsbox" aria-labelledby="hoStepH"><h2 id="hoStepH">First steps</h2>${body}</section>`;
  }

  // what the hazard records do not cover
  function notCovered() {
    const nc = S.O && S.O.hazards && S.O.hazards.available ? S.O.hazards.not_covered || [] : [];
    return nc.length ? ` <b>Not covered yet:</b> ${esc(nc.map((t) => lower(String(t).split(":")[0])).join("; "))}.` : "";
  }

  function foot() {
    const answered = [], missed = [], seen = new Set();
    const add = (name, ok = true) => {
      const k = String(name || "").toLowerCase();
      if (!name || seen.has(k)) return;
      seen.add(k);
      (ok ? answered : missed).push(String(name));
    };
    (F.sources || []).forEach((s) => add(s.name, s.answered));
    if (S.O) {
      ((S.O.hazards || {}).findings || []).forEach((f) => add(f.source));
      ((S.O.hazards || {}).did_not_answer || []).forEach((s) => add(s, false));
      if ((S.O.housing || {}).available) add("State housing department progress reports");
    }
    const figs = F.figures || [], mine = figs.filter((f) => f.yours);
    const siteFigs = figs.filter((f) => f.group === "The site");
    const figWords = siteFigs.map((f) => `${lower(shortLabel(f.label))}, ${figureWords(f)}${f.yours ? " (the owner's figure)" : ""}`);
    return `<footer class="ho-foot">
      <p><b>Sources:</b> ${answered.length ? esc(answered.join(", ")) : NONE}.${missed.length ? ` Did not answer just now: ${esc(listWords(missed))}.` : ""}${!S.O && !S.Oerr ? " The hazard sources are added when the city's records arrive." : ""}${notCovered()}</p>
      ${figs.length ? `<p><b>Starting figures (assumptions):</b> ${countWord(figs.length).toLowerCase()}, set out on the forecast page${mine.length ? `, ${countWord(mine.length).toLowerCase()} of them the owner's own` : ""}.${figWords.length && uses.length ? ` *Years at the forecast's expected pace, resting on: ${esc(figWords.join("; "))}.` : ""}</p>` : ""}
      <p class="ho-limit">A forecast from public records and stated figures, not a market study or an appraisal.</p>
    </footer>`;
  }

  // ---------------------------------------------------------------- drawing the sheet and keeping it on one page

  main.innerHTML = `<div class="ho-stage">
    <div class="ho-bar" role="toolbar" aria-label="One-page summary">
      <a class="btn small" href="${esc(backHref)}">${icon("arrow", "ho-flip")}<span>Back to the forecast</span></a>
      <p class="ho-bar-note" aria-live="polite"></p>
      <a class="btn small" href="${esc(presentHref)}">Open the presentation</a>
      <button type="button" class="btn small primary" data-print>Print</button>
    </div>
    <div class="ho-fitbox"><article class="ho-sheet" aria-label="One-page summary of ${esc(siteName)}"><div class="ho-inner"></div></article></div>
  </div>`;
  const stage = main.querySelector(".ho-stage"), sheet = main.querySelector(".ho-sheet"), inner = main.querySelector(".ho-inner");
  const note = main.querySelector(".ho-bar-note");

  function paint() {
    // 1: less room between blocks; 2: running text at 9pt; 3: four steps, not five; 4: the steps without who does them
    // (the hazards then take the wider column); 5: each hazard finding's first sentence only
    inner.className = "ho-inner" + (S.tight >= 1 ? " ho-t1" : "") + (S.tight >= 2 ? " ho-t2" : "") + (S.tight >= 4 ? " ho-t4" : "");
    inner.dataset.tight = String(S.tight);
    inner.innerHTML = header() + `<div class="ho-row ho-top">${plan()}${mix()}</div>` + numbers() + housingLine() +
      `<div class="ho-row ho-bottom">${hazards()}${steps()}</div>` + foot();
    note.textContent = !S.O && !S.Oerr ? "Hazards and first steps are still being read; they fill in by themselves." : "Prints on one Letter page.";
  }
  const over = () => inner.scrollHeight > inner.clientHeight + 1;
  // text from the records runs longer on some sites: the sheet tightens a step at a time until it fits one page
  function draw() {
    S.tight = 0;
    paint();
    while (over() && S.tight < MOST_TIGHT) { S.tight++; paint(); }
    const still = over();
    sheet.classList.toggle("ho-over", still);
    if (still) note.textContent = "This site's records run longer than one page: the sheet prints on two.";
  }
  // the sheet keeps its paper shape; a narrow window shows it smaller
  function scale() {
    const room = stage.clientWidth;
    sheet.style.zoom = room && room < 816 ? String(Math.max(0.35, room / 816)) : "";
  }

  stage.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.hasAttribute("data-print")) window.print();
    else if (b.hasAttribute("data-outlook-again")) askOutlook();
  });
  const onResize = () => { if (!gone) scale(); };
  window.addEventListener("resize", onResize);
  cleanups.push(() => window.removeEventListener("resize", onResize));

  function askOutlook() {
    S.Oerr = "";
    draw();
    api.outlook(cityId, apns).then((o) => {
      if (gone || !alive()) return;
      S.O = o || {};
      draw();
    }, (e) => {
      if (gone || !alive()) return;
      S.Oerr = (e && e.message) || "no answer";
      draw();
    });
  }

  scale();
  askOutlook();
}

// The frame of the app: the sidebar and which page is showing. Addresses look like
//   #/cities   #/lands/menifee   #/my-lands   #/land/menifee/372100001/terrain
import { cities, saved } from "./api.js";
import { esc, num, plural, icon, problem } from "./util.js";
import * as citiesView from "./views/cities.js";
import * as landsView from "./views/lands.js";
import * as myLandsView from "./views/mylands.js";
import * as landView from "./views/land.js";
import * as forecastView from "./views/forecast.js";
import * as presentView from "./views/present.js";
import * as handoutView from "./views/handout.js";
import * as districtView from "./district/router.js";

const DISTRICTS_ICON = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 21h18M4 21V10l5-3v14M9 21V4l7 3v14M16 21v-9l4 2v7M12 9v.01M12 12v.01M12 15v.01"/></svg>';
const main = document.getElementById("main"), side = document.getElementById("side");
let visit = 0, leaving = [], lastCity = null, openLand = null;

const decode = (x) => { try { return decodeURIComponent(x); } catch (e) { return x; } };
// A parcel number is digits; dashes, dots and spaces between them are allowed (372-100-001). Anything else, letters
// included, is not a parcel number, and is kept as typed so the page can say so instead of quietly dropping it.
const tidy = (x) => x.replace(/[\s.\-]/g, "");
const isApn = (x) => /^\d+$/.test(x);
function apnList(text) {
  const given = text.split(/[+,\s]+/).filter(Boolean);
  return { apns: given.map(tidy).filter(isApn), bad: given.filter((x) => !isApn(tidy(x))) };
}

function parse() {
  const raw = location.hash.replace(/^#\/?/, "").split("?")[0].split("/").map(decode);
  while (raw.length && raw[raw.length - 1] === "") raw.pop();   // a trailing slash is nothing
  const [first, a] = raw;
  if (first === "lands") return { name: "lands", city: a || null };
  if (first === "my-lands") return { name: "my-lands" };
  // #/districts/...: the district workspace, which reads the rest of the address itself
  if (first === "districts") return { name: "districts", rest: raw.slice(1) };
  // #/land/menifee/372100001/zoning (an empty or lettered parcel number is kept in `bad`)
  if (first === "land" && a) {
    const given = raw[2] === undefined ? "" : raw[2], apn = tidy(given), page = raw[3] || "overview";
    return isApn(apn) ? { name: "land", city: a, apn, page } : { name: "land", city: a, apn: "", page, bad: [given] };
  }
  // #/forecast/menifee/360350024+360350017: one parcel, or several forecast as one site
  if (first === "forecast" && a) { const l = apnList(raw[2] || ""); return { name: "forecast", city: a, apns: l.apns, bad: l.bad }; }
  // #/present/menifee/360350024+360350017: the same site as slides for the city (the sidebar is hidden)
  if (first === "present" && a) { const l = apnList(raw[2] || ""); return { name: "present", city: a, apns: l.apns, bad: l.bad }; }
  // #/handout/menifee/360350024+360350017: the same site on one printed page, to leave with the people in the room
  if (first === "handout" && a) { const l = apnList(raw[2] || ""); return { name: "handout", city: a, apns: l.apns, bad: l.bad }; }
  return { name: "cities" };
}

function drawSide(route) {
  const count = saved.list().length;
  const item = (href, name, label, extra = "") =>
    `<a href="${href}" class="nav${route.name === name ? " on" : ""}"${route.name === name ? ' aria-current="page"' : ""}>${icon(name === "my-lands" ? "saved" : name)}<span>${label}</span>${extra}</a>`;
  let html = `
    <a class="brand" href="#/cities" aria-label="Land Planner, home">
      <svg viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="8" fill="#f2b632"/><path d="M7 22.5 12 9l7 3.5 6-2.5-2.5 13.5-8-2.5-7.5 1.5z" fill="none" stroke="#1f4436" stroke-width="2.4" stroke-linejoin="round"/></svg>
      <span>Land Planner</span></a>
    <nav aria-label="Sections">
      ${item("#/cities", "cities", "Cities")}
      ${item("#/lands" + (lastCity ? "/" + lastCity : ""), "lands", "Lands")}
      ${item("#/my-lands", "my-lands", "My lands", count ? `<i class="badge">${count}</i>` : "")}
      <a href="#/districts" class="nav${route.name === "districts" ? " on" : ""}"${route.name === "districts" ? ' aria-current="page"' : ""}>${DISTRICTS_ICON}<span>Districts</span></a>
    </nav>`;
  if (route.name === "districts") { side.innerHTML = html + districtView.side(route); return; }
  if (openLand) {
    const base = `#/land/${esc(openLand.city)}/${esc(openLand.apn)}`;
    const forecastOn = route.name === "forecast" && route.apns.length === 1 && route.apns[0] === openLand.apn && route.city === openLand.city;
    html += `<div class="side-land"><p class="side-title">${route.name === "land" || forecastOn ? "This land" : "Last opened"}</p>
      <a class="side-parcel" href="${base}"><b>${esc(openLand.number || openLand.apn)}</b>${openLand.acres != null ? `<span>${num(openLand.acres, 2)} ${plural(openLand.acres, "acre", "acres", 2)}</span>` : ""}</a>
      <nav aria-label="This land's pages">${landView.PAGES.map(([id, label]) => {
        const on = route.name === "land" && route.apn === openLand.apn && route.page === id;
        return `<a href="${base}/${id}" class="nav sub${on ? " on" : ""}"${on ? ' aria-current="page"' : ""}>${icon(id)}<span>${label}</span></a>`;
      }).join("")}<a href="${landView.forecastLink(openLand.city, [openLand.apn])}" class="nav sub${forecastOn ? " on" : ""}"${forecastOn ? ' aria-current="page"' : ""}>${landView.FORECAST_ICON}<span>Forecast</span></a></nav></div>`;
  }
  html += `<p class="side-foot">Real public records only. Outlines are not a survey, and zoning changes go through the city.</p>`;
  side.innerHTML = html;
}

// "37210000a is not a parcel number", with a way back to the Lands list
function notAParcel(route) {
  const typed = route.bad.filter(Boolean).map((x) => "“" + esc(x) + "”");
  const words = !typed.length ? "This address does not have a parcel number in it."
    : typed.length === 1 ? `${typed[0]} is not a parcel number.` : `${typed.join(", ")} are not parcel numbers.`;
  main.innerHTML = `<header class="page-head"><h1>That is not a parcel number</h1></header>` +
    `<div class="state problem" role="alert">${icon("alert")}<p>${words} A parcel number (APN) has 9 digits, for example 372-100-001.</p></div>` +
    `<p><a class="btn" href="#/lands/${encodeURIComponent(route.city)}">Back to the lands</a></p>`;
  main.focus({ preventScroll: true });
}

async function show() {
  const route = parse(), mine = ++visit;
  leaving.splice(0).forEach((fn) => { try { fn(); } catch (e) { console.error(e); } });
  const alive = () => mine === visit;
  alive.onLeave = (fn) => { if (alive()) leaving.push(fn); else fn(); };

  if (route.name === "lands" && !route.city) {
    try {
      const list = await cities();
      if (alive()) location.replace("#/lands/" + (lastCity || list[0].id));
    } catch (e) {
      if (alive()) { drawSide(route); main.innerHTML = `<header class="page-head"><h1>Lands</h1></header>` + problem(e.message); main.querySelector("[data-retry]").addEventListener("click", show); }
    }
    return;
  }
  if (route.name === "lands") lastCity = route.city;
  if (route.name === "land" && route.bad && route.bad.length) {
    // a parcel number with letters in it, or none at all: say so, and show the way back
    lastCity = route.city;
    if (!openLand || openLand.city !== route.city) openLand = null;
  } else if (route.name === "land") {
    lastCity = route.city;
    if (!openLand || openLand.apn !== route.apn || openLand.city !== route.city) openLand = { city: route.city, apn: route.apn };
  }
  if (route.name === "forecast" || route.name === "present" || route.name === "handout") lastCity = route.city;
  document.body.classList.toggle("presenting", route.name === "present");
  document.title = { cities: "Cities", lands: "Lands", "my-lands": "My lands", land: "Land", forecast: "Forecast", present: "Presentation", handout: "One-page summary", districts: "Districts" }[route.name] + " · Land Planner";
  drawSide(route);
  main.scrollTop = 0;
  window.scrollTo(0, 0);
  main.className = "main " + route.name;
  if (route.bad && route.bad.length) { notAParcel(route); return; }
  const view = { cities: citiesView, lands: landsView, "my-lands": myLandsView, land: landView, forecast: forecastView, present: presentView, handout: handoutView, districts: districtView }[route.name];
  try {
    await view.render(main, route, alive);
  } catch (e) {
    console.error(e);
    if (alive()) main.innerHTML = `<header class="page-head"><h1>Something went wrong</h1></header>` + problem("This page could not be shown. Reload the page; if it keeps happening, close Land Planner and start it again.", "");
  }
  if (alive()) main.focus({ preventScroll: true });
}

document.addEventListener("land-open", (e) => {
  openLand = e.detail;
  drawSide(parse());
});
saved.onChange(() => drawSide(parse()));
window.addEventListener("hashchange", show);
saved.load().catch(() => {}).finally(() => drawSide(parse()));
show();

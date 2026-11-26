// The frame of the app: the sidebar and which page is showing. Addresses look like
//   #/cities   #/lands/menifee   #/my-lands   #/land/menifee/372100001/terrain
import { cities, saved } from "./api.js";
import { esc, num, icon, problem } from "./util.js";
import * as citiesView from "./views/cities.js";
import * as landsView from "./views/lands.js";
import * as myLandsView from "./views/mylands.js";
import * as landView from "./views/land.js";
import * as forecastView from "./views/forecast.js";

const main = document.getElementById("main"), side = document.getElementById("side");
let visit = 0, leaving = [], lastCity = null, openLand = null;

function parse() {
  const parts = location.hash.replace(/^#\/?/, "").split("?")[0].split("/").filter(Boolean).map(decodeURIComponent);
  const [first, a, b, c] = parts;
  if (first === "lands") return { name: "lands", city: a || null };
  if (first === "my-lands") return { name: "my-lands" };
  if (first === "land" && a && b) return { name: "land", city: a, apn: b.replace(/\D/g, ""), page: c || "overview" };
  // #/forecast/menifee/360350024+360350017: one parcel, or several forecast as one site
  if (first === "forecast" && a) return { name: "forecast", city: a, apns: (b || "").split(/[+,\s]+/).map((x) => x.replace(/\D/g, "")).filter(Boolean) };
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
    </nav>`;
  if (openLand) {
    const base = `#/land/${esc(openLand.city)}/${esc(openLand.apn)}`;
    const forecastOn = route.name === "forecast" && route.apns.length === 1 && route.apns[0] === openLand.apn && route.city === openLand.city;
    html += `<div class="side-land"><p class="side-title">${route.name === "land" || forecastOn ? "This land" : "Last opened"}</p>
      <a class="side-parcel" href="${base}"><b>${esc(openLand.number || openLand.apn)}</b>${openLand.acres != null ? `<span>${num(openLand.acres, 2)} acres</span>` : ""}</a>
      <nav aria-label="This land's pages">${landView.PAGES.map(([id, label]) => {
        const on = route.name === "land" && route.apn === openLand.apn && route.page === id;
        return `<a href="${base}/${id}" class="nav sub${on ? " on" : ""}"${on ? ' aria-current="page"' : ""}>${icon(id)}<span>${label}</span></a>`;
      }).join("")}<a href="${landView.forecastLink(openLand.city, [openLand.apn])}" class="nav sub${forecastOn ? " on" : ""}"${forecastOn ? ' aria-current="page"' : ""}>${landView.FORECAST_ICON}<span>Forecast</span></a></nav></div>`;
  }
  html += `<p class="side-foot">Real public records only. Outlines are not a survey, and zoning changes go through the city.</p>`;
  side.innerHTML = html;
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
  if (route.name === "land") {
    lastCity = route.city;
    if (!openLand || openLand.apn !== route.apn || openLand.city !== route.city) openLand = { city: route.city, apn: route.apn };
  }
  if (route.name === "forecast") lastCity = route.city;
  document.title = { cities: "Cities", lands: "Lands", "my-lands": "My lands", land: "Land", forecast: "Forecast" }[route.name] + " · Land Planner";
  drawSide(route);
  main.scrollTop = 0;
  window.scrollTo(0, 0);
  main.className = "main " + route.name;
  const view = { cities: citiesView, lands: landsView, "my-lands": myLandsView, land: landView, forecast: forecastView }[route.name];
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

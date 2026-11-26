// My lands: the parcels saved with "Save to My lands". The list is kept by the server in data/my-lands.json,
// so it is still here after the app is closed and started again.
// Under the cards, "Compare my lands" puts the saved lands side by side (two or more; one shows its own row).
import { saved, compareLands } from "../api.js";
import { forecastLink, FORECAST_ICON } from "./land.js";
import { NONE, esc, has, num, money, dateOnly, icon, loading, problem, toast, shapeSvg, apnText } from "../util.js";

// The columns of the compare table. `from` is where a value is read: "land" = the row itself, "plan" = the plan
// shown (today's zoning or your own plan, or the best use). Money columns marked `best` get a "highest" tag on the
// highest figure; costs are shown but never tagged, since a higher cost is not the better one.
const COLUMNS = [
  { key: "apn", label: "Parcel", from: "land", text: true },
  { key: "acres", label: "Acres", from: "land", num: true },
  { key: "zoning", label: "Zoning", from: "land", text: true },
  { key: "mix", label: "Mix of uses", sortable: false },
  { key: "largest_use", label: "Largest use", from: "plan", text: true },
  { key: "homes", label: "Homes", from: "plan", num: true },
  { key: "floor_space_sq_ft", label: "Floor space (sq ft)", from: "plan", num: true },
  { key: "jobs", label: "Jobs", from: "plan", num: true },
  { key: "trips_per_day", label: "Trips a day", from: "plan", num: true },
  { key: "revenue", label: "Land sales", from: "plan", num: true, money: true, best: true },
  { key: "costs", label: "Costs", from: "plan", num: true, money: true },
  { key: "profit", label: "Profit", from: "plan", num: true, money: true, best: true },
  { key: "profit_per_acre", label: "Profit per acre", from: "plan", num: true, money: true, best: true },
];
const MODES = [["kept", "Today's zoning (or your own plan)"], ["best", "Best use"]];
const colourOf = (c) => (/^#[0-9a-f]{3,8}$/i.test(String(c)) ? c : "#9aa0a6");
const plain = (name) => String(name).replace(/_/g, " ");

export async function render(el, params, alive) {
  el.innerHTML = `
    <header class="page-head">
      <p class="kicker">Land Planner</p>
      <h1>My lands</h1>
      <p class="lead">The parcels you saved. They stay here when you close Land Planner and open it again.</p>
    </header>
    <div id="mine">${loading("Opening your saved lands…")}</div>
    <section class="cmp" id="cmp" aria-labelledby="cmpTitle" hidden></section>
    <p class="fine foot" id="keptIn" hidden></p>`;
  const box = el.querySelector("#mine"), keptIn = el.querySelector("#keptIn"), cmpBox = el.querySelector("#cmp");
  let asking = null;   // the land whose "Remove" was pressed once and is waiting for a yes
  const unticked = new Set();   // lands left out of "Forecast selected lands together" (every land starts ticked)
  let cmpKey = "", cmpRows = null, cmpToken = 0, cmpMode = "kept", cmpSort = null, cmpFocus = "";

  function drawKeptIn() {
    // where the list lives, said only when the server tells us
    const path = saved.keptIn();
    keptIn.hidden = !path;
    keptIn.innerHTML = path ? `These lands are saved on this computer, in the file <span class="path">${esc(path)}</span>. They are not uploaded anywhere. Deleting Land Planner's data folder removes them.` : "";
  }

  // ---------------------------------------------------------------- Compare my lands
  const planOf = (row) => (row.plans && row.plans[cmpMode]) || null;
  const ready = (row) => !row.problem && !!planOf(row);   // a row that has figures to compare

  function valueOf(row, col) {
    if (!ready(row)) return null;
    if (col.from !== "land" && planOf(row).nothing_to_build) return null;
    const v = col.from === "land" ? row[col.key] : planOf(row)[col.key];
    if (col.text) return has(v) ? String(v) : null;
    return has(v) && !isNaN(Number(v)) ? Number(v) : null;
  }
  function sortedRows() {
    if (!cmpSort) return cmpRows;
    const col = COLUMNS.find((c) => c.key === cmpSort.key), sign = cmpSort.dir === "asc" ? 1 : -1;
    const all = cmpRows.map((row, i) => ({ row, i, v: valueOf(row, col) }));
    const known = all.filter((x) => x.v !== null).sort((a, b) => {
      const d = col.text ? a.v.localeCompare(b.v, "en", { numeric: true }) : a.v - b.v;
      return (d * sign) || (a.i - b.i);
    });
    return known.concat(all.filter((x) => x.v === null)).map((x) => x.row);   // rows with no figure stay at the bottom
  }
  function bestValues() {
    // the highest figure of each tagged money column, when there are at least two figures to compare
    const out = {};
    COLUMNS.filter((c) => c.best).forEach((col) => {
      const v = cmpRows.map((row) => valueOf(row, col)).filter((x) => x !== null);
      if (v.length >= 2) out[col.key] = Math.max(...v);
    });
    return out;
  }
  function parcelCell(row) {
    const known = saved.list().find((x) => x.city === row.city && x.apn === row.apn);
    const number = row.apn_formatted || apnText(known && known.parcel) || row.apn;
    let html = `<a class="apn" href="#/land/${esc(row.city)}/${esc(row.apn)}/plan" title="Open this land's Plan page">${esc(number)}</a>`;
    if (row.has_own_plan) {
      html += ` <span class="cmp-tag gold" title="${cmpMode === "kept" ? "You changed this land's plan; the figures shown are your plan." : "You changed this land's plan; the best use does not use your changes."}">your plan</span>`;
    }
    html += `<small>${esc(row.city_name || row.city)}${row.address ? " · " + esc(row.address) : ""}</small>`;
    if ((row.did_not_answer || []).length) {
      html += `<small class="cmp-warn">Did not answer just now: ${esc(row.did_not_answer.map(plain).join(", "))}. Figures may be incomplete.</small>`;
    }
    return html;
  }
  function mixCell(h) {
    const uses = (h.uses || []).filter((u) => Number(u.share_pct) > 0 || Number(u.acres) > 0);
    if (!uses.length) return NONE;
    const words = uses.map((u) => `${u.label || u.short} ${num(u.share_pct, 1)}%`).join(", ");
    let html = `<div class="cmp-bar" role="img" aria-label="${esc("Mix of uses: " + words)}">${uses.map((u) =>
      `<span style="flex:${Math.max(Number(u.acres) || 0, 0.05)} 1 0;background:${colourOf(u.colour)}" title="${esc((u.label || u.short) + ": " + num(u.share_pct, 1) + "% of the land, " + num(u.acres, 1) + " acres")}"></span>`).join("")}</div>
      <ul class="cmp-mix">${uses.map((u) => `<li><i style="background:${colourOf(u.colour)}"></i>${esc(u.short || u.label)} ${num(u.share_pct, 1)}%</li>`).join("")}</ul>`;
    if ((h.needs_zoning_change || []).length) {
      html += `<p class="cmp-change"><span class="cmp-tag warn">needs a zoning change</span> <span>for ${esc(h.needs_zoning_change.join(", ").toLowerCase())}</span></p>`;
    }
    return html;
  }
  function cellFor(col, row, h, best) {
    if (col.key === "acres") return has(row.acres) ? num(row.acres, 2) : NONE;
    if (col.key === "zoning") {
      return has(row.zoning) ? `<b>${esc(row.zoning)}</b>${row.zoning_name && row.zoning_name !== row.zoning ? `<small>${esc(row.zoning_name)}</small>` : ""}` : NONE;
    }
    if (col.key === "mix") return mixCell(h);
    const v = valueOf(row, col);
    if (v === null) return NONE;
    if (col.text) return esc(v);
    let html = col.money ? money(v) : num(v);
    if (col.best && best[col.key] === v) html += ` <span class="cmp-tag best">highest</span>`;
    if (col.key === "profit" && has(h.land)) {
      html += `<small>after land cost of ${money(h.land)}${h.land_is_stand_in ? ", the county's assessed value standing in for the real price" : ""}</small>`;
    }
    return html;
  }
  function compareRow(row, best) {
    const first = `<th scope="row" class="cmp-first">${parcelCell(row)}</th>`;
    const span = COLUMNS.length - 1;
    if (row.problem) return `<tr class="cmp-problem">${first}<td colspan="${span}"><span class="cmp-tag warn">no figures</span> ${esc(row.problem)}</td></tr>`;
    const h = planOf(row);
    if (!h) return `<tr class="cmp-problem">${first}<td colspan="${span}">The plan for this land is ${NONE}.</td></tr>`;
    const cell = (col) => `<td${col.num ? ' class="num"' : ""}>${cellFor(col, row, h, best)}</td>`;
    if (h.nothing_to_build) {
      return `<tr>${first}${COLUMNS.slice(1, 3).map(cell).join("")}<td colspan="${COLUMNS.length - 3}" class="cmp-nothing">${cmpMode === "kept" ? "Nothing can be built under today's zoning." : "Nothing can be built on this land."}</td></tr>`;
    }
    return `<tr>${first}${COLUMNS.slice(1).map(cell).join("")}</tr>`;
  }
  function drawCompare() {
    if (!cmpRows) return;
    const scroller = cmpBox.querySelector(".cmp-scroll"), left = scroller ? scroller.scrollLeft : 0;
    const best = bestValues();
    const heads = COLUMNS.map((col) => {
      const on = !!cmpSort && cmpSort.key === col.key;
      const inner = col.sortable === false ? `<span class="cmp-plainhead">${col.label}</span>`
        : `<button type="button" class="sort${on ? " on" : ""}" data-sort="${col.key}" title="Sort by ${esc(col.label.toLowerCase())}">${col.label}<i>${on ? (cmpSort.dir === "asc" ? "▲" : "▼") : ""}</i></button>`;
      const aria = col.sortable === false ? "" : ` aria-sort="${on ? (cmpSort.dir === "asc" ? "ascending" : "descending") : "none"}"`;
      return `<th scope="col"${col.num ? ' class="num"' : ""}${aria}>${inner}</th>`;
    }).join("");
    cmpBox.innerHTML = `
      <div class="cmp-head">
        <div><p class="kicker">Side by side</p><h2 id="cmpTitle">Compare my lands</h2></div>
        <div class="cmp-switch" role="group" aria-label="Which plan to compare">${MODES.map(([id, label]) =>
          `<button type="button" data-mode="${id}" aria-pressed="${cmpMode === id}">${label}</button>`).join("")}</div>
      </div>
      <p>These are first suggestions worked out from public records and starting figures. Use them to compare your lands with each other. They are not appraisals. A land whose plan you changed is marked “your plan”.</p>
      <p class="fine cmp-mode">${cmpMode === "kept"
        ? "Showing each land as today's zoning allows it, or as you changed its plan."
        : "Showing the best use suggested for each land. It may need a zoning change, and it does not use plans you changed."}</p>
      ${cmpRows.length === 1 ? '<p class="cmp-one"><b>Saving another land lets you compare the two side by side.</b></p>' : ""}
      <div class="scroll cmp-scroll" tabindex="0" role="region" aria-label="Your saved lands side by side. This table scrolls sideways when the screen is narrow.">
        <table class="data cmp-table"><thead><tr>${heads}</tr></thead>
        <tbody>${sortedRows().map((row) => compareRow(row, best)).join("")}</tbody></table>
      </div>
      <p class="fine">Click a column heading to sort by it. Numbers sort from the highest down first; click again to reverse. “Highest” marks the best figure in the land sales, profit and profit per acre columns. Profit is land sales less costs and the cost of the land itself.</p>`;
    const now = cmpBox.querySelector(".cmp-scroll");
    if (now) now.scrollLeft = left;
    if (cmpFocus) {
      const target = cmpBox.querySelector(cmpFocus);
      if (target) target.focus({ preventScroll: true });
      cmpFocus = "";
    }
  }
  function syncCompare() {
    // asked again only when the set of saved lands changes (a sort or the switch never asks)
    const lands = saved.list();
    if (!lands.length) {
      cmpKey = ""; cmpRows = null; cmpToken++;
      cmpBox.hidden = true; cmpBox.innerHTML = "";
      return;
    }
    const key = lands.map((x) => x.city + "/" + x.apn).sort().join("|");
    if (key === cmpKey) return;
    cmpKey = key; cmpRows = null;
    const mine = ++cmpToken;
    cmpBox.hidden = false;
    const title = '<p class="kicker">Side by side</p><h2 id="cmpTitle">Compare my lands</h2>';
    cmpBox.innerHTML = title + loading("Reading the public records for your saved lands. The first time takes several seconds for each land.");
    compareLands().then((d) => {
      if (!alive() || mine !== cmpToken) return;
      cmpRows = d.lands || [];
      drawCompare();
    }).catch((e) => {
      if (!alive() || mine !== cmpToken) return;
      cmpBox.innerHTML = title + problem(e.message);
      cmpBox.querySelector("[data-retry]").addEventListener("click", () => { cmpKey = ""; syncCompare(); });
    });
  }
  cmpBox.addEventListener("click", (e) => {
    const sort = e.target.closest("[data-sort]"), mode = e.target.closest("[data-mode]");
    if (sort) {
      const key = sort.dataset.sort, col = COLUMNS.find((c) => c.key === key);
      cmpSort = cmpSort && cmpSort.key === key ? { key, dir: cmpSort.dir === "asc" ? "desc" : "asc" } : { key, dir: col.text ? "asc" : "desc" };
      cmpFocus = `[data-sort="${key}"]`;
      drawCompare();
    } else if (mode && mode.dataset.mode !== cmpMode) {
      cmpMode = mode.dataset.mode;
      cmpFocus = `[data-mode="${cmpMode}"]`;
      drawCompare();
    }
  });

  // ---------------------------------------------------------------- the cards
  function draw() {
    drawKeptIn();
    syncCompare();
    const lands = saved.list();
    if (!lands.length) {
      box.innerHTML = `<div class="card empty">${icon("saved", "huge")}
        <h2>Nothing saved yet</h2>
        <p>Go to Lands, find a parcel worth keeping an eye on, and press “Save to My lands”.</p>
        <a class="btn primary" href="#/lands">Go to Lands ${icon("arrow")}</a></div>`;
      return;
    }
    box.innerHTML = `<div class="mine-tools"><p class="count-line"><b>${lands.length}</b> saved ${lands.length === 1 ? "land" : "lands"}</p>
        <div class="mine-forecast" id="mineForecast"></div></div>
      <div class="mine-grid">${lands.map((x) => {
        const p = x.parcel || {}, key = x.city + "/" + x.apn, link = `#/land/${esc(x.city)}/${esc(x.apn)}`;
        return `<article class="card mine">
          <a class="mine-shape" href="${link}" aria-label="Open ${esc(apnText(p) || x.apn)}">${shapeSvg(p.rings, 104)}</a>
          <div class="mine-body">
            <p class="kicker">${esc(x.city_name)}</p>
            <h2><a href="${link}">${p.acres != null ? num(p.acres, 2) + " acres" : "Parcel"}</a></h2>
            <p class="muted">Parcel ${esc(apnText(p) || x.apn)}${p.address ? " · " + esc(p.address) : ""}</p>
            <p><b>${esc(p.zoning || "No zoning listed")}</b>${p.zoning_name && p.zoning_name !== p.zoning ? " · " + esc(p.zoning_name) : ""}</p>
            <p class="fine">Saved ${esc(dateOnly(x.saved_at))} · ${p.looks_vacant ? "no buildings on the assessor's records" : "buildings on the assessor's records"}</p>
            <div class="mine-actions">
              <label class="check mine-pick"><input type="checkbox" data-pick="${esc(key)}"${unticked.has(key) ? "" : " checked"}> In the forecast</label>
              <a class="btn small primary" href="${link}">Open ${icon("arrow")}</a>
              ${asking === key
                ? `<span class="confirm">Take it off My lands? <button type="button" class="btn small danger" data-yes="${esc(key)}">Yes, remove</button> <button type="button" class="btn small" data-no>Keep</button></span>`
                : `<button type="button" class="btn small" data-remove="${esc(key)}">Remove</button>`}
            </div>
          </div></article>`;
      }).join("")}</div>
      <p class="fine foot">Each card shows the parcel's facts as they were on the day it was saved; opening a land reads them again. Outlines are the assessor's drawings, not a survey.</p>`;
    drawForecastPick();
  }

  // "Forecast selected lands together": the ticked lands, as one site. A forecast covers one city.
  function drawForecastPick() {
    const slot = box.querySelector("#mineForecast");
    if (!slot) return;
    const ticked = saved.list().filter((x) => !unticked.has(x.city + "/" + x.apn));
    const cities = [...new Set(ticked.map((x) => x.city))];
    let words, ok = false;
    if (!ticked.length) words = "Tick at least one land to forecast it.";
    else if (cities.length > 1) words = `The ticked lands are in ${cities.length} cities. A forecast covers one city: untick the lands of the others.`;
    else {
      ok = true;
      words = ticked.length === 1 ? "One land ticked: it is forecast on its own." : `${ticked.length} lands ticked, forecast as one site.`;
    }
    const href = ok ? forecastLink(cities[0], ticked.map((x) => x.apn)) : "";
    slot.innerHTML = `${ok ? `<a class="btn primary" href="${esc(href)}">${FORECAST_ICON} Forecast selected lands together</a>`
      : `<button type="button" class="btn primary" disabled>${FORECAST_ICON} Forecast selected lands together</button>`}
      <span class="fine">${esc(words)}</span>`;
  }
  box.addEventListener("change", (e) => {
    const pick = e.target.closest("[data-pick]");
    if (!pick) return;
    if (pick.checked) unticked.delete(pick.dataset.pick); else unticked.add(pick.dataset.pick);
    drawForecastPick();
  });

  box.addEventListener("click", async (e) => {
    const remove = e.target.closest("[data-remove]"), yes = e.target.closest("[data-yes]");
    if (remove) { asking = remove.dataset.remove; draw(); }
    else if (e.target.closest("[data-no]")) { asking = null; draw(); }
    else if (yes) {
      const [cityId, apn] = yes.dataset.yes.split("/");
      yes.disabled = true;
      try { await saved.remove(cityId, apn); toast("Taken off My lands."); } catch (err) { toast(err.message); }
      asking = null;
      if (alive()) draw();
    }
  });
  alive.onLeave(saved.onChange(() => { if (alive()) draw(); }));

  try {
    await saved.load();
    if (alive()) draw();
  } catch (e) {
    if (!alive()) return;
    box.innerHTML = problem(e.message);
    box.querySelector("[data-retry]").addEventListener("click", () => render(el, params, alive));
  }
}

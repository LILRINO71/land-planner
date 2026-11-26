// My lands: the parcels saved with "Save to My lands". The list is kept by the server in data/my-lands.json,
// so it is still here after the app is closed and started again.
import { saved } from "../api.js";
import { esc, num, dateOnly, icon, loading, problem, toast, shapeSvg, apnText } from "../util.js";

export async function render(el, params, alive) {
  el.innerHTML = `
    <header class="page-head">
      <p class="kicker">Land Planner</p>
      <h1>My lands</h1>
      <p class="lead">The parcels you saved. They stay here when you close Land Planner and open it again.</p>
    </header>
    <div id="mine">${loading("Opening your saved lands…")}</div>`;
  const box = el.querySelector("#mine");
  let asking = null;   // the land whose "Remove" was pressed once and is waiting for a yes

  function draw() {
    const lands = saved.list();
    if (!lands.length) {
      box.innerHTML = `<div class="card empty">${icon("saved", "huge")}
        <h2>Nothing saved yet</h2>
        <p>Go to Lands, find a parcel worth keeping an eye on, and press “Save to My lands”.</p>
        <a class="btn primary" href="#/lands">Go to Lands ${icon("arrow")}</a></div>`;
      return;
    }
    box.innerHTML = `<p class="count-line"><b>${lands.length}</b> saved ${lands.length === 1 ? "land" : "lands"}</p>
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
              <a class="btn small primary" href="${link}">Open ${icon("arrow")}</a>
              ${asking === key
                ? `<span class="confirm">Take it off My lands? <button type="button" class="btn small danger" data-yes="${esc(key)}">Yes, remove</button> <button type="button" class="btn small" data-no>Keep</button></span>`
                : `<button type="button" class="btn small" data-remove="${esc(key)}">Remove</button>`}
            </div>
          </div></article>`;
      }).join("")}</div>
      <p class="fine foot">Each card shows the parcel's facts as they were on the day it was saved; opening a land reads them again. Outlines are the assessor's drawings, not a survey.</p>`;
  }

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

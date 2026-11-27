// Papers vs. city record: each of the project's parcels as the package states it (acres, zoning) beside the city's
// live record from the app's own city routes, every difference flagged, with a way into the app's land pages and the
// forecast of all the parcels together.
import { esc, isNum, nFix, fold, page, leadHtml, calmBox, NK, entities, useLabel, guarded, loadingHtml, smallTable } from "./common.js";
import { land, city as cityInfo } from "../../api.js";

const digits = (s) => String(s || "").replace(/\D/g, "");
const zoneKey = (z) => String(z || "").toUpperCase().replace(/[\s_]+/g, "").replace(/–|—/g, "-");
const ACRE_TOLERANCE = 0.05;

export async function render(el, ctx) {
  el.innerHTML = loadingHtml("Reading the package's parcels…");
  await guarded(el, ctx, async () => {
    let layer = null;
    try {
      const p = encodeURIComponent(ctx.project.id), aud = ctx.viewAs ? { audience: ctx.viewAs } : null;
      const layers = ((await ctx.api.get(`/projects/${p}/gis`, aud)).layers || []).filter((l) => l.kind === "parcels" && !l.removed);
      if (layers[0]) layer = await ctx.api.get(`/projects/${p}/gis/${encodeURIComponent(layers[0].id)}`, aud);
    } catch (e) { layer = null; /* the package's own figures still show */ }
    let cityName = "";
    try { if (ctx.project.city) cityName = (await cityInfo(ctx.project.city)).name; } catch (e) { cityName = ""; }
    if (ctx.alive && !ctx.alive()) return;
    draw(el, ctx, layer, cityName);
  });
}

// the package's word on each APN: acres from the parcels, zoning from the parcels layer or the parcel's note
function paperOf(ctx, apn, layer) {
  const d = digits(apn);
  const row = (entities(ctx).parcels || []).find((x) => digits(x.apn || x.id) === d) || null;
  const f = layer ? (layer.features || []).find((x) => digits((x.properties || {}).apn) === d) : null;
  const pr = (f && f.properties) || {};
  let zoning = pr.documents_zoning || (row && row.zoning) || "";
  let zFrom = zoning ? "the package's parcels layer" : "";
  if (!zoning && row && row.note) { const m = /Zoning:\s*([^(;|\n]+?)\s*(?:\(|;|\||\n|$)/i.exec(row.note); if (m) { zoning = m[1].trim(); zFrom = "the parcel's note"; } }
  return { apn: (row && row.apn) || apn, digits: d, label: (row && row.label) || pr.label || "", acres: row && isNum(row.acres) ? row.acres : pr.documents_gross_acres, net: row && row.net_acres,
    zoning, zFrom, use: row && row.use ? useLabel(ctx, row.use) : "", snapshot: pr.city_zoning || isNum(pr.city_acres) ? { acres: pr.city_acres, zoning: pr.city_zoning, gp: pr.city_general_plan } : null };
}

function draw(el, ctx, layer, cityName) {
  const P = page(el, ctx);
  const cityId = ctx.project.city;
  const apns = (ctx.project.apns && ctx.project.apns.length ? ctx.project.apns : (entities(ctx).parcels || []).map((x) => x.apn || x.id)).filter((a) => digits(a));
  const papers = apns.map((a) => paperOf(ctx, a, layer));
  const where = cityName || cityId || "the city";

  if (!cityId) {
    P.set({ lead: leadHtml({ sentence: "This project is not tied to a city in Land Planner, so there is no live city record to compare its papers with.", aside: "An administrator can set the project's city; the parcels below are as the package states them." }),
      parts: [["papers", "Papers", papers.length ? smallTable([{ label: "APN" }, { label: "Name" }, { label: "Acres (gross)", num: true }, { label: "Zoning" }],
        papers.map((x) => [esc(x.apn), esc(x.label), esc(isNum(x.acres) ? nFix(x.acres, 2) : NK), esc(x.zoning || NK)]), "Parcels in the package") : calmBox("No parcels in the package", "")]] });
    return;
  }
  if (!papers.length) { P.set({ lead: leadHtml({ sentence: "The package lists no parcels (APNs) to check against the city's record." }), parts: [["x", "", calmBox("Nothing to compare", "")]] }); return; }

  const forecast = `#/forecast/${encodeURIComponent(cityId)}/${papers.map((x) => x.digits).join("+")}`;
  const leadBox = () => {
    const done = papers.filter((x) => x.live || x.liveError), differ = papers.filter((x) => x.diff && (x.diff.acres || x.diff.zoning));
    const waiting = papers.length - done.length;
    return leadHtml({
      kicker: "The answer",
      sentence: waiting ? `Reading ${esc(where)}'s record for ${papers.length} parcels… ${done.length} read so far.` : differ.length
        ? `<b>${differ.length} of ${papers.length} parcels</b> differ between the package and ${esc(where)}'s record${differ.some((x) => x.diff.zoning) ? "; zoning differs on " + differ.filter((x) => x.diff.zoning).length : ""}.`
        : `All ${papers.length} parcels match ${esc(where)}'s record on acres and zoning.`,
      big: waiting ? "" : String(differ.length), bigLabel: waiting ? "" : differ.length === 1 ? "parcel differs" : "parcels differ",
      aside: `The package's figures beside the city's live parcel record. Acres within ${ACRE_TOLERANCE} of an acre count as the same.`,
      chips: `<a class="btn small primary" href="${esc(forecast)}">Forecast all ${papers.length} parcels together</a>`,
    });
  };
  const rowHtml = (x) => {
    const live = x.live, d = x.diff || {};
    const cityAcres = live ? live.acres : null, cityZone = live ? live.zoning : null;
    const cell = (v, flag) => `<span class="${flag ? "d" : ""}">${esc(v)}</span>`;
    const state = x.liveError ? `<span class="tl-state unknown">City record not read</span>` : !live ? `<span class="tl-state unknown">Reading…</span>` : d.acres || d.zoning ? '<span class="tl-state not_met">Differs</span>' : '<span class="tl-state met">Matches</span>';
    return `<li class="${d.acres || d.zoning ? "differs" : ""}" data-apn="${esc(x.digits)}">
      <div class="tl-rec-head"><b>APN ${esc(x.apn)}</b>${state}</div>
      ${x.label ? `<p class="tl-note">${esc(x.label)}${x.use ? " · " + esc(x.use) : ""}</p>` : ""}
      <div class="tl-rec-grid" role="table" aria-label="APN ${esc(x.apn)}: package beside city record">
        <span class="h" role="columnheader"></span><span class="h" role="columnheader">Package</span><span class="h" role="columnheader">${esc(where)} record</span>
        <span role="rowheader">Gross acres</span><span role="cell">${esc(isNum(x.acres) ? nFix(x.acres, 2) : NK)}</span><span role="cell">${live ? cell(isNum(cityAcres) ? nFix(cityAcres, 2) : NK, d.acres) : "-"}${d.acres && isNum(d.acresBy) ? ` <small>(${d.acresBy > 0 ? "+" : ""}${esc(nFix(d.acresBy, 2))})</small>` : ""}</span>
        <span role="rowheader">Zoning</span><span role="cell">${esc(x.zoning || NK)}</span><span role="cell">${live ? cell((cityZone || NK) + (live.zoning_name ? " (" + live.zoning_name + ")" : ""), d.zoning) : "-"}</span>
        ${live && live.general_plan ? `<span role="rowheader">General plan</span><span role="cell">-</span><span role="cell">${esc(live.general_plan)}</span>` : ""}
      </div>
      ${x.liveError ? `<p class="fine">${esc(x.liveError)}${x.snapshot ? ` The package's parcels layer kept the city's record as read earlier: ${isNum(x.snapshot.acres) ? nFix(x.snapshot.acres, 2) + " acres, " : ""}zoning ${x.snapshot.zoning || NK}.` : ""}</p>` : ""}
      ${!x.zoning ? `<p class="fine">The package does not state this parcel's zoning.</p>` : ""}
      <div class="tl-rec-actions"><a class="btn small" href="#/land/${encodeURIComponent(cityId)}/${x.digits}/overview">Open this parcel in Land Planner</a></div></li>`;
  };
  const listHtml = () => `<ul class="tl-rec">${papers.map(rowHtml).join("")}</ul>`;
  P.set({ lead: `<div data-lead>${leadBox()}</div>`, parts: [["records", "Records", `<p class="tl-note">The city's record is read live from ${esc(where)}'s public parcel service through Land Planner; a recent copy is kept for a while so it opens quickly next time.</p><div data-list>${listHtml()}</div>
    ${fold("cr-how", "How the package's figures are read", `<p>Acres are the gross acres of the package's parcels. Zoning is the zoning the package's documents give, from its parcels layer or, failing that, the parcel's note. A parcel whose zoning the package does not state is not flagged for zoning.</p>`, P.openFolds)}`]] });

  // the city's record, a few at a time, each row filled in as it arrives
  const paint = (x) => {
    const l = el.querySelector("[data-lead]"), li = el.querySelector(`[data-apn="${x.digits}"]`);
    if (l) l.innerHTML = leadBox();
    if (li) li.outerHTML = rowHtml(x);
  };
  let next = 0;
  const worker = async () => {
    while (next < papers.length) {
      const x = papers[next++];
      try {
        const q = await land(cityId, x.digits).quick;
        x.live = q.parcel || {};
        const a = Number(x.live.acres), pa = Number(x.acres);
        x.diff = { acres: isNum(x.acres) && isNum(x.live.acres) && Math.abs(a - pa) >= ACRE_TOLERANCE, acresBy: isNum(x.acres) && isNum(x.live.acres) ? a - pa : null,
          zoning: !!x.zoning && !!x.live.zoning && zoneKey(x.zoning) !== zoneKey(x.live.zoning) };
        if (q.parcel_stale) x.live.stale = true;
      } catch (e) { x.liveError = e.status === 404 ? `${where} has no parcel with this number.` : `${where}'s record could not be read just now (${e.message})`; }
      if (ctx.alive && !ctx.alive()) return;
      paint(x);
    }
  };
  Promise.all([worker(), worker(), worker()]).catch((e) => console.error(e));
}

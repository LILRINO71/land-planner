// Land value and pricing: residual land value by use (per gross acre, net acre, SF; low/base/high), by parcel or
// block, the four pricing tiers of each as a ladder, and what-if sliders (nothing is saved). An economic
// calculation, not an appraisal.
import {
  esc, isNum, nFix, fold, compute, page, leadHtml, missingHtml, hiddenHtml, isOutside, disclaimerHtml, calmBox, smallTable, seg, wireSegKeys,
  num, usd, usdM, pct, acres, int, plural, noun, NK, SF_PER_ACRE, rowOf, useLabel, entities, inputSpec, inputValue, debounce, guarded, loadingHtml, problemHtml,
} from "./common.js";

const SCN = [["low", "Low"], ["base", "Base"], ["high", "High"]];
const TIERS = [["upside_stretch", "Stretch"], ["target_market", "Target"], ["minimum_recommended", "Minimum recommended"], ["economic_cost_floor", "Cost floor"]];
const PER = [["gross_ac", "Per gross acre"], ["net_ac", "Per net acre"], ["sf", "Per SF"]];
const BASIS_WORDS = { stated: "Stated price", residual: "Residual value", target_market: "Target price" };

// the priced items of a response: parcels, or blocks when the package prices blocks
export function pricedOf(r) {
  const src = (r && (r.by_block || r.by_parcel)) || null;
  const list = src ? src.blocks || src.parcels || src.items || [] : [];
  return { src, list, kind: r && r.by_block ? "block" : "parcel" };
}
// the bases a response offers (stated price, residual value), when there is a choice
export function basesOf(r, resp) {
  if (r && (r.comparison || r.by_basis)) return ["stated", "residual"];
  const b = (r && (r.bases || r.basis_options)) || (resp && resp.bases) || null;
  if (Array.isArray(b) && b.length > 1) return b.map((x) => (typeof x === "string" ? x : x.id));
  if (r && r.stated && r.residual) return ["stated", "residual"];
  return null;
}

// the value of one scenario row in the chosen measure
function per(row, measure, sfBasis) {
  if (!row) return null;
  if (measure === "gross_ac") return row.rlv_per_gross_ac_usd;
  if (measure === "net_ac") return row.rlv_per_net_ac_usd;
  if (sfBasis === "gross") return isNum(row.rlv_per_gross_ac_usd) ? row.rlv_per_gross_ac_usd / SF_PER_ACRE : null;
  return row.rlv_per_net_sf_usd;
}
const perWords = (v, measure) => (!isNum(v) ? NK : measure === "sf" ? (v < 0 ? "-$" : "$") + nFix(Math.abs(v), 2) + "/SF" : usd(v) + "/acre");
const measureWords = (measure, sfBasis) => (measure === "gross_ac" ? "per gross acre" : measure === "net_ac" ? "per net acre" : sfBasis === "gross" ? "per gross SF of land" : "per net SF of land");

// the figures one use is worked out from
function useInputs(ctx, resp, useId) {
  const costIds = new Set((entities(ctx).cost_items || []).filter((c) => c.use === useId).map((c) => c.id));
  return (resp.inputs_used || []).filter((x) => {
    const f = x.field || "";
    if (f.startsWith(`land_uses/${useId}/`)) return true;
    if (f.startsWith("cost_items/")) return costIds.has(f.split("/")[1]);
    return x.assumption_id === "FIN-NET-TO-GROSS-PCT";
  });
}
function itemInputs(ctx, resp, item) {
  const id = item.id, costIds = new Set((entities(ctx).cost_items || []).filter((c) => c.parcel === id || c.block === id).map((c) => c.id));
  const uses = Object.keys(item.uses || {});
  return (resp.inputs_used || []).filter((x) => {
    const f = x.field || "";
    if (f.startsWith(`parcels/${id}/`) || f.startsWith(`blocks/${id}/`)) return true;
    if (f.startsWith("cost_items/")) return costIds.has(f.split("/")[1]);
    return uses.some((u) => f.startsWith(`land_uses/${u}/`)) || /^FIN-/.test(x.assumption_id || "");
  });
}
function scenarioNote(byUse) {
  const s = (byUse && byUse.assumptions && byUse.assumptions.scenarios) || {};
  const w = (a) => {
    if (!a || !Object.keys(a).length) return "the package's figures as they are";
    const out = [];
    if (isNum(a.revenue_pct)) out.push(`revenue ${a.revenue_pct > 0 ? "+" : ""}${a.revenue_pct}%`);
    if (isNum(a.cost_pct)) out.push(`cost ${a.cost_pct > 0 ? "+" : ""}${a.cost_pct}%`);
    if (isNum(a.cap_rate_delta_pct)) out.push(`cap rate ${a.cap_rate_delta_pct > 0 ? "+" : ""}${a.cap_rate_delta_pct} points`);
    if (isNum(a.required_return_delta_pct)) out.push(`required return ${a.required_return_delta_pct > 0 ? "+" : ""}${a.required_return_delta_pct} points`);
    return out.join(", ");
  };
  return `Low case: ${w(s.low)}. Base case: ${w(s.base)}. High case: ${w(s.high)}.`;
}

// a low-to-high range bar with the base marked; scale = {lo, hi} shared by the rows
function rangeBar(lo, base, hi, scale) {
  if (![lo, base, hi].some(isNum)) return `<span class="muted">${NK}</span>`;
  const span = scale.hi - scale.lo || 1, at = (v) => Math.max(0, Math.min(100, ((v - scale.lo) / span) * 100));
  const a = isNum(lo) ? at(lo) : at(base), b = isNum(hi) ? at(hi) : at(base);
  return `<div class="tl-range" aria-hidden="true">${scale.lo < 0 && scale.hi > 0 ? `<i class="tl-range-zero" style="left:${at(0).toFixed(1)}%"></i>` : ""}
    <i class="tl-range-bar" style="left:${Math.min(a, b).toFixed(1)}%;width:${Math.max(1.5, Math.abs(b - a)).toFixed(1)}%"></i>
    ${isNum(base) ? `<i class="tl-range-dot" style="left:${at(base).toFixed(1)}%"></i>` : ""}</div>`;
}

export async function render(el, ctx) {
  el.innerHTML = loadingHtml("Working out land values…");
  const state = { measure: "net_ac", sfBasis: "net", scenario: "base", basis: "", item: "" };
  const run = async () => {
    const resp = await compute(ctx, "landvalue", { options: state.basis ? { basis: state.basis } : null });
    if (ctx.alive && !ctx.alive()) return;
    const box = document.createElement("div");
    el.replaceChildren(box);
    draw(box, ctx, resp, state, () => { el.innerHTML = loadingHtml("Working out land values…"); return guarded(el, ctx, run); });
  };
  await guarded(el, ctx, run);
}

function draw(el, ctx, resp, state, rerun) {
  const P = page(el, ctx), reg = P.reg;
  P.resp = resp;
  const r = resp.result || {}, byUse = r.by_use, uses = (byUse && byUse.uses) || [];
  const { src, list: items, kind } = pricedOf(r);
  const tiers = r.pricing_tiers || [];
  const outside = isOutside(resp);
  const bases = basesOf(r, resp);
  const kinds = kind === "block" ? "blocks" : "parcels";
  const blocks = Array.isArray(r.blocks) ? r.blocks : [], comp = r.comparison || null;
  const stated = r.basis_used === "stated";
  const blockRow = (id) => (entities(ctx).blocks || []).find((b) => b.id === id) || {};
  const blockSpec = (b, what, v) => ({ label: `${b.name || b.id}, ${what}`, value: v,
    how: [`Stated price = price per net SF (${b.price_from || "stated"}) x net SF (${nFix(b.net_sf || 0, 0)} SF).`, "Residual estimate = the residual land value of its use from the land use library, for its net acres."],
    inputs: (resp.inputs_used || []).filter((x) => (x.field || "").startsWith(`blocks/${b.id}/`) || (blockRow(b.id).cites || []).includes(x.assumption_id)) });
  const blocksTotal = blocks.reduce((t, b) => t + (isNum(b.gross_price_usd) ? b.gross_price_usd : 0), 0);
  const blockInputs = (resp.inputs_used || []).filter((x) => (x.field || "").startsWith("blocks/"));
  const hasRlv = uses.some((u) => isNum(((u.scenarios || {}).base || {}).rlv_per_net_ac_usd));

  // ---- the answer
  const ranked = (byUse && byUse.ranking) || [];
  const top = uses.find((u) => u.id === ranked[0]) || uses[0];
  const topBase = top && top.scenarios && top.scenarios.base;
  const total = src && src.totals_usd ? src.totals_usd.base : null;
  let lead;
  if (blocks.length && stated) {
    const both = comp && comp.compared > 0 && isNum(comp.difference_pct);
    const allSpec = { label: "All blocks at their stated prices", value: usd(blocksTotal), how: ["Each block: stated price per net SF x its net SF; a range is priced at its middle."], inputs: blockInputs };
    lead = leadHtml({
      sentence: `${blocks.length === 1 ? "The one block" : `The ${blocks.length} blocks`} the package prices ${blocks.length === 1 ? "adds" : "add"} up to ${num(reg, usdM(blocksTotal), allSpec)} at their stated prices.${both ? ` Priced both ways, the stated prices are ${num(reg, pct(Math.abs(comp.difference_pct), 0), { label: "Stated against residual, in total", value: usd(comp.difference_usd), how: [comp.note || "", `Stated ${usd(comp.stated_total_usd)} against residual ${usd(comp.residual_total_usd)} for the ${plural(comp.compared, "piece")} priced both ways.`] })} ${comp.difference_pct < 0 ? "below" : "above"} the residual value the land use library supports.` : ""}`,
      big: usdM(blocksTotal), bigLabel: "All blocks, stated prices", bigSrc: reg.add(allSpec),
      aside: "An economic calculation, not an appraisal. A stated price is the package's own; the residual is what a buyer could pay and still earn the required return.",
    });
  } else if (uses.length && !hasRlv) {
    lead = leadHtml({ sentence: `What ${uses.length === 1 ? "the one use is" : `each of the ${uses.length} uses is`} worth once built, and what it costs to build, for one net acre.`,
      aside: "Residual land value (what the land itself is worth to a buyer) is kept to the internal view. An economic calculation, not an appraisal." });
  } else if (!uses.length && !items.length) {
    lead = leadHtml({ sentence: "Land value cannot be worked out yet: the package does not hold the finance inputs it needs.", aside: "The list below says what is missing. As soon as the package has them, this screen fills in by itself." });
  } else {
    const totalSrc = isNum(total) ? reg.add({ label: `All ${kinds}, base case residual land value`, value: usd(total), how: (src.formula || []).concat([src.assumptions && src.assumptions.total_basis ? `Each ${kind} is counted at ${src.assumptions.total_basis}.` : ""]).filter(Boolean), inputs: (resp.inputs_used || []).filter((x) => /^(parcels|blocks)\//.test(x.field || "")) }) : "";
    const topSrc = topBase ? reg.add({ label: `${top.label}, base residual per net acre`, value: perWords(topBase.rlv_per_net_ac_usd, "net_ac"), how: byUse.formula, inputs: useInputs(ctx, resp, top.id) }) : "";
    const sentence = top
      ? `In the base case <b>${esc(top.label)}</b> supports the most for the land: ${num(reg, usd(topBase && topBase.rlv_per_net_ac_usd), { label: `${top.label}, base residual per net acre`, value: perWords(topBase && topBase.rlv_per_net_ac_usd, "net_ac"), how: byUse.formula, inputs: useInputs(ctx, resp, top.id) })} per net acre.`
      : `The ${kinds} are priced below.`;
    lead = leadHtml({
      sentence, big: isNum(total) ? usdM(total) : topBase ? perWords(topBase.rlv_per_net_ac_usd, "net_ac") : "",
      bigLabel: isNum(total) ? `All ${kinds}, base case` : "Per net acre, base case", bigSrc: isNum(total) ? totalSrc : topSrc,
      aside: "An economic calculation, not an appraisal: what a buyer could pay for the land and still earn the required return, under the stated assumptions.",
    });
  }
  const before = (outside ? hiddenHtml(resp, hasRlv ? [] : ["residual_land_value"]) : "") + missingHtml(resp, { labelOf: (id) => useLabel(ctx, id), open: P.openFolds }) +
    (bases ? `<div class="tl-controls">${seg("basis", bases.map((b) => [b, BASIS_WORDS[b] || b]), state.basis || r.basis_used || bases[0], "Price basis")}</div>` : "");

  // ---- part 1: by use
  const usePart = () => {
    if (!uses.length) return calmBox("No uses are priced yet", "Residual land value by use needs the finance library: for each use its density, revenue, cap rate and required return.");
    if (!hasRlv) {
      const t = uses.map((u) => { const s = (u.scenarios || {})[state.scenario] || {}; return [esc(u.label), esc(usd(s.value_on_completion_usd)), esc(usd(s.development_cost_usd)), esc(isNum(s.units) ? nFix(s.units, 0) : "-"), esc(isNum(s.building_sf) ? nFix(s.building_sf, 0) : "-")]; });
      return `<div class="tl-controls">${seg("scenario", SCN, state.scenario, "Case")}</div>
        <p class="tl-note">For one net acre of each use in the ${esc(state.scenario)} case. ${esc(scenarioNote(byUse))}</p>
        ${smallTable([{ label: "Use" }, { label: "Worth once built", num: true }, { label: "Cost to build", num: true }, { label: "Homes or keys", num: true }, { label: "Building SF", num: true }], t, "Value and cost by use")}`;
    }
    const vals = uses.flatMap((u) => SCN.map(([s]) => per(u.scenarios && u.scenarios[s], state.measure, state.sfBasis))).filter(isNum);
    const scale = { lo: Math.min(0, ...vals), hi: Math.max(0, ...vals) };
    const ordered = ranked.length ? ranked.map((id) => uses.find((u) => u.id === id)).filter(Boolean).concat(uses.filter((u) => !ranked.includes(u.id))) : uses;
    const rows = ordered.map((u) => {
      const sc = u.scenarios || {}, v = (s) => per(sc[s], state.measure, state.sfBasis);
      const cell = (s) => num(reg, perWords(v(s), state.measure), { label: `${u.label}, ${s} case, ${measureWords(state.measure, state.sfBasis)}`, value: perWords(v(s), state.measure), how: (byUse.formula || []).concat([scenarioNote(byUse)]), inputs: useInputs(ctx, resp, u.id) }, s === state.scenario ? "on" : "");
      const b = sc.base || {};
      return `<li class="tl-use">
        <div class="tl-use-head"><b>${esc(u.label)}</b>${b.feasible_now === false ? '<span class="dz-chip warn">Not feasible in the base case</span>' : ""}${b.cost_is_partial ? `<span class="dz-chip gold">${plural(b.cost_unknown_items, "cost item")} not known</span>` : ""}</div>
        ${rangeBar(v("low"), v("base"), v("high"), scale)}
        <div class="tl-range-nums"><span>Low ${cell("low")}</span><span class="b">Base ${cell("base")}</span><span>High ${cell("high")}</span></div>
        ${b.why ? `<p class="fine">${esc(b.why)}</p>` : ""}</li>`;
    }).join("");
    const pickedRows = ordered.map((u) => {
      const s = (u.scenarios || {})[state.scenario] || {};
      return [esc(u.label), esc(usdM(s.value_on_completion_usd)), esc(usdM(s.development_cost_usd)), esc(usdM(s.required_profit_usd)), esc(usd(s.rlv_usd)), esc(isNum(s.yield_on_cost_pct) ? pct(s.yield_on_cost_pct, 2) : "-")];
    });
    return `<div class="tl-controls">${seg("measure", PER, state.measure, "Show values")}${state.measure === "sf" ? seg("sfbasis", [["net", "Net SF"], ["gross", "Gross SF"]], state.sfBasis, "Land area") : ""}${seg("scenario", SCN, state.scenario, "Highlight case")}</div>
      <p class="tl-note">Residual land value of one net acre for each use, ${esc(measureWords(state.measure, state.sfBasis))}. The bar runs from the low case to the high case; the dot is the base case.</p>
      <ul class="tl-uses">${rows}</ul>
      ${fold("lv-working", `Show the working for the ${state.scenario} case`, smallTable([{ label: "Use" }, { label: "Value on completion", num: true }, { label: "Development cost", num: true }, { label: "Required profit", num: true }, { label: "Residual, one net acre", num: true }, { label: "Yield on cost", num: true }], pickedRows, "Working by use") + `<p class="fine">${esc(scenarioNote(byUse))}</p>`, P.openFolds)}`;
  };

  // ---- part 2: by parcel or block
  const itemPart = () => {
    if (!items.length) return outside ? "" : calmBox(`No ${kinds} are priced yet`, `A ${kind} is priced once its use is in the finance library.`);
    const rows = items.map((it) => {
      const useId = it.totalled_use || it.assigned_use || it.best_use, u = (it.uses || {})[useId] || {};
      const b = u.base || {}, lo = u.low || {}, hi = u.high || {};
      const spec = (what, v) => ({ label: `${it.name || it.id}, ${what}`, value: v, how: (src.formula || []).concat([`Use priced: ${useLabel(ctx, useId)}${it.assigned_use ? " (the use the plan assigns)" : " (the best use by base residual)"}.`]), inputs: itemInputs(ctx, resp, it) });
      return [`<b>${esc(it.name || it.id)}</b><small>${esc(it.id)}</small>`, esc(acres(it.gross_ac)), esc(acres(it.net_ac)), esc(useId ? useLabel(ctx, useId) : NK),
        num(reg, usd(b.rlv_usd), spec("base residual", usd(b.rlv_usd))),
        num(reg, isNum(b.rlv_per_gross_ac_usd) ? usd(b.rlv_per_gross_ac_usd) : NK, spec("base residual per gross acre", usd(b.rlv_per_gross_ac_usd))),
        `${esc(usdM(lo.rlv_usd))} to ${esc(usdM(hi.rlv_usd))}`];
    });
    const t = src.totals_usd || {};
    return `<p class="tl-note">Each ${kind} at its assigned use (or its best use when none is assigned). Low to high is the range across the three cases.</p>
      ${smallTable([{ label: cap(kind) }, { label: "Gross", num: true }, { label: "Net", num: true }, { label: "Use priced" }, { label: "Base residual", num: true }, { label: "Per gross acre", num: true }, { label: "Low to high", num: true }], rows, `Residual land value by ${kind}`)}
      <p class="tl-total">All ${kinds}: low ${esc(usdM(t.low))}, base <b>${esc(usdM(t.base))}</b>, high ${esc(usdM(t.high))}.${src.parcels_not_priced ? ` ${src.parcels_not_priced} not priced.` : ""}</p>`;
  };

  // ---- blocks: the package's own sale pieces, stated against residual
  const blockPart = () => {
    if (!blocks.length) return "";
    const INTENT = { sell: "Sell", hold: "Hold", jv: "Joint venture", ground_lease: "Ground lease", hold_develop: "Hold and develop" };
    const rows = blocks.map((b) => {
      const row = blockRow(b.id);
      const perSf = isNum(row.price_per_sf_low) && isNum(row.price_per_sf_high) ? `$${nFix(row.price_per_sf_low, 2)} to $${nFix(row.price_per_sf_high, 2)}` : isNum(b.price_per_sf) ? `$${nFix(b.price_per_sf, 2)}` : NK;
      const d = b.difference_pct;
      return { cls: b.core ? "flag" : "", cells: [
        `<b>${esc(b.name || b.id)}</b><small>${esc(b.id)}${(b.apns || []).length ? " · in " + esc(b.apns.join(", ")) : ""}${b.intent ? " · " + esc(INTENT[b.intent] || b.intent) : ""}${b.core ? " · core, kept" : ""}</small>`,
        esc(acres(b.net_acres)), esc(perSf),
        num(reg, usd(b.gross_price_usd), blockSpec(b, "stated price", usd(b.gross_price_usd))) + (isNum(b.low_usd) && isNum(b.high_usd) ? `<small>${esc(usdM(b.low_usd))} to ${esc(usdM(b.high_usd))}</small>` : ""),
        isNum(b.residual_estimate_usd) ? num(reg, usd(b.residual_estimate_usd), blockSpec(b, "residual estimate", usd(b.residual_estimate_usd))) : `<span class="muted">${NK}</span>`,
        isNum(d) ? `<span class="${d >= 0 ? "dz-diff-up" : "dz-diff-down"}">${d >= 0 ? "+" : "-"}${esc(nFix(Math.abs(d), 0))}%</span>` : "-"] };
    });
    const parcelsBoth = comp ? (comp.units || []).filter((u) => u.kind === "parcel") : [];
    return `<p class="tl-note">The pieces the package sells or keeps; a block can cut across parcels. The difference is the stated price against the residual estimate.</p>
      ${smallTable([{ label: "Block" }, { label: "Net", num: true }, { label: "Stated price per net SF", num: true }, { label: "Stated price", num: true }, { label: "Residual estimate", num: true }, { label: "Difference", num: true }], rows, "Blocks")}
      ${comp && !(comp.compared > 0) ? `<p class="tl-note">The residual basis has no figures yet for these blocks: a residual estimate needs the finance library for its use (density, revenue, cost line items and cap rate).</p>` : ""}
      ${comp && comp.compared > 0 ? `<p class="tl-total">Priced both ways (${esc(plural(int(comp.compared), "piece"))}): stated <b>${esc(usdM(comp.stated_total_usd))}</b> against residual <b>${esc(usdM(comp.residual_total_usd))}</b>. ${esc(comp.note || "")}</p>` : ""}
      ${parcelsBoth.length ? fold("lv-parcel-both", "Show parcels with a stated target price", smallTable([{ label: "Parcel" }, { label: "Stated", num: true }, { label: "Residual", num: true }, { label: "Difference", num: true }],
        parcelsBoth.map((u) => [esc(parcelLabelOf(ctx, u.id)), esc(usdM(u.stated_usd)), esc(usdM(u.residual_usd)), esc(isNum(u.difference_pct) ? nFix(u.difference_pct, 0) + "%" : "-")]), "Parcels priced both ways"), P.openFolds) : ""}`;
  };

  // ---- part 3: pricing tiers, one item at a time
  const tierPart = () => {
    const anyPrice = tiers.some((t) => Object.values(t.tiers || {}).some((x) => isNum(x && x.price_usd)));
    if (!tiers.length || !anyPrice) return outside ? "" : calmBox("No pricing tiers yet", "Pricing tiers need each " + kind + "'s cost basis and residual value.");
    const idOf = (t) => t.parcel_id || t.block_id || t.parcel || t.block || t.id;
    const cur = tiers.find((t) => idOf(t) === state.item) || tiers[0];
    state.item = idOf(cur);
    const label = (t) => { const it = items.find((x) => x.id === idOf(t)); return (it && (it.name || it.label)) || (rowOf(ctx, "parcels", idOf(t)) || {}).label || idOf(t); };
    const prices = TIERS.map(([k]) => (cur.tiers[k] || {}).price_usd).filter(isNum);
    const max = Math.max(1, ...prices);
    const sfOf = (t) => (state.sfBasis === "gross" ? (isNum(t.per_gross_ac_usd) ? t.per_gross_ac_usd / SF_PER_ACRE : null) : t.per_net_sf_usd);
    const rungs = TIERS.map(([k, short]) => {
      const t = cur.tiers[k] || {}, v = t.price_usd;
      const spec = { label: `${label(cur)}: ${t.label || short}`, value: usd(v), how: (cur.formula || []).concat([t.source ? `This tier: ${t.source}.` : ""]).filter(Boolean),
        inputs: (resp.inputs_used || []).filter((x) => /^FIN-(SPONSOR|STRATEGIC|TARGET|UPSIDE|NET)/.test(x.assumption_id || "") || (x.field || "").startsWith("cost_items/")).filter((x) => !x.field || ((rowOf(ctx, "cost_items", x.field.split("/")[1]) || {}).parcel === idOf(cur))) };
      return `<li class="tl-rung t-${k}">
        <div class="tl-rung-name"><b>${esc(short)}</b><small>${esc(t.source || "")}</small></div>
        <div class="tl-rung-bar"><i style="width:${isNum(v) && v > 0 ? Math.max(2, (v / max) * 100).toFixed(1) : 0}%"></i></div>
        <div class="tl-rung-num">${num(reg, usd(v), spec)}<small>${esc(isNum(sfOf(t)) ? "$" + nFix(sfOf(t), 2) + (state.sfBasis === "gross" ? "/gross SF" : "/net SF") : NK)} · ${esc(isNum(t.per_net_ac_usd) ? usd(t.per_net_ac_usd) + "/net acre" : NK + " per acre")}</small></div></li>`;
    }).join("");
    const notes = (cur.notes || []).concat(cur.cost_floor_is_lower_bound ? [`${cur.cost_items_unknown} cost items are not known, so the cost floor is a lower bound.`] : []);
    const all = smallTable([{ label: cap(kind) }].concat(TIERS.slice().reverse().map(([, w]) => ({ label: w, num: true }))),
      tiers.map((t) => [esc(label(t))].concat(TIERS.slice().reverse().map(([k]) => esc(usdM((t.tiers[k] || {}).price_usd))))), "Pricing tiers");
    return `<div class="tl-controls"><label class="field"><span>${esc(cap(kind))}</span><select data-item>${tiers.map((t) => `<option value="${esc(idOf(t))}"${idOf(t) === state.item ? " selected" : ""}>${esc(label(t))}</option>`).join("")}</select></label>
        ${seg("sfbasis", [["net", "Net SF"], ["gross", "Gross SF"]], state.sfBasis, "Price per SF of")}</div>
      <ol class="tl-ladder" aria-label="Pricing tiers for ${esc(label(cur))}, highest first">${rungs}</ol>
      <p class="tl-note">${isNum(cur.headroom_target_over_minimum_usd) ? `The target is ${esc(usdM(cur.headroom_target_over_minimum_usd))} above the minimum recommended price.` : ""} ${cur.tiers_in_order === false ? "<b>The tiers are not in order:</b> check the inputs." : ""}</p>
      ${notes.length ? `<ul class="tl-mini">${notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
      ${fold("lv-tiers-all", `Show every ${kind}'s tiers`, all, P.openFolds)}
      <p class="fine">The target is an economic target, not a value opinion. Stretch is the high-case residual.</p>`;
  };

  // ---- part 4: what if
  const whatPart = () => {
    if (!uses.length || !hasRlv) return "";
    const v = (id, d) => inputValue(resp, id, d);
    const sliders = [
      ["FIN-NET-TO-GROSS-PCT", "Net acres as a share of gross", v("FIN-NET-TO-GROSS-PCT", 100), 50, 100, 1, "%"],
      ...(outside ? [] : [["FIN-TARGET-PCT-OF-RLV", "Target price as a share of residual value", v("FIN-TARGET-PCT-OF-RLV", 100), 50, 130, 1, "%"],
        ["FIN-SPONSOR-HURDLE-PCT", "Sponsor hurdle on cost (minimum price)", v("FIN-SPONSOR-HURDLE-PCT", 20), 0, 50, 1, "%"],
        ["FIN-UPSIDE-PCT", "Upside over the target price", v("FIN-UPSIDE-PCT", 15), 0, 50, 1, "%"]]),
      ...(blocks.length && !outside ? [["~blocks", "Stated block prices per SF", 0, -30, 30, 1, "% change"]] : []),
      ["~revenue", "Rents, prices and room rates", 0, -25, 25, 1, "% change"],
      ["~cap", "Cap rates", 0, -1.5, 1.5, 0.25, " points change"],
    ];
    return `<p class="tl-note"><b>These changes are not saved.</b> Move a slider to see what the land is worth with that figure; the other parts keep the package's own figures.</p>
      <div class="tl-sliders">${sliders.map(([id, label, val, min, max, step, unit]) => `<label class="tl-slider"><span>${esc(label)}</span>
        <input type="range" min="${min}" max="${max}" step="${step}" value="${isNum(val) ? val : min}" data-wi="${esc(id)}" data-start="${isNum(val) ? val : min}" aria-valuetext="${esc(nFix(isNum(val) ? val : min, step < 1 ? 2 : 0) + unit)}">
        <output>${esc(nFix(isNum(val) ? val : min, step < 1 ? 2 : 0) + unit)}</output></label>`).join("")}</div>
      <p><button type="button" class="btn small" data-wi-reset>Back to the package's figures</button></p>
      <div class="tl-wi-out" aria-live="polite">${calmBox("Move a slider to start", "The result appears here.")}</div>`;
  };

  P.set({ lead, before, parts: [
    ["uses", "By use", usePart()],
    ["blocks", "Blocks", blockPart()],
    ["items", kind === "block" ? "By block" : "By parcel", itemPart()],
    ["tiers", "Pricing tiers", tierPart()],
    ["whatif", "What if", whatPart()],
  ], after: disclaimerHtml(resp) });
  wireSegKeys(el);

  // the controls redraw only the part they belong to
  const redraw = (part, html) => { const node = el.querySelector(`[data-part="${part}"]`); if (node) { const keep = node.querySelector(".dz-part-title"); P.swap(node, (keep ? keep.outerHTML : "") + html); } };
  el.addEventListener("click", (e) => {
    const b = e.target.closest("[data-seg]");
    if (!b || !el.contains(b)) return;
    const name = b.dataset.seg, val = b.dataset.val;
    if (name === "basis") { state.basis = val; rerun(); return; }
    if (name === "measure") state.measure = val;
    if (name === "sfbasis") state.sfBasis = val;
    if (name === "scenario") state.scenario = val;
    const part = b.closest("[data-part]").dataset.part;
    redraw(part, part === "uses" ? usePart() : tierPart());
    const again = el.querySelector(`[data-part="${part}"] [data-seg="${name}"][data-val="${CSS.escape(val)}"]`);
    if (again) again.focus();
  });
  el.addEventListener("change", (e) => {
    if (e.target.matches("[data-item]")) { state.item = e.target.value; redraw("tiers", tierPart()); const s = el.querySelector("[data-item]"); if (s) s.focus(); }
  });

  // ---- what if: POST, nothing saved
  const out = () => el.querySelector(".tl-wi-out");
  const whatIf = debounce(async () => {
    const body = { assumptions: {}, records: {} };
    let changed = false;
    const said = [];
    el.querySelectorAll("[data-wi]").forEach((s) => {
      const id = s.dataset.wi, x = Number(s.value);
      if (x === Number(s.dataset.start)) return;
      changed = true;
      said.push(`${s.previousElementSibling.textContent}: ${s.nextElementSibling.textContent}`);
      if (id === "~blocks") {
        body.records.blocks = (entities(ctx).blocks || []).map((b) => {
          const rec = { id: b.id };
          ["price_per_sf", "price_per_sf_low", "price_per_sf_high"].forEach((f) => { if (isNum(b[f])) rec[f] = Math.round(b[f] * (1 + x / 100) * 100) / 100; });
          return rec;
        }).filter((rec) => Object.keys(rec).length > 1);
      } else if (id === "~revenue" || id === "~cap") {
        const rows = (entities(ctx).land_uses || []).map((u) => {
          const rec = { id: u.id };
          if (id === "~revenue") ["price_per_unit", "price_per_sf", "rent_per_unit_mo", "rent_per_sf_yr", "adr"].forEach((f) => { if (isNum(u[f])) rec[f] = Math.round(u[f] * (1 + x / 100) * 100) / 100; });
          else ["cap_rate_pct", "exit_cap_pct"].forEach((f) => { if (isNum(u[f])) rec[f] = Math.max(0.25, Math.round((u[f] + x) * 100) / 100); });
          return rec;
        }).filter((rec) => Object.keys(rec).length > 1);
        const have = body.records.land_uses || [];
        rows.forEach((rec) => { const old = have.find((h) => h.id === rec.id); if (old) Object.assign(old, rec); else have.push(rec); });
        body.records.land_uses = have;
      } else body.assumptions[id] = x;
    });
    if (!changed) { if (out()) out().innerHTML = calmBox("These are the package's own figures", "Move a slider to see a what-if."); return; }
    if (out()) out().innerHTML = loadingHtml("Working it out…");
    try {
      const w = await compute(ctx, "landvalue", { body });
      if (!out()) return;
      P.swap(out(), whatIfResult(w, resp, ctx, reg, kinds, said));
    } catch (err) { if (out()) out().innerHTML = problemHtml(err).replace("data-retry", "data-wi-retry"); }
  }, 400);
  el.addEventListener("input", (e) => {
    const s = e.target.closest("[data-wi]");
    if (!s) return;
    const step = Number(s.step), unit = s.dataset.wi === "~revenue" || s.dataset.wi === "~blocks" ? "% change" : s.dataset.wi === "~cap" ? " points change" : "%";
    const words = nFix(Number(s.value), step < 1 ? 2 : 0) + unit;
    s.nextElementSibling.textContent = words; s.setAttribute("aria-valuetext", words);
    whatIf();
  });
  el.addEventListener("click", (e) => {
    if (e.target.closest("[data-wi-retry]")) { whatIf(); return; }
    if (!e.target.closest("[data-wi-reset]")) return;
    el.querySelectorAll("[data-wi]").forEach((s) => { s.value = s.dataset.start; s.dispatchEvent(new Event("input", { bubbles: true })); });
  });
}

const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const parcelLabelOf = (ctx, id) => { const p = (entities(ctx).parcels || []).find((x) => x.id === id); return p ? p.label || p.apn || id : id; };

// the what-if answer beside the package's own
function whatIfResult(w, base, ctx, reg, kinds, said) {
  const r = w.result || {}, r0 = base.result || {};
  const uses = (r.by_use && r.by_use.uses) || [], uses0 = (r0.by_use && r0.by_use.uses) || [];
  const t = (pricedOf(r).src || {}).totals_usd || {}, t0 = (pricedOf(r0).src || {}).totals_usd || {};
  const changed = said || [];
  const bt = (list) => (Array.isArray(list) ? list : []).reduce((t, b) => t + (isNum(b.gross_price_usd) ? b.gross_price_usd : 0), 0);
  const b1 = bt(r.blocks), b0 = bt(r0.blocks);
  const delta = (a, b) => (isNum(a) && isNum(b) ? `<span class="${a - b >= 0 ? "dz-diff-up" : "dz-diff-down"}">${a - b >= 0 ? "+" : "-"}${esc(usdM(Math.abs(a - b)))}</span>` : "");
  const rows = uses.map((u) => {
    const u0 = uses0.find((x) => x.id === u.id) || {}, a = ((u.scenarios || {}).base || {}).rlv_per_net_ac_usd, b = ((u0.scenarios || {}).base || {}).rlv_per_net_ac_usd;
    return [esc(u.label), esc(usd(b)), num(reg, usd(a), { label: `${u.label}, what-if base residual per net acre`, value: usd(a), how: (r.by_use.formula || []).concat(["What-if: the changed figures are not saved."]), inputs: (w.inputs_used || []).filter((x) => x.what_if || (x.field || "").startsWith(`land_uses/${u.id}/`)) }), delta(a, b)];
  });
  const tiers = r.pricing_tiers || [], tiers0 = r0.pricing_tiers || [];
  const tgt = (list) => list.reduce((s, x) => s + (isNum(((x.tiers || {}).target_market || {}).price_usd) ? x.tiers.target_market.price_usd : 0), 0);
  return `<div class="tl-wi-head"><span class="dz-chip warn">What-if, not saved</span>${changed.length ? `<span class="muted">You changed: ${esc(changed.join("; "))}</span>` : ""}</div>
    <div class="tl-compare">
      ${b1 || b0 ? `<div><small>All blocks, stated prices</small><b>${esc(usdM(b1))}</b><span>was ${esc(usdM(b0))} ${delta(b1, b0)}</span></div>` : ""}
      ${isNum(t.base) ? `<div><small>All ${esc(kinds)}, base case</small><b>${esc(usdM(t.base))}</b><span>was ${esc(usdM(t0.base))} ${delta(t.base, t0.base)}</span></div>` : ""}
      ${tiers.length ? `<div><small>Target prices added up</small><b>${esc(usdM(tgt(tiers)))}</b><span>was ${esc(usdM(tgt(tiers0)))} ${delta(tgt(tiers), tgt(tiers0))}</span></div>` : ""}
    </div>
    ${rows.length ? smallTable([{ label: "Use" }, { label: "Package, per net acre", num: true }, { label: "What-if", num: true }, { label: "Change", num: true }], rows, "What-if residual by use") : ""}`;
}

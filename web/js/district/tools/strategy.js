// Hold, sell, partner or lease: for each parcel (or block) the four options' 10- and 15-year NPV, their scores and
// the recommendation, with critical-asset conflicts first; the sale proceeds from gross to net; the capital-target
// plan (max cash, balanced, max retention) against the targets as a timeline; and retained land over time.
import {
  esc, isNum, nFix, fold, compute, page, leadHtml, missingHtml, hiddenHtml, isOutside, disclaimerHtml, calmBox, smallTable, seg, wireSegKeys,
  num, usd, usdM, pct, acres, int, noun, NK, pieceLabel as parcelLabel, useLabel, guarded, loadingHtml, inputSpec,
} from "./common.js";
import { basesOf } from "./landvalue.js";

const OPT = [["fee_simple_sale", "Sell"], ["hold_develop", "Hold and develop"], ["joint_venture", "Joint venture"], ["ground_lease", "Ground lease"]];
const OPT_WORDS = Object.fromEntries(OPT);
const PLANS = [["max_cash", "Most cash"], ["balanced", "Balanced"], ["max_retention", "Keep the most"]];
const PRICE = [["target_market", "Target price"], ["minimum_recommended", "Minimum recommended"], ["upside_stretch", "Stretch"], ["economic_cost_floor", "Cost floor"]];
const BASIS_WORDS = { stated: "Stated price", residual: "Residual value" };

export async function render(el, ctx) {
  el.innerHTML = loadingHtml("Comparing the options…");
  const state = { item: "", plan: "balanced", price: "target_market", wf: "__all", basis: "" };
  const run = async () => {
    const extra = state.basis ? { basis: state.basis } : {};
    const [st, pr] = await Promise.all([
      compute(ctx, "strategy", { options: extra }),
      compute(ctx, "proceeds", { options: { price_basis: state.price, ...extra } }).catch((e) => ({ failed: e })),
    ]);
    if (ctx.alive && !ctx.alive()) return;
    const box = document.createElement("div");
    el.replaceChildren(box);
    draw(box, ctx, st, pr, state, () => { el.innerHTML = loadingHtml("Working it out again…"); return guarded(el, ctx, run); });
  };
  await guarded(el, ctx, run);
}

function draw(el, ctx, st, pr, state, rerun) {
  const P = page(el, ctx), reg = P.reg;
  P.resp = st;
  const r = st.result || {}, dec = r.decisions || {}, items = dec.parcels || dec.blocks || dec.items || [];
  const kind = r.decided_for === "blocks" || dec.blocks ? "block" : "parcel", kinds = kind + "s";
  const outside = isOutside(st);
  const pres = (pr && !pr.failed && pr.result) || {}, wf = pres.waterfall, plan = pres.capital_plan;
  const conflicts = ((r.conflicts || dec.critical_asset_conflicts || {}).conflicts) || [];
  const bases = basesOf(r, st) || basesOf(pres, pr);
  const curBasis = state.basis || r.basis_used || pres.basis_used || (bases ? bases[0] : "");
  const name = (it) => it.name || it.label || parcelLabel(ctx, it.id);
  const stratInputs = (st.inputs_used || []).filter((x) => /^STR-|^FIN-CRITICAL/.test(x.assumption_id || ""));

  // ---- the answer
  const available = items.filter((it) => it.recommended_strategy || it.guarded_recommendation);
  const counts = {};
  available.forEach((it) => { const k = it.guarded_recommendation || it.recommended_strategy; counts[k] = (counts[k] || 0) + 1; });
  const NOUN = { fee_simple_sale: ["sale", "sales"], hold_develop: ["hold and develop", "hold and develop"], joint_venture: ["joint venture", "joint ventures"], ground_lease: ["ground lease", "ground leases"] };
  const said = OPT.filter(([k]) => counts[k]).map(([k]) => `${counts[k]} ${NOUN[k][counts[k] === 1 ? 0 : 1]}`);
  const countWords = said.length > 1 ? said.slice(0, -1).join(", ") + " and " + said[said.length - 1] : said.join("");
  const bal = plan && plan.strategies && plan.strategies[state.plan];
  const sp = pres.stated_plan;
  const spMet = sp ? (sp.against_targets || []).filter((t) => t.met).length : 0, spAll = sp ? (sp.against_targets || []).length : 0;
  const planWords = sp ? ` The package's own plan sells ${esc(acres(sp.net_acres_sold))} and meets ${spMet === spAll ? "every cash target" : `${spMet} of ${spAll} cash targets`}${sp.net_is_upper_bound ? " (net at most: a stub cost is not known)" : ""}.`
    : bal ? ` The ${esc((PLANS.find((p) => p[0] === state.plan) || [])[1].toLowerCase())} cash plan ${bal.all_targets_met ? "meets every cash target" : "falls short of a cash target"}.` : "";
  const bigV = sp ? sp.net_usd : bal ? bal.total_net_proceeds_usd : null;
  const bigSpec = sp ? { label: "Net cash, the package's own plan", value: usd(sp.net_usd), how: ["Each block marked for sale: stated price less the itemised deductions and its stub cost."].concat(sp.net_is_upper_bound ? ["A stub cost is not known, so the net is at most this."] : []), inputs: (pr.inputs_used || []).filter((x) => /^FIN-/.test(x.assumption_id || "") || (x.field || "").startsWith("blocks/")) }
    : bal ? { label: "Net cash from the plan's sales", value: usd(bal.total_net_proceeds_usd), how: (plan.formula || []).concat([bal.rule || ""]), inputs: (pr.inputs_used || []).filter((x) => /^FIN-/.test(x.assumption_id || "") || (x.field || "").startsWith("capital_targets/")) } : null;
  let lead;
  if (outside && !items.length) {
    lead = leadHtml({ sentence: "Hold, sell, joint venture and ground lease decisions are kept to the internal view.", aside: "The city view shows the program, infrastructure and fiscal figures on the other screens." });
  } else if (!available.length) {
    lead = leadHtml({ sentence: `The four options cannot be compared yet: no ${kind} has everything the comparison needs.`, aside: "The list below says what is missing. Nothing is guessed in its place." });
  } else {
    lead = leadHtml({
      sentence: `Across ${available.length} ${available.length === 1 ? kind : kinds} the engine recommends ${esc(countWords)}.${conflicts.length ? ` <b>${conflicts.length} critical-asset ${conflicts.length === 1 ? "conflict needs" : "conflicts need"} a decision.</b>` : ""}${planWords}`,
      big: isNum(bigV) ? usdM(bigV) : "", bigLabel: sp ? "Net cash, the package's own plan" : bal ? `Net cash, ${(PLANS.find((p) => p[0] === state.plan) || [])[1].toLowerCase()} plan` : "",
      bigSrc: bigSpec ? reg.add(bigSpec) : "",
      aside: "A recommendation from the stated figures and weights, not advice. A critical strategic asset is never recommended for sale.",
    });
  }
  const before = (outside ? hiddenHtml(st) : "") + (bases ? `<div class="tl-controls">${seg("basis", bases.map((b) => [b, BASIS_WORDS[b] || b]), curBasis, "Price basis")}</div>` : "") +
    missingHtml({ missing: [...new Set([...(st.missing || []), ...((pr && pr.missing) || [])])] }, { labelOf: (id) => useLabel(ctx, id), open: P.openFolds });

  // ---- part 1: the decision for each item
  const decisionPart = () => {
    if (!items.length) return outside ? "" : calmBox(`No ${kinds} to compare yet`, "");
    const cur = items.find((it) => it.id === state.item) || items.find((it) => it.critical_strategic_asset) || items[0];
    state.item = cur.id;
    const flags = conflicts.length ? `<div class="tl-flag" role="note"><span><b>Critical-asset conflicts.</b> ${conflicts.map((c) => esc(`${parcelLabel(ctx, c.parcel_id || c.id)}: ${c.why || c.kind || ""}`)).join(" ")}</span></div>` : "";
    const rows = items.map((it) => {
      const rec = it.guarded_recommendation || it.recommended_strategy, s = rec && it.comparison && it.comparison.strategies[rec];
      const npv15 = s && s.npv_by_horizon_usd ? s.npv_by_horizon_usd["15"] : null;
      return { cls: (it.conflicts || []).length ? "flag" : "", cells: [
        `<button type="button" class="link" data-item="${esc(it.id)}">${esc(name(it))}</button>${it.critical_strategic_asset ? ' <span class="dz-chip warn">Critical</span>' : ""}`,
        esc(isNum(it.strategic_score) ? nFix(it.strategic_score, 0) : NK),
        rec ? `<b>${esc(OPT_WORDS[rec] || rec)}</b>${it.recommended_strategy && it.guarded_recommendation && it.recommended_strategy !== it.guarded_recommendation ? `<small>Economics alone: ${esc(OPT_WORDS[it.recommended_strategy])}</small>` : ""}` : `<span class="muted">${esc(it.why || "Not enough to compare")}</span>`,
        isNum(npv15) ? num(reg, usdM(npv15), { label: `${name(it)}, ${OPT_WORDS[rec]}, NPV over 15 years`, value: usd(npv15), how: (it.comparison.formula || []).concat([s.basis || ""]), inputs: stratInputs.concat((st.inputs_used || []).filter((x) => (x.field || "").includes(`/${it.id}/`))) }) : "-",
      ] };
    });
    const strat = (cur.comparison && cur.comparison.strategies) || {};
    const recK = cur.guarded_recommendation || cur.recommended_strategy;
    const cards = OPT.map(([k, w]) => {
      const s = strat[k] || {};
      if (!s.available) return `<article class="tl-card"><span class="tl-card-k">Option</span><h3>${esc(w)}</h3><p>${esc(s.why || "Not available: its inputs are not in the package.")}</p></article>`;
      const n = s.npv_by_horizon_usd || {};
      const how = (cur.comparison.formula || []).concat([s.basis || ""]);
      const ins = stratInputs.concat((st.inputs_used || []).filter((x) => (x.field || "").includes(`/${cur.id}/`)));
      return `<article class="tl-card${k === recK ? " best" : ""}"><span class="tl-card-k">${k === recK ? "Recommended" : "Option"}</span><h3>${esc(w)}</h3>
        <dl class="tl-kv">
          <dt>NPV, 10 years</dt><dd>${num(reg, usdM(n["10"]), { label: `${name(cur)}, ${w}, NPV over 10 years`, value: usd(n["10"]), how, inputs: ins })}</dd>
          <dt>NPV, 15 years</dt><dd>${num(reg, usdM(n["15"]), { label: `${name(cur)}, ${w}, NPV over 15 years`, value: usd(n["15"]), how, inputs: ins })}</dd>
          <dt>Cash in the first year</dt><dd>${esc(usdM(s.upfront_cash_usd))}</dd>
          <dt>Owner's capital in</dt><dd>${esc(usdM(Math.abs(s.capital_required_usd || 0)))}</dd>
          <dt>Income, per year</dt><dd>${esc(usdM(s.recurring_income_usd_yr))}</dd>
          <dt>First cash</dt><dd>${esc(isNum(s.first_cash_month) ? "month " + int(s.first_cash_month) : NK)}</dd>
          <dt>Score (economics)</dt><dd>${esc(nFix(s.economic_score || 0, 0))} of 100</dd>
          <dt>Score with strategy</dt><dd>${esc(nFix(s.combined_score || 0, 0))} of 100</dd>
        </dl><p>${esc(s.basis || "")}</p></article>`;
    }).join("");
    const crit = (cur.comparison && cur.comparison.criteria) || [];
    const critTable = crit.length ? smallTable([{ label: "What is scored (weight)" }].concat(OPT.map(([, w]) => ({ label: w, num: true }))),
      crit.map((c) => [esc(`${c.label} (${nFix(c.weight, 0)})`)].concat(OPT.map(([k]) => esc(strat[k] && strat[k].available ? nFix((strat[k].criteria_scores || {})[c.id] ?? 0, 0) : "-")))), "Scores by criterion") : "";
    return `${flags}
      ${smallTable([{ label: cap(kind) }, { label: "Strategic score", num: true }, { label: "Recommended" }, { label: "Its NPV, 15 years", num: true }], rows, "Recommendation by " + kind)}
      <div class="tl-controls"><label class="field"><span>Compare the four options for</span><select data-pick>${items.map((it) => `<option value="${esc(it.id)}"${it.id === state.item ? " selected" : ""}>${esc(name(it))}</option>`).join("")}</select></label></div>
      ${cur.critical_strategic_asset ? `<p class="tl-flag"><span><b>${esc(name(cur))} is a critical strategic asset</b> (strategic score ${esc(nFix(cur.strategic_score || 0, 0))}). It is never recommended for sale.</span></p>` : ""}
      ${(cur.conflicts || []).length ? `<p class="tl-flag"><span>${cur.conflicts.map((c) => esc(c.why || c.kind || String(c))).join(" ")}</span></p>` : ""}
      <div class="tl-cards">${cards}</div>
      ${fold("st-crit", "Show how each option is scored", critTable + `<p class="fine">${esc((dec.formula || []).join(" "))}</p>`, P.openFolds)}`;
  };

  // ---- part 2: sale proceeds, gross to net
  const proceedsPart = () => {
    const soldAs = pres.sold_as === "blocks" ? "blocks" : kinds;
    const ctl = pres.sold_as === "blocks" ? "" : `<div class="tl-controls">${seg("price", PRICE, state.price, "Priced at")}</div>`;
    const bb = pres.by_basis;
    const bbHtml = bb && bb.stated && bb.residual && isNum(bb.stated.gross_usd) && isNum(bb.residual.gross_usd) ? `<p class="tl-note">On the stated prices the ${esc(bb.stated.sold_as || "pieces")} bring ${esc(usdM(bb.stated.gross_usd))} gross (${esc(usdM(bb.stated.net_usd))} net); on the residual value the ${esc(bb.residual.sold_as || "parcels")} would bring ${esc(usdM(bb.residual.gross_usd))} gross (${esc(usdM(bb.residual.net_usd))} net). ${esc(bb.note || "")}</p>` : "";
    if (!wf || !(wf.parcels || wf.blocks || []).length) return outside ? "" : ctl + calmBox("No sale proceeds yet", `Proceeds need a price for each ${kind} on the chosen basis.`);
    const list = wf.parcels || wf.blocks || [];
    const opts = [["__all", `All ${soldAs}`]].concat(list.map((p) => [p.id, parcelLabel(ctx, p.id)]));
    const one = state.wf === "__all" ? null : list.find((p) => p.id === state.wf);
    // deductions summed by kind for all items
    const byKind = new Map();
    (one ? [one] : list).forEach((p) => (p.deductions || []).forEach((d) => { const x = byKind.get(d.id) || { label: cap(String(d.label || d.id)), amount: 0, unknown: 0 }; if (isNum(d.amount_usd)) x.amount += d.amount_usd; else x.unknown++; byKind.set(d.id, x); }));
    const gross = one ? one.gross_price_usd : wf.gross_total_usd, net = one ? one.net_cash_proceeds_usd : wf.net_total_usd;
    const steps = [{ label: "Price", value: gross, kind: "start" }].concat([...byKind.values()].filter((d) => d.amount > 0).map((d) => ({ label: d.label, value: d.amount, kind: "minus" }))).concat([{ label: "Net cash", value: net, kind: "total" }]);
    const how = (one ? one.formula : [wf.formula]) || [];
    const rows = [...byKind.entries()].map(([id, d]) => [esc(d.label), esc(d.unknown ? `${usd(d.amount)} + ${d.unknown} not known` : usd(d.amount))]);
    const upper = one ? one.net_proceeds_is_upper_bound : wf.net_total_is_upper_bound;
    return `${ctl}<div class="tl-controls"><label class="field"><span>Show</span><select data-wf>${opts.map(([v, w]) => `<option value="${esc(v)}"${v === state.wf ? " selected" : ""}>${esc(w)}</option>`).join("")}</select></label></div>
      <p class="tl-note">From a price of ${num(reg, usd(gross), { label: "Gross price", value: usd(gross), how: pr.formula || [] })} the seller keeps ${num(reg, usd(net), { label: "Net cash proceeds", value: usd(net), how, inputs: (pr.inputs_used || []).filter((x) => /^FIN-(BROKERAGE|CLOSING|TRANSFER|RECORDING)/.test(x.assumption_id || "")) })}${upper ? ", at most: some deductions are not known yet" : ""}.</p>
      ${P.chart("waterfall", { steps, unit: "usd", title: `Gross to net${one ? ", " + parcelLabel(ctx, one.id) : ""} (dollars)` })}
      ${bbHtml}
      ${fold("st-wf", "Show every deduction", smallTable([{ label: "Deduction" }, { label: "Amount", num: true }], rows.concat([[`<b>Net cash</b>`, `<b>${esc(usd(net))}</b>`]]), "Deductions"), P.openFolds)}`;
  };

  // ---- part 3: the capital plan against the targets
  const statedPlan = () => {
    const sp = pres.stated_plan;
    if (!sp) return "";
    const evs = (sp.by_close_month || []).map((m) => ({ month: Number(m.month) || 0, state: "sale", html: `<b>${esc((m.units || []).map((id) => parcelLabel(ctx, id)).join(", "))}</b> ${m.units && m.units.length > 1 ? "close" : "closes"}: ${esc(usdM(m.net_usd))} net (${esc(usdM(m.cumulative_net_usd))} to date)` }))
      .concat((sp.against_targets || []).map((t) => ({ month: Number(t.month) || 0, state: t.met ? "met" : "not_met", html: `<b>${esc(t.label || "Cash target")}</b>: ${esc(usdM(t.cumulative_target_usd))} needed by now, ${esc(usdM(t.cumulative_net_usd))} in hand${t.met ? "" : `, short by ${esc(usdM(t.shortfall_usd))}`}${t.net_is_upper_bound ? " (at most: a stub cost is not known)" : ""}` })))
      .sort((a, b) => a.month - b.month || (a.state === "sale" ? -1 : 1));
    const phases = (sp.by_phase || []).map((ph) => [esc(ph.phase ? "Phase " + ph.phase : "Phase not given"), esc((ph.units || []).map((id) => parcelLabel(ctx, id)).join(", ")), esc(acres(ph.net_acres)), esc(usdM(ph.net_usd))]);
    return `<h3 class="tl-sub">The package's own plan</h3>
      <p class="tl-note">The blocks the package marks for sale: ${esc(acres(sp.net_acres_sold))} sold for ${num(reg, usdM(sp.net_usd), { label: "The package's plan, net cash", value: usd(sp.net_usd), how: ["Each block marked for sale: stated price less the itemised deductions and its stub cost."].concat(sp.net_is_upper_bound ? ["A stub cost is not known, so the net is at most this."] : []) })} net${sp.net_is_upper_bound ? " at most" : ""}; ${esc(acres(sp.net_acres_kept))} kept (${esc((sp.kept || []).map((id) => parcelLabel(ctx, id)).join(", ") || "none")}).</p>
      ${sp.unknown_stubs ? `<p class="tl-note">${esc(sp.unknown_stubs === 1 ? "1 block has" : sp.unknown_stubs + " blocks have")} no stub cost yet, so the net is an upper bound.</p>` : ""}
      <ol class="tl-trig" aria-label="Timeline of the package's plan">${evs.map((e) => `<li><span class="tl-state ${e.state === "sale" ? "unknown" : e.state}">Month ${esc(int(e.month))}</span><span>${e.html}</span>${e.state === "sale" ? "" : `<span class="tl-state ${e.state}">${e.state === "met" ? "Met" : "Short"}</span>`}</li>`).join("")}</ol>
      ${phases.length ? fold("st-sp-phase", "Show by phase", smallTable([{ label: "Phase" }, { label: "Blocks" }, { label: "Net acres", num: true }, { label: "Net cash", num: true }], phases, "The package's plan by phase"), P.openFolds) : ""}
      <h3 class="tl-sub">Or let the engine choose</h3>`;
  };
  const planPart = () => {
    if (!plan || !plan.strategies) return outside ? "" : pres.stated_plan ? statedPlan().replace('<h3 class="tl-sub">Or let the engine choose</h3>', "") : calmBox("No capital plan yet", "The plan needs capital targets and priced " + kinds + ".");
    const s = plan.strategies[state.plan] || {};
    const targets = (s.proceeds_by_period || []).slice().sort((a, b) => a.month - b.month);
    const events = (s.picks || []).map((p) => ({ month: Number(p.close_month) || 0, html: `<b>${esc(p.name || parcelLabel(ctx, p.id))}</b> sale closes: ${esc(usdM(p.net_proceeds_usd))} net, ${esc(acres(p.net_ac))}${p.critical ? ' <span class="dz-chip warn">Critical asset</span>' : ""}`, state: "sale" }))
      .concat(targets.map((t) => ({ month: Number(t.month) || 0, html: `<b>${esc(t.label || ((pres.targets || []).find((x) => Number(x.month) === Number(t.month)) || {}).label || "Cash target")}</b>: ${esc(usdM(t.cumulative_target_usd))} needed by now, ${esc(usdM(t.cumulative_closed_usd))} in hand${t.met ? "" : `, short by ${esc(usdM(t.shortfall_usd))}`}`, state: t.met ? "met" : "not_met" })))
      .sort((a, b) => a.month - b.month || (a.state === "sale" ? -1 : 1));
    const cmp = PLANS.map(([k, w]) => { const x = plan.strategies[k] || {}; return [esc(w), esc(usdM(x.total_net_proceeds_usd)), esc(acres(x.acres_sold)), esc(acres((x.retained || {}).acres)), esc(x.all_targets_met ? "Yes" : "No"), esc(String((x.critical_asset_conflicts || []).length))]; });
    return `${statedPlan()}<div class="tl-controls">${seg("plan", PLANS, state.plan, "Plan")}</div>
      <p class="tl-note">${esc(s.rule || "")}</p>
      ${(s.critical_asset_conflicts || []).length ? `<p class="tl-flag"><span><b>This plan sells a critical asset.</b> ${s.critical_asset_conflicts.map((c) => esc(c.why || "")).join(" ")}</span></p>` : ""}
      <ol class="tl-trig" aria-label="Timeline">${events.map((e) => `<li><span class="tl-state ${e.state === "sale" ? "unknown" : e.state}">Month ${esc(int(e.month))}</span><span>${e.html}</span>${e.state === "sale" ? "" : `<span class="tl-state ${e.state}">${e.state === "met" ? "Met" : "Short"}</span>`}</li>`).join("")}</ol>
      <p class="tl-total">Sold: ${esc(acres(s.acres_sold))} for ${num(reg, usdM(s.total_net_proceeds_usd), { label: "Net cash from the plan", value: usd(s.total_net_proceeds_usd), how: plan.formula || [] })} net. Kept: ${esc(acres((s.retained || {}).acres))} (${esc(((s.retained || {}).parcel_ids || []).map((id) => parcelLabel(ctx, id)).join(", ") || "none")}).</p>
      ${fold("st-plans", "Compare the three plans", smallTable([{ label: "Plan" }, { label: "Net cash", num: true }, { label: "Sold", num: true }, { label: "Kept", num: true }, { label: "Every target met" }, { label: "Critical sold", num: true }], cmp, "The three plans"), P.openFolds)}`;
  };

  // ---- part 4: retained land over time and paced releases
  const keptPart = () => {
    const rv = r.retained_value, pace = r.paced_releases;
    if (!rv && !pace) return outside ? "" : calmBox("No retained-land figures yet", "These need the land kept and its value per acre.");
    let html = "";
    if (rv && (rv.yearly || []).length) {
      const a = rv.assumptions || {};
      html += `<p class="tl-note">${esc(acres(a.acres))} kept, worth ${num(reg, usdM(a.base_value_usd), { label: "Retained land, value today", value: usd(a.base_value_usd), how: [rv.formula || ""] })} today, growing ${esc(pct(a.appreciation_pct, 1))} a year${a.placemaking_lift_pct ? ` with a ${esc(pct(a.placemaking_lift_pct, 0))} lift from year ${esc(a.lift_year)}` : ""}: ${num(reg, usdM(rv.value_at_end_usd), { label: "Retained land, value at the end", value: usd(rv.value_at_end_usd), how: [rv.formula || ""], inputs: stratInputs })} by year ${esc(a.years)}. Land only, no rent.</p>
        ${P.chart("line", { x: rv.yearly.map((y) => "Year " + y.year), series: [{ name: "Value of the land kept", values: rv.yearly.map((y) => y.value_usd) }], unit: "usd", title: "Retained land value by year (dollars)" })}`;
    }
    if (pace && (pace.events || []).length) {
      const a = pace.assumptions || {};
      html += `<h3 class="tl-sub">Paced releases: ${esc(acres(a.release_acres))} every ${esc(a.every_years)} ${noun(a.every_years, "year", "years")}</h3>
        <p class="tl-note">Net from the releases ${num(reg, usdM(pace.total_net_proceeds_usd), { label: "Paced releases, net proceeds", value: usd(pace.total_net_proceeds_usd), how: pace.formula || [] })}; ${esc(acres(pace.acres_left))} left worth ${esc(usdM(pace.value_left_usd))}. Together ${esc(usdM(pace.total_wealth_usd))}, not discounted.</p>
        ${fold("st-pace", "Show each release", smallTable([{ label: "Year" }, { label: "Acres sold", num: true }, { label: "Price per acre", num: true }, { label: "Net", num: true }, { label: "Acres left", num: true }], pace.events.map((e) => [esc("Year " + e.year), esc(nFix(e.acres_sold, 1)), esc(usd(e.price_per_ac_usd)), esc(usdM(e.net_usd)), esc(nFix(e.acres_left, 1))]), "Paced releases"), P.openFolds)}`;
    } else if (rv) html += `<p class="fine">Paced releases need the acres released in each tranche and the years between them (STR-RELEASE-ACRES, STR-RELEASE-EVERY-YEARS).</p>`;
    return html;
  };

  P.set({ lead, before, parts: [["decisions", "Decisions", decisionPart()], ["proceeds", "Sale proceeds", proceedsPart()], ["plan", "Cash plan", planPart()], ["kept", "Land kept", keptPart()]],
    after: disclaimerHtml(st) });
  wireSegKeys(el);
  const redraw = (part, html) => { const node = el.querySelector(`[data-part="${part}"]`); if (!node) return; const keep = node.querySelector(".dz-part-title"); P.swap(node, (keep ? keep.outerHTML : "") + html); };
  el.addEventListener("change", (e) => {
    if (e.target.matches("[data-pick]")) { state.item = e.target.value; redraw("decisions", decisionPart()); el.querySelector("[data-pick]").focus(); }
    if (e.target.matches("[data-wf]")) { state.wf = e.target.value; redraw("proceeds", proceedsPart()); el.querySelector("[data-wf]").focus(); }
  });
  el.addEventListener("click", (e) => {
    const it = e.target.closest("[data-item]");
    if (it) { state.item = it.dataset.item; redraw("decisions", decisionPart()); const s = el.querySelector("[data-pick]"); if (s) s.focus(); return; }
    const b = e.target.closest("[data-seg]");
    if (!b) return;
    if (b.dataset.seg === "plan") { state.plan = b.dataset.val; redraw("plan", planPart()); el.querySelector(`[data-seg="plan"][data-val="${b.dataset.val}"]`).focus(); }
    if (b.dataset.seg === "price" && b.dataset.val !== state.price) { state.price = b.dataset.val; rerun(); }
    if (b.dataset.seg === "basis") { state.basis = b.dataset.val; rerun(); }
  });
}
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

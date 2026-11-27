// Phase returns: each phase's cost, NOI, value, yield on cost against the hurdle, IRR (with whether it could be
// pinned down), equity multiple and NPV; the dated annual cash flow; break-evens as "needs at least X, the plan has
// Y"; and the one-at-a-time sensitivity tornado.
import {
  esc, isNum, nFix, fold, compute, page, leadHtml, missingHtml, hiddenHtml, isOutside, disclaimerHtml, calmBox, smallTable, seg, wireSegKeys,
  num, usd, usdM, pct, ratio, int, noun, NK, entities, guarded, loadingHtml, inputSpec, useLabel,
} from "./common.js";

const METRICS = [["irr_pct", "IRR"], ["yoc_pct", "Yield on cost"], ["npv_usd", "NPV"], ["equity_multiple", "Equity multiple"]];
const METRIC_UNIT = { irr_pct: "pct", yoc_pct: "pct", npv_usd: "usd", equity_multiple: "ratio", rlv_total_usd: "usd" };
const BE_WORDS = {
  apartment_rent: ["Apartment rent", (v) => usd(v) + " per home per month"],
  retail_nnn_rent: ["Retail rent (NNN)", (v) => (isNum(v) ? `$${nFix(v, 2)}/SF per year ($${nFix(v / 12, 2)}/SF per month)` : NK)],
  hotel_adr: ["Hotel room rate (ADR)", (v) => usd(v) + " per night"],
  for_sale_price: ["For-sale home price", (v) => usd(v)],
  exit_cap_rate: ["Exit cap rate", (v) => pct(v, 2)],
};

export async function render(el, ctx) {
  el.innerHTML = loadingHtml("Working out the phase returns…");
  const state = { metric: "irr_pct", flow: "full" };
  const run = async () => {
    const resp = await compute(ctx, "proforma", { options: { tornado_metric: state.metric } });
    if (ctx.alive && !ctx.alive()) return;
    const box = document.createElement("div");
    el.replaceChildren(box);
    draw(box, ctx, resp, state, () => { el.innerHTML = loadingHtml("Working out the sensitivity…"); return guarded(el, ctx, run); });
  };
  await guarded(el, ctx, run);
}

function irrWords(irr) {
  if (!irr) return "";
  if (!irr.converged) return `The IRR could not be pinned down${irr.why ? ": " + irr.why : "."}`;
  let s = `Worked out exactly (${irr.method === "newton" ? "Newton's method" : irr.method || "search"}, ${irr.iterations || 0} steps).`;
  if (irr.sign_changes > 1) s += ` The cash flow changes direction ${irr.sign_changes} times, so more than one rate could fit: read it with the NPV.`;
  return s;
}

function draw(el, ctx, resp, state, rerun) {
  const P = page(el, ctx), reg = P.reg;
  P.resp = resp;
  const r = resp.result || {}, phases = r.phases || [], full = r.full_buildout, outside = isOutside(resp);
  const F = resp.formula || [];
  const allInputs = resp.inputs_used || [];
  const pfInputs = allInputs.filter((x) => /^PF-/.test(x.assumption_id || ""));
  const spec = (label, value, more = []) => ({ label, value, how: F.concat(more), inputs: pfInputs.concat(allInputs.filter((x) => (x.field || "").startsWith("phases/"))) });

  // ---- the answer
  let lead;
  const ft = (full && full.totals) || {}, fy = (full && full.yield_on_cost) || {}, fi = (full && full.irr) || {};
  const modelled = [full].concat(phases).some((ph) => ph && ph.totals && ["total_cost_incl_land_usd", "stabilized_noi_usd_yr", "net_sales_revenue_usd"].some((k) => Number(ph.totals[k]) > 0));
  if (!modelled) {
    lead = leadHtml({ sentence: phases.length ? `${phases.length === 1 ? "The one phase is" : `The ${phases.length} phases are`} laid out, but ${phases.length === 1 ? "its returns cannot" : "their returns cannot"} be worked out yet: the package gives no development costs or income for their uses.` : "Phase returns cannot be worked out yet: the package does not hold the finance inputs they need.", aside: "The list below says what is missing. Nothing is guessed in its place." });
  } else if (!outside && isNum(fy.yoc_pct)) {
    const meets = fy.meets_hurdle;
    lead = leadHtml({
      sentence: `Across the full buildout the plan earns ${num(reg, pct(fy.yoc_pct, 2), spec("Full buildout, yield on cost", pct(fy.yoc_pct, 2), ["Yield on cost = stabilised NOI / (development cost + land)."]))} on cost${isNum(fy.hurdle_pct) ? `, ${meets ? "above" : "below"} the ${num(reg, pct(fy.hurdle_pct, 2), inputSpec(ctx, resp, "PF-HURDLE-YOC-PCT", "Hurdle yield on cost"))} hurdle` : ""}${isNum(fi.irr_pct) ? `, and an IRR of ${num(reg, pct(fi.irr_pct, 2), spec("Full buildout, IRR", pct(fi.irr_pct, 2), [irrWords(fi)]))}` : ""}.`,
      big: isNum(fi.irr_pct) ? pct(fi.irr_pct, 1) : pct(fy.yoc_pct, 1), bigLabel: isNum(fi.irr_pct) ? "IRR, full buildout (unlevered)" : "Yield on cost, full buildout",
      bigSrc: reg.add(spec(isNum(fi.irr_pct) ? "Full buildout, IRR" : "Full buildout, yield on cost", isNum(fi.irr_pct) ? pct(fi.irr_pct, 2) : pct(fy.yoc_pct, 2), [irrWords(fi)])),
      aside: `${irrWords(fi)} Unlevered and annual, money at year end.`,
      chips: isNum(fy.hurdle_pct) ? `<span class="dz-chip${meets ? "" : " warn"}">${meets ? "Meets" : "Misses"} the yield-on-cost hurdle by ${esc(nFix(Math.abs(fy.spread_bps || 0), 0))} basis points</span>` : "",
    });
  } else {
    lead = leadHtml({
      sentence: `The full buildout costs ${num(reg, usdM(ft.total_cost_incl_land_usd), spec("Full buildout, total cost with land", usd(ft.total_cost_incl_land_usd)))} with land and earns ${num(reg, usdM(ft.stabilized_noi_usd_yr) + " a year", spec("Full buildout, stabilised NOI per year", usd(ft.stabilized_noi_usd_yr)))} once stabilised.`,
      big: usdM(ft.implied_value_usd), bigLabel: "Value of the income uses when stabilised", bigSrc: reg.add(spec("Full buildout, implied value", usd(ft.implied_value_usd), ["Implied value = NOI / exit cap x (1 - selling cost)."])),
    });
  }
  const before = (outside ? hiddenHtml(resp, ["returns"]) : "") + missingHtml(resp, { labelOf: (id) => useLabel(ctx, id), open: P.openFolds });

  // ---- part 1: phase by phase
  const phaseCard = (ph, label, isFull) => {
    const t = ph.totals || {}, y = ph.yield_on_cost || {}, i = ph.irr || {};
    const s = (what, v, more) => num(reg, v, spec(`${label}, ${what}`, v, more));
    const kv = [
      ["Cost with land", s("total cost with land", usdM(t.total_cost_incl_land_usd))],
      ["Stabilised NOI, per year", s("stabilised NOI per year", usdM(t.stabilized_noi_usd_yr))],
      ["Value of income uses", s("implied value", usdM(t.implied_value_usd), ["Implied value = NOI / exit cap x (1 - selling cost)."])],
      ["Net sales (for-sale uses)", s("net sales revenue", usdM(t.net_sales_revenue_usd))],
    ];
    if (!outside) {
      if (isNum(y.yoc_pct)) kv.push(["Yield on cost", s("yield on cost", pct(y.yoc_pct, 2)) + (isNum(y.hurdle_pct) ? ` <small>vs ${esc(pct(y.hurdle_pct, 2))}</small>` : "")]);
      if (isNum(i.irr_pct)) kv.push(["IRR", s("IRR", pct(i.irr_pct, 2), [irrWords(i)]) + (isNum(i.hurdle_pct) ? ` <small>vs ${esc(pct(i.hurdle_pct, 2))}</small>` : "")]);
      if (isNum(ph.equity_multiple)) kv.push(["Equity multiple", s("equity multiple", ratio(ph.equity_multiple), ["Equity multiple = money back / money put in."])]);
      if (ph.npv && isNum(ph.npv.npv_usd)) kv.push([`NPV at ${pct(ph.npv.discount_rate_pct, 1)}`, s("NPV", usdM(ph.npv.npv_usd), ["NPV = sum of flow / (1 + rate)^year."])]);
    }
    const ok = !outside && isNum(y.yoc_pct) && isNum(y.hurdle_pct) ? (y.meets_hurdle ? "good" : "bad") : "";
    return `<article class="tl-card ${ok}${isFull ? " best" : ""}"><span class="tl-card-k">${esc(isFull ? "All phases together" : "Phase")}</span><h3>${esc(label)}</h3>
      <dl class="tl-kv">${kv.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("")}</dl>
      ${!outside && i && i.irr_pct !== undefined && !i.converged ? `<p class="fine">${esc(irrWords(i))}</p>` : ""}
      ${t.cost_unknown_items ? `<p class="fine">${t.cost_unknown_items} cost items are not known, so the cost is a lower bound.</p>` : ""}</article>`;
  };
  const phasePart = () => {
    if (!phases.length || !modelled) return calmBox("No phases are modelled yet", "A phase is modelled once its base-case program lines have uses in the finance library.");
    const lines = phases.map((ph) => fold("pf-lines-" + ph.phase_id, `Show what ${ph.label || "phase " + ph.phase_id} builds`, smallTable(
      [{ label: "Use" }, { label: "Net acres", num: true }, { label: "Homes or keys", num: true }, { label: "Building SF", num: true }, { label: "Cost", num: true }, { label: "NOI per year", num: true }, { label: "Net sales", num: true }],
      (ph.lines || []).map((l) => [esc(l.label || useLabel(ctx, l.use)), esc(nFix(l.net_ac || 0, 1)), esc(isNum(l.units) ? int(l.units) : "-"), esc(isNum(l.building_sf) ? int(l.building_sf) : "-"), esc(usdM(l.development_cost_usd)), esc(isNum(l.stabilized_noi_usd_yr) ? usdM(l.stabilized_noi_usd_yr) : "-"), esc(isNum(l.net_sales_usd) ? usdM(l.net_sales_usd) : "-")]),
      `${ph.label} program`), P.openFolds)).join("");
    const a = (phases[0] && phases[0].assumptions) || {};
    return `<div class="tl-cards">${full ? phaseCard(full, "Full buildout", true) : ""}${phases.map((ph) => phaseCard(ph, ph.label || "Phase " + ph.phase_id, false)).join("")}</div>
      ${lines}
      <p class="fine">Settings used: build ${esc(a.build_years ?? NK)} ${noun(a.build_years, "year", "years")}, lease-up ${esc(a.lease_up_months ?? NK)} ${noun(a.lease_up_months, "month", "months")}, held ${esc(a.hold_years ?? NK)} ${noun(a.hold_years, "year", "years")} after stabilisation, NOI growth ${esc(pct(a.noi_growth_pct, 1))} a year, discount rate ${esc(pct(a.discount_rate_pct, 1))}.</p>`;
  };

  // ---- part 2: the dated cash flow
  const flowPart = () => {
    const opts = (full ? [["full", "Full buildout"]] : []).concat(phases.map((ph) => [ph.phase_id, ph.label || "Phase " + ph.phase_id]));
    if (!opts.length || !modelled) return "";
    if (!opts.some((o) => o[0] === state.flow)) state.flow = opts[0][0];
    const src = state.flow === "full" ? full : phases.find((ph) => ph.phase_id === state.flow);
    const flows = (src && src.cash_flows) || [];
    if (!flows.length) return calmBox("No cash flow yet", "");
    let cum = 0;
    const years = flows.map((f) => String(f.year ?? f.t));
    const net = flows.map((f) => f.net_usd), cumul = net.map((v) => (cum += isNum(v) ? v : 0));
    const cols = [["land_usd", "Land"], ["construction_cost_usd", "Construction"], ["noi_usd", "NOI"], ["sales_net_usd", "Net sales"], ["exit_net_usd", "Sale at the end"], ["net_usd", "Net"]];
    const tbl = smallTable([{ label: "Year" }].concat(cols.map(([, w]) => ({ label: w, num: true }))).concat([{ label: "Cumulative", num: true }]),
      flows.map((f, k) => [esc(years[k])].concat(cols.map(([c]) => esc(usdM(f[c])))).concat([esc(usdM(cumul[k]))])), "Annual cash flow");
    return `<div class="tl-controls"><label class="field"><span>Cash flow of</span><select data-flow>${opts.map(([v, w]) => `<option value="${esc(v)}"${v === state.flow ? " selected" : ""}>${esc(w)}</option>`).join("")}</select></label></div>
      <p class="tl-note">Money out is below zero, money in above. Peak money out: <b>${esc(usdM(src.peak_cumulative_outflow_usd))}</b>${isNum(src.payback_year_index) ? `; the money is back by year ${esc(years[src.payback_year_index] || src.payback_year_index)}` : ""}.</p>
      ${P.chart("line", { x: years, series: [{ name: "Net cash flow in the year", values: net }, { name: "Cumulative", values: cumul }], unit: "usd", title: "Annual cash flow (dollars per year)" })}
      ${fold("pf-flow-table", "Show the year-by-year figures", tbl, P.openFolds)}`;
  };

  // ---- part 3: break-evens
  const bePart = () => {
    const be = r.break_even || {};
    const keys = Object.keys(be);
    if (!keys.length) return outside ? "" : calmBox("No break-evens yet", "Break-evens need a phase with priced uses and a hurdle (yield on cost or IRR) in the register.");
    const items = keys.map((k) => {
      const b = be[k] || {}, [name, fmt] = BE_WORDS[k] || [k.replace(/_/g, " "), (v) => (isNum(v) ? nFix(v, 2) : NK)];
      const metric = b.metric === "irr" ? "IRR" : "yield on cost";
      const target = `${metric} of ${pct(b.target_pct, 2)}`;
      const how = (b.formula || []).concat([`Target: ${target}.`, b.why || ""]).filter(Boolean);
      const isCap = k === "exit_cap_rate";
      let lineHtml;
      if (!b.converged && !isNum(b.breakeven_value) && !isNum(b.breakeven_factor)) {
        lineHtml = `<p><b>${esc(name)}</b>: ${esc(b.already_met_today ? `the ${metric} target is met with room to spare; no break-even inside the range searched.` : (b.why || "no break-even inside the range searched."))}</p>`;
      } else {
        const uses = (b.by_use || []).filter((u) => isNum(u.breakeven));
        const one = isNum(b.breakeven_value) ? b.breakeven_value : null;
        const curs = uses.map((u) => u.current).filter(isNum);
        const lo = curs.length ? Math.min(...curs) : null, hi = curs.length ? Math.max(...curs) : null;
        const planWords = !curs.length ? "" : lo === hi ? fmt(lo) : `${fmt(lo)} to ${fmt(hi)}`;
        const head = one !== null
          ? `${isCap ? "can be at most" : "needs at least"} ${num(reg, fmt(one), { label: `${name}, break-even`, value: fmt(one), how })}${planWords ? `; the plan has ${esc(planWords)}` : ""}.`
          : `${isCap ? "can rise to" : "can fall to"} ${num(reg, nFix((b.breakeven_factor || 0) * 100, 0) + "% of today's figures", { label: `${name}, break-even`, value: nFix((b.breakeven_factor || 0) * 100, 1) + "% of today", how })} across every use.`;
        const article = /^[aeiouAEIOU]|^IRR/.test(metric) ? "an" : "a";
        const sameBe = uses.length > 1 && uses.every((u) => Math.abs(u.breakeven - uses[0].breakeven) < 1e-6);
        lineHtml = `<p>To reach ${article} ${esc(target)}, <b>${esc(name.charAt(0).toLowerCase() + name.slice(1))}</b> ${head}</p>
          ${uses.length > 1 && !sameBe ? fold("be-" + k, "Show by use", `<ul class="tl-mini">${uses.map((u) => `<li>${esc(useLabel(ctx, u.use))}: needs ${isCap ? "at most" : "at least"} ${esc(fmt(u.breakeven))}; the plan has ${esc(fmt(u.current))}</li>`).join("")}</ul>`, P.openFolds) : ""}`;
      }
      const room = b.already_met_today ? '<span class="tl-state met">Met today</span>' : '<span class="tl-state not_met">Not met today</span>';
      return `<li><div>${lineHtml}</div>${room}</li>`;
    });
    return `<p class="tl-note">For each driver the program has: the value at which the full buildout just meets its hurdle, beside what the plan has.</p><ul class="tl-be">${items.join("")}</ul>`;
  };

  // ---- part 4: sensitivity
  const tornPart = () => {
    const t = r.tornado;
    if (!t || !(t.rows || []).length) return outside ? "" : calmBox("No sensitivity yet", (t && t.why) || "The sensitivity needs the full buildout to be modelled.");
    const unit = METRIC_UNIT[t.metric] || "";
    const fmt = (v) => (unit === "pct" ? pct(v, 2) : unit === "usd" ? usdM(v) : unit === "ratio" ? ratio(v) : nFix(v, 2));
    const rows = t.rows.map((x) => [esc(x.label), num(reg, fmt(x.metric_at_low), { label: `${x.label}, low setting`, value: fmt(x.metric_at_low), how: [t.formula || "", `Low setting: ${JSON.stringify(x.low_setting || {}).replace(/[{}"]/g, "").replace(/_/g, " ")}`] }),
      num(reg, fmt(x.metric_at_high), { label: `${x.label}, high setting`, value: fmt(x.metric_at_high), how: [t.formula || "", `High setting: ${JSON.stringify(x.high_setting || {}).replace(/[{}"]/g, "").replace(/_/g, " ")}`] }), esc(fmt(x.swing))]);
    return `<div class="tl-controls">${seg("metric", METRICS, state.metric, "Measure")}</div>
      <p class="tl-note">Each input moves alone to its low and its high end; the widest bar moves the result most. Base: <b>${esc(fmt(t.base_value))}</b>.</p>
      ${P.chart("tornado", { rows: t.rows.map((x) => ({ label: x.label, low: x.metric_at_low, high: x.metric_at_high })), base: t.base_value, unit, title: `${(METRICS.find((m) => m[0] === t.metric) || [0, t.metric])[1]}: what moves it most` })}
      ${fold("pf-torn", "Show the figures", smallTable([{ label: "Input" }, { label: "At the low end", num: true }, { label: "At the high end", num: true }, { label: "Swing", num: true }], rows, "Sensitivity"), P.openFolds)}`;
  };

  P.set({ lead, before, parts: [["phases", "By phase", phasePart()], ["flow", "Cash flow", flowPart()], ["breakeven", "Break-evens", bePart()], ["sensitivity", "Sensitivity", tornPart()]], after: disclaimerHtml(resp) });
  wireSegKeys(el);
  el.addEventListener("change", (e) => {
    if (!e.target.matches("[data-flow]")) return;
    state.flow = e.target.value;
    const node = el.querySelector('[data-part="flow"]'), keep = node.querySelector(".dz-part-title");
    P.swap(node, (keep ? keep.outerHTML : "") + flowPart());
    const s = node.querySelector("[data-flow]"); if (s) s.focus();
  });
  el.addEventListener("click", (e) => {
    const b = e.target.closest('[data-seg="metric"]');
    if (b && b.dataset.val !== state.metric) { state.metric = b.dataset.val; rerun(); }
  });
}

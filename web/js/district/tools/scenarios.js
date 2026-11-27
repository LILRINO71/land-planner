// Phases and scenarios: what each phase builds by use (SF, homes, keys, acres) in the low, base and high case, the
// three cases side by side, named unit-count scenarios, absorption by year, and each phase's triggers (met, not met,
// or not known yet, with what each needs).
import {
  esc, isNum, nFix, fold, compute, page, leadHtml, missingHtml, hiddenHtml, isOutside, disclaimerHtml, calmBox, smallTable, seg, wireSegKeys,
  num, usd, usdM, pct, int, ratio, NK, entities, useLabel, phaseLabel, guarded, loadingHtml, inputSpec, sum,
} from "./common.js";

const CASES = [["low", "Low"], ["base", "Base"], ["high", "High"]];
const MEAS = [["sf", "SF", "Building SF"], ["units", "Homes", "Homes"], ["keys", "Keys", "Hotel keys"], ["acres", "Acres", "Acres"]];
const METRIC = {
  units_total: ["Homes", (v) => int(v)], rlv_total_usd: ["Residual land value, all parcels", usdM], development_cost_usd: ["Development cost", usdM],
  total_cost_incl_land_usd: ["Cost with land", usdM], stabilized_noi_usd_yr: ["Stabilised NOI, per year", usdM], implied_value_usd: ["Value of the income uses", usdM],
  net_sales_revenue_usd: ["Net sales (for-sale uses)", usdM], yoc_pct: ["Yield on cost", (v) => pct(v, 2)], irr_pct: ["IRR", (v) => pct(v, 2)],
  equity_multiple: ["Equity multiple", ratio], npv_usd: ["NPV", usdM],
};
const OP_WORDS = { ">=": "at least", ">": "more than", "<=": "at most", "<": "less than", "==": "exactly" };
const METRIC_WORDS = { units_absorbed: "homes sold and occupied", units_delivered: "homes delivered", occupancy_pct: "occupancy", pre_leasing_pct: "pre-leasing", absorption_per_month: "homes absorbed a month" };

export async function render(el, ctx) {
  el.innerHTML = loadingHtml("Laying out the phases…");
  await guarded(el, ctx, async () => {
    const resp = await compute(ctx, "scenarios");
    if (ctx.alive && !ctx.alive()) return;
    draw(el, ctx, resp);
  });
}

function programOf(ctx) {
  const lines = entities(ctx).program_lines || [];
  const phases = (entities(ctx).phases || []).slice().sort((a, b) => (a.order ?? 99) - (b.order ?? 99));
  const ids = phases.map((p) => p.id).filter((id) => lines.some((l) => String(l.phase) === String(id)));
  lines.forEach((l) => { if (!ids.includes(String(l.phase))) ids.push(String(l.phase)); });
  // the full buildout last
  ids.sort((a, b) => (a === "full") - (b === "full"));
  return { lines, ids };
}

function draw(el, ctx, resp) {
  const P = page(el, ctx), reg = P.reg;
  P.resp = resp;
  const r = resp.result || {}, outside = isOutside(resp);
  const { lines, ids } = programOf(ctx);
  const state = { phase: ids.find((x) => x !== "full") || ids[0] || "", kase: "base" };
  const lbh = r.low_base_high;

  // ---- the answer
  const base = lbh && (lbh.scenarios || []).find((s) => s.name === (lbh.base_name || "base"));
  const phased = lines.filter((l) => l.scenario === "base" && l.phase !== "full");
  const homes = sum(phased.map((l) => l.units)), sf = sum(phased.map((l) => l.sf)), ac = sum(phased.map((l) => l.acres));
  const nPhases = ids.filter((x) => x !== "full").length;
  let lead;
  if (base && isNum(base.metrics.units_total)) {
    const t = lbh.table || {};
    lead = leadHtml({
      sentence: `The base case delivers ${num(reg, int(base.metrics.units_total) + " homes", { label: "Homes, base case", value: int(base.metrics.units_total), how: [lbh.formula || ""] })}${t.rlv_total_usd && !outside && isNum(t.rlv_total_usd.low) && isNum(t.rlv_total_usd.high) ? `; residual land value runs from ${num(reg, usdM(t.rlv_total_usd.low), { label: "Residual land value, low case", value: usd(t.rlv_total_usd.low), how: [lbh.formula || ""] })} in the low case to ${num(reg, usdM(t.rlv_total_usd.high), { label: "Residual land value, high case", value: usd(t.rlv_total_usd.high), how: [lbh.formula || ""] })} in the high case` : ""}.`,
      big: int(base.metrics.units_total), bigLabel: "Homes, base case", bigSrc: reg.add({ label: "Homes, base case", value: int(base.metrics.units_total), how: [lbh.formula || ""] }),
      aside: `${nPhases} ${nPhases === 1 ? "phase" : "phases"} in the package. The low and high cases move rents, costs, cap rates and required returns together.`,
    });
  } else if (lines.length) {
    lead = leadHtml({
      sentence: `The package lays the program out in ${nPhases} ${nPhases === 1 ? "phase" : "phases"}: ${homes ? `<b>${esc(int(homes))} homes</b>` : ""}${homes && sf ? " and " : ""}${sf ? `<b>${esc(int(sf))} SF</b> of buildings` : ""}${ac ? ` on ${esc(nFix(ac, 1))} acres` : ""} in the base case, as the phases state them.`,
      big: homes ? int(homes) : sf ? int(sf) : "", bigLabel: homes ? "Homes in the phased base case" : "Building SF in the phased base case",
      aside: "The full buildout is shown on its own: it is the whole plan, not a phase added to the others.",
    });
  } else lead = leadHtml({ sentence: "The package has no program lines yet, so there are no phases to lay out." });
  const before = (outside ? hiddenHtml(resp, ["returns"]) : "") + missingHtml(resp, { labelOf: (id) => useLabel(ctx, id), open: P.openFolds });

  // ---- part 1: what each phase builds
  const programPart = () => {
    if (!ids.length) return calmBox("No program lines yet", "");
    const inPhase = lines.filter((l) => String(l.phase) === String(state.phase));
    const cases = CASES.filter(([c]) => inPhase.some((l) => l.scenario === c));
    if (!cases.some(([c]) => c === state.kase)) state.kase = cases.some(([c]) => c === "base") ? "base" : (cases[0] || ["base"])[0];
    const rows = inPhase.filter((l) => l.scenario === state.kase);
    const meas = MEAS.filter(([m]) => inPhase.some((l) => isNum(l[m])));
    const cellOf = (l, m) => {
      if (!isNum(l[m])) return '<span class="muted">-</span>';
      const words = m === "acres" ? nFix(l[m], 2) : int(l[m]);
      return num(reg, words, l.assumption ? { label: `${useLabel(ctx, l.use)}, ${phaseLabel(ctx, l.phase)}, ${state.kase} case`, value: words, figure: l.assumption }
        : { label: `${useLabel(ctx, l.use)}, ${phaseLabel(ctx, l.phase)}`, value: words, how: [`From the program line ${l.id} (${l.status || "status not given"}).`].concat(l.note ? [l.note] : []) });
    };
    const body = rows.map((l) => [`${esc(useLabel(ctx, l.use))}${l.note ? `<small>${esc(String(l.note).slice(0, 140))}${String(l.note).length > 140 ? "…" : ""}</small>` : ""}`].concat(meas.map(([m]) => cellOf(l, m))));
    const totals = { cls: "total", cells: ["<b>Total</b>"].concat(meas.map(([m]) => { const v = sum(rows.map((l) => l[m])); return rows.some((l) => isNum(l[m])) ? `<b>${esc(m === "acres" ? nFix(v, 2) : int(v))}</b>` : "-"; })) };
    const blank = rows.length && !meas.length;
    // side by side: the main measure in every case
    const main = (meas.find(([m]) => m === "units") || meas.find(([m]) => m === "sf") || meas[0] || [])[0];
    const useIds = [...new Set(inPhase.map((l) => l.use))];
    const side = main && cases.length > 1 ? smallTable([{ label: "Use" }].concat(cases.map(([, w]) => ({ label: w, num: true }))),
      useIds.map((u) => [esc(useLabel(ctx, u))].concat(cases.map(([c]) => { const v = inPhase.filter((l) => l.use === u && l.scenario === c).map((l) => l[main]); return v.some(isNum) ? esc(main === "acres" ? nFix(sum(v), 2) : int(sum(v))) : "-"; }))),
      "Cases side by side") : "";
    const acresChart = rows.filter((l) => isNum(l.acres)).length > 1 ? P.chart("bar", { labels: rows.filter((l) => isNum(l.acres)).map((l) => useLabel(ctx, l.use)), values: rows.filter((l) => isNum(l.acres)).map((l) => l.acres), unit: "acres", title: `Acres by use, ${phaseLabel(ctx, state.phase)}` }) : "";
    const ph = (entities(ctx).phases || []).find((p) => String(p.id) === String(state.phase)) || {};
    return `<div class="tl-controls"><label class="field"><span>Phase</span><select data-phase>${ids.map((id) => `<option value="${esc(id)}"${id === state.phase ? " selected" : ""}>${esc(phaseLabel(ctx, id))}</option>`).join("")}</select></label>
        ${cases.length > 1 ? seg("kase", cases, state.kase, "Case") : `<p class="tl-note">Only the ${esc(state.kase)} case is in the package for this phase.</p>`}</div>
      ${ph.absorption_note ? `<p class="tl-note">${esc(ph.absorption_note)}</p>` : ""}
      ${blank ? calmBox("This phase names its uses but gives no quantities yet", "The uses are listed below; their SF, homes or acres are not in the package.") : ""}
      ${rows.length ? smallTable([{ label: "Use" }].concat(meas.map(([, , w]) => ({ label: w, num: true }))), body.concat(meas.length ? [totals] : []), `${phaseLabel(ctx, state.phase)}, ${state.kase} case`) : calmBox("Nothing in this case", "")}
      ${acresChart}
      ${side ? fold("sc-side", "Show low, base and high side by side", side, P.openFolds) : ""}`;
  };

  // ---- part 2: the three cases side by side
  const casesPart = () => {
    if (!lbh || !lbh.table) return outside ? "" : calmBox("The three cases cannot be worked out yet", "They need the finance library: each use's density, revenue, cap rate and required return.");
    const keys = Object.keys(lbh.table).filter((k) => METRIC[k]);
    const sc = lbh.scenarios || [];
    const adj = (s) => Object.entries(s.adjustments || {}).map(([k, v]) => `${k.replace(/_pct$|_delta_pct$/, "").replace(/_/g, " ")} ${v > 0 ? "+" : ""}${v}${/delta/.test(k) ? " points" : "%"}`).join(", ") || "the package's figures as they are";
    const rows = keys.map((k) => [esc(METRIC[k][0])].concat(CASES.map(([c]) => {
      const v = lbh.table[k][c], d = (lbh.vs_base || {})[c] ? lbh.vs_base[c][k] : null;
      const words = METRIC[k][1](v);
      return num(reg, words, { label: `${METRIC[k][0]}, ${c} case`, value: words, how: [lbh.formula || "", `${c} case: ${adj(sc.find((s) => s.name === c) || {})}.`] }) + (c !== "base" && isNum(d) && d !== 0 ? `<small class="${d > 0 ? "dz-diff-up" : "dz-diff-down"}">${d > 0 ? "+" : "-"}${esc(METRIC[k][1](Math.abs(d)))} vs base</small>` : "");
    })));
    return `<p class="tl-note">The same engine run three times. ${CASES.map(([c, w]) => `${w}: ${esc(adj(sc.find((s) => s.name === c) || {}))}.`).join(" ")}</p>
      ${smallTable([{ label: "Measure" }].concat(CASES.map(([, w]) => ({ label: w + " case", num: true }))), rows, "Low, base and high")}`;
  };

  // ---- part 3: named unit-count scenarios
  const unitsPart = () => {
    const u = r.unit_scenarios;
    if (!u || !(u.scenarios || []).length) return outside ? "" : calmBox("No unit-count scenarios in the package", "Each one is a register figure named SCN-UNITS- and the number of homes, for example SCN-UNITS-2000.");
    const keys = Object.keys(u.table || {}).filter((k) => METRIC[k]);
    const names = u.scenarios.map((s) => s.name);
    const nice = (n) => n.replace(/_units$/, " homes").replace(/_/g, " ");
    return `<p class="tl-note">The program scaled so the residential uses hold each total. ${esc(u.formula || "")}</p>
      ${smallTable([{ label: "Measure" }].concat(names.map((n) => ({ label: nice(n), num: true }))), keys.map((k) => [esc(METRIC[k][0])].concat(names.map((n) => num(reg, METRIC[k][1](u.table[k][n]), { label: `${METRIC[k][0]}, ${nice(n)}`, value: METRIC[k][1](u.table[k][n]), how: [u.formula || ""], figure: "" })))), "Unit-count scenarios")}`;
  };

  // ---- part 4: absorption
  const absorbPart = () => {
    const a = r.absorption;
    if (!a || !(a.yearly || []).length) return outside ? "" : calmBox("No absorption schedule yet", "It needs the homes absorbed per year (SCN-ABSORPTION-UNITS-PER-YEAR) and the homes in the program.");
    const spec = inputSpec(ctx, resp, "SCN-ABSORPTION-UNITS-PER-YEAR", "Home absorption per year");
    return `<p class="tl-note">About ${num(reg, nFix(a.absorption_per_month, 1) + " " + (a.unit_label === "units" || !a.unit_label ? "homes" : a.unit_label) + " a month", spec)} (${esc(int(a.absorption_per_month * 12))} a year) for ${esc(int(a.target_quantity))} ${esc(a.unit_label === "units" || !a.unit_label ? "homes" : a.unit_label)}: ${isNum(a.stabilization_year) ? `all absorbed by year ${esc(a.stabilization_year)} (month ${esc(a.stabilization_month)}).` : esc(a.why || "not all absorbed within the horizon.")}</p>
      ${P.chart("line", { x: a.yearly.map((y) => "Year " + y.year), series: [{ name: "Absorbed by the end of the year", values: a.yearly.map((y) => y.end_cumulative) }], unit: "units", title: "Homes absorbed, cumulative by year" })}
      ${fold("sc-abs", "Show year by year", smallTable([{ label: "Year" }, { label: "Absorbed in the year", num: true }, { label: "By the end of the year", num: true }, { label: "Average occupancy", num: true }],
        a.yearly.map((y) => [esc("Year " + y.year), esc(int(y.absorbed_in_year)), esc(int(y.end_cumulative)), esc(pct(y.average_occupancy_pct, 0))]), "Absorption by year"), P.openFolds)}
      <p class="fine">${esc((a.formula || []).join(" "))}</p>`;
  };

  // ---- part 5: phase triggers
  const trigPart = () => {
    const list = r.phase_triggers || [];
    const words = (entities(ctx).phases || []).filter((p) => p.triggers);
    if (!list.length && !words.length) return calmBox("No phase triggers in the package", "");
    const fmtV = (m, v) => (!isNum(v) ? NK : /pct/.test(m) ? pct(v, 0) : int(v));
    const blocks = list.map((p) => {
      const items = (p.triggers || []).map((t) => {
        const need = `${METRIC_WORDS[t.metric] || t.metric.replace(/_/g, " ")} ${OP_WORDS[t.operator] || t.operator} ${fmtV(t.metric, t.threshold)}`;
        const has = t.state === "unknown" ? "not known yet" : `${fmtV(t.metric, t.value)}${t.state === "not_met" && isNum(t.gap) ? `, ${fmtV(t.metric, t.gap)} short` : ""}`;
        return `<li><span class="tl-state ${esc(t.state)}">${t.state === "met" ? "Met" : t.state === "not_met" ? "Not met" : "Not known"}</span><span><b>${esc(t.label || t.id)}</b><small>Needs ${esc(need)}; ${t.state === "unknown" ? "" : "has "}${esc(has)}${t.why && t.state === "unknown" ? ". " + esc(t.why) : ""}</small></span></li>`;
      }).join("");
      const ph = (entities(ctx).phases || []).find((x) => String(x.id) === String(p.phase)) || {};
      return `<section class="tl-box"><h3>${esc(p.label || phaseLabel(ctx, p.phase))}${isNum(p.at_month) ? ` <small class="muted">checked at month ${esc(p.at_month)}</small>` : ""}</h3>
        <p class="tl-note">${esc(p.summary || "")}</p><ul class="tl-trig">${items}</ul>
        ${ph.triggers ? fold("sc-tw-" + p.phase, "What the documents say", `<p>${esc(ph.triggers)}</p>`, P.openFolds) : ""}</section>`;
    }).join("");
    const textOnly = words.filter((p) => !list.some((x) => String(x.phase) === String(p.id)));
    return `<p class="tl-note">Each phase starts when its triggers are met. A trigger with no figure behind it stays "not known"; it is never counted as met.</p>
      <div class="tl-grid2">${blocks}</div>
      ${textOnly.length ? `<h3 class="tl-sub">Triggers the documents describe in words only</h3><ul class="tl-mini">${textOnly.map((p) => `<li><b>${esc(p.label || p.id)}</b>: ${esc(p.triggers)}</li>`).join("")}</ul>` : ""}`;
  };

  const parts = () => [["program", "By phase", programPart()], ["cases", "Low, base, high", casesPart()], ["units", "Unit scenarios", unitsPart()], ["absorption", "Absorption", absorbPart()], ["triggers", "Phase triggers", trigPart()]];
  P.set({ lead, before, parts: parts(), after: disclaimerHtml(resp) });
  wireSegKeys(el);
  const redraw = () => { const node = el.querySelector('[data-part="program"]'); if (!node) return; const keep = node.querySelector(".dz-part-title"); P.swap(node, (keep ? keep.outerHTML : "") + programPart()); };
  el.addEventListener("change", (e) => { if (e.target.matches("[data-phase]")) { state.phase = e.target.value; redraw(); el.querySelector("[data-phase]").focus(); } });
  el.addEventListener("click", (e) => {
    const b = e.target.closest('[data-seg="kase"]');
    if (b) { state.kase = b.dataset.val; redraw(); const again = el.querySelector(`[data-seg="kase"][data-val="${b.dataset.val}"]`); if (again) again.focus(); }
  });
}

// Infrastructure and funding: the register by phase and payer (costs that are not known are counted, never added as
// zero), the owner's funding gap year by year against land-sale proceeds, and the fiscal impact (jobs, output, taxes,
// the EIFD-style increment) from the rates the package gives.
import {
  esc, isNum, nFix, fold, compute, page, leadHtml, missingHtml, hiddenHtml, isOutside, disclaimerHtml, calmBox, smallTable,
  num, usd, usdM, int, plural, noun, NK, phaseLabel, useLabel, guarded, loadingHtml, inputSpec,
} from "./common.js";

const PAYERS = [["owner", "Owner"], ["builder", "Builders"], ["city", "City"], ["district_financing", "District financing"], ["not_known", "Payer not known"]];
const PAYER_WORDS = Object.fromEntries(PAYERS);

export async function render(el, ctx) {
  el.innerHTML = loadingHtml("Adding up the infrastructure…");
  await guarded(el, ctx, async () => {
    const [fu, fi] = await Promise.all([compute(ctx, "funding"), compute(ctx, "fiscal").catch((e) => ({ failed: e, result: {}, missing: [] }))]);
    if (ctx.alive && !ctx.alive()) return;
    draw(el, ctx, fu, fi);
  });
}

function draw(el, ctx, fu, fi) {
  const P = page(el, ctx), reg = P.reg;
  P.resp = fu;
  const r = fu.result || {}, regi = r.register || {}, gap = r.funding_gap, outside = isOutside(fu);
  const items = regi.items || [], total = regi.total || {};
  const unknown = isNum(r.unknown_cost_items) ? r.unknown_cost_items : total.unknown_count || 0;
  const infraInputs = (fu.inputs_used || []).filter((x) => (x.field || "").startsWith("infrastructure/"));
  const regSpec = (label, value, more = []) => ({ label, value, how: [regi.formula || ""].concat(more), inputs: infraInputs });
  const noCost = (n) => (n === 1 ? "1 item has no cost yet" : `${n} items have no cost yet`);

  // ---- the answer
  let lead;
  if (!items.length) lead = leadHtml({ sentence: "The package has no infrastructure items yet." });
  else {
    const s = gap && gap.summary;
    let gapWords = "";
    if (s && isNum(s.peak_gap_usd)) gapWords = s.peak_gap_usd > 0 ? ` At its worst the owner is short ${num(reg, usdM(s.peak_gap_usd), { label: "Peak funding gap", value: usd(s.peak_gap_usd), how: gap.formula || [] })} (${esc(s.peak_gap_period)}) before land sales catch up${s.peak_gap_is_lower_bound ? ", and more once the missing costs are known" : ""}.` : " Land sales cover the owner's share in every year.";
    lead = leadHtml({
      sentence: `Infrastructure adds up to ${num(reg, usdM(total.known_usd), regSpec("Infrastructure, known cost", usd(total.known_usd)))} across ${plural(items.length, "item")}${unknown ? `, and <b>${esc(noCost(unknown))}</b>: the total is a floor, not the full cost` : ""}.${gapWords}`,
      big: usdM(total.known_usd), bigLabel: unknown ? `Known cost; ${noCost(unknown)}` : "Infrastructure, all items", bigSrc: reg.add(regSpec("Infrastructure, known cost", usd(total.known_usd))),
      aside: "A cost the package does not give is counted as not known. It is never added as zero.",
    });
  }
  const before = (outside ? hiddenHtml(fu) : "") + missingHtml(fu, { labelOf: (id) => useLabel(ctx, id), open: P.openFolds });

  // ---- part 1: the register by phase and payer
  const regPart = () => {
    if (!items.length) return calmBox("No infrastructure items yet", "");
    const phases = [...new Set(items.map((i) => String(i.phase ?? "")))];
    const payers = PAYERS.filter(([p]) => items.some((i) => (i.payer || "not_known") === p));
    const series = payers.map(([p, w]) => ({ name: w, values: phases.map((ph) => { const v = items.filter((i) => String(i.phase ?? "") === ph && (i.payer || "not_known") === p && isNum(i.cost_usd)).reduce((t, i) => t + i.cost_usd, 0); return v || null; }) }));
    const labels = phases.map((ph) => (ph ? phaseLabel(ctx, ph) : "Phase not given"));
    const byPayer = PAYERS.filter(([p]) => regi.by_payer && regi.by_payer[p] && regi.by_payer[p].item_count).map(([p, w]) => {
      const x = regi.by_payer[p];
      return [esc(w), esc(int(x.item_count)), num(reg, usd(x.known_usd), regSpec(`${w}, known cost`, usd(x.known_usd))), esc(x.unknown_count ? noCost(x.unknown_count) : "All known")];
    });
    const byPhase = Object.entries(regi.by_phase || {}).map(([ph, x]) => [esc(phaseLabel(ctx, ph)), esc(int(x.item_count)), num(reg, usd(x.known_usd), regSpec(`${phaseLabel(ctx, ph)}, known cost`, usd(x.known_usd))), esc(x.unknown_count ? noCost(x.unknown_count) : "All known")]);
    const list = items.map((i) => ({ cls: i.cost_known ? "" : "flag", cells: [
      `${esc(i.name || i.code)}<small>${esc(i.code || "")}${i.reimbursable ? " · paid back later" : ""}</small>`, esc(i.phase ? phaseLabel(ctx, i.phase) : "-"), esc(i.payer_label || PAYER_WORDS[i.payer] || NK),
      esc(isNum(i.due_period) ? String(i.due_period) : "-"),
      i.cost_known ? num(reg, usd(i.cost_usd), (() => { const row = (ctx.content.entities.infrastructure || []).find((x) => x.id === i.code); return row && row.assumption ? { label: i.name, value: usd(i.cost_usd), figure: row.assumption } : regSpec(i.name, usd(i.cost_usd), [i.note || ""]); })()) : '<span class="dz-chip gold">No cost yet</span>'] }));
    return `${unknown ? `<p class="tl-flag"><span><b>${esc(noCost(unknown))}.</b> ${unknown === 1 ? "It is" : "They are"} counted, not added as zero: every total below is what is known so far.</span></p>` : ""}
      ${(regi.items_with_unknown_payer || 0) ? `<p class="tl-note">${esc(int(regi.items_with_unknown_payer))} ${noun(regi.items_with_unknown_payer, "item does", "items do")} not say who pays; ${noun(regi.items_with_unknown_payer, "it is", "they are")} shown as "Payer not known".</p>` : ""}
      ${P.chart("stacked", { labels, series, unit: "usd", title: "Known cost by phase and payer (dollars)" })}
      <div class="tl-grid2">${smallTable([{ label: "Who pays" }, { label: "Items", num: true }, { label: "Known cost", num: true }, { label: "Not known" }], byPayer, "By payer")}
      ${smallTable([{ label: "Phase" }, { label: "Items", num: true }, { label: "Known cost", num: true }, { label: "Not known" }], byPhase, "By phase")}</div>
      ${fold("fu-items", items.length === 1 ? "Show the item" : `Show all ${items.length} items`, smallTable([{ label: "Item" }, { label: "Phase" }, { label: "Who pays" }, { label: "Due", num: true }, { label: "Cost", num: true }], list, "Infrastructure items"), P.openFolds)}`;
  };

  // ---- part 2: the funding gap against land sales
  const gapPart = () => {
    if (!gap || !(gap.rows || []).length) return outside ? "" : calmBox("The funding gap cannot be laid out yet", "It needs each owner-paid item's due year and the land-sale proceeds by year.");
    const rows = gap.rows, s = gap.summary || {};
    const x = rows.map((g) => String(g.period));
    const tbl = smallTable([{ label: gap.period_unit === "month" ? "Month" : "Year" }, { label: "Owner cost", num: true }, { label: "Costs not known" , num: true }, { label: "Land sales", num: true }, { label: "Other funding", num: true }, { label: "Gap to date", num: true }],
      rows.map((g) => ({ cls: g.cumulative_gap_usd > 0 ? "flag" : "", cells: [esc(String(g.period)), esc(usdM(g.owner_cost_known_usd)), esc(g.owner_items_unknown_cost ? String(g.owner_items_unknown_cost) : "-"), esc(usdM(g.land_sale_proceeds_usd)), esc(usdM(g.other_funding_usd)),
        `${esc(g.cumulative_gap_usd > 0 ? "Short " + usdM(g.cumulative_gap_usd) : "Covered, " + usdM(-g.cumulative_gap_usd) + " spare")}${g.gap_is_lower_bound ? "<small>at least: some costs not known</small>" : ""}`] })), "Funding gap by period");
    const others = Object.entries(gap.paid_by_others || {}).filter(([, v]) => v.item_count).map(([k, v]) => `${PAYER_WORDS[k] || k}: ${v.display}`);
    return `<p class="tl-note">${esc(s.headline || "")}. Land-sale proceeds are the net cash from the cash plan's sales.</p>
      ${P.chart("line", { x, series: [{ name: "Owner's infrastructure cost to date", values: rows.map((g) => g.cumulative_cost_known_usd) }, { name: "Cash in to date (land sales and other funding)", values: rows.map((g) => g.cumulative_funding_usd) }], unit: "usd", title: "Cost against cash in, to date (dollars)" })}
      ${s.owner_items_unknown_cost ? `<p class="tl-note">${esc(noCost(s.owner_items_unknown_cost))} among the owner's items, so the gap is at least what is shown.</p>` : ""}
      ${fold("fu-gap", "Show period by period", tbl, P.openFolds)}
      ${others.length ? `<p class="fine">Paid by others, not part of the owner's gap: ${esc(others.join("; "))}.</p>` : ""}`;
  };

  // ---- part 3: fiscal impact
  const fiscalPart = () => {
    if (fi.failed) return calmBox("The fiscal figures could not be worked out just now", esc(fi.failed.message || ""));
    const fr = fi.result || {}, imp = fr.impact, eifd = fr.eifd;
    const own = { ...fi, missing: (fi.missing || []).filter((m) => !(fu.missing || []).includes(m)) };
    const miss = missingHtml(own, { title: "What the fiscal figures still need", labelOf: (id) => useLabel(ctx, id), open: P.openFolds, intro: "Fiscal figures come only from rates the package gives; none is assumed." });
    if (!imp && !eifd) return miss || calmBox("No fiscal figures yet", "");
    let html = isOutside(fi) ? hiddenHtml(fi) : "";
    const fSpec = (label, value, more = []) => ({ label, value, how: ((imp && imp.formula) || []).concat(more), inputs: (fi.inputs_used || []).filter((x) => /^FISCAL|^EIFD/.test(x.assumption_id || "")) });
    if (imp) {
      const t = imp.totals || {};
      const card = (k, v, sub = "") => `<article class="tl-card"><span class="tl-card-k">${esc(k)}</span><span class="tl-card-v">${v}</span>${sub ? `<p>${esc(sub)}</p>` : ""}</article>`;
      html += `<div class="tl-cards">
        ${card("Jobs while building", num(reg, int(t.construction_job_years), fSpec("Construction job-years", int(t.construction_job_years))), "job-years")}
        ${card("Jobs once open", num(reg, int(t.permanent_jobs), fSpec("Permanent jobs", int(t.permanent_jobs))), "permanent jobs")}
        ${card("Economic output while building", num(reg, usdM(t.construction_output_usd), fSpec("Construction output", usd(t.construction_output_usd))))}
        ${card("Economic output, per year", num(reg, usdM(t.annual_operating_output_usd), fSpec("Operating output per year", usd(t.annual_operating_output_usd))))}
        ${card("Taxes to the city, per year", num(reg, usdM(t.annual_agency_revenue_usd), fSpec("City revenue per year", usd(t.annual_agency_revenue_usd))), "sales tax, the city's share of property tax and hotel tax")}
      </div>`;
      const ph = imp.phases || [];
      html += fold("fi-phases", "Show by phase", smallTable([{ label: "Phase" }, { label: "Job-years", num: true }, { label: "Jobs", num: true }, { label: "Sales tax / yr", num: true }, { label: "Property tax / yr", num: true }, { label: "City share / yr", num: true }, { label: "Hotel tax / yr", num: true }],
        ph.map((p) => [esc(p.label || phaseLabel(ctx, p.id))].concat([p.construction_job_years, p.permanent_jobs].map((v) => esc(isNum(v) ? int(v) : NK))).concat([p.sales_tax_usd_yr, p.property_tax_usd_yr, p.agency_property_tax_usd_yr, p.hotel_tax_usd_yr].map((v) => esc(usdM(v))))), "Fiscal impact by phase")
        + (ph.some((p) => (p.not_worked_out || []).length) ? `<ul class="tl-mini">${ph.filter((p) => (p.not_worked_out || []).length).map((p) => `<li>${esc(p.label || phaseLabel(ctx, p.id))}: not worked out: ${esc(p.not_worked_out.join("; "))}</li>`).join("")}</ul>` : ""), P.openFolds);
    }
    if (eifd && (eifd.yearly || []).length) {
      const a = eifd.assumptions || {};
      html += `<h3 class="tl-sub">Tax increment a district could capture</h3>
        <p class="tl-note">${num(reg, usdM(eifd.total_increment_usd), { label: "Tax increment over the years shown", value: usd(eifd.total_increment_usd), how: [eifd.formula || ""], inputs: (fi.inputs_used || []).filter((x) => /^EIFD|^FISCAL-PROPERTY/.test(x.assumption_id || "")) })} over ${esc(a.years)} years at a ${esc(nFix(a.participating_share_pct || 0, 0))}% participating share, values growing ${esc(nFix(a.assessed_growth_pct || 0, 1))}% a year. ${esc(eifd.disclaimer || "")}</p>
        ${P.chart("line", { x: eifd.yearly.map((y) => "Year " + y.year), series: [{ name: "Increment captured to date", values: eifd.yearly.map((y) => y.cumulative_usd) }], unit: "usd", title: "Tax increment, cumulative (dollars)" })}`;
    }
    return html + miss + `<p class="fine">${esc((imp && imp.disclaimer) || "")}</p>`;
  };

  P.set({ lead, before, parts: [["register", "Register", regPart()], ["gap", "Funding gap", gapPart()], ["fiscal", "Fiscal impact", fiscalPart()]], after: disclaimerHtml(fu) });
}

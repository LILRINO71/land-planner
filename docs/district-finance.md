# District finance engine

`landplanner/district/finance.py` is the calculation layer for land-development finance: what land is worth to a buyer for
a given use, what to ask for it, what the seller keeps, which parcels to sell to hit a cash target, what a phase of
development earns, and whether to sell, hold, joint-venture or ground-lease each parcel.

The work is in `finance_common.py`, `finance_uses.py`, `finance_land.py`, `finance_proforma.py`, `finance_scenarios.py`,
`finance_solver.py`, `finance_decision.py` and `finance_infra.py`. Import everything from `landplanner.district.finance`.
`finance.PUBLIC_FUNCTIONS` lists the public names; a test checks that each one is described below.

**It is an economic calculation, not an appraisal.** Nothing here is a market value opinion or a promise of a price, an
approval, a tenant, public funding or a return. Answers that name a price carry a `disclaimer` saying so.

## Rules every function follows

- Plain dicts and lists in, plain dicts and lists out. No file, no network, no clock, no random numbers: the same inputs
  always give the same answer.
- Key names carry units. `_usd` dollars, `_sf` square feet, `_ac` acres, `_pct` a percent (3.5 means 3.5%), `_mo` a month
  count or monthly amount, `_yr` a yearly amount. Rents say which they are: `rent_per_unit_mo` (dollars per unit per month),
  `rent_per_sf_yr` (dollars per SF per year; `rent_per_sf_mo` is accepted and multiplied by 12). A monthly figure is never
  treated as a yearly one without a conversion you can see.
- Nothing returns NaN or Infinity. A number that cannot be worked out is `None` and the answer has a `why` sentence.
  Zero, negative, missing and absurdly large inputs do not raise; a number too large to work with gives `{"failed": true, "why": ...}`.
- An unknown stays unknown. A cost, a deduction or a component that is `None` is listed, counted and reported as "not
  known"; totals say how many items they could not include (`unknown_count`, `cost_unknown_items`, `unknown_deductions`,
  `*_is_lower_bound`, `*_is_partial`). It is never added as zero.
- Every answer repeats the key assumptions it used (`assumptions`) and the working (`formula`: a sentence or a list of
  steps) so a screen can show how a number was reached.
- Dollars are rounded to cents and percents to four decimals on the way out; the arithmetic inside is not rounded.
- The default rates below are starting points, not facts about any place. Pass your own.

## The shapes the functions share

**Land use library**: `{use_id: use}`. Nothing about a project is built into the code; every use comes from the library.

```
{"label": "Apartments",
 "density": {"units_per_net_ac": 20, "sf_per_unit": 1000},        # or {"far": 0.25} (building SF per SF of land)
 "revenue": {"type": "rent_per_unit_mo", "rent_per_unit_mo": 2000, "vacancy_pct": 5, "other_income_pct": 0,
             "opex_pct_of_income": 35},
 "cost_line_items": {"site_work": 100000, "building_shell": 200, "hard_contingency": 5},
 "sales_cost_pct": 0, "cap_rate_pct": 5, "exit_cap_pct": 5, "required_return_pct": 15}
```

Revenue types: `per_unit_sale` (`price_per_unit`), `per_sf_sale` (`price_per_sf`), `rent_per_unit_mo`, `rent_per_sf_yr`
(plus `efficiency_pct`, default 100), `room_revenue` (`adr` in dollars per night, `occupancy_pct`, `other_income_pct`).
Income uses need `cap_rate_pct` above zero. `exit_cap_pct` (optional) overrides the cap rate for the sale at the end of a pro forma.

**Cost line items**: a list `[{id, label, category, basis, amount}]` or a mapping `{id: amount}`. Bases:
`per_unit` (dollars per unit or key), `per_building_sf`, `per_net_ac`, `lump_sum`, `pct_of_hard` (percent of the direct hard
items), `pct_of_prior` (percent of every item listed above it). An item whose amount is `None`, or whose quantity is not
known, is "not known". `default_cost_line_items()` gives the default list of 15 to fill in.

**Phase**: `{id, label, land_cost_usd, start_offset_years, lines: [{use, net_ac | units | building_sf, land_cost_usd,
start_offset_years, build_years, spend_curve_pct, lease_up_months, absorption_per_month, sellout_months, hold_years,
noi_growth_pct}]}`. The phase's land cost is split over its lines by net acres.

**Pro forma assumptions**: `{base_year, discount_rate_pct (10), hold_years (10), build_years (2), lease_up_months (24),
sellout_months (24), noi_growth_pct (0), hurdle_yoc_pct, hurdle_irr_pct}`. A line's own setting beats the phase's, which beats these.

**Scenario adjustment**: `{revenue_pct, revenue_factor_by_type, cost_pct, cap_rate_delta_pct, cap_rate_set_pct,
required_return_delta_pct, density_pct, target_units: {total, use_ids}, quantity_factor_by_use}`. Percent keys are plus or minus
percent; `*_delta_pct` are percentage points.

## 1. Residual land value

### `residual_land_value_by_use(library, net_to_gross_pct=100.0, scenarios=None, net_ac=1.0)`
Residual land value of every use in the library for `net_ac` net acres, under each scenario (default `low`, `base`, `high`;
see `finance_land.DEFAULT_SCENARIOS`, which you can replace with any `{name: adjustment}`).
- Inputs: library; `net_to_gross_pct` (percent of gross acres that are net acres); scenarios; net acres to price.
- Outputs: `uses` (per use and scenario: units, building SF, value on completion, NOI per year, development cost, required
  profit, `rlv_usd`, `rlv_per_net_ac_usd`, `rlv_per_net_sf_usd`, `rlv_per_gross_ac_usd`, yield on cost, `feasible_now`, `why`),
  `ranking` (uses by base residual per net acre), assumptions, formula, disclaimer.
- Formula: value on completion = net sale revenue (sale uses) or NOI / cap rate less selling cost (income uses). Residual =
  value on completion / (1 + required return) - development cost (land excluded). Per net SF = per net acre / 43,560;
  per gross acre = per net acre x net-to-gross.

### `residual_land_value_by_parcel(parcels, library, scenarios=None)`
Residual for each parcel under each candidate use and scenario.
- Inputs: parcels `[{id, name, gross_ac, net_ac | net_to_gross_pct, candidate_uses, use}]`; library; scenarios.
- Outputs: per parcel the residual (total, per gross acre, per net acre, per net SF) for every candidate use and scenario,
  `best_use` (highest base residual), `assigned_use`, `totalled_use`; `totals_usd` per scenario (the assigned use, else the best
  use); `parcels_not_priced`.

### `check_land_use_library(library)`
Lists what is missing from a library (revenue type, cost items, cap rate) before any calculation. Outputs `ok`, `issues`.

### `default_cost_line_items()`
The default 15 cost line items with their basis and category and amount `None`.

## 2. Four pricing tiers

### `pricing_tiers(parcel, rlv_base_usd=None, rlv_high_usd=None, sponsor_hurdle_pct=20.0, strategic_premium_pct=0.0, strategic_premium_usd=None, score_premium=None, target_pct_of_rlv=100.0, upside_pct=15.0, target_price_usd=None, upside_price_usd=None)`
- Inputs: parcel `{id, gross_ac, net_ac, cost_items {name: dollars | None} | cost_basis_usd, strategic_score}`; base and high
  residual of the parcel; sponsor hurdle (percent on cost); a strategic premium as a percent of cost or a flat dollar amount, or
  rising with the strategic score (`score_premium {threshold, pct_per_point}`); target as a percent of the base residual or an
  explicit price; upside as the high residual, an explicit price, or target plus a percent.
- Outputs: `tiers`: `economic_cost_floor`, `minimum_recommended`, `target_market`, `upside_stretch`, each with total price, per
  gross acre, per net acre, per net SF and its source; `tiers_in_order`; `headroom_target_over_minimum_usd`; unknown cost items
  (the floor is then a lower bound); `notes` (for example when the target is below the minimum).
- Formula: cost floor = sum of the parcel's cost items. Minimum = floor x (1 + hurdle) + strategic premium. Target = base
  residual x target percent. Upside = high residual (or target x (1 + upside percent)).

## 3. Gross-to-net waterfall

### `gross_to_net_waterfall(gross_price_usd, net_ac=None, seller_note_usd=0.0, debt_release_usd=0.0, brokerage_pct=3.5, closing_cost_pct=0.75, transfer_tax_pct=0.11, recording_fee_usd=0.0, stub_per_net_ac_usd=0.0, infrastructure_stubs=None, other_deductions=None)`
- Inputs: price; net acres; seller note and debt release paid from proceeds; brokerage, closing and county transfer tax as
  percent of the price (defaults 3.5, 0.75, 0.11); a flat recording fee (default 0: enter your county's); parcel stub per net
  acre and/or a list of stubs `[{name, amount_usd}]` where `None` means the cost is not known; other deductions.
- Outputs: `deductions` (id, label, basis, `amount_usd`, `pct_of_gross`), `total_deductions_usd`, `net_cash_proceeds_usd`,
  `net_per_net_ac_usd`, `transaction_cost_pct`, `unknown_deductions`, `net_proceeds_is_upper_bound`, a summary sentence.
- Formula: net = price - (price x each percent rate) - each flat amount - stub per acre x acres. An unknown deduction is
  listed and counted; the net is then an upper bound.

### `waterfall_for_parcels(parcels, brokerage_pct=3.5, closing_cost_pct=0.75, transfer_tax_pct=0.11, recording_fee_usd=0.0, stub_per_net_ac_usd=0.0)`
The waterfall for each parcel `{id, gross_price_usd, net_ac, seller_note_usd, debt_release_usd, stub_per_net_ac_usd,
infrastructure_stubs}` and the totals (gross, deductions, net, unknown count).

## 4. Capital target solver

### `solve_capital_targets(parcels, targets, strategies=("max_cash", "balanced", "max_retention"), targets_are_cumulative=True, brokerage_pct=3.5, closing_cost_pct=0.75, transfer_tax_pct=0.11, recording_fee_usd=0.0, default_strategic_score=50.0, critical_threshold=75.0, balanced_cash_weight=0.5)`
Chooses what to sell to reach one or more cash targets.
- Inputs: parcels `{id, name, net_ac, net_proceeds_usd | gross_price_usd (run through the waterfall), strategic_score 0-100,
  close_month (month the cash arrives), must_keep, critical, do_not_sell_until_month}`; targets `[{month, amount_usd}]`
  (cumulative by that month, or per-period if `targets_are_cumulative` is false); the strategies to run.
- Rules: max cash ranks parcels by net cash per acre (fewest acres sold); max strategic retention ranks by lowest strategic
  score first and never sells a critical (score at or above the threshold, or flagged) or must-keep parcel; balanced ranks by
  a weighted blend (`balanced_cash_weight` of cash per acre, the rest of low strategic score). Must-keep parcels are never sold.
- Method: for each target in month order, sell down the ranking among parcels that close by that month until the cumulative
  cash reaches the target; then drop any sale that is not needed. A greedy ranking with pruning, not a proof of the optimum.
- Outputs per strategy: `picks`, `proceeds_by_period` (target, cumulative target, closed in period, cumulative closed,
  `shortfall_usd`, `surplus_usd`, `met`), `total_net_proceeds_usd`, `acres_sold`, `retained` (acres, parcel ids, value at price,
  acre-weighted strategic score), `critical_asset_conflicts`, `critical_parcels_that_would_close_the_gap`, `all_targets_met`.

## 5. Phase pro forma

### `phase_pro_forma(phase, library, assumptions=None)`
- Inputs: a phase (shape above), the library, pro forma assumptions.
- Outputs: `lines` (program, cost, NOI, value, net sales per line), `totals` (development cost, land, stabilised NOI, implied
  value, net sales revenue, development margin, `cost_unknown_items`), `yield_on_cost` (`yoc_pct`, `yoc_excl_land_pct`,
  hurdle, `spread_pct_points`, `spread_bps`, `meets_hurdle`), `irr` (`irr_pct`, `converged`, `method`, `iterations`,
  `residual_npv_usd`, `sign_changes`, `why`, spread against the IRR hurdle), `equity_multiple`, `npv`, `cash_flows` (one row
  per year: land, construction, NOI, net sales, exit sale, net), assumptions, formula, disclaimer.
- Formula: development cost = sum of the use's cost line items, spent over the build years on the spend curve. NOI = effective
  income x (1 - operating expense share) at stabilisation, reached along the lease-up (absorption) schedule. Implied value = NOI /
  exit cap x (1 - selling cost). Sale uses book net sales as units close. Yield on cost = stabilised NOI / (development cost +
  land); spread = yield on cost - hurdle. The model is unlevered and annual, money at year end.

### `full_buildout_pro_forma(phases, library, assumptions=None)`
Every phase (1-4) and the full buildout: each phase as above, shifted by its `start_offset_years` and added year by year. Outputs
`phases` and `full_buildout` (totals, yield on cost against the hurdle, IRR, equity multiple, NPV, dated cash flows).

### `cash_flow_metrics(flows, discount_rate_pct=10.0, base_year=None)`
Return measures of one stream of yearly flows (negative is money out). Outputs `irr` (Newton-Raphson from 10%, then a grid scan
and bisection if Newton does not settle; `converged`, `method`, `sign_changes`, `why`), `npv_usd`, `equity_multiple`, totals in
and out, peak cumulative outflow, payback year index, dated flows. NPV = sum of flow / (1 + rate)^year; equity multiple = money
back / money put in.

## 6. Break-even

### `break_even(phase, library, assumptions, variable, metric=None, target_pct=None, lower=None, upper=None)`
The value of one driver at which the phase (or a list of phases) just meets its hurdle.
- `variable`: `apartment_rent` ($ per unit per month), `retail_nnn_rent` ($ per SF per year), `hotel_adr` ($ per night),
  `for_sale_price`, `exit_cap_rate` (percent). `metric` is `yoc` (default for rents and ADR) or `irr` (default for sale price
  and exit cap); the target is `hurdle_yoc_pct` or `hurdle_irr_pct` from the assumptions unless `target_pct` is given.
- Outputs: `breakeven_value` (when one use sets the driver), `by_use` (current and break-even per use), `breakeven_factor`
  (multiple of today's value; all uses of that kind move together), the metric today and at break-even, `already_met_today`,
  `converged`, `why`. If the hurdle cannot be reached inside the search range it says so instead of returning a number.
- Method: re-run the pro forma with the driver scaled (or the exit cap set), scan for where the hurdle is first met, then bisect.

## 7. Hold, sell, joint venture or ground lease

### `default_strategic_dimensions()` and `default_economic_criteria()`
The 12 default strategic dimensions (equal weights) and the 9 default weighted economic criteria. Both are starting points: pass
your own weights.

### `score_strategic_dimensions(scores, weights=None, dimensions=None)`
A parcel's strategic score: sum(score x weight) / sum(weight) over the dimensions that have a score (each held to 0-100).
Unscored dimensions are listed in `dimensions_missing`; if none is scored the score is `None`.

### `compare_strategies(parcel, assumptions=None, criteria_weights=None, strategy_profiles=None)`
Fee-simple sale, hold and develop, institutional joint venture (land contributed as equity) and a 65-99 year NNN ground lease
for one parcel.
- Inputs: parcel `{id, net_ac, land_value_usd, appreciation_pct, sale {sale_year, sale_cost_pct}, carry_cost_usd_per_year,
  develop {total_cost_usd, stabilized_noi_usd, start_year, build_years, lease_up_years, exit_cap_pct, noi_growth_pct},
  jv {cash_out_pct, project_cost_usd, stabilized_noi_usd, exit_cap_pct}, ground_lease {rent_yield_pct, escalation_pct | bump_pct +
  bump_years, key_money_pct, term_years, start_year, leased_fee_cap_pct, include_terminal_value}}`; assumptions `{discount_rate_pct
  (8), horizons_years (10, 15), appreciation_pct (3), sale_cost_pct (4.36)}`; criteria weights; strategy profiles (execution risk
  score, control kept, upside kept; starting values in `finance_decision.DEFAULT_PROFILES`).
- Outputs per strategy: NPV for each horizon, cash in the first 12 months, capital the owner must put in, recurring income per
  year, months to first cash, the nine criterion scores (0-100, best strategy = 100), the weighted `economic_score`, a `basis`
  sentence, `notes`, and `available`/`why` (a strategy without its inputs is unavailable, not zero). `ranking_by_npv`.
- Formula: sale = price grown at the appreciation rate, less selling cost, discounted. Develop = -construction cost, + NOI after
  lease-up, + sale of the finished asset at the horizon (the land itself is not charged). JV = cash taken at close + the land's
  share of NOI and sale; share = land credit / (land credit + project cost); unlevered, before any promote. Ground lease = key
  money + rent (land value x yield, escalated) + the leased fee sold at the horizon (at the leased-fee cap rate, default equal to
  the rent yield). NPV = sum of flow / (1 + discount rate)^year to each horizon; sale proceeds are not reinvested.

### `decide_parcels(parcels, assumptions=None, criteria_weights=None, dimension_weights=None, strategy_profiles=None, sell_ids=None)`
The decision for each parcel: strategic score (from `strategic_score` or the 12 `strategic_scores`), the four strategies compared,
a combined score for each, `recommended_strategy`, `guarded_recommendation` (never a sale for a critical asset), and conflicts.
- Formula: combined = (1 - k) x economic score + k x (strategic score x control kept + (100 - strategic score) x (1 - control
  kept)), k = `strategic_influence` (default 0.3). A parcel scored high is rewarded for keeping control; one scored low for selling.

### `critical_asset_conflicts(parcels, sell_ids=None, assumptions=None, recommendations=None)`
Flags a **critical strategic asset** (flagged `critical` or `must_keep`, or a strategic score at or above `critical_threshold`,
default 75) that a cash plan sells (`cash_plan_sells_critical_asset`) or that the economics recommend selling
(`recommendation_is_sale`), and any parcel planned for sale before its `do_not_sell_until_month` (`sold_inside_hold_period`).

## 8. Absorption, lease-up and phasing triggers

### `absorption_schedule(quantity, absorption_per_month=None, absorption_per_year=None, start_month=1, stabilized_occupancy_pct=100.0, pre_leased_pct=0.0, deliveries=None, horizon_months=120, unit_label="units", include_monthly=True)`
Lease-up or sales absorption by month and by year. Give the rate per month **or** per year, not both. Outputs `monthly`
(delivered, absorbed in the month, cumulative, occupancy), `yearly` (absorbed in the year, end cumulative, average occupancy),
`stabilization_month`, `stabilization_year` (`None` and a `why` if not reached in the horizon), `target_quantity`.
Each month: cumulative = min(delivered x stabilised occupancy, previous cumulative + monthly rate); pre-leased quantity is in
place before the first month.

### `schedule_status_at_month(schedule, month, pre_leased_pct=0.0)`
The trigger metrics of a schedule at a month: `units_delivered`, `units_absorbed`, `occupancy_pct`, `pre_leasing_pct`,
`absorption_per_month` (average of the last six months).

### `evaluate_phasing_triggers(triggers, status)`
Triggers `[{id, label, metric, operator (>=, >, <=, <, ==), threshold}]` against a status `{metric: value}`. Each is `met`,
`not_met` or `unknown` (no value: "not known"), with the gap; `all_met` is true only if every one is met.

## 9. Scenarios and sensitivity

### `run_scenarios(inputs, scenarios=None, base_name=None, evaluate=None)`
The same inputs under several scenarios (default low, base, high). `inputs` is `{library, parcels, phases, assumptions}`.
Outputs `scenarios` (adjustments and metrics), `table` (`{metric: {scenario: value}}`), `vs_base` (difference from the base).
`evaluate` can be your own function `inputs -> {metric: number}`; the default is `evaluate_program`.

### `evaluate_program(inputs)`
Flat headline metrics of one set of inputs: `rlv_total_usd`, `units_total`, `development_cost_usd`, `total_cost_incl_land_usd`,
`stabilized_noi_usd_yr`, `implied_value_usd`, `net_sales_revenue_usd`, `yoc_pct`, `irr_pct`, `equity_multiple`, `npv_usd`.

### `unit_count_scenarios(totals=(1500, 2000, 2500), use_ids=None)`
Named scenarios that scale the program lines so the chosen uses hold N units in all (for example `"2000_units"`).

### `sensitivity_tornado(inputs, variables=None, metric=None, evaluate=None)`
One-at-a-time sensitivity. Each variable (default: density +/-10%, rents +/-10%, costs +/-10%, required return +/-2 points, cap rate
+/-0.5 points) is moved alone to its low and high setting and the metric re-run. Outputs `base_value` and `rows` sorted by swing,
largest first: `rank`, `id`, `label`, `metric_at_low`, `metric_at_high`, `change_at_low`, `change_at_high`, `swing` (the absolute
difference between the two ends), ready to draw as a tornado chart.

## 10. Retained land over time

### `retained_land_value(base_value_usd, appreciation_pct, placemaking_lift_pct=0.0, lift_year=1, years=15, milestones=(5, 10, 15), acres=None)`
Value in year t = base x (1 + appreciation)^t, times (1 + lift) from the lift year on. Land value only, no rent. Outputs
`yearly` rows, `milestones` (value, gain, implied growth per year), `value_at_end_usd`.

### `retained_land_value_scenarios(scenarios, milestones=(5, 10, 15))`
`retained_land_value` for named scenarios `{name: {base_value_usd, appreciation_pct, placemaking_lift_pct, lift_year, acres}}`,
side by side (`table` by milestone year).

### `paced_land_releases(retained_acres, value_per_ac_today_usd, release_acres, every_years, years=15, appreciation_pct=0.0, placemaking_lift_pct=0.0, lift_year=1, first_release_year=1, min_core_acres=0.0, sale_cost_pct=4.36)`
Sells retained land in tranches (for example 5 acres every 2 years). Price per acre in year t = today's value per acre x
(1 + appreciation)^t (x (1 + lift) from the lift year); acres sold = min(release, acres left - core floor); net = gross x
(1 - sale cost). Outputs `events`, total net proceeds, acres and value left at the end, total wealth (net proceeds + value left,
undiscounted), `floor_reached_year`, `sold_out_year`.

### `compare_release_cadences(cadences, retained_acres, value_per_ac_today_usd, **kwargs)`
`paced_land_releases` for several cadences `[{name, release_acres, every_years}]` side by side, with the cadence that leaves the most
total wealth. `kwargs` are the other inputs of `paced_land_releases`.

## 11. Infrastructure funding

### `infrastructure_register(items, period_unit="month")`
Items `[{code, name, phase, cost_usd (None = not known), responsible (owner, builder, city, district_financing), due_period,
reimbursable, note}]`. An unrecognised or missing payer is "not known". Outputs `items`, `total`, `by_payer`, `by_phase`; every
total is `{known_usd, unknown_count, item_count, complete, display}` and the display text says "$X known; N items not known".

### `infrastructure_funding_gap(items, periods, land_sale_proceeds=None, other_funding=None, period_unit="month")`
The gap period by period between the owner's infrastructure costs and the cash that arrives to pay for them. `periods` are the
ends of periods (months or years); land sale proceeds are a `{period: dollars}` map or a list aligned with the periods; other
funding `[{period, amount_usd, source}]` (bonds, fee credits, builder cost-sharing). An owner item falls in the first period that
ends on or after its due period. Per period: owner cost (known), owner items whose cost is not known, funding, cumulative gap
(positive = shortfall) and `gap_is_lower_bound`. Summary: peak gap and its period, items after the horizon, undated items, items
with an unknown payer. Items another party pays are shown (`paid_by_others`) but are not the owner's gap.

## 12. Fiscal and economic impact (optional)

### `fiscal_impact(phases, rates)`
By phase, from rates you supply (none is assumed). Phase `{id, construction_cost_usd, permanent_jobs | building_sf_by_use,
taxable_sales_usd_yr, hotel_room_revenue_usd_yr, assessed_value_usd}`; rates `{construction_jobs_per_million_usd,
jobs_per_1000_sf_by_use, construction_output_multiplier, operating_output_multiplier, sales_tax_rate_pct, property_tax_rate_pct,
city_property_tax_share_pct, hotel_tax_pct}`. Construction job-years = cost / $1 million x jobs per million; permanent jobs =
SF / 1,000 x jobs per 1,000 SF; output = cost (or taxable sales + room revenue) x multiplier; sales tax = taxable sales x rate;
property tax = assessed value x rate, the agency's part x its share; hotel tax = room revenue x rate. A figure whose input or rate
is missing is `None` and listed in `not_worked_out`.

### `eifd_increment(phases, property_tax_rate_pct, participating_share_pct, years=30, assessed_growth_pct=2.0, discount_rate_pct=None)`
Property-tax increment an EIFD-style district could capture, by phase and year. Phase `{id, assessed_value_usd,
base_assessed_value_usd (default 0), delivery_year}`. Increment in year t = (assessed value in t - base) x tax rate x participating
share, with value growing from the delivery year. Outputs `by_phase`, `yearly` (with cumulative), `total_increment_usd`,
`present_value_usd` (only with a discount rate). An illustration of the increment, not a bond sizing.

## 13. Program reconciliation

### `reconcile_program(headline, components, tolerance_abs=None, tolerance_pct=None, label="total")`
Checks a headline total against the lines that should add up to it. Components are numbers or `{label, value}`; a missing value
is counted, not treated as zero. Outputs `components_sum`, `difference` (headline - sum), `difference_pct`, `within_tolerance`
(true or false; `None` when a component is not known, because it cannot be confirmed), `missing_components`, an `explanation` sentence.
Within tolerance means the difference is inside `tolerance_abs` or inside `tolerance_pct` percent of the headline.

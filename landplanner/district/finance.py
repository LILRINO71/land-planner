"""The land-development finance engine for the district tools: one place to import every public calculation from.

Pure functions only: plain dicts and lists in, plain dicts and lists out, no file or network access. The work lives in the
finance_*.py files next to this one; this file re-exports the public functions and lists them in PUBLIC_FUNCTIONS.
Every function is described, with its inputs, outputs and formula in plain words, in docs/district-finance.md.

All results are economic calculations under the caller's assumptions. They are not appraisals or market value opinions.
"""
from .finance_common import DISCLAIMER, PUBLIC, SF_PER_AC  # noqa: F401
from .finance_decision import (compare_strategies, critical_asset_conflicts, decide_parcels, default_economic_criteria,  # noqa: F401
                               default_strategic_dimensions, score_strategic_dimensions)
from .finance_infra import eifd_increment, fiscal_impact, infrastructure_funding_gap, infrastructure_register  # noqa: F401
from .finance_land import (gross_to_net_waterfall, pricing_tiers, residual_land_value_by_parcel, residual_land_value_by_use,  # noqa: F401
                           waterfall_for_parcels)
from .finance_proforma import (absorption_schedule, cash_flow_metrics, evaluate_phasing_triggers, full_buildout_pro_forma,  # noqa: F401
                               phase_pro_forma, schedule_status_at_month)
from .finance_scenarios import break_even, evaluate_program, run_scenarios, sensitivity_tornado, unit_count_scenarios  # noqa: F401
from .finance_solver import (compare_release_cadences, paced_land_releases, reconcile_program, retained_land_value,  # noqa: F401
                             retained_land_value_scenarios, solve_capital_targets)
from .finance_uses import check_land_use_library, default_cost_line_items  # noqa: F401

PUBLIC_FUNCTIONS = tuple(sorted(PUBLIC))

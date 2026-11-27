"""The district project's data schema: every entity, its fields, their types and units, and the tags that decide
which audience may see a field. Everything else in landplanner/district reads this one table: validation, the import
templates and data dictionary, the comparison, the audience filter and the documented contract
(docs/district-data-contract.md has the same tables, made by `markdown()`; a test keeps them equal).

A field is a dict:
    type      text | number | integer | bool | date | choice | list | refs | json
    unit      a code from UNITS (numbers), or None
    required  True when a row without it is rejected
    min, max  inclusive range for numbers
    choices   the allowed values for a choice (stored in the case written here)
    tags      sensitivity tags (see TAGS); an audience whose deny-list holds a tag never receives the field
    desc      what it is, in plain words
"""

# ---------------------------------------------------------------- vocabularies

STATUSES = ("Baseline", "Consultant", "Legacy Assumption", "Superseded")

PROVENANCE = (
    "VERIFIED PROJECT FACT",
    "CURRENT OWNERSHIP INPUT",
    "CONSULTANT INPUT",
    "ESRI / ARCGIS DATA",
    "OWNERSHIP ASSUMPTION",
    "MARKET ASSUMPTION",
    "CALCULATED",
    "REQUIRES VALIDATION",
    "HISTORICAL / SUPERSEDED",
)

CONFIDENCE = ("high", "medium", "low")

UNITS = {
    "sf": "square feet",
    "acres": "acres",
    "units": "dwelling units",
    "keys": "hotel keys",
    "usd": "US dollars",
    "usd_per_yr": "US dollars per year",
    "usd_per_sf_yr": "US dollars per square foot per year",
    "usd_per_sf_mo": "US dollars per square foot per month",
    "usd_per_sf": "US dollars per square foot",
    "usd_per_acre": "US dollars per acre",
    "usd_per_unit": "US dollars per unit",
    "usd_per_unit_mo": "US dollars per unit per month",
    "usd_per_night": "US dollars per room night",
    "pct": "percent (0-100)",
    "ratio": "a plain ratio (1.5 = one and a half times)",
    "people": "people",
    "households": "households",
    "jobs": "jobs",
    "count": "a count",
    "years": "years",
    "months": "months",
    "sf_per_yr": "square feet per year",
    "units_per_yr": "units per year",
    "miles": "miles",
    "text": "words, not a number",
}

TAGS = {
    "returns": "returns, IRR, yield, yield on cost, return on cost, equity multiple",
    "rlv_parcel": "residual land value of a parcel",
    "price_floor": "price floors",
    "disposition": "disposition pricing and terms (target, minimum and stretch prices, buyer terms)",
}

AUDIENCES = ("internal", "consultant", "partner", "city")

# what each audience must never receive (FR-61). Driven by the tags above, nowhere else.
AUDIENCE_DENY = {
    "internal": frozenset(),
    "consultant": frozenset(),
    "partner": frozenset(),
    "city": frozenset({"returns", "rlv_parcel", "price_floor", "disposition"}),
}

# Free-form figures (site facts, GIS properties, computed results from other modules) have no schema. Their keys are
# read as words: a key holding one of these words, or one of these phrases, carries the tag.
SENSITIVE_KEY_WORDS = {
    "irr": "returns", "yoc": "returns", "npv": "returns", "roc": "returns", "returns": "returns",
    "rlv": "rlv_parcel", "disposition": "disposition",
}
SENSITIVE_KEY_PHRASES = {
    "yield": "returns", "return_on_cost": "returns", "equity_multiple": "returns", "cash_on_cash": "returns",
    "residual_land_value": "rlv_parcel", "price_floor": "price_floor", "floor_price": "price_floor",
    "cost_floor": "price_floor", "target_price": "disposition", "stretch_price": "disposition",
    "disposition_price": "disposition", "minimum_price": "disposition", "min_price": "disposition",
    "proceeds": "disposition", "pricing_tier": "disposition", "tiers": "disposition", "minimum_recommended": "disposition",
    "target_market": "disposition", "upside_stretch": "disposition", "gross_price": "disposition",
    "land_value": "disposition", "break_even": "returns", "breakeven": "returns", "hurdle": "returns",
    "spread": "returns", "sponsor": "price_floor", "required_return": "returns", "margin": "returns",
    # value - cost - required profit is the residual land value, and required profit / value gives the return
    "required_profit": "returns", "developer_profit": "returns", "profit_margin": "returns",
}
# Records whose own words (id, label, heading, metric, body) name one of these are kept from an audience that denies
# the tag even when nobody tagged them: the city view fails closed. An administrator can set city_safe on a record.
SENSITIVE_WORDS = {
    r"\birr\b": "returns", r"\byield\b": "returns", r"\byoc\b": "returns", r"return on cost": "returns",
    r"equity multiple": "returns", r"\bnpv\b": "returns", r"\breturns?\b": "returns",
    r"residual land value": "rlv_parcel", r"\brlv\b": "rlv_parcel",
    r"price floors?": "price_floor", r"floor price": "price_floor",
    r"\bdisposition\b": "disposition", r"target price": "disposition", r"stretch price": "disposition",
}


def F(type_, unit=None, required=False, desc="", **more):
    return {"type": type_, "unit": unit, "required": required, "desc": desc, **more}


_COMMON_TAIL = {
    "tags": F("list", desc="sensitivity tags for the whole row (returns, rlv_parcel, price_floor, disposition)"),
    "city_safe": F("bool", desc="an administrator's word that this row may go to the city view although its words "
                                "sound sensitive"),
    "note": F("text", desc="a short note"),
}

# ---------------------------------------------------------------- the entities

ENTITIES = {
    "uses": {
        "label": "Use", "natural_key": ("use_group", "category", "typology"),
        "fields": {
            "id": F("text", required=True, desc="short id, for example retail-grocery"),
            "label": F("text", desc="the name shown on screens"),
            "use_group": F("text", required=True, desc="residential, retail, hospitality, office, civic, open space, ..."),
            "category": F("text", required=True, desc="the category inside the group (Grocery, Townhomes, ...)"),
            "typology": F("text", desc="the building form (pad, inline, podium, garden, ...)"),
        },
    },
    "phases": {
        "label": "Phase", "natural_key": ("label",),
        "fields": {
            "id": F("text", required=True, desc="1, 2, 3 or full"),
            "label": F("text", required=True, desc="the name shown on screens"),
            "order": F("integer", min=0, max=99, desc="sort order"),
            "start_year": F("integer", min=1900, max=2200, desc="first year of the phase"),
            "end_year": F("integer", min=1900, max=2200, desc="last year of the phase"),
            "residential_units_trigger": F("integer", "units", min=0, desc="homes delivered before this phase starts"),
            "preleasing_pct_trigger": F("number", "pct", min=0, max=100, desc="pre-leasing needed before it starts"),
            "absorption_note": F("text", desc="what absorption the phase depends on"),
            "triggers": F("text", desc="the other triggers and dependencies, in words"),
            "land_cost_usd": F("number", "usd", min=0, max=1e11, desc="compute: the land cost charged to the phase's "
                                                                        "pro forma"),
            "start_offset_years": F("integer", "years", min=0, max=100, desc="compute: years after the first phase "
                                                                              "that it starts"),
        },
    },
    "program_lines": {
        "label": "ProgramLine", "natural_key": ("use", "phase", "scenario"),
        "fields": {
            "id": F("text", required=True, desc="short id"),
            "use": F("text", required=True, desc="the id of a Use"),
            "phase": F("text", required=True, desc="the id of a Phase (1, 2, 3, full)"),
            "scenario": F("choice", required=True, choices=("low", "base", "high"), desc="low, base or high"),
            "sf": F("number", "sf", min=0, max=1e8, desc="building area"),
            "units": F("integer", "units", min=0, max=1e6, desc="dwelling units"),
            "keys": F("integer", "keys", min=0, max=1e5, desc="hotel keys"),
            "acres": F("number", "acres", min=0, max=1e6, desc="land area"),
            "base_rent_usd_sf_yr": F("number", "usd_per_sf_yr", min=0, max=1e4, desc="base rent per square foot per year"),
            "status": F("choice", choices=STATUSES, desc="Baseline, Consultant, Legacy Assumption or Superseded"),
            "assumption": F("text", desc="the id of the Assumption this line's main figure comes from"),
        },
    },
    "market_metrics": {
        "label": "MarketMetric", "natural_key": ("metric", "geography", "year"),
        "fields": {
            "id": F("text", required=True, desc="short id"),
            "metric": F("text", required=True, desc="what is measured (population, households, median income, ...)"),
            "geography": F("text", required=True, desc="primary trade area, secondary trade area, city, ..."),
            "year": F("integer", required=True, min=1900, max=2200, desc="the year the value is for"),
            "value": F("number", required=True, min=-1e13, max=1e13, desc="the value"),
            "unit": F("choice", required=True, choices=tuple(UNITS), desc="a unit code from the units list"),
            "segment": F("text", desc="a segment (lifestyle segment, spending category, ...)"),
            "source_id": F("text", desc="the id of a DataSource"),
            "assumption": F("text", desc="the id of the Assumption, when the value is also in the register"),
        },
    },
    "competitors": {
        "label": "Competitor", "natural_key": ("name",),
        "fields": {
            "id": F("text", required=True, desc="short id"),
            "name": F("text", required=True, desc="the competitor's name"),
            "type": F("text", required=True, desc="retail center, apartment community, hotel, office, ..."),
            "lat": F("number", min=-90, max=90, desc="latitude"),
            "lon": F("number", min=-180, max=180, desc="longitude"),
            "sf": F("number", "sf", min=0, max=1e8, desc="building area"),
            "units": F("integer", "units", min=0, max=1e6, desc="dwelling units"),
            "keys": F("integer", "keys", min=0, max=1e5, desc="hotel keys"),
            "rent": F("number", min=0, max=1e6, desc="rent, in rent_unit"),
            "rent_unit": F("choice", choices=("usd_per_sf_yr", "usd_per_sf_mo", "usd_per_unit_mo"), desc="the rent's unit"),
            "occupancy_pct": F("number", "pct", min=0, max=100, desc="occupancy"),
            "absorption": F("number", min=0, max=1e8, desc="absorption, in absorption_unit"),
            "absorption_unit": F("choice", choices=("sf_per_yr", "units_per_yr"), desc="the absorption's unit"),
            "sales_usd_sf": F("number", "usd_per_sf", min=0, max=1e5, desc="sales per square foot"),
            "adr": F("number", "usd_per_night", min=0, max=1e5, desc="average daily rate"),
            "revpar": F("number", "usd_per_night", min=0, max=1e5, desc="revenue per available room"),
            "market_flag": F("choice", choices=("saturated", "underserved", "balanced"), desc="what the market looks like"),
            "relocation_candidate": F("bool", desc="a tenant that might relocate or expand to the project"),
            "source_id": F("text", desc="the id of a DataSource"),
        },
    },
    "parcels": {
        "label": "Parcel", "natural_key": ("apn",),
        "fields": {
            "id": F("text", required=True, desc="short id (the APN when none is given)"),
            "apn": F("text", required=True, desc="the assessor's parcel number"),
            "label": F("text", desc="the planning parcel's name (PA-1, Lot 3, ...)"),
            "acres": F("number", "acres", required=True, min=0, max=1e6, desc="gross acres"),
            "net_acres": F("number", "acres", min=0, max=1e6, desc="net acres"),
            "use": F("text", desc="the id of a Use"),
            "phase": F("text", desc="the id of a Phase"),
            "hold_sell": F("choice", choices=("hold", "sell", "jv", "ground lease", "undecided"), tags=("disposition",),
                           desc="the plan for it"),
            "buyer_type": F("text", tags=("disposition",), desc="the kind of buyer"),
            "timing": F("text", tags=("disposition",), desc="when it is offered"),
            "price_floor": F("number", "usd", min=0, max=1e11, tags=("price_floor", "disposition"),
                             desc="the lowest acceptable price"),
            "target_price": F("number", "usd", min=0, max=1e11, tags=("disposition",), desc="the asking price"),
            "rlv": F("number", "usd", min=-1e11, max=1e11, tags=("rlv_parcel",), desc="residual land value"),
            "rlv_per_acre": F("number", "usd_per_acre", min=-1e10, max=1e10, tags=("rlv_parcel",),
                              desc="residual land value per acre"),
            "funding_target": F("text", tags=("disposition",), desc="the funding target the sale is linked to"),
            "provenance": F("choice", choices=PROVENANCE, desc="where the row's figures come from"),
            "candidate_uses": F("refs", desc="compute: the land_uses ids its residual value is worked out for"),
            "strategic_score": F("number", min=0, max=100, desc="compute: its strategic score, 0-100"),
            "strategic_scores": F("json", desc="compute: {dimension id: score 0-100} for the 12 strategic dimensions"),
            "critical": F("bool", tags=("disposition",), desc="compute: a critical strategic asset (never sold by a cash plan)"),
            "must_keep": F("bool", tags=("disposition",), desc="compute: never sold"),
            "close_month": F("integer", "months", min=0, max=600, tags=("disposition",),
                             desc="compute: month a sale would close (cash in)"),
            "do_not_sell_until_month": F("integer", "months", min=0, max=600, tags=("disposition",),
                                         desc="compute: no sale before this month"),
            "land_value_usd": F("number", "usd", min=0, max=1e11, tags=("disposition",),
                                desc="compute: today's land value for the hold/sell/JV/ground-lease comparison"),
            "seller_note_usd": F("number", "usd", min=0, max=1e11, tags=("disposition",),
                                 desc="compute: a seller note paid from the sale"),
            "debt_release_usd": F("number", "usd", min=0, max=1e11, tags=("disposition",),
                                  desc="compute: debt released from the sale"),
            "strategy_inputs": F("json", tags=("returns", "disposition"),
                                 desc="compute: {sale, develop, jv, ground_lease, carry_cost_usd_per_year} as in "
                                      "docs/district-finance.md section 7"),
        },
    },
    "assumptions": {
        "label": "Assumption", "natural_key": ("label",), "require_one_of": ("value", "value_low", "value_text"),
        "fields": {
            "id": F("text", required=True, desc="the register id every figure cites, for example A-RET-GLA"),
            "label": F("text", required=True, desc="the figure's name"),
            "value": F("number", min=-1e13, max=1e13, desc="the value, when it is one number"),
            "value_low": F("number", min=-1e13, max=1e13, desc="the low end, when it is a range"),
            "value_high": F("number", min=-1e13, max=1e13, desc="the high end, when it is a range"),
            "value_text": F("text", desc="the value in words, when it is not one number (450-500 plus)"),
            "unit": F("choice", required=True, choices=tuple(UNITS), desc="a unit code from the units list"),
            "source_doc": F("text", desc="the document it comes from"),
            "source_model": F("text", desc="the model it comes from"),
            "as_of": F("date", desc="the date it is true for"),
            "owner": F("text", desc="who answers for it"),
            "status": F("choice", required=True, choices=STATUSES, desc="Baseline, Consultant, Legacy Assumption or "
                                                                         "Superseded"),
            "provenance": F("choice", required=True, choices=PROVENANCE, desc="the 9-tier provenance class"),
            "confidence": F("choice", choices=CONFIDENCE, desc="high, medium or low"),
            "conflict": F("bool", desc="true when two sources disagree about it"),
            "conflict_note": F("text", desc="what disagrees with what"),
            "description": F("text", desc="what it means and how it is used"),
            "superseded_by": F("text", desc="the id of the Assumption that replaces it"),
        },
    },
    "deliverables": {
        "label": "Deliverable", "natural_key": ("task", "title", "version"),
        "fields": {
            "id": F("text", required=True, desc="short id"),
            "task": F("text", required=True, desc="the scope-of-work task (Task 1, Task 2, ...)"),
            "title": F("text", required=True, desc="the deliverable's title"),
            "version": F("text", desc="its version"),
            "file": F("text", desc="the id of a document in the library"),
            "upload_date": F("date", desc="when it arrived"),
            "accepted": F("bool", desc="accepted by the owner"),
            "accepted_by": F("text", desc="who accepted it"),
        },
    },
    "infrastructure": {
        "label": "InfrastructureItem", "natural_key": ("item", "phase"),
        "fields": {
            "id": F("text", required=True, desc="short id"),
            "item": F("text", required=True, desc="what is built (road, sewer line, signal, basin, ...)"),
            "category": F("text", desc="roads, wet utilities, dry utilities, grading, ..."),
            "phase": F("text", desc="the id of a Phase"),
            "quantity": F("number", min=0, max=1e9, desc="how much"),
            "quantity_unit": F("text", desc="linear feet, each, acres, ..."),
            "cost_usd": F("number", "usd", min=0, max=1e11, desc="cost"),
            "status": F("choice", choices=("planned", "designed", "under construction", "complete"), desc="where it stands"),
            "provenance": F("choice", choices=PROVENANCE, desc="where the cost comes from"),
            "assumption": F("text", desc="the id of the Assumption for the cost"),
            "payer": F("choice", choices=("owner", "builder", "city", "district_financing"), desc="compute: who pays"),
            "due_period": F("integer", min=0, max=3000, desc="compute: the year it must be paid for"),
            "reimbursable": F("bool", desc="compute: the cost is paid back later"),
            "parcel": F("text", desc="compute: the parcel whose sale carries it as a stub (the id of a Parcel)"),
        },
    },
    "risks": {
        "label": "Risk", "natural_key": ("title",),
        "fields": {
            "id": F("text", required=True, desc="short id"),
            "title": F("text", required=True, desc="the risk"),
            "category": F("text", desc="market, entitlement, infrastructure, capital, ..."),
            "likelihood": F("choice", choices=("low", "medium", "high"), desc="how likely"),
            "impact": F("choice", choices=("low", "medium", "high"), desc="how much it would hurt"),
            "mitigation": F("text", desc="what is done about it"),
            "owner": F("text", desc="who watches it"),
            "status": F("choice", choices=("open", "watching", "closed"), desc="where it stands"),
        },
    },
    "comps": {
        "label": "Comp", "natural_key": ("kind", "name", "date"),
        "fields": {
            "id": F("text", required=True, desc="short id"),
            "kind": F("choice", required=True, choices=("rent", "sale"), desc="a rent comparable or a sale comparable"),
            "name": F("text", required=True, desc="the property"),
            "use": F("text", desc="the id of a Use, or the use in words"),
            "address": F("text", desc="its address"),
            "lat": F("number", min=-90, max=90, desc="latitude"),
            "lon": F("number", min=-180, max=180, desc="longitude"),
            "date": F("date", desc="the date of the sale or the rent survey"),
            "price_usd": F("number", "usd", min=0, max=1e11, desc="sale price"),
            "size": F("number", min=0, max=1e9, desc="size, in size_unit"),
            "size_unit": F("choice", choices=("sf", "acres", "units", "keys"), desc="the size's unit"),
            "rent": F("number", min=0, max=1e6, desc="rent, in rent_unit"),
            "rent_unit": F("choice", choices=("usd_per_sf_yr", "usd_per_sf_mo", "usd_per_unit_mo"), desc="the rent's unit"),
            "source_id": F("text", desc="the id of a DataSource"),
        },
    },
    "data_sources": {
        "label": "DataSource", "natural_key": ("name",),
        "fields": {
            "id": F("text", required=True, desc="short id"),
            "name": F("text", required=True, desc="the dataset"),
            "provider": F("text", desc="who publishes or sells it"),
            "url": F("text", desc="where it is found"),
            "how_to_get": F("text", desc="how to get it (download, subscription, request, ...)"),
            "cadence": F("text", desc="how often it is refreshed"),
            "validation": F("text", desc="how a new copy is checked"),
            "license": F("text", desc="what its terms allow"),
            "last_refreshed": F("date", desc="when it was last read"),
            "owner": F("text", desc="who keeps it current"),
        },
    },
    "requirements": {
        "label": "Requirement", "natural_key": ("source_document", "section"),
        "fields": {
            "id": F("text", required=True, desc="the requirement's id in its document (FR-01, SEC-02, ...)"),
            "source_document": F("text", required=True, desc="the document it comes from"),
            "section": F("text", desc="the section of that document"),
            "text": F("text", required=True, desc="the requirement, in the document's words or a short summary"),
            "kind": F("choice", choices=("functional", "non-functional", "data", "security", "financial", "other"),
                      desc="what kind of requirement"),
            "status": F("choice", choices=("open", "done", "adapted", "needs-owner", "not-applicable"), default="open",
                        desc="open (not built yet, the default), done, adapted, needs-owner or not-applicable"),
            "where_in_app": F("text", desc="a link inside the app (#/districts/...) where it is met"),
            "title": F("text", desc="a short title"),
            "page": F("integer", min=0, max=100000, desc="the page of the source document"),
            "priority": F("text", desc="the priority the document gives it (Mandatory, High, ...)"),
            "category": F("text", desc="the register's own kind: feature, data-content, calculation, access-security, "
                                       "export, non-functional, data-source, advisory-question, owner-decision, "
                                       "open-item, consultant-process, context"),
            "gap": F("text", desc="what is still missing"),
            "evidence": F("text", desc="how it is shown to be met (a test, a screen, a file)"),
        },
    },
    "sections": {
        "label": "Section", "natural_key": ("module", "heading"),
        "fields": {
            "id": F("text", required=True, desc="short id"),
            "module": F("text", required=True, desc="the id of the module (page) it belongs to"),
            "order": F("integer", min=0, max=9999, desc="its place on the page"),
            "kind": F("choice", required=True, choices=("narrative", "table", "qa", "banner"),
                      desc="narrative text, a table, questions and answers, or a rule banner"),
            "heading": F("text", desc="its heading"),
            "body": F("text", desc="the text (narrative and banner)"),
            "columns": F("json", desc="table: the column names, a list of text"),
            "column_tags": F("json", desc="table: one list of sensitivity tags per column (a hidden column goes "
                                          "with its cells)"),
            "rows": F("json", desc="table: the rows, a list of lists"),
            "items": F("json", desc="qa: a list of {question, answer, cites, tags}"),
            "cites": F("refs", desc="the Assumption ids its figures come from"),
            "ai_assisted": F("bool", desc="written with AI help (NFR-09: it must cite what it uses)"),
        },
    },
    "blocks": {
        "label": "Block (a sale piece)", "natural_key": ("name",),
        "fields": {
            "id": F("text", required=True, desc="short id (B-1, ...)"),
            "name": F("text", required=True, desc="the block's name"),
            "apns": F("refs", desc="the parcels it lies in (parcel ids or APNs); a block may cut across them"),
            "net_acres": F("number", "acres", required=True, min=0, max=1e6, desc="net acres sold or kept"),
            "gross_acres": F("number", "acres", min=0, max=1e6, desc="gross acres"),
            "price_per_sf_low": F("number", "usd_per_sf", min=0, max=1e5, tags=("price_floor", "disposition"),
                                  desc="the low end of the stated price per net SF"),
            "price_per_sf": F("number", "usd_per_sf", min=0, max=1e5, tags=("disposition",),
                              desc="the stated price per net SF (empty with a range: the middle of the range)"),
            "price_per_sf_high": F("number", "usd_per_sf", min=0, max=1e5, tags=("disposition",),
                                   desc="the high end of the stated price per net SF"),
            "phase": F("text", desc="the id of a Phase"),
            "close_month": F("integer", "months", min=0, max=600, tags=("disposition",),
                             desc="month the sale closes (cash in)"),
            "buyer_type": F("text", tags=("disposition",), desc="the kind of buyer"),
            "intent": F("choice", choices=("sell", "hold", "jv", "ground_lease", "hold_develop"), tags=("disposition",),
                        desc="sell, hold, jv, ground_lease or hold_develop"),
            "core": F("bool", tags=("disposition",), desc="a strategic core block: never sold by the max-retention plan, flagged when sold"),
            "strategic_score": F("number", min=0, max=100, desc="its strategic score, 0-100"),
            "stub_cost_usd": F("number", "usd", min=0, max=1e11,
                               desc="infrastructure stub paid from the sale; leave empty when not known, 0 when none"),
            "use": F("text", desc="the id of a Use"),
            "cites": F("refs", desc="the Assumption ids its price comes from"),
            "strategy_inputs": F("json", tags=("returns", "disposition"),
                                 desc="{sale, develop, jv, ground_lease} for the hold/sell/JV/lease comparison"),
            "provenance": F("choice", choices=PROVENANCE, desc="where its price comes from"),
        },
    },
    "land_uses": {
        "label": "LandUse (finance library)", "natural_key": ("label",),
        "fields": {
            "id": F("text", required=True, desc="the id of the Use it prices (res-mf, ret-shops, ...)"),
            "label": F("text", required=True, desc="the name shown on screens"),
            "units_per_net_ac": F("number", min=0, max=1000, desc="homes or hotel keys per net acre"),
            "sf_per_unit": F("number", "sf", min=0, max=1e5, desc="building SF per home or key"),
            "far": F("number", "ratio", min=0, max=50, desc="or: building SF per SF of land"),
            "revenue_type": F("choice", required=True, choices=("per_unit_sale", "per_sf_sale", "rent_per_unit_mo",
                                                                 "rent_per_sf_yr", "room_revenue"),
                              desc="how the use earns"),
            "price_per_unit": F("number", "usd_per_unit", min=0, max=1e9, desc="sale price per home"),
            "price_per_sf": F("number", "usd_per_sf", min=0, max=1e6, desc="sale price per building SF"),
            "rent_per_unit_mo": F("number", "usd_per_unit_mo", min=0, max=1e6, desc="rent per home per month"),
            "rent_per_sf_yr": F("number", "usd_per_sf_yr", min=0, max=1e4, desc="rent per SF per year"),
            "efficiency_pct": F("number", "pct", min=0, max=100, desc="leasable share of building SF"),
            "adr": F("number", "usd_per_night", min=0, max=1e5, desc="hotel average daily rate"),
            "occupancy_pct": F("number", "pct", min=0, max=100, desc="hotel occupancy"),
            "vacancy_pct": F("number", "pct", min=0, max=100, desc="vacancy and credit loss"),
            "other_income_pct": F("number", "pct", min=0, max=1000, desc="other income as a share of rent"),
            "opex_pct_of_income": F("number", "pct", min=0, max=100, desc="operating cost as a share of income"),
            "sales_cost_pct": F("number", "pct", min=0, max=100, desc="selling cost"),
            "cap_rate_pct": F("number", "pct", min=0, max=100, desc="capitalisation rate"),
            "exit_cap_pct": F("number", "pct", min=0, max=100, desc="cap rate at the sale at the end"),
            "required_return_pct": F("number", "pct", min=0, max=1000, tags=("returns",),
                                     desc="the developer's required profit on cost"),
            "provenance": F("choice", choices=PROVENANCE, desc="where the row's figures come from"),
        },
    },
    "cost_items": {
        "label": "CostItem", "natural_key": ("use", "parcel", "item"),
        "row_tags_when": {"parcel": ("price_floor",)},
        "fields": {
            "id": F("text", required=True, desc="short id"),
            "use": F("text", desc="the land_uses id it is a development cost of"),
            "parcel": F("text", desc="or: the parcel whose cost basis (price floor) it is part of"),
            "item": F("text", required=True, desc="the cost item id (site_work, building_shell, ... see the finance doc)"),
            "label": F("text", desc="the name shown on screens"),
            "category": F("choice", choices=("hard", "soft", "financing", "land"), desc="the kind of cost"),
            "basis": F("choice", choices=("per_unit", "per_building_sf", "per_net_ac", "lump_sum", "pct_of_hard",
                                          "pct_of_prior"), desc="what the amount is per (development costs)"),
            "amount": F("number", min=0, max=1e11, desc="dollars per basis, or a percent; empty = not known"),
            "provenance": F("choice", choices=PROVENANCE, desc="where the amount comes from"),
        },
    },
    "capital_targets": {
        "label": "CapitalTarget", "natural_key": ("label",), "tags": ("disposition",),
        "fields": {
            "id": F("text", required=True, desc="short id"),
            "label": F("text", required=True, desc="what the cash is for"),
            "month": F("integer", "months", required=True, min=0, max=600, desc="the month the cash is needed by"),
            "amount_usd": F("number", "usd", required=True, min=0, max=1e11, desc="the cash needed"),
            "cumulative": F("bool", desc="true (the default): the amount is the total needed by that month"),
        },
    },
    "reconciliations": {
        "label": "Reconciliation", "natural_key": ("label",),
        "fields": {
            "id": F("text", required=True, desc="short id"),
            "label": F("text", required=True, desc="what should add up"),
            "total": F("text", required=True, desc="the id of the Assumption holding the total"),
            "parts": F("refs", desc="the ids of Assumptions that should add up to it"),
            "parts_entity": F("text", desc="or: an entity whose rows add up to it (program_lines, ...)"),
            "parts_field": F("text", desc="the field of those rows that is added (sf, acres, ...)"),
            "parts_where": F("json", desc="only the rows with these values, for example {\"phase\": \"1\", "
                                          "\"scenario\": \"base\"}"),
            "tolerance": F("number", min=0, max=1e13, desc="a difference up to this size counts as equal"),
            "explanation": F("text", desc="why the two differ, when they do"),
        },
    },
}

for _e in ENTITIES.values():
    for _k, _v in _COMMON_TAIL.items():
        _e["fields"].setdefault(_k, _v)

# ---------------------------------------------------------------- modules.json (NFR-08)

MODULE_FIELDS = {
    "id": "short id; sections name it in their module field",
    "label": "the page's name",
    "order": "its place in the menu",
    "description": "one or two lines under the heading",
    "audiences": "the audiences that see it (internal, consultant, partner, city); missing = all",
    "tags": "sensitivity tags for the whole module",
    "banner": "a rule banner shown on the page, or empty",
    "source_tags": "the tags shown under the heading (GROUND REVIEW, MODEL YIELD, ...)",
    "cards": "the KPI cards, a list of card objects",
    "tables": "entities shown as tables on the page: a list of {entity, columns, where}",
}
CARD_FIELDS = {
    "id": "short id",
    "label": "the card's heading",
    "assumption": "the id of the Assumption whose value it shows",
    "assumptions": "or: several Assumption ids (a range, a pair)",
    "description": "a short description under the value",
    "source_tags": "the tags shown on the card",
    "format": "sf | acres | units | keys | usd | usd_m | usd_per_sf_yr | usd_per_sf_mo | pct | int | number | range | text",
    "tags": "sensitivity tags for the card",
}
CARD_FORMATS = ("sf", "acres", "units", "keys", "usd", "usd_m", "usd_per_sf_yr", "usd_per_sf_mo", "pct", "int",
                "number", "range", "text")


def entity(name):
    return ENTITIES.get(name)


def row_tags(entity_name, record):
    """The tags a row carries because of its entity or its own fields (besides its own tags field)."""
    e = ENTITIES.get(entity_name) or {}
    out = set(e.get("tags", ()))
    for f, tags in (e.get("row_tags_when") or {}).items():
        if record.get(f) not in (None, "", []):
            out |= set(tags)
    return out


def field_tags(entity_name, field_name):
    f = ENTITIES.get(entity_name, {}).get("fields", {}).get(field_name)
    return set(f.get("tags", ())) if f else set()


def dictionary_rows():
    """The data dictionary as rows: entity, field, type, unit, required, range, choices, tags, description."""
    out = []
    for name, e in ENTITIES.items():
        for fname, f in e["fields"].items():
            lo, hi = f.get("min"), f.get("max")
            span = "" if lo is None and hi is None else f"{_n(lo)} to {_n(hi)}"
            choices = ""
            if f["type"] == "choice":
                choices = "a code from the Units sheet" if fname == "unit" else "; ".join(f["choices"])
            out.append([name, fname, f["type"], f.get("unit") or "", "yes" if f.get("required") else "",
                        span, choices, "; ".join(f.get("tags", ())), f.get("desc", "")])
    return out


DICTIONARY_COLUMNS = ["entity", "field", "type", "unit", "required", "range", "choices", "tags", "description"]


def _n(x):
    if x is None:
        return "any"
    return f"{int(x):,}" if float(x).is_integer() else str(x)


def markdown():
    """The entity tables for docs/district-data-contract.md."""
    lines = []
    for name, e in ENTITIES.items():
        extra = ""
        if e.get("require_one_of"):
            extra = f" A row needs at least one of: {', '.join(e['require_one_of'])}."
        if e.get("tags"):
            extra += f" Every row carries the tags {', '.join(e['tags'])}."
        for f_, tg in (e.get("row_tags_when") or {}).items():
            extra += f" A row with a {f_} carries the tags {', '.join(tg)}."
        lines.append(f"### `{name}` ({e['label']})\n")
        lines.append(f"Id made from {', '.join(e['natural_key'])} when a row has no id.{extra}\n")
        lines.append("| field | type | unit | required | range | choices | tags | description |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for fname, f in e["fields"].items():
            lo, hi = f.get("min"), f.get("max")
            span = "" if lo is None and hi is None else f"{_n(lo)} to {_n(hi)}"
            choices = ""
            if f["type"] == "choice":
                choices = "a unit code" if fname == "unit" else ", ".join(f["choices"])
            lines.append(f"| {fname} | {f['type']} | {f.get('unit') or ''} | {'yes' if f.get('required') else ''} | "
                         f"{span} | {choices} | {', '.join(f.get('tags', ()))} | {f.get('desc', '')} |")
        lines.append("")
    return "\n".join(lines)


BEGIN, END = "<!-- entities:begin -->", "<!-- entities:end -->"


def fill_contract(text):
    """The contract document's text with its entity tables replaced by the ones made from this schema."""
    head, _, rest = text.partition(BEGIN)
    _, _, tail = rest.partition(END)
    return f"{head}{BEGIN}\n{markdown()}\n{END}{tail}"

"""The built-in Sample District: an invented project with made-up round numbers that fills every entity, so the
screens and the tests always have a complete package to show. Nothing here describes a real place or project;
project.json carries "sample": true so every screen can say so.
"""
PROJECT_ID = "sample-district"

PROJECT = {
    "id": PROJECT_ID,
    "name": "Sample District",
    "place": "Sample City, California",
    "city": None,
    "apns": ["999-000-001", "999-000-002", "999-000-003", "999-000-004"],
    "branding": {"title": "SAMPLE DISTRICT", "subtitle": "Market Intelligence & Development Strategy",
                 "location": "Sample City, California - Sample Master Plan", "badge": "Private Management Platform",
                 "notice": "Authorized Access Only", "footer": "Sample data - invented for demonstration",
                 "model_label": "Sample Commercial Model - Underwriting Baseline"},
    "site": {"gross_acres": 120, "net_acres": 96, "on_site_homes": 1200, "freeway": "Sample Freeway"},
}


def _a(id_, label, unit, value=None, provenance="OWNERSHIP ASSUMPTION", status="Baseline", **more):
    out = {"id": id_, "label": label, "unit": unit, "status": status, "provenance": provenance,
           "source_doc": "Sample Baseline Memo", "source_model": "Sample Commercial Model", "as_of": "2026-01-01",
           "owner": "Sample Owner", "confidence": "medium"}
    if value is not None:
        out["value"] = value
    out.update(more)
    return out


ASSUMPTIONS = [
    _a("A-SITE-GROSS", "Site area, gross", "acres", 120, "VERIFIED PROJECT FACT", confidence="high"),
    _a("A-SITE-NET", "Site area, net", "acres", 96, "VERIFIED PROJECT FACT", confidence="high"),
    _a("A-RES-UNITS", "On-site homes", "units", 1200, "CURRENT OWNERSHIP INPUT", conflict=True,
       conflict_note="The sample consultant scope tests 1,000 and 1,400 homes as well."),
    _a("A-RET-GLA", "Near-term retail GLA", "sf", 180000),
    _a("A-RET-CAT-TOTAL", "Retail GLA in the category table", "sf", 170000, "CALCULATED"),
    _a("A-RET-MARKET", "Broader market opportunity", "sf", None, "MARKET ASSUMPTION", value_low=220000,
       value_high=240000),
    _a("A-RET-CEILING", "Long-term entitlement ceiling", "sf", None, "OWNERSHIP ASSUMPTION", value_low=300000,
       value_high=400000, value_text="300,000-400,000+ SF"),
    _a("A-RET-RENT", "Weighted base rent", "usd_per_sf_yr", 36.0),
    _a("A-RET-RENT-TOTAL", "Total annual base rent", "usd_per_yr", 6120000, "CALCULATED"),
    _a("A-RET-LEAKAGE", "Actionable retail leakage", "usd_per_yr", 400000000, "ESRI / ARCGIS DATA",
       value_text=None, source_doc="Sample trade-area report"),
    _a("A-OFF-SF", "Creative office", "sf", 10000),
    _a("A-SHOW-SF", "Small showroom space", "sf", 5000),
    _a("A-OTHER-SF", "Other commercial uses, total", "sf", 15000, "CALCULATED"),
    _a("A-HOTEL-KEYS", "Hotel keys", "keys", 120, "CONSULTANT INPUT", status="Consultant"),
    _a("A-HOTEL-ADR", "Hotel average daily rate", "usd_per_night", 180, "MARKET ASSUMPTION"),
    _a("A-POP-PTA", "Population, primary trade area, 2026", "people", 100000, "ESRI / ARCGIS DATA"),
    _a("A-IRR", "Project IRR, base case", "pct", 18.0, "CALCULATED", tags=["returns"]),
    _a("A-YOC", "Yield on cost, Phase 1 retail", "pct", 7.5, "CALCULATED", tags=["returns"]),
    _a("A-RLV-RETAIL", "Residual land value, retail, per acre", "usd_per_acre", 900000, "CALCULATED",
       tags=["rlv_parcel"]),
    _a("A-OLD-GLA", "Retail GLA in the earlier plan", "sf", 150000, "HISTORICAL / SUPERSEDED",
       status="Superseded", superseded_by="A-RET-GLA"),
    _a("A-ABSORB", "Home absorption per year", "units_per_yr", 200, "REQUIRES VALIDATION", confidence="low"),
]

USES = [
    {"id": "res-sfd", "label": "Single-family homes", "use_group": "residential", "category": "For sale",
     "typology": "detached"},
    {"id": "res-mf", "label": "Apartments", "use_group": "residential", "category": "For rent", "typology": "garden"},
    {"id": "ret-grocery", "label": "Grocery", "use_group": "retail", "category": "Grocery", "typology": "anchor"},
    {"id": "ret-restaurant", "label": "Restaurants", "use_group": "retail", "category": "Restaurants", "typology": "pad"},
    {"id": "ret-shops", "label": "Shops", "use_group": "retail", "category": "Shops", "typology": "inline"},
    {"id": "ret-service", "label": "Services", "use_group": "retail", "category": "Services", "typology": "inline"},
    {"id": "hotel", "label": "Hotel", "use_group": "hospitality", "category": "Select service", "typology": "mid-rise"},
    {"id": "office", "label": "Creative office", "use_group": "office", "category": "Creative office",
     "typology": "low-rise"},
    {"id": "park", "label": "Parks and open space", "use_group": "open space", "category": "Parks", "typology": ""},
]

PHASES = [
    {"id": "1", "label": "Phase 1", "order": 1, "start_year": 2027, "end_year": 2029, "residential_units_trigger": 0,
     "preleasing_pct_trigger": 50, "triggers": "Grocery lease signed; first 300 homes under way."},
    {"id": "2", "label": "Phase 2", "order": 2, "start_year": 2030, "end_year": 2032, "residential_units_trigger": 600,
     "preleasing_pct_trigger": 60, "absorption_note": "Needs 200 homes a year sold."},
    {"id": "3", "label": "Phase 3", "order": 3, "start_year": 2033, "end_year": 2036, "residential_units_trigger": 1000,
     "preleasing_pct_trigger": 60, "triggers": "Hotel only after Phase 2 retail is open."},
    {"id": "full", "label": "Full buildout", "order": 4, "start_year": 2027, "end_year": 2036},
]


def _pl(use, phase, scenario, sf=None, units=None, keys=None, acres=None, rent=None, assumption=None):
    r = {"id": f"pl-{use}-{phase}-{scenario}", "use": use, "phase": phase, "scenario": scenario, "status": "Baseline"}
    for k, v in (("sf", sf), ("units", units), ("keys", keys), ("acres", acres), ("base_rent_usd_sf_yr", rent),
                 ("assumption", assumption)):
        if v is not None:
            r[k] = v
    return r


PROGRAM = [
    _pl("ret-grocery", "1", "base", sf=50000, acres=5, rent=24),
    _pl("ret-restaurant", "1", "base", sf=40000, acres=5, rent=48),
    _pl("ret-shops", "1", "base", sf=50000, acres=5, rent=40),
    _pl("ret-service", "1", "base", sf=30000, acres=3, rent=32),
    _pl("ret-shops", "1", "low", sf=40000, acres=4, rent=36),
    _pl("ret-shops", "1", "high", sf=60000, acres=6, rent=44),
    _pl("res-sfd", "1", "base", units=300, acres=30),
    _pl("res-sfd", "2", "base", units=400, acres=35),
    _pl("res-mf", "2", "base", units=300, acres=10),
    _pl("res-mf", "3", "base", units=200, acres=7),
    _pl("hotel", "3", "base", keys=120, acres=3, assumption="A-HOTEL-KEYS"),
    _pl("office", "2", "base", sf=10000, acres=1, rent=36, assumption="A-OFF-SF"),
    _pl("park", "full", "base", acres=12),
]

MARKET = [
    {"id": "mm-pop-pta-2026", "metric": "population", "geography": "primary trade area", "year": 2026, "value": 100000,
     "unit": "people", "source_id": "ds-demographics", "assumption": "A-POP-PTA"},
    {"id": "mm-pop-pta-2031", "metric": "population", "geography": "primary trade area", "year": 2031, "value": 110000,
     "unit": "people", "source_id": "ds-demographics"},
    {"id": "mm-hh-pta-2026", "metric": "households", "geography": "primary trade area", "year": 2026, "value": 32000,
     "unit": "households", "source_id": "ds-demographics"},
    {"id": "mm-income-pta-2026", "metric": "median household income", "geography": "primary trade area", "year": 2026,
     "value": 90000, "unit": "usd", "source_id": "ds-demographics"},
    {"id": "mm-spend-dining", "metric": "spending potential", "geography": "primary trade area", "year": 2026,
     "value": 200000000, "unit": "usd_per_yr", "segment": "dining", "source_id": "ds-demographics"},
]

COMPETITORS = [
    {"id": "c-north-plaza", "name": "North Sample Plaza", "type": "retail center", "lat": 34.0, "lon": -117.0,
     "sf": 200000, "rent": 30, "rent_unit": "usd_per_sf_yr", "occupancy_pct": 95, "market_flag": "saturated",
     "source_id": "ds-costar"},
    {"id": "c-east-commons", "name": "East Sample Commons", "type": "retail center", "lat": 34.02, "lon": -116.98,
     "sf": 120000, "rent": 28, "rent_unit": "usd_per_sf_yr", "occupancy_pct": 88, "market_flag": "underserved",
     "relocation_candidate": True, "source_id": "ds-costar"},
    {"id": "c-garden-apts", "name": "Sample Garden Apartments", "type": "apartment community", "lat": 34.01,
     "lon": -117.02, "units": 300, "rent": 2400, "rent_unit": "usd_per_unit_mo", "occupancy_pct": 96,
     "absorption": 20, "absorption_unit": "units_per_yr"},
    {"id": "c-inn", "name": "Sample Inn", "type": "hotel", "lat": 33.99, "lon": -117.01, "keys": 100, "adr": 160,
     "revpar": 120, "occupancy_pct": 75},
]

PARCELS = [
    {"id": "PA-1", "apn": "999-000-001", "label": "Retail center", "acres": 20, "net_acres": 18, "use": "ret-shops",
     "phase": "1", "hold_sell": "hold", "buyer_type": "retail developer", "timing": "2027",
     "price_floor": 10000000, "target_price": 12000000, "rlv": 15000000, "rlv_per_acre": 750000,
     "funding_target": "Phase 1 roads", "provenance": "CALCULATED"},
    {"id": "PA-2", "apn": "999-000-002", "label": "Homes north", "acres": 40, "net_acres": 32, "use": "res-sfd",
     "phase": "1", "hold_sell": "sell", "buyer_type": "home builder", "timing": "2027", "price_floor": 20000000,
     "target_price": 24000000, "rlv": 26000000, "rlv_per_acre": 650000, "provenance": "CALCULATED"},
    {"id": "PA-3", "apn": "999-000-003", "label": "Apartments", "acres": 20, "net_acres": 17, "use": "res-mf",
     "phase": "2", "hold_sell": "jv", "buyer_type": "apartment developer", "timing": "2030",
     "price_floor": 9000000, "rlv": 11000000, "provenance": "OWNERSHIP ASSUMPTION"},
    {"id": "PA-4", "apn": "999-000-004", "label": "Hotel and office", "acres": 40, "net_acres": 29, "use": "hotel",
     "phase": "3", "hold_sell": "undecided", "timing": "2033", "provenance": "REQUIRES VALIDATION"},
]

INFRA = [
    {"id": "inf-main-road", "item": "Main street, two lanes each way", "category": "roads", "phase": "1",
     "quantity": 4000, "quantity_unit": "linear feet", "cost_usd": 8000000, "status": "designed",
     "provenance": "CONSULTANT INPUT"},
    {"id": "inf-sewer", "item": "Sewer line to the plant", "category": "wet utilities", "phase": "1", "quantity": 6000,
     "quantity_unit": "linear feet", "cost_usd": 3000000, "status": "planned", "provenance": "OWNERSHIP ASSUMPTION"},
    {"id": "inf-signal", "item": "Signal at the main entrance", "category": "roads", "phase": "1", "quantity": 1,
     "quantity_unit": "each", "cost_usd": 500000, "status": "planned", "provenance": "MARKET ASSUMPTION"},
]

RISKS = [
    {"id": "r-anchor", "title": "Grocery anchor not signed in time", "category": "market", "likelihood": "medium",
     "impact": "high", "mitigation": "Talk to three grocers at once.", "owner": "Sample Owner", "status": "open"},
    {"id": "r-sewer", "title": "Sewer capacity needs an upgrade", "category": "infrastructure", "likelihood": "low",
     "impact": "medium", "mitigation": "Capacity letter from the district.", "owner": "Sample Engineer",
     "status": "watching"},
]

COMPS = [
    {"id": "comp-land-1", "kind": "sale", "name": "Sample land sale A", "use": "res-sfd", "date": "2025-06-01",
     "price_usd": 30000000, "size": 50, "size_unit": "acres", "source_id": "ds-costar"},
    {"id": "comp-rent-1", "kind": "rent", "name": "Sample shops lease", "use": "ret-shops", "date": "2025-09-01",
     "rent": 38, "rent_unit": "usd_per_sf_yr", "size": 2000, "size_unit": "sf", "source_id": "ds-costar"},
]

SOURCES = [
    {"id": "ds-demographics", "name": "Trade-area demographics", "provider": "Sample data vendor",
     "how_to_get": "Download the trade-area report from the vendor's site", "cadence": "yearly",
     "validation": "Totals checked against the census within 5%", "license": "Internal use only",
     "last_refreshed": "2026-01-01", "owner": "Sample Analyst"},
    {"id": "ds-costar", "name": "Commercial rents and sales", "provider": "Sample listing service",
     "how_to_get": "Export from a paid subscription", "cadence": "quarterly",
     "validation": "Spot-check five properties by phone", "license": "Subscription terms", "owner": "Sample Analyst"},
]

REQUIREMENTS = [
    {"id": "SR-01", "source_document": "Sample Requirements v1", "section": "Access", "kind": "security",
     "text": "Only people on the user list may sign in.", "status": "done", "where_in_app": "#/districts"},
    {"id": "SR-02", "source_document": "Sample Requirements v1", "section": "Figures", "kind": "data",
     "text": "Every figure names where it comes from.", "status": "done",
     "where_in_app": "#/districts/sample-district/register"},
    {"id": "SR-03", "source_document": "Sample Requirements v1", "section": "Hosting", "kind": "non-functional",
     "text": "Served over HTTPS on a public address.", "status": "needs-owner",
     "note": "Runs on this computer only; hosting is the owner's decision."},
    {"id": "SR-04", "source_document": "Sample Requirements v1", "section": "Exports", "kind": "functional",
     "text": "Investor exports carry the counsel's disclaimer.", "status": "adapted",
     "note": "A marked placeholder until counsel supplies the wording."},
    {"id": "SR-05", "source_document": "Sample Requirements v1", "section": "Phases", "kind": "functional",
     "text": "A phase explorer compares low, base and high side by side.", "status": "open"},
]

SECTIONS = [
    {"id": "s-overview", "module": "overview", "order": 1, "kind": "narrative", "heading": "What the district is",
     "body": "A 120-acre invented district with 1,200 homes, a neighbourhood retail center and a small hotel.",
     "cites": ["A-SITE-GROSS", "A-RES-UNITS"]},
    {"id": "s-rule", "module": "commercial", "order": 0, "kind": "banner", "heading": "Scope rule",
     "body": "Do not treat the near-term program (180,000 SF), the market opportunity (220,000-240,000 SF) and the "
             "entitlement ceiling (300,000-400,000+ SF) as one figure.",
     "cites": ["A-RET-GLA", "A-RET-MARKET", "A-RET-CEILING"]},
    {"id": "s-categories", "module": "commercial", "order": 2, "kind": "table", "heading": "Retail by category",
     "columns": ["Category", "SF", "Base rent $/SF/yr"],
     "rows": [["Grocery", 50000, 24], ["Restaurants", 40000, 48], ["Shops", 50000, 40], ["Services", 30000, 32]],
     "cites": ["A-RET-CAT-TOTAL", "A-RET-RENT"]},
    {"id": "s-qa", "module": "commercial", "order": 3, "kind": "qa", "heading": "Questions for the consultant",
     "items": [{"question": "How much retail does the trade area support today?",
                "answer": "About 220,000-240,000 SF across all categories.", "cites": ["A-RET-MARKET"]},
               {"question": "Is a hotel supportable in Phase 3?", "answer": "To be answered by the market study."}]},
    {"id": "s-returns", "module": "returns", "order": 1, "kind": "narrative", "heading": "Returns",
     "body": "The base case IRR is 18% with a Phase 1 yield on cost of 7.5%.", "cites": ["A-IRR", "A-YOC"],
     "tags": ["returns"]},
    {"id": "s-disposition", "module": "parcels", "order": 2, "kind": "table", "heading": "Parcel pricing",
     "columns": ["Parcel", "Acres", "Price floor", "Residual land value"],
     "column_tags": [[], [], ["price_floor"], ["rlv_parcel"]],
     "rows": [["PA-1", 20, 10000000, 15000000], ["PA-2", 40, 20000000, 26000000]],
     "cites": ["A-RLV-RETAIL"]},
    {"id": "s-ai", "module": "overview", "order": 2, "kind": "narrative", "heading": "Market summary (AI-assisted)",
     "body": "The primary trade area holds about 100,000 people.", "cites": ["A-POP-PTA"], "ai_assisted": True},
]

RECONCILIATIONS = [
    {"id": "rec-gla", "label": "Near-term retail GLA against the category table", "total": "A-RET-GLA",
     "parts_entity": "program_lines", "parts_field": "sf",
     "parts_where": {"phase": "1", "scenario": "base"},
     "explanation": "The KPI counts 10,000 SF of pad buildings that the category table leaves out (invented example)."},
    {"id": "rec-other", "label": "Other commercial uses add up", "total": "A-OTHER-SF",
     "parts": ["A-OFF-SF", "A-SHOW-SF"], "explanation": ""},
]

DELIVERABLES = [
    {"id": "d-task1", "task": "Task 1", "title": "Market data package", "version": "1", "upload_date": "2026-02-01",
     "accepted": False},
]

MODULES = [
    {"id": "overview", "label": "Overview", "order": 1, "description": "The district in a few numbers.",
     "source_tags": ["SAMPLE MODEL"],
     "cards": [{"id": "site", "label": "Site area", "assumption": "A-SITE-GROSS", "format": "acres",
                "source_tags": ["VERIFIED"]},
               {"id": "homes", "label": "On-site homes", "assumption": "A-RES-UNITS", "format": "units"},
               {"id": "pop", "label": "Trade-area population", "assumption": "A-POP-PTA", "format": "int"}]},
    {"id": "commercial", "label": "Commercial", "order": 2,
     "description": "Near-term retail program, market opportunity and entitlement ceiling.",
     "banner": "Do not treat the near-term program, the market opportunity and the entitlement ceiling as one figure.",
     "source_tags": ["SAMPLE MODEL", "MODEL YIELD"],
     "cards": [{"id": "gla", "label": "Near-term retail GLA", "assumption": "A-RET-GLA", "format": "sf",
                "description": "Phase 1 retail, base case."},
               {"id": "ceiling", "label": "Long-term entitlement ceiling", "assumption": "A-RET-CEILING",
                "format": "range"},
               {"id": "rent", "label": "Total annual base rent", "assumption": "A-RET-RENT-TOTAL", "format": "usd_m"},
               {"id": "leakage", "label": "Actionable retail leakage", "assumption": "A-RET-LEAKAGE", "format": "usd_m"}],
     "tables": [{"entity": "program_lines", "columns": ["use", "phase", "sf", "base_rent_usd_sf_yr"],
                 "where": {"scenario": "base"}}]},
    {"id": "parcels", "label": "Parcels", "order": 3, "description": "The land, parcel by parcel.",
     "cards": [{"id": "rlv", "label": "Residual land value, retail", "assumption": "A-RLV-RETAIL",
                "format": "usd", "tags": ["rlv_parcel"]}],
     "tables": [{"entity": "parcels", "columns": ["apn", "label", "acres", "net_acres", "use", "phase", "hold_sell",
                                                  "price_floor", "rlv"]}]},
    {"id": "returns", "label": "Returns", "order": 4, "audiences": ["internal", "partner"], "tags": ["returns"],
     "description": "Underwriting returns (never in the city view).",
     "cards": [{"id": "irr", "label": "Project IRR", "assumption": "A-IRR", "format": "pct"},
               {"id": "yoc", "label": "Yield on cost", "assumption": "A-YOC", "format": "pct"}]},
    {"id": "requirements", "label": "Requirements", "order": 9, "audiences": ["internal", "consultant"],
     "description": "The requirement documents, line by line, and where each is met.",
     "tables": [{"entity": "requirements", "columns": ["id", "section", "text", "status", "where_in_app", "note"]}]},
]


def content():
    return {"format": 1, "entities": {
        "uses": USES, "phases": PHASES, "program_lines": PROGRAM, "market_metrics": MARKET, "competitors": COMPETITORS,
        "parcels": PARCELS, "assumptions": ASSUMPTIONS, "deliverables": DELIVERABLES, "infrastructure": INFRA,
        "risks": RISKS, "comps": COMPS, "data_sources": SOURCES, "requirements": REQUIREMENTS, "sections": SECTIONS,
        "reconciliations": RECONCILIATIONS}}


GIS = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"name": "Primary trade area", "ring": "primary"},
     "geometry": {"type": "Polygon", "coordinates": [[[-117.1, 33.9], [-116.9, 33.9], [-116.9, 34.1], [-117.1, 34.1],
                                                       [-117.1, 33.9]]]}},
    {"type": "Feature", "properties": {"name": "PA-1", "price_floor": 10000000, "rlv_per_acre": 750000},
     "geometry": {"type": "Point", "coordinates": [-117.0, 34.0]}}]}


def install(store, user, replace=True):
    """Write the Sample District (with one published baseline, a consultant submission and a GIS layer)."""
    import copy
    import shutil
    from .gis import summarise
    if store.exists(PROJECT_ID):
        if not replace:
            return store.project(PROJECT_ID)
        shutil.rmtree(store.root / PROJECT_ID)
    store.create_project(PROJECT, user, sample=True)
    store.update_project(PROJECT_ID, {"settings": {"partner_export": True, "city_export": True}}, user)
    store.set_modules(PROJECT_ID, copy.deepcopy(MODULES), user, "sample")
    store.put_records(PROJECT_ID, "baseline", copy.deepcopy(content()["entities"]), user, "replace", "sample")
    store.publish(PROJECT_ID, "baseline", user, "Sample baseline")
    sub = store.create_dataset(PROJECT_ID, "consultant", "Sample consultant submission", user,
                               {"dataset": "baseline", "version": "published"})
    changed = copy.deepcopy(ASSUMPTIONS)
    for a in changed:
        if a["id"] == "A-RET-GLA":
            a.update(value=200000, status="Consultant", provenance="CONSULTANT INPUT")      # +11%: flagged
        if a["id"] == "A-RET-RENT":
            a.update(value=37.0, status="Consultant", provenance="CONSULTANT INPUT")        # +3%: not flagged
    store.put_records(PROJECT_ID, sub["id"], {"assumptions": changed}, user, "merge", "sample consultant figures")
    info, fc = summarise(copy.deepcopy(GIS))
    store.add_layer(PROJECT_ID, fc, {"label": "Sample trade area", "kind": "trade_area", "source_name": "sample",
                                     **info, "audiences": ["internal", "consultant", "partner", "city"]}, user)
    return store.project(PROJECT_ID)

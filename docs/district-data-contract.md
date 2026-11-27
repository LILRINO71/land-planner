# District project: the data contract

A **district project** is one development (a master-planned district) with its whole market-intelligence package:
the program, market figures, competitors, parcels, the assumptions register, narrative and questions and answers,
documents, GIS layers and a requirements checklist. Everything is data: a new project, a new consultant package
or a new dashboard card needs no code change. This file is the contract the back end (`landplanner/district/`),
the finance engine, the Excel and PDF writers and the screens share. The entity tables below are generated from
`landplanner/district/schema.py` (`schema.markdown()`) and a test keeps them equal.

Everything in examples and tests is the invented **Sample District** with made-up round numbers. Real project data
lives only under `data/`, which git ignores.

## 1. Files on disk

```
data/
  district-users.json         the user directory (who may sign in, their role, their projects)
  district-settings.json      Google client id, idle timeout, NDA text and version, export disclaimers
  district-audit.jsonl        append-only audit log; each line holds the hash of the line before it
  projects/<project_id>/
    project.json              name, branding lines, place, city id, APNs, site facts, settings, sample flag
    modules.json              the pages and their KPI cards (section 4)
    datasets/<dataset_id>/
      meta.json               kind, label, owner, the list of published versions
      draft.json              the working copy (dataset content, section 3)
      v0001.json, v0002.json  published versions, never changed once written
    revisions.jsonl           append-only revision log (oldValue, newValue, user, reason, classification), hash-chained
    notes.json                notes and comments on figures, with resolution status
    documents/library.json    the document library and every version's facts
    documents/<doc_id>/v1.pdf the files themselves (PDF, PPTX, XLSX, DOCX, CSV)
    gis/layers.json           the GIS layers
    gis/<layer_id>.geojson    each layer as GeoJSON (a zipped shapefile is converted on upload)
    imports/<import_id>.json  an import preview waiting to be committed (kept 24 hours)
    backups/<YYYY-MM-DD>.zip  the daily backup, made on the first use each day; the last 14 are kept
```

Ids (`project_id`, `dataset_id`, record ids, layer and document ids) are 1 to 64 characters of letters, digits,
`.`, `_`, `:` and `-` (project, dataset, layer and document ids: lower-case letters, digits and `-` only). The
baseline dataset of every project is `baseline`.

Not done, on purpose: files are not encrypted at rest (the standard library has no cipher; turn on BitLocker or
Windows device encryption for the `data` folder) and the project zip is not password-protected (move it on a
private drive). The server answers on 127.0.0.1 only, so the HTTPS of NFR-01 does not apply until it is hosted.

## 2. Datasets and versions

A dataset is one full copy of the package's entities. Kinds:

| kind | made by | what it is |
|---|---|---|
| `baseline` | created with the project | the project's own figures; viewers see its published versions |
| `scenario` | administrator, analyst | a what-if copy; draft until an administrator publishes it |
| `consultant` | administrator, analyst, consultant | a consultant submission. An import of consultant deliverables always lands here, never in the baseline |

Each dataset has one **draft** (edited in place; every change is written to the revision log) and any number of
**published versions** (`v0001.json`, ...), which never change. Publishing copies the draft into the next version.
Rolling back publishes an older version's content again as a new version (nothing is deleted, the history says
which version it came from). `meta.json`:

```json
{"id": "baseline", "kind": "baseline", "label": "Baseline", "owner": "u-1a2b", "created_by": "u-1a2b",
 "created_at": "2026-11-26T10:00:00-08:00", "draft_updated_at": "...", "draft_updated_by": "u-1a2b",
 "published": [{"version": 1, "at": "...", "by": "u-1a2b", "note": "first", "from_version": null, "reason": ""}],
 "current": 1}
```

## 3. Dataset content

```json
{"format": 1, "entities": {"assumptions": [{...}, ...], "program_lines": [...], ...}}
```

Every entity is a list of records (JSON objects) with a unique `id`. Missing collections are empty lists. Numbers
are plain JSON numbers in the field's unit (never text, never NaN or Infinity). Every record may also carry `tags`
(sensitivity tags for the whole row), `city_safe` and `note`.

Rent is stored per square foot per **year** (`usd_per_sf_yr`); screens show per month as year / 12 and label both.

### Vocabularies

- **status** (FR-52): `Baseline`, `Consultant`, `Legacy Assumption`, `Superseded`.
- **provenance** (FIN-01, the 9 tiers): `VERIFIED PROJECT FACT`, `CURRENT OWNERSHIP INPUT`, `CONSULTANT INPUT`,
  `ESRI / ARCGIS DATA`, `OWNERSHIP ASSUMPTION`, `MARKET ASSUMPTION`, `CALCULATED`, `REQUIRES VALIDATION`,
  `HISTORICAL / SUPERSEDED`.
- **confidence**: `high`, `medium`, `low`.
- **units**: `sf`, `acres`, `units`, `keys`, `usd`, `usd_per_yr`, `usd_per_sf_yr`, `usd_per_sf_mo`, `usd_per_sf`,
  `usd_per_acre`, `usd_per_unit`, `usd_per_unit_mo`, `usd_per_night`, `pct` (0 to 100), `ratio`, `people`,
  `households`, `jobs`, `count`, `years`, `months`, `sf_per_yr`, `units_per_yr`, `miles`, `text`.
- **sensitivity tags**: `returns` (IRR, yield, yield on cost, return on cost, equity multiple), `rlv_parcel`
  (residual land value of a parcel), `price_floor`, `disposition` (target, minimum and stretch prices, buyer terms).

### Entities

<!-- entities:begin -->
### `uses` (Use)

Id made from use_group, category, typology when a row has no id.

| field | type | unit | required | range | choices | tags | description |
|---|---|---|---|---|---|---|---|
| id | text |  | yes |  |  |  | short id, for example retail-grocery |
| label | text |  |  |  |  |  | the name shown on screens |
| use_group | text |  | yes |  |  |  | residential, retail, hospitality, office, civic, open space, ... |
| category | text |  | yes |  |  |  | the category inside the group (Grocery, Townhomes, ...) |
| typology | text |  |  |  |  |  | the building form (pad, inline, podium, garden, ...) |
| tags | list |  |  |  |  |  | sensitivity tags for the whole row (returns, rlv_parcel, price_floor, disposition) |
| city_safe | bool |  |  |  |  |  | an administrator's word that this row may go to the city view although its words sound sensitive |
| note | text |  |  |  |  |  | a short note |

### `phases` (Phase)

Id made from label when a row has no id.

| field | type | unit | required | range | choices | tags | description |
|---|---|---|---|---|---|---|---|
| id | text |  | yes |  |  |  | 1, 2, 3 or full |
| label | text |  | yes |  |  |  | the name shown on screens |
| order | integer |  |  | 0 to 99 |  |  | sort order |
| start_year | integer |  |  | 1,900 to 2,200 |  |  | first year of the phase |
| end_year | integer |  |  | 1,900 to 2,200 |  |  | last year of the phase |
| residential_units_trigger | integer | units |  | 0 to any |  |  | homes delivered before this phase starts |
| preleasing_pct_trigger | number | pct |  | 0 to 100 |  |  | pre-leasing needed before it starts |
| absorption_note | text |  |  |  |  |  | what absorption the phase depends on |
| triggers | text |  |  |  |  |  | the other triggers and dependencies, in words |
| land_cost_usd | number | usd |  | 0 to 100,000,000,000 |  |  | compute: the land cost charged to the phase's pro forma |
| start_offset_years | integer | years |  | 0 to 100 |  |  | compute: years after the first phase that it starts |
| tags | list |  |  |  |  |  | sensitivity tags for the whole row (returns, rlv_parcel, price_floor, disposition) |
| city_safe | bool |  |  |  |  |  | an administrator's word that this row may go to the city view although its words sound sensitive |
| note | text |  |  |  |  |  | a short note |

### `program_lines` (ProgramLine)

Id made from use, phase, scenario when a row has no id.

| field | type | unit | required | range | choices | tags | description |
|---|---|---|---|---|---|---|---|
| id | text |  | yes |  |  |  | short id |
| use | text |  | yes |  |  |  | the id of a Use |
| phase | text |  | yes |  |  |  | the id of a Phase (1, 2, 3, full) |
| scenario | choice |  | yes |  | low, base, high |  | low, base or high |
| sf | number | sf |  | 0 to 100,000,000 |  |  | building area |
| units | integer | units |  | 0 to 1,000,000 |  |  | dwelling units |
| keys | integer | keys |  | 0 to 100,000 |  |  | hotel keys |
| acres | number | acres |  | 0 to 1,000,000 |  |  | land area |
| base_rent_usd_sf_yr | number | usd_per_sf_yr |  | 0 to 10,000 |  |  | base rent per square foot per year |
| status | choice |  |  |  | Baseline, Consultant, Legacy Assumption, Superseded |  | Baseline, Consultant, Legacy Assumption or Superseded |
| assumption | text |  |  |  |  |  | the id of the Assumption this line's main figure comes from |
| tags | list |  |  |  |  |  | sensitivity tags for the whole row (returns, rlv_parcel, price_floor, disposition) |
| city_safe | bool |  |  |  |  |  | an administrator's word that this row may go to the city view although its words sound sensitive |
| note | text |  |  |  |  |  | a short note |

### `market_metrics` (MarketMetric)

Id made from metric, geography, year when a row has no id.

| field | type | unit | required | range | choices | tags | description |
|---|---|---|---|---|---|---|---|
| id | text |  | yes |  |  |  | short id |
| metric | text |  | yes |  |  |  | what is measured (population, households, median income, ...) |
| geography | text |  | yes |  |  |  | primary trade area, secondary trade area, city, ... |
| year | integer |  | yes | 1,900 to 2,200 |  |  | the year the value is for |
| value | number |  | yes | -10,000,000,000,000 to 10,000,000,000,000 |  |  | the value |
| unit | choice |  | yes |  | a unit code |  | a unit code from the units list |
| segment | text |  |  |  |  |  | a segment (lifestyle segment, spending category, ...) |
| source_id | text |  |  |  |  |  | the id of a DataSource |
| assumption | text |  |  |  |  |  | the id of the Assumption, when the value is also in the register |
| tags | list |  |  |  |  |  | sensitivity tags for the whole row (returns, rlv_parcel, price_floor, disposition) |
| city_safe | bool |  |  |  |  |  | an administrator's word that this row may go to the city view although its words sound sensitive |
| note | text |  |  |  |  |  | a short note |

### `competitors` (Competitor)

Id made from name when a row has no id.

| field | type | unit | required | range | choices | tags | description |
|---|---|---|---|---|---|---|---|
| id | text |  | yes |  |  |  | short id |
| name | text |  | yes |  |  |  | the competitor's name |
| type | text |  | yes |  |  |  | retail center, apartment community, hotel, office, ... |
| lat | number |  |  | -90 to 90 |  |  | latitude |
| lon | number |  |  | -180 to 180 |  |  | longitude |
| sf | number | sf |  | 0 to 100,000,000 |  |  | building area |
| units | integer | units |  | 0 to 1,000,000 |  |  | dwelling units |
| keys | integer | keys |  | 0 to 100,000 |  |  | hotel keys |
| rent | number |  |  | 0 to 1,000,000 |  |  | rent, in rent_unit |
| rent_unit | choice |  |  |  | usd_per_sf_yr, usd_per_sf_mo, usd_per_unit_mo |  | the rent's unit |
| occupancy_pct | number | pct |  | 0 to 100 |  |  | occupancy |
| absorption | number |  |  | 0 to 100,000,000 |  |  | absorption, in absorption_unit |
| absorption_unit | choice |  |  |  | sf_per_yr, units_per_yr |  | the absorption's unit |
| sales_usd_sf | number | usd_per_sf |  | 0 to 100,000 |  |  | sales per square foot |
| adr | number | usd_per_night |  | 0 to 100,000 |  |  | average daily rate |
| revpar | number | usd_per_night |  | 0 to 100,000 |  |  | revenue per available room |
| market_flag | choice |  |  |  | saturated, underserved, balanced |  | what the market looks like |
| relocation_candidate | bool |  |  |  |  |  | a tenant that might relocate or expand to the project |
| source_id | text |  |  |  |  |  | the id of a DataSource |
| tags | list |  |  |  |  |  | sensitivity tags for the whole row (returns, rlv_parcel, price_floor, disposition) |
| city_safe | bool |  |  |  |  |  | an administrator's word that this row may go to the city view although its words sound sensitive |
| note | text |  |  |  |  |  | a short note |

### `parcels` (Parcel)

Id made from apn when a row has no id.

| field | type | unit | required | range | choices | tags | description |
|---|---|---|---|---|---|---|---|
| id | text |  | yes |  |  |  | short id (the APN when none is given) |
| apn | text |  | yes |  |  |  | the assessor's parcel number |
| label | text |  |  |  |  |  | the planning parcel's name (PA-1, Lot 3, ...) |
| acres | number | acres | yes | 0 to 1,000,000 |  |  | gross acres |
| net_acres | number | acres |  | 0 to 1,000,000 |  |  | net acres |
| use | text |  |  |  |  |  | the id of a Use |
| phase | text |  |  |  |  |  | the id of a Phase |
| hold_sell | choice |  |  |  | hold, sell, jv, ground lease, undecided |  | the plan for it |
| buyer_type | text |  |  |  |  |  | the kind of buyer |
| timing | text |  |  |  |  |  | when it is offered |
| price_floor | number | usd |  | 0 to 100,000,000,000 |  | price_floor, disposition | the lowest acceptable price |
| target_price | number | usd |  | 0 to 100,000,000,000 |  | disposition | the asking price |
| rlv | number | usd |  | -100,000,000,000 to 100,000,000,000 |  | rlv_parcel | residual land value |
| rlv_per_acre | number | usd_per_acre |  | -10,000,000,000 to 10,000,000,000 |  | rlv_parcel | residual land value per acre |
| funding_target | text |  |  |  |  | disposition | the funding target the sale is linked to |
| provenance | choice |  |  |  | VERIFIED PROJECT FACT, CURRENT OWNERSHIP INPUT, CONSULTANT INPUT, ESRI / ARCGIS DATA, OWNERSHIP ASSUMPTION, MARKET ASSUMPTION, CALCULATED, REQUIRES VALIDATION, HISTORICAL / SUPERSEDED |  | where the row's figures come from |
| candidate_uses | refs |  |  |  |  |  | compute: the land_uses ids its residual value is worked out for |
| strategic_score | number |  |  | 0 to 100 |  |  | compute: its strategic score, 0-100 |
| strategic_scores | json |  |  |  |  |  | compute: {dimension id: score 0-100} for the 12 strategic dimensions |
| critical | bool |  |  |  |  |  | compute: a critical strategic asset (never sold by a cash plan) |
| must_keep | bool |  |  |  |  |  | compute: never sold |
| close_month | integer | months |  | 0 to 600 |  | disposition | compute: month a sale would close (cash in) |
| do_not_sell_until_month | integer | months |  | 0 to 600 |  | disposition | compute: no sale before this month |
| land_value_usd | number | usd |  | 0 to 100,000,000,000 |  | disposition | compute: today's land value for the hold/sell/JV/ground-lease comparison |
| seller_note_usd | number | usd |  | 0 to 100,000,000,000 |  | disposition | compute: a seller note paid from the sale |
| debt_release_usd | number | usd |  | 0 to 100,000,000,000 |  | disposition | compute: debt released from the sale |
| strategy_inputs | json |  |  |  |  | returns, disposition | compute: {sale, develop, jv, ground_lease, carry_cost_usd_per_year} as in docs/district-finance.md section 7 |
| tags | list |  |  |  |  |  | sensitivity tags for the whole row (returns, rlv_parcel, price_floor, disposition) |
| city_safe | bool |  |  |  |  |  | an administrator's word that this row may go to the city view although its words sound sensitive |
| note | text |  |  |  |  |  | a short note |

### `assumptions` (Assumption)

Id made from label when a row has no id. A row needs at least one of: value, value_low, value_text.

| field | type | unit | required | range | choices | tags | description |
|---|---|---|---|---|---|---|---|
| id | text |  | yes |  |  |  | the register id every figure cites, for example A-RET-GLA |
| label | text |  | yes |  |  |  | the figure's name |
| value | number |  |  | -10,000,000,000,000 to 10,000,000,000,000 |  |  | the value, when it is one number |
| value_low | number |  |  | -10,000,000,000,000 to 10,000,000,000,000 |  |  | the low end, when it is a range |
| value_high | number |  |  | -10,000,000,000,000 to 10,000,000,000,000 |  |  | the high end, when it is a range |
| value_text | text |  |  |  |  |  | the value in words, when it is not one number (450-500 plus) |
| unit | choice |  | yes |  | a unit code |  | a unit code from the units list |
| source_doc | text |  |  |  |  |  | the document it comes from |
| source_model | text |  |  |  |  |  | the model it comes from |
| as_of | date |  |  |  |  |  | the date it is true for |
| owner | text |  |  |  |  |  | who answers for it |
| status | choice |  | yes |  | Baseline, Consultant, Legacy Assumption, Superseded |  | Baseline, Consultant, Legacy Assumption or Superseded |
| provenance | choice |  | yes |  | VERIFIED PROJECT FACT, CURRENT OWNERSHIP INPUT, CONSULTANT INPUT, ESRI / ARCGIS DATA, OWNERSHIP ASSUMPTION, MARKET ASSUMPTION, CALCULATED, REQUIRES VALIDATION, HISTORICAL / SUPERSEDED |  | the 9-tier provenance class |
| confidence | choice |  |  |  | high, medium, low |  | high, medium or low |
| conflict | bool |  |  |  |  |  | true when two sources disagree about it |
| conflict_note | text |  |  |  |  |  | what disagrees with what |
| description | text |  |  |  |  |  | what it means and how it is used |
| superseded_by | text |  |  |  |  |  | the id of the Assumption that replaces it |
| tags | list |  |  |  |  |  | sensitivity tags for the whole row (returns, rlv_parcel, price_floor, disposition) |
| city_safe | bool |  |  |  |  |  | an administrator's word that this row may go to the city view although its words sound sensitive |
| note | text |  |  |  |  |  | a short note |

### `deliverables` (Deliverable)

Id made from task, title, version when a row has no id.

| field | type | unit | required | range | choices | tags | description |
|---|---|---|---|---|---|---|---|
| id | text |  | yes |  |  |  | short id |
| task | text |  | yes |  |  |  | the scope-of-work task (Task 1, Task 2, ...) |
| title | text |  | yes |  |  |  | the deliverable's title |
| version | text |  |  |  |  |  | its version |
| file | text |  |  |  |  |  | the id of a document in the library |
| upload_date | date |  |  |  |  |  | when it arrived |
| accepted | bool |  |  |  |  |  | accepted by the owner |
| accepted_by | text |  |  |  |  |  | who accepted it |
| tags | list |  |  |  |  |  | sensitivity tags for the whole row (returns, rlv_parcel, price_floor, disposition) |
| city_safe | bool |  |  |  |  |  | an administrator's word that this row may go to the city view although its words sound sensitive |
| note | text |  |  |  |  |  | a short note |

### `infrastructure` (InfrastructureItem)

Id made from item, phase when a row has no id.

| field | type | unit | required | range | choices | tags | description |
|---|---|---|---|---|---|---|---|
| id | text |  | yes |  |  |  | short id |
| item | text |  | yes |  |  |  | what is built (road, sewer line, signal, basin, ...) |
| category | text |  |  |  |  |  | roads, wet utilities, dry utilities, grading, ... |
| phase | text |  |  |  |  |  | the id of a Phase |
| quantity | number |  |  | 0 to 1,000,000,000 |  |  | how much |
| quantity_unit | text |  |  |  |  |  | linear feet, each, acres, ... |
| cost_usd | number | usd |  | 0 to 100,000,000,000 |  |  | cost |
| status | choice |  |  |  | planned, designed, under construction, complete |  | where it stands |
| provenance | choice |  |  |  | VERIFIED PROJECT FACT, CURRENT OWNERSHIP INPUT, CONSULTANT INPUT, ESRI / ARCGIS DATA, OWNERSHIP ASSUMPTION, MARKET ASSUMPTION, CALCULATED, REQUIRES VALIDATION, HISTORICAL / SUPERSEDED |  | where the cost comes from |
| assumption | text |  |  |  |  |  | the id of the Assumption for the cost |
| payer | choice |  |  |  | owner, builder, city, district_financing |  | compute: who pays |
| due_period | integer |  |  | 0 to 3,000 |  |  | compute: the year it must be paid for |
| reimbursable | bool |  |  |  |  |  | compute: the cost is paid back later |
| parcel | text |  |  |  |  |  | compute: the parcel whose sale carries it as a stub (the id of a Parcel) |
| tags | list |  |  |  |  |  | sensitivity tags for the whole row (returns, rlv_parcel, price_floor, disposition) |
| city_safe | bool |  |  |  |  |  | an administrator's word that this row may go to the city view although its words sound sensitive |
| note | text |  |  |  |  |  | a short note |

### `risks` (Risk)

Id made from title when a row has no id.

| field | type | unit | required | range | choices | tags | description |
|---|---|---|---|---|---|---|---|
| id | text |  | yes |  |  |  | short id |
| title | text |  | yes |  |  |  | the risk |
| category | text |  |  |  |  |  | market, entitlement, infrastructure, capital, ... |
| likelihood | choice |  |  |  | low, medium, high |  | how likely |
| impact | choice |  |  |  | low, medium, high |  | how much it would hurt |
| mitigation | text |  |  |  |  |  | what is done about it |
| owner | text |  |  |  |  |  | who watches it |
| status | choice |  |  |  | open, watching, closed |  | where it stands |
| tags | list |  |  |  |  |  | sensitivity tags for the whole row (returns, rlv_parcel, price_floor, disposition) |
| city_safe | bool |  |  |  |  |  | an administrator's word that this row may go to the city view although its words sound sensitive |
| note | text |  |  |  |  |  | a short note |

### `comps` (Comp)

Id made from kind, name, date when a row has no id.

| field | type | unit | required | range | choices | tags | description |
|---|---|---|---|---|---|---|---|
| id | text |  | yes |  |  |  | short id |
| kind | choice |  | yes |  | rent, sale |  | a rent comparable or a sale comparable |
| name | text |  | yes |  |  |  | the property |
| use | text |  |  |  |  |  | the id of a Use, or the use in words |
| address | text |  |  |  |  |  | its address |
| lat | number |  |  | -90 to 90 |  |  | latitude |
| lon | number |  |  | -180 to 180 |  |  | longitude |
| date | date |  |  |  |  |  | the date of the sale or the rent survey |
| price_usd | number | usd |  | 0 to 100,000,000,000 |  |  | sale price |
| size | number |  |  | 0 to 1,000,000,000 |  |  | size, in size_unit |
| size_unit | choice |  |  |  | sf, acres, units, keys |  | the size's unit |
| rent | number |  |  | 0 to 1,000,000 |  |  | rent, in rent_unit |
| rent_unit | choice |  |  |  | usd_per_sf_yr, usd_per_sf_mo, usd_per_unit_mo |  | the rent's unit |
| source_id | text |  |  |  |  |  | the id of a DataSource |
| tags | list |  |  |  |  |  | sensitivity tags for the whole row (returns, rlv_parcel, price_floor, disposition) |
| city_safe | bool |  |  |  |  |  | an administrator's word that this row may go to the city view although its words sound sensitive |
| note | text |  |  |  |  |  | a short note |

### `data_sources` (DataSource)

Id made from name when a row has no id.

| field | type | unit | required | range | choices | tags | description |
|---|---|---|---|---|---|---|---|
| id | text |  | yes |  |  |  | short id |
| name | text |  | yes |  |  |  | the dataset |
| provider | text |  |  |  |  |  | who publishes or sells it |
| url | text |  |  |  |  |  | where it is found |
| how_to_get | text |  |  |  |  |  | how to get it (download, subscription, request, ...) |
| cadence | text |  |  |  |  |  | how often it is refreshed |
| validation | text |  |  |  |  |  | how a new copy is checked |
| license | text |  |  |  |  |  | what its terms allow |
| last_refreshed | date |  |  |  |  |  | when it was last read |
| owner | text |  |  |  |  |  | who keeps it current |
| tags | list |  |  |  |  |  | sensitivity tags for the whole row (returns, rlv_parcel, price_floor, disposition) |
| city_safe | bool |  |  |  |  |  | an administrator's word that this row may go to the city view although its words sound sensitive |
| note | text |  |  |  |  |  | a short note |

### `requirements` (Requirement)

Id made from source_document, section when a row has no id.

| field | type | unit | required | range | choices | tags | description |
|---|---|---|---|---|---|---|---|
| id | text |  | yes |  |  |  | the requirement's id in its document (FR-01, SEC-02, ...) |
| source_document | text |  | yes |  |  |  | the document it comes from |
| section | text |  |  |  |  |  | the section of that document |
| text | text |  | yes |  |  |  | the requirement, in the document's words or a short summary |
| kind | choice |  |  |  | functional, non-functional, data, security, financial, other |  | what kind of requirement |
| status | choice |  |  |  | open, done, adapted, needs-owner, not-applicable |  | open (not built yet, the default), done, adapted, needs-owner or not-applicable |
| where_in_app | text |  |  |  |  |  | a link inside the app (#/districts/...) where it is met |
| title | text |  |  |  |  |  | a short title |
| page | integer |  |  | 0 to 100,000 |  |  | the page of the source document |
| priority | text |  |  |  |  |  | the priority the document gives it (Mandatory, High, ...) |
| category | text |  |  |  |  |  | the register's own kind: feature, data-content, calculation, access-security, export, non-functional, data-source, advisory-question, owner-decision, open-item, consultant-process, context |
| gap | text |  |  |  |  |  | what is still missing |
| evidence | text |  |  |  |  |  | how it is shown to be met (a test, a screen, a file) |
| tags | list |  |  |  |  |  | sensitivity tags for the whole row (returns, rlv_parcel, price_floor, disposition) |
| city_safe | bool |  |  |  |  |  | an administrator's word that this row may go to the city view although its words sound sensitive |
| note | text |  |  |  |  |  | a short note |

### `sections` (Section)

Id made from module, heading when a row has no id.

| field | type | unit | required | range | choices | tags | description |
|---|---|---|---|---|---|---|---|
| id | text |  | yes |  |  |  | short id |
| module | text |  | yes |  |  |  | the id of the module (page) it belongs to |
| order | integer |  |  | 0 to 9,999 |  |  | its place on the page |
| kind | choice |  | yes |  | narrative, table, qa, banner |  | narrative text, a table, questions and answers, or a rule banner |
| heading | text |  |  |  |  |  | its heading |
| body | text |  |  |  |  |  | the text (narrative and banner) |
| columns | json |  |  |  |  |  | table: the column names, a list of text |
| column_tags | json |  |  |  |  |  | table: one list of sensitivity tags per column (a hidden column goes with its cells) |
| rows | json |  |  |  |  |  | table: the rows, a list of lists |
| items | json |  |  |  |  |  | qa: a list of {question, answer, cites, tags} |
| cites | refs |  |  |  |  |  | the Assumption ids its figures come from |
| ai_assisted | bool |  |  |  |  |  | written with AI help (NFR-09: it must cite what it uses) |
| tags | list |  |  |  |  |  | sensitivity tags for the whole row (returns, rlv_parcel, price_floor, disposition) |
| city_safe | bool |  |  |  |  |  | an administrator's word that this row may go to the city view although its words sound sensitive |
| note | text |  |  |  |  |  | a short note |

### `land_uses` (LandUse (finance library))

Id made from label when a row has no id.

| field | type | unit | required | range | choices | tags | description |
|---|---|---|---|---|---|---|---|
| id | text |  | yes |  |  |  | the id of the Use it prices (res-mf, ret-shops, ...) |
| label | text |  | yes |  |  |  | the name shown on screens |
| units_per_net_ac | number |  |  | 0 to 1,000 |  |  | homes or hotel keys per net acre |
| sf_per_unit | number | sf |  | 0 to 100,000 |  |  | building SF per home or key |
| far | number | ratio |  | 0 to 50 |  |  | or: building SF per SF of land |
| revenue_type | choice |  | yes |  | per_unit_sale, per_sf_sale, rent_per_unit_mo, rent_per_sf_yr, room_revenue |  | how the use earns |
| price_per_unit | number | usd_per_unit |  | 0 to 1,000,000,000 |  |  | sale price per home |
| price_per_sf | number | usd_per_sf |  | 0 to 1,000,000 |  |  | sale price per building SF |
| rent_per_unit_mo | number | usd_per_unit_mo |  | 0 to 1,000,000 |  |  | rent per home per month |
| rent_per_sf_yr | number | usd_per_sf_yr |  | 0 to 10,000 |  |  | rent per SF per year |
| efficiency_pct | number | pct |  | 0 to 100 |  |  | leasable share of building SF |
| adr | number | usd_per_night |  | 0 to 100,000 |  |  | hotel average daily rate |
| occupancy_pct | number | pct |  | 0 to 100 |  |  | hotel occupancy |
| vacancy_pct | number | pct |  | 0 to 100 |  |  | vacancy and credit loss |
| other_income_pct | number | pct |  | 0 to 1,000 |  |  | other income as a share of rent |
| opex_pct_of_income | number | pct |  | 0 to 100 |  |  | operating cost as a share of income |
| sales_cost_pct | number | pct |  | 0 to 100 |  |  | selling cost |
| cap_rate_pct | number | pct |  | 0 to 100 |  |  | capitalisation rate |
| exit_cap_pct | number | pct |  | 0 to 100 |  |  | cap rate at the sale at the end |
| required_return_pct | number | pct |  | 0 to 1,000 |  | returns | the developer's required profit on cost |
| provenance | choice |  |  |  | VERIFIED PROJECT FACT, CURRENT OWNERSHIP INPUT, CONSULTANT INPUT, ESRI / ARCGIS DATA, OWNERSHIP ASSUMPTION, MARKET ASSUMPTION, CALCULATED, REQUIRES VALIDATION, HISTORICAL / SUPERSEDED |  | where the row's figures come from |
| tags | list |  |  |  |  |  | sensitivity tags for the whole row (returns, rlv_parcel, price_floor, disposition) |
| city_safe | bool |  |  |  |  |  | an administrator's word that this row may go to the city view although its words sound sensitive |
| note | text |  |  |  |  |  | a short note |

### `cost_items` (CostItem)

Id made from use, parcel, item when a row has no id. A row with a parcel carries the tags price_floor.

| field | type | unit | required | range | choices | tags | description |
|---|---|---|---|---|---|---|---|
| id | text |  | yes |  |  |  | short id |
| use | text |  |  |  |  |  | the land_uses id it is a development cost of |
| parcel | text |  |  |  |  |  | or: the parcel whose cost basis (price floor) it is part of |
| item | text |  | yes |  |  |  | the cost item id (site_work, building_shell, ... see the finance doc) |
| label | text |  |  |  |  |  | the name shown on screens |
| category | choice |  |  |  | hard, soft, financing, land |  | the kind of cost |
| basis | choice |  |  |  | per_unit, per_building_sf, per_net_ac, lump_sum, pct_of_hard, pct_of_prior |  | what the amount is per (development costs) |
| amount | number |  |  | 0 to 100,000,000,000 |  |  | dollars per basis, or a percent; empty = not known |
| provenance | choice |  |  |  | VERIFIED PROJECT FACT, CURRENT OWNERSHIP INPUT, CONSULTANT INPUT, ESRI / ARCGIS DATA, OWNERSHIP ASSUMPTION, MARKET ASSUMPTION, CALCULATED, REQUIRES VALIDATION, HISTORICAL / SUPERSEDED |  | where the amount comes from |
| tags | list |  |  |  |  |  | sensitivity tags for the whole row (returns, rlv_parcel, price_floor, disposition) |
| city_safe | bool |  |  |  |  |  | an administrator's word that this row may go to the city view although its words sound sensitive |
| note | text |  |  |  |  |  | a short note |

### `capital_targets` (CapitalTarget)

Id made from label when a row has no id. Every row carries the tags disposition.

| field | type | unit | required | range | choices | tags | description |
|---|---|---|---|---|---|---|---|
| id | text |  | yes |  |  |  | short id |
| label | text |  | yes |  |  |  | what the cash is for |
| month | integer | months | yes | 0 to 600 |  |  | the month the cash is needed by |
| amount_usd | number | usd | yes | 0 to 100,000,000,000 |  |  | the cash needed |
| cumulative | bool |  |  |  |  |  | true (the default): the amount is the total needed by that month |
| tags | list |  |  |  |  |  | sensitivity tags for the whole row (returns, rlv_parcel, price_floor, disposition) |
| city_safe | bool |  |  |  |  |  | an administrator's word that this row may go to the city view although its words sound sensitive |
| note | text |  |  |  |  |  | a short note |

### `reconciliations` (Reconciliation)

Id made from label when a row has no id.

| field | type | unit | required | range | choices | tags | description |
|---|---|---|---|---|---|---|---|
| id | text |  | yes |  |  |  | short id |
| label | text |  | yes |  |  |  | what should add up |
| total | text |  | yes |  |  |  | the id of the Assumption holding the total |
| parts | refs |  |  |  |  |  | the ids of Assumptions that should add up to it |
| parts_entity | text |  |  |  |  |  | or: an entity whose rows add up to it (program_lines, ...) |
| parts_field | text |  |  |  |  |  | the field of those rows that is added (sf, acres, ...) |
| parts_where | json |  |  |  |  |  | only the rows with these values, for example {"phase": "1", "scenario": "base"} |
| tolerance | number |  |  | 0 to 10,000,000,000,000 |  |  | a difference up to this size counts as equal |
| explanation | text |  |  |  |  |  | why the two differ, when they do |
| tags | list |  |  |  |  |  | sensitivity tags for the whole row (returns, rlv_parcel, price_floor, disposition) |
| city_safe | bool |  |  |  |  |  | an administrator's word that this row may go to the city view although its words sound sensitive |
| note | text |  |  |  |  |  | a short note |

<!-- entities:end -->

## 4. modules.json (configurable pages and KPI cards, NFR-08)

```json
{"modules": [
  {"id": "commercial", "label": "Commercial", "order": 2, "description": "...",
   "audiences": ["internal", "consultant", "partner", "city"], "tags": [],
   "banner": "Do not treat the near-term program, the market opportunity and the entitlement ceiling as one figure.",
   "source_tags": ["SAMPLE MODEL"],
   "cards": [{"id": "gla", "label": "Near-term retail GLA", "assumption": "A-RET-GLA",
              "description": "...", "source_tags": ["SAMPLE MODEL"], "format": "sf", "tags": []}],
   "tables": [{"entity": "program_lines", "columns": ["use", "phase", "sf", "base_rent_usd_sf_yr"],
               "where": {"scenario": "base"}}]}
]}
```

Card `format`: `sf`, `acres`, `units`, `keys`, `usd`, `usd_m` (millions), `usd_per_sf_yr`, `usd_per_sf_mo`, `pct`,
`int`, `number`, `range` (uses `value_low` and `value_high`, or two `assumptions`), `text` (uses `value_text`).
A module's sections are the `sections` records whose `module` is the module's id, in `order`.

## 5. Roles, audiences and what each may do

| role | audience | in short |
|---|---|---|
| `administrator` | internal | everything: users, publish, roll back, audit log, settings, backups, project zip |
| `analyst` | internal | upload, edit drafts and assumptions, create scenarios (draft only); no publish |
| `consultant` | consultant | assigned projects only: upload into own consultant submissions, view the published baseline; no publish |
| `viewer_partner` | partner | assigned projects: published baseline and scenarios, read-only; export when the project allows it |
| `viewer_city` | city | assigned projects: the published baseline in the city view, read-only; export when the project allows it |

A user's `projects` list names the projects a consultant or viewer may open (`"*"` = all). Administrators and
analysts see every project. The permission table is `access.PERMISSIONS` (one place):

| action | administrator | analyst | consultant | viewer_partner | viewer_city |
|---|---|---|---|---|---|
| project.view | yes | yes | assigned | assigned | assigned |
| project.create, project.edit, modules.edit, settings.edit, users.manage, audit.read | yes | | | | |
| dataset.publish, dataset.rollback, backup.manage, package.export, package.import, documents.share, sample.install | yes | | | | |
| dataset.read_draft, dataset.edit | yes | yes | own submissions | | |
| dataset.create_scenario | yes | yes | | | |
| dataset.create_submission, import, compare, checks, templates | yes | yes | yes | | |
| revisions.read, notes.resolve, gis.remove | yes | yes | | | |
| notes.read, notes.write, documents.upload, gis.upload | yes | yes | yes | | |
| documents.read, gis.read, compute | yes | yes | yes | yes | yes |
| export | yes | yes | yes | if `partner_export` | if `city_export` |

Which datasets each role can read: administrator and analyst all, every version; consultant the published
baseline and their own submissions; partner every dataset that has a published version; city the published
baseline only.

**Field filtering is done on the server.** Before any answer, export or GIS layer leaves the server it is filtered
for the audience (`access.filter_content`, `access.scrub`). `schema.AUDIENCE_DENY` says which tags each audience
never receives; today only `city` denies `returns`, `rlv_parcel`, `price_floor` and `disposition`. Removed:

1. a field whose schema tags meet the deny-list (`parcels.price_floor`, `parcels.rlv`, ...);
2. a record whose own `tags` meet it (an assumption tagged `returns`, a section tagged `disposition`);
3. a record whose words (id, label, heading, metric, body) name a denied subject (`IRR`, `yield`, `residual land
   value`, `price floor`, `disposition`, ...) even when untagged, unless an administrator set `city_safe`;
4. a card, reconciliation or table row that cites a removed assumption, and a table column tagged in `column_tags`;
5. in free-form objects (site facts, GIS properties, computed results) any key named like a denied subject
   (`irr`, `rlv_per_acre`, `price_floor`, `target_price`, `yield_on_cost`, ...).

An administrator or analyst may add `?audience=city` (or `partner`, `consultant`) to any read or export to see
exactly what that audience would get; a viewer cannot widen theirs.

## 6. Signing in

- **Name and passcode.** `POST /api/districts/session {"method": "passcode", "name", "passcode"}`. Passcodes are kept
  as PBKDF2-SHA256 with a salt per user. Five wrong tries in 15 minutes lock that name for 15 minutes.
- **Google.** When `google_client_id` is set in `data/district-settings.json`, the page gets a Google ID token
  (Google Identity Services) and sends `{"method": "google", "id_token"}`. The server checks it with
  `https://oauth2.googleapis.com/tokeninfo` (audience = the client id, issuer Google, e-mail verified, not
  expired) and the e-mail must belong to an ACTIVE user in the directory; otherwise it is refused with a clear
  message and logged. With no client id the answer is `501 google-not-set-up` (the owner creates the client id in
  Google Cloud; nothing is faked).
- **First run.** While the directory is empty, the first person to sign in (either way) becomes the administrator,
  and the Sample District is installed so the workspace is not empty.
- **Session.** A cookie `lp_district` (HttpOnly, SameSite=Strict, Path=/api/districts) that ends after
  `idle_minutes` (default 30) without a request, at sign-out, or when the app restarts.
- **NDA.** Data is served only after the user has acknowledged the current NDA version
  (`POST /api/districts/session/nda {"accept": true}`); the time and version are recorded. The default NDA text is
  the placeholder "Confidentiality agreement (NDA): wording to be supplied by counsel."
- **Last administrator.** The last active administrator can never be removed, deactivated or given another role.

## 7. Requests and answers

- Every route is under `/api/districts`. Methods: GET, POST, DELETE (HEAD answers like GET).
- JSON bodies: `Content-Type: application/json`, up to 2 MB. Files (imports, documents, GIS, project zip): the raw
  bytes with `Content-Type: application/octet-stream`, up to 64 MB, and the file name in `?name=`.
- Errors: `{"error": {"code", "message"}}` with codes `sign-in-needed` (401), `session-expired` (401), `nda-needed`
  (403), `forbidden` (403), `not-found` (404), `bad-request` (400), `conflict` (409), `last-admin` (409),
  `sign-in-refused` (401, wrong passcode or a Google token that fails a check), `not-authorized` (403, a Google account that is not an active user), `unreadable` (500, a damaged data file),
  `too-large` (413), `too-many-tries` (429), `not-ready` (501, the Excel or PDF writer is not installed yet),
  `google-not-set-up` (501), `google-unreachable` (502).
- Every request is also checked by the app's server: only 127.0.0.1/localhost as Host, and an Origin header (when
  sent) must be this computer.
- Files come back with `Content-Disposition: attachment; filename=...`.
- No answer ever holds NaN or Infinity: every division is guarded and the writer refuses them.

## 8. Routes

Role column: who may call it (`any` = no sign-in needed; `signed-in` = any role after the NDA).

```
GET    /api/districts                                   any        {available, signed_in, bootstrap, google:{enabled, client_id}, features:{excel, pdf}, idle_minutes, landing?:{title, subtitle, place, badge, notice, footer}}
GET    /api/districts/session                           any        {signed_in:false, bootstrap, google} | {signed_in:true, user, audience, nda:{required, version, text}, idle_minutes}
POST   /api/districts/session                           any        {method:"passcode", name, passcode} | {method:"google", id_token} -> session (Set-Cookie)
DELETE /api/districts/session                           any        sign out -> {signed_in:false}
POST   /api/districts/session/nda                       signed-in  {accept:true} -> session
POST   /api/districts/session/passcode                  signed-in  {old, new} -> {ok:true}

GET    /api/districts/users                             admin      {users:[user]}
POST   /api/districts/users                             admin      {id?, name, email?, role, status?, projects?, passcode?} -> {user}  (no id = new)
DELETE /api/districts/users/<user_id>                   admin      {removed:true}
GET    /api/districts/settings                          admin      settings (the client id is shown, no secrets are kept)
POST   /api/districts/settings                          admin      {google_client_id?, idle_minutes?, nda_text?, nda_version?, disclaimers?, landing?} -> settings
GET    /api/districts/audit                             admin      ?q= &action= &user= &outcome= &project= &limit=200 &offset=0 -> {entries, total, chain:{ok, lines, broken_at, reason}}

GET    /api/districts/templates                         templates  {entities:[names], columns:{entity:[fields]}, dictionary:{columns, rows}, units:{code:label}}
GET    /api/districts/templates/<entity>.csv            templates  CSV with the header row
GET    /api/districts/templates/dictionary.csv          templates  the data dictionary as CSV
GET    /api/districts/templates/workbook.xlsx           templates  one sheet per entity + Dictionary + Units (501 until xlsx.py exists)

GET    /api/districts/projects                          signed-in  {projects:[{id, name, place, sample, branding, role}]}
POST   /api/districts/projects                          admin      {id?, name, place?, city?, apns?, branding?, site?} -> {project}
POST   /api/districts/projects/sample                   admin      install or reinstall the Sample District -> {project}
POST   /api/districts/projects/import                   admin      raw zip, ?replace=1 to replace a project with the same id -> {project, replaced, safety_backup}
GET    /api/districts/projects/<p>                      view       {project, datasets:[meta], modules, audience, can:{action: bool}, is_sample}
POST   /api/districts/projects/<p>                      admin      {name?, place?, city?, apns?, branding?, site?, settings?:{partner_export, city_export, compare_threshold_pct}} -> {project}
GET    /api/districts/projects/<p>/package.zip          admin      the whole project as one zip (manifest.json with each file's SHA-256)
GET    /api/districts/projects/<p>/backups              admin      {backups:[{name, size, at}]}
POST   /api/districts/projects/<p>/backups              admin      back up now -> {backup}
POST   /api/districts/projects/<p>/backups/<name>/restore admin    -> {restored, safety_backup}

GET    /api/districts/projects/<p>/modules              view       {modules} (only the modules and cards the audience may see)
POST   /api/districts/projects/<p>/modules              admin      {modules:[...], reason} -> {modules}

GET    /api/districts/projects/<p>/datasets             view       {datasets:[meta]}
POST   /api/districts/projects/<p>/datasets             scenario/submission  {kind:"scenario"|"consultant", label, copy_from?:{dataset, version}} -> {dataset}
GET    /api/districts/projects/<p>/datasets/<d>         view       ?version=published|draft|<n> &audience= -> {dataset, version, audience, content}
GET    /api/districts/projects/<p>/datasets/<d>/versions view      {draft:{updated_at, updated_by}|null, published:[...], current}
POST   /api/districts/projects/<p>/datasets/<d>/records edit       {entity, record, reason?, classification?} -> {record, changes:[{field, old, new}]}
DELETE /api/districts/projects/<p>/datasets/<d>/records/<entity>/<id>  edit  ?reason= -> {removed:true}
POST   /api/districts/projects/<p>/datasets/<d>/publish admin      {note?} -> {version}
POST   /api/districts/projects/<p>/datasets/<d>/rollback admin     {version, reason, reset_draft?} -> {version, from_version}  (the draft is kept unless reset_draft)
GET    /api/districts/projects/<p>/datasets/<d>/figures/<assumption_id>  view  ?version= -> {figure, found, used_by:[...], notes:[...]}
GET    /api/districts/projects/<p>/datasets/<d>/checks  checks     ?version= -> {unregistered, uncited, reconciliations, conflicts, untagged_sensitive, superseded_in_use}
GET    /api/districts/projects/<p>/revisions            revisions  ?dataset= &entity= &id= &limit=500 -> {revisions, chain}
GET    /api/districts/projects/<p>/compare              compare    ?base=baseline &base_version=published &other=<d> &other_version=draft &threshold=10 -> comparison

POST   /api/districts/projects/<p>/imports              import     raw CSV or XLSX, ?name=file.csv &entity=<entity> (CSV needs it; an XLSX sheet is matched by its name) -> preview
POST   /api/districts/projects/<p>/imports/<i>/commit   import     {target:"baseline"|"consultant"|"<dataset id>", mode:"merge"|"replace", label?, reason?} -> {dataset, imported:{entity:n}}

GET    /api/districts/projects/<p>/documents            documents.read  {documents}
POST   /api/districts/projects/<p>/documents            documents.upload raw file, ?name= &title= &task= &document=<id, for a new version> &note= -> {document}
POST   /api/districts/projects/<p>/documents/<doc>/share admin     {audiences:[...]} -> {document}
GET    /api/districts/projects/<p>/documents/<doc>/<version|latest>  documents.read  the file

GET    /api/districts/projects/<p>/gis                  gis.read   {layers}
POST   /api/districts/projects/<p>/gis                  gis.upload raw .geojson/.json or zipped shapefile, ?name= &kind=trade_area|competitors|parcels|other &label= -> {layer, warnings}
POST   /api/districts/projects/<p>/gis/<layer>/share    admin      {audiences:[...]} -> {layer} (new layers are internal + consultant)
GET    /api/districts/projects/<p>/gis/<layer>          gis.read   a GeoJSON FeatureCollection (properties filtered for the audience)
DELETE /api/districts/projects/<p>/gis/<layer>          gis.remove {removed:true} (the file is kept, the layer is hidden)

GET    /api/districts/projects/<p>/notes                notes.read ?status=open|resolved &entity= &id= -> {notes}
POST   /api/districts/projects/<p>/notes                notes.write {target:{dataset?, entity, id, field?}, text} -> {note}
POST   /api/districts/projects/<p>/notes/<n>/replies    notes.write {text} -> {note}
POST   /api/districts/projects/<p>/notes/<n>/resolve    notes.resolve {status:"resolved"|"open", resolution?} -> {note}

GET|POST /api/districts/projects/<p>/compute/<tool>  compute   see section 11
GET    /api/districts/projects/<p>/export/table.xlsx    export     ?dataset= &version= &entity=<entity>|all|section:<section id> &audience= (501 until xlsx.py exists)
GET    /api/districts/projects/<p>/export/module.pdf    export     ?module= &dataset= &version= &audience= (501 until pdf.py exists)
```

`landing` (before sign-in, so only these six lines of text, never an id, a name or a figure): the settings' own
`landing` when an administrator has set it (`null` clears it); otherwise, when exactly one project that is not the sample
exists, that project's branding (`place` is its `location` line); otherwise left out. `footer` is one string with " · "
between its parts; a list given for it is joined that way.

Shapes used above:

- **user**: `{id, name, email, role, status ("ACTIVE"|"INACTIVE"), projects, has_passcode, nda_version,
  nda_accepted_at, created_at, created_by, last_sign_in}`. Passcode hashes never leave the server.
- **session**: `{signed_in: true, user, audience, nda: {required, version, text}, idle_minutes}`.
- **preview**: `{import_id, file, format, entities: {name: {rows_ok, rows_rejected, rejected: [{row, errors:[text]}],
  sample: [first 5 clean rows], unknown_columns, missing_columns, column_units}}, rows_ok, rows_rejected, can_commit,
  errors:[text]}`. Row numbers are as in the file (the header is row 1). Nothing is written to a dataset until commit.
- **comparison**: `{base:{dataset, version}, other:{dataset, version}, threshold_pct, entities: {name: {added:[id],
  removed:[id], changed:[{id, field, base, other, change, change_pct, flagged}]}}, flagged, changed, added,
  removed}`. `change_pct` is null when the base is 0 (a change from 0 is always flagged).
- **reconciliation**: `{id, label, total, parts_total, difference, difference_pct, within_tolerance, explanation,
  explained, parts:[{id, value}], missing:[ids]}`.
- **figure**: the assumption record plus `display` (the value as words in its unit).
- **audit entry**: `{seq, at, user, name, role, action, outcome ("ok"|"denied"|"failed"), project, detail, prev,
  hash}`. Actions: `sign-in`, `sign-out`, `session-expired`, `nda`, `denied`, `user-add`, `user-change`,
  `user-remove`, `settings`, `project-create`, `project-edit`, `modules`, `dataset-create`, `edit`, `publish`,
  `rollback`, `import-preview`, `import`, `upload-document`, `share-document`, `download-document`, `upload-gis`,
  `remove-gis`, `share-gis`, `compute`, `note`, `export`, `backup`, `restore`, `package-export`, `package-import`, `sample`.
- **revision**: `{seq, at, user, name, dataset, entity, id, field, oldValue, newValue, reason, classification, prev,
  hash}`. `classification` is the record's provenance class (or the one given with the edit).

## 9. Exports

Every export carries "CONFIDENTIAL", the as-of date (the dataset version's publish date, or today for a draft) and
the disclaimer for its audience from `district-settings.json`:

| audience | default disclaimer |
|---|---|
| internal | Internal working figures. Not for distribution. |
| consultant | Shared with the consultant for the assigned scope of work. |
| partner | Reg D disclaimer: wording to be supplied by counsel |
| city | City-facing view: returns, residual land value by parcel and disposition pricing are not included. |

The investor wording is a marked placeholder until counsel supplies it; nothing legal is invented. The content is
filtered for the audience first. Every export is in the audit log with what was exported.

Interfaces called (owned by other workers): `landplanner.district.xlsx.read_workbook(data) -> {sheet: rows}`,
`write_workbook(sheets, widths=None) -> bytes`; `landplanner.district.pdf.build_pdf(doc) -> bytes` with
`doc = {title, subtitle, as_of, watermark, disclaimer, header, cover, toc, sections: [{heading, paragraphs,
tables: [{title, columns, rows, align}]}]}`. While a file is missing the route answers `501 not-ready`.

## 10. Python interface (for the finance engine and other modules)

```python
from landplanner.district.store import Store
store = Store(data_dir)                                  # the same data folder the app uses
content = store.content(project_id, dataset_id, "published")   # or "draft" or a version number -> {"format", "entities"}
from landplanner.district import register
register.figure(content, "A-RET-GLA")                    # the register entry (or None)
register.value(content, "A-RET-GLA")                     # its number (or None)
from landplanner.district import access
access.filter_content(content, "city")                   # what the city may see
access.scrub(any_json_object, "city")                    # remove sensitive keys from free-form results
from landplanner.district.jsonsafe import clean
clean(obj)                                               # NaN and Infinity become None, everywhere
```

A module that adds routes for computed results must pass its answer through `access.scrub` for the caller's
audience before it is sent.

## 11. Compute (computed results)

```
GET    /api/districts/projects/<p>/compute/<tool>       compute    ?dataset=baseline &version= &audience= (admin/analyst only) &<option>=
POST   /api/districts/projects/<p>/compute/<tool>       compute    {dataset?, version?, audience?, assumptions?, records?, options?}
```

`<tool>` is one of `landvalue`, `proceeds`, `proforma`, `strategy`, `scenarios`, `funding`, `fiscal`, `reconcile`. Every
role may call them (viewers on the versions they can read). The answer:

```json
{"tool": "landvalue", "dataset": "baseline", "version": 1, "audience": "internal", "as_of": "2026-11-27",
 "inputs_used": [{"assumption_id": "FIN-NET-TO-GROSS-PCT", "label": "...", "value": 80, "unit": "pct",
                  "provenance": "VERIFIED PROJECT FACT", "what_if": false, "tags": []},
                 {"field": "land_uses/ret-shops/rent_per_sf_yr", "value": 40, "unit": "usd_per_sf_yr",
                  "provenance": "OWNERSHIP ASSUMPTION", "what_if": false, "tags": []}],
 "result": {}, "formula": ["...", "..."], "missing": ["what the dataset lacks, in plain words"],
 "disclaimer": "Economic calculation under the stated assumptions. ...", "what_if": [], "hidden_parts": []}
```

- `missing` names every input the tool looked for and did not find. A figure the engine has a starting value for is
  used and said so (`provenance: "ENGINE STARTING FIGURE"`); one it has none for leaves that part out.
- **What-if (POST).** Nothing is saved. `assumptions` is `{id: number}` (an existing register entry, or a convention id
  below); `records` is `{entity: [{id, field: value}]}` merged into existing rows and checked like an edit. A viewer can
  change only what their own view shows. `what_if` lists what was changed; those inputs carry `"what_if": true`.
- **Options.** `proceeds`: `price_basis` = `target_market` (default), `minimum_recommended`, `upside_stretch` or
  `economic_cost_floor`. `proforma`: `tornado_metric` = `irr_pct` (default), `yoc_pct`, `npv_usd`, `rlv_total_usd` or
  `equity_multiple`. On a GET they are query parameters.
- **Audience.** The answer is filtered on the server: result parts tagged in `compute.RESULT_TAGS` are removed for an
  audience that denies the tag (listed in `hidden_parts`), inputs whose tags it denies are removed, and `access.scrub`
  removes every remaining key named like a denied subject. The city never receives returns (IRR, yield on cost, NPV,
  equity multiple, required return, margins, break-evens, the tornado), residual land value by parcel, pricing tiers,
  sale proceeds, the capital plan, hold/sell decisions or the funding gap against land sales.

### Where each input comes from

| input | from |
|---|---|
| land use library | `land_uses` rows (one per Use id) and their `cost_items` (rows with `use`) |
| a parcel's cost basis (price floor) | `cost_items` rows with `parcel`; an item without an amount is "not known" |
| parcels | `parcels`: acres, net_acres (else `FIN-NET-TO-GROSS-PCT`), use, candidate_uses, strategic_score(s), critical, must_keep, close_month, do_not_sell_until_month, seller_note_usd, debt_release_usd, land_value_usd, strategy_inputs |
| phases | `phases` (land_cost_usd, start_offset_years, the two triggers) with the base-case `program_lines` of each phase (units, else keys, else sf, else acres). The `full` phase is the whole buildout, not a phase of its own. Uses in the groups open space, civic, infrastructure and parks are left out quietly |
| infrastructure stubs | `infrastructure` rows with `parcel`; payer and due year from `payer` and `due_period` |
| capital targets | `capital_targets` (month, amount_usd, cumulative) |
| everything else | assumptions by id, below |

| assumption id | meaning | unit | engine starting figure |
|---|---|---|---|
| `PF-BASE-YEAR` | first year of the pro forma | count |  |
| `PF-DISCOUNT-RATE-PCT` | pro forma discount rate | pct | 10.0 |
| `PF-HOLD-YEARS` | years held after stabilisation | years | 10 |
| `PF-BUILD-YEARS` | years to build | years | 2 |
| `PF-LEASE-UP-MONTHS` | months to lease up | months | 24 |
| `PF-SELLOUT-MONTHS` | months to sell out | months | 24 |
| `PF-NOI-GROWTH-PCT` | NOI growth per year | pct | 0.0 |
| `PF-HURDLE-YOC-PCT` | hurdle yield on cost | pct |  |
| `PF-HURDLE-IRR-PCT` | hurdle IRR | pct |  |
| `FIN-NET-TO-GROSS-PCT` | net acres as a share of gross | pct | 100.0 |
| `FIN-SPONSOR-HURDLE-PCT` | sponsor hurdle on cost | pct | 20.0 |
| `FIN-STRATEGIC-PREMIUM-PCT` | strategic premium on cost | pct | 0.0 |
| `FIN-TARGET-PCT-OF-RLV` | target price as a share of residual value | pct | 100.0 |
| `FIN-UPSIDE-PCT` | upside over the target price | pct | 15.0 |
| `FIN-BROKERAGE-PCT` | brokerage commission | pct | 3.5 |
| `FIN-CLOSING-PCT` | closing costs | pct | 0.75 |
| `FIN-TRANSFER-TAX-PCT` | transfer tax | pct | 0.11 |
| `FIN-RECORDING-FEE-USD` | recording fee per sale | usd | 0.0 |
| `FIN-CRITICAL-THRESHOLD` | strategic score that makes a parcel critical | count | 75.0 |
| `STR-DISCOUNT-RATE-PCT` | strategy comparison discount rate | pct | 8.0 |
| `STR-APPRECIATION-PCT` | land appreciation per year | pct | 3.0 |
| `STR-SALE-COST-PCT` | selling cost of retained land | pct | 4.36 |
| `STR-PLACEMAKING-LIFT-PCT` | placemaking lift on retained land | pct | 0.0 |
| `STR-LIFT-YEAR` | year the placemaking lift arrives | count | 1 |
| `STR-RELEASE-ACRES` | acres released in each tranche | acres |  |
| `STR-RELEASE-EVERY-YEARS` | years between tranches | years |  |
| `STR-MIN-CORE-ACRES` | core acres never released | acres | 0.0 |
| `SCN-ABSORPTION-UNITS-PER-YEAR` | home absorption per year | units_per_yr |  |
| `SCN-PRELEASING-PCT` | pre-leasing today | pct |  |
| `FISCAL-CONSTRUCTION-JOBS-PER-MILLION` | construction job-years per $1 million | count |  |
| `FISCAL-CONSTRUCTION-MULTIPLIER` | construction output multiplier | ratio |  |
| `FISCAL-OPERATING-MULTIPLIER` | operating output multiplier | ratio |  |
| `FISCAL-SALES-TAX-PCT` | local sales tax rate | pct |  |
| `FISCAL-PROPERTY-TAX-PCT` | property tax rate | pct |  |
| `FISCAL-CITY-SHARE-PCT` | city share of property tax | pct |  |
| `FISCAL-HOTEL-TAX-PCT` | hotel room tax | pct |  |
| `EIFD-PARTICIPATING-SHARE-PCT` | share of the increment a district captures | pct |  |
| `EIFD-YEARS` | years of increment shown | years | 30 |
| `EIFD-GROWTH-PCT` | assessed value growth per year | pct | 2.0 |
| `FISCAL-JOBS-PER-1000SF-<x>` | jobs per 1,000 SF of that use | jobs | |
| `FISCAL-SALES-PER-SF-<x>` | taxable sales per SF per year | usd_per_sf | |
| `SCN-UNITS-<n>` | a named unit-count scenario (one per id) | units | |

`FISCAL-JOBS-PER-1000SF-<x>` and `FISCAL-SALES-PER-SF-<x>` are looked up first by the use id (`ret-shops`), then by the
use's group in capitals (`RETAIL`, `OFFICE`, `HOSPITALITY`).

### What each tool returns, and one example body

| tool | result | example POST body |
|---|---|---|
| `landvalue` | `by_use` (residual per use and low/base/high: per net acre, gross acre, net SF), `by_parcel` (per parcel and candidate use), `pricing_tiers` (per parcel: cost floor, minimum recommended, target, upside) | `{"assumptions": {"FIN-TARGET-PCT-OF-RLV": 90}, "records": {"land_uses": [{"id": "ret-shops", "rent_per_sf_yr": 44}]}}` |
| `proceeds` | `price_basis`, `waterfall` (gross-to-net per parcel and totals), `capital_plan` (max cash, balanced, max retention against the targets), `targets` | `{"options": {"price_basis": "minimum_recommended"}, "assumptions": {"FIN-BROKERAGE-PCT": 2.5}}` |
| `proforma` | `phases`, `full_buildout` (totals, yield on cost, IRR with `converged`, equity multiple, NPV, cash flows), `break_even` (per driver the program has), `tornado` | `{"options": {"tornado_metric": "yoc_pct"}, "assumptions": {"PF-HURDLE-IRR-PCT": 18}}` |
| `strategy` | `decisions` (hold, sell, JV, ground lease per parcel: NPVs, scores, guarded recommendation), `conflicts` (critical assets), `retained_value` (land kept, over 15 years), `paced_releases`, `retained_parcels` | `{"assumptions": {"STR-APPRECIATION-PCT": 4, "STR-RELEASE-ACRES": 4}}` |
| `scenarios` | `low_base_high` (headline metrics side by side and against the base), `unit_scenarios` (one per `SCN-UNITS-<n>`), `absorption` (homes by year), `phase_triggers` (each phase's triggers met, not met or not known) | `{"assumptions": {"SCN-ABSORPTION-UNITS-PER-YEAR": 150, "SCN-PRELEASING-PCT": 65}}` |
| `funding` | `register` (infrastructure totals by phase and payer, with the count of costs not known), `funding_gap` (owner cost against land-sale proceeds by year), `unknown_cost_items` | `{"records": {"infrastructure": [{"id": "inf-water", "cost_usd": 2000000}]}}` |
| `fiscal` | `impact` (jobs, output, sales, property and hotel tax by phase), `eifd` (increment by year) | `{"assumptions": {"FISCAL-SALES-TAX-PCT": 1.5, "EIFD-PARTICIPATING-SHARE-PCT": 30}}` |
| `reconcile` | `reconciliations` (each rule's difference, explanation and the engine's own check), `all_explained` | `{"assumptions": {"A-RET-CAT-TOTAL": 175000}}` |

Every compute call is in the audit log (`compute`, with the tool, dataset, version, audience and what-if changes).

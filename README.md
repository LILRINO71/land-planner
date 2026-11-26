# Land Planner

Software for a land developer in Menifee, California: someone who buys a large piece of raw land, works with the
city to decide what each part of it may become, lays out the plan, and then sells the planned pieces to the
companies that build on them.

The goal is a tool that looks at one piece of land and answers, with reasons he can check:

1. **What is this land?** Size, shape, slope, zoning, what the city's general plan intends, what surrounds it,
   which roads and how much traffic pass it.
2. **How should it be divided?** For example "of these 140 acres, about 25 for a shopping centre on the corner
   with the most traffic, 80 for homes, 15 for parks and drainage, the rest for roads", and why.
3. **Who would buy each piece?** Kinds of buyers and builders for each use (home builders, retail developers,
   apartment developers), and real companies active in the area.
4. **What would it cost and earn?** Grading, roads, utilities and fees against what the finished pieces sell for,
   with his own cost numbers imported from a spreadsheet.
5. **What would it look like?** A 3D view of the land with the proposed plan on it: blocks, roads, signals, and a
   "ten years from now" view.

## What exists today

`tools/menifee.py` gets real public facts about any parcel in Menifee. No account or key is needed.

```
python tools/menifee.py parcels --min-acres 80 --vacant     large empty parcels, biggest first
python tools/menifee.py parcel 372100001                    one parcel: facts, centre point, outline
python tools/menifee.py site 372100001 --miles 1            the parcel and everything around it
python tools/menifee.py selfcheck                           did every data source answer just now?
```

### The site report page

Double-click `report/index.html`. To show a different parcel, run this once and reload the page:

```
python tools/build_report.py <APN>                  add --confirmed when it really is the owner's parcel
python -m unittest discover -s tests                offline checks
```

It writes `report/data.js` (the `site` answer plus neighbouring outlines, zoning code names and a USGS 3DEP height
grid). Known gap: the aerial background does not load yet (the USGS layer named in `report/app.js` refuses tiles).

`site` returns, for one parcel number (APN):

| Part | What it says | From |
|---|---|---|
| parcel | acres, zoning code, general plan code, assessor class, assessed value, fire hazard zone, outline | City of Menifee public GIS |
| zoning, general_plan | what the codes mean in words | City of Menifee public GIS |
| surroundings | acres and parcel counts of each zoning type within the chosen distance | City of Menifee public GIS |
| terrain | height above sea level at five points, fall across the site, rough slope | U.S. Geological Survey |
| state_highway_traffic | vehicles per day at the nearest count stations on I-215, SR-74, SR-79 | Caltrans |

Checked on 2026-11-25 with parcel 372100001: 142.1 acres, zoned EDC-CC (Economic Development Corridor, Community
Core), nearly flat (20 ft of fall, about 0.8 % slope), 0.8 miles from the I-215 count station at Scott Road
(about 121,000 to 126,000 vehicles a day).

## What it cannot tell you yet

- Population, income and spending around the site. The Census API now wants a free key; getting one is a
  two-minute sign-up at api.census.gov/data/key_signup.html.
- Traffic on city streets (only state highways are covered). Menifee publishes its own counts.
- Utilities, flood zones, protected habitat and other limits on what can be built.
- Prices: what land, finished lots and buildings sell for now.
- Riverside County's own parcel site blocks automated reading, so the city's copy is used instead.

## What it is not

Zoning and the general plan say what is allowed today. Changing a use goes through the city (general plan
amendment, zone change or specific plan, with public hearings). Parcel outlines are the assessor's drawings, not a
boundary survey. Anything this tool suggests is a starting point for the people whose job it is to decide: the
owner, his engineer and the city's planners.

## Build order

1. Site report: one page for a parcel with the facts above, on a map. *(data: done)*
2. Land-use mix: a first proposal from rules a planner would recognise (retail wants traffic and a corner, homes
   want quiet edges, every plan needs roads, parks and drainage), each choice shown with its reason and adjustable
   by hand.
3. 3D view of the site and the proposed blocks.
4. Costs and returns from his imported numbers.
5. Buyers and builders per use.
6. Traffic and "future city" views.

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

![The Plan page: the suggested mix drawn on the parcel](docs/screens/plan-map.jpg)

| The plan in 3D | Every parcel on the aerial map | Saved lands side by side |
|---|---|---|
| ![3D view of the plan](docs/screens/plan-3d.jpg) | ![Lands list and map](docs/screens/lands.jpg) | ![Compare my lands](docs/screens/compare.jpg) |

## What exists today

`tools/menifee.py` gets real public facts about any parcel in Menifee. No account or key is needed.

```
python tools/menifee.py parcels --min-acres 80 --vacant     large empty parcels, biggest first
python tools/menifee.py parcel 372100001                    one parcel: facts, centre point, outline
python tools/menifee.py site 372100001 --miles 1            the parcel and everything around it
python tools/menifee.py selfcheck                           did every data source answer just now?
```

### The app

Double-click `Start Land Planner.bat` (or run `python -m landplanner`). It starts a small server on this computer
only and opens the app in the browser. It needs Python 3 and nothing else.

- **Cities**: Menifee today. A city is one adapter in `landplanner/cities/` (see `base.py`), so another city is
  added by writing one file for its public parcel and zoning records.
- **Lands**: the city's parcels as a sortable list and on an aerial-photo map. The list starts at 10 acres and
  can be lowered to 1; zoomed in, the map outlines every parcel of any size. Filter by size, zoning and "no
  buildings on record", search by parcel number, save one to My lands. Every map says when the city last changed
  its parcel records and when the aerial photo was taken.
- **My lands**: the parcels you saved, and a table that compares them side by side (mix, homes, jobs, trips, land
  sales, costs, profit) under today's zoning or best use.
- **Each land** has its own pages: Overview, Zoning, Surroundings, Terrain 3D, Traffic, and Plan.
  Surroundings also maps what is being built nearby (the city's project lists), schools and traffic signals;
  Overview links to Google Maps and Street View.
- **Plan** is the prediction: a suggested split of the land into shops, offices, apartments, houses, business
  park and parks, each with a score and the reasons behind it; the plan drawn on the parcel (map and 3D); who is
  building that kind of project nearby (from the city's own project lists); traffic, entrances and signals worth
  studying; a cost sheet you can edit or import from a .csv file; land sales and profit; jobs, residents and taxes.
  Two modes: follow today's zoning, or best use (what the location supports, which may need a zoning change).
  Every number is tagged as measured from a record or as a starting figure to replace with your own.

### Where your data is kept

Everything you save stays on this computer, in the `data/` folder beside the app. It is never uploaded and is not
part of the repository.

- `data/my-lands.json`: My lands.
- `data/plans.json`: your changes to each land's plan (acres, prices, costs, imported cost lines).
- `data/cache/`: copies of answers from the public services, so the app is quick; safe to delete.

Copy the `data/` folder to back it up or to move to another computer.

### How the prediction works

`landplanner/plan.py` scores each use from the facts the app holds: the zoning and what it is meant for, the
nearest state highway's traffic count (Caltrans), the class of the street the parcel fronts and existing signals
(city), people and homes within 1, 3 and 5 miles (2020 Census), the zoning of the land around it, the slope of the
ground (USGS), and what is on the city's project lists nearby. Shops are held to the size of centre the nearby
population supports; parks are sized from drainage and the new residents. `landplanner/geometry.py` then cuts the
parcel's outline into one piece per use: shops on the busiest street, business park toward the highway, houses at
the back, drainage toward the lowest ground. These are rules of thumb, stated on the page beside each result.

```
python -m unittest discover -s tests                offline checks (recorded answers, no network)
python tools/menifee.py selfcheck                   did every public source answer just now?
```

## What it cannot tell you yet

- Income and spending around the site (people and homes are counted; the Census income tables want a free key).
- Traffic counts on city streets (only state highways are counted). Menifee publishes its own counts.
- Utilities, flood zones, protected habitat, soil and other limits on what can be built.
- Real prices and quotes. The Plan page starts from editable figures; replace them with the owner's own.
- Which uses each zone allows outright, with a permit, or not at all (the city's table is not read yet; "fits the
  zoning" means "this is what the zone is for").
- City and agency fees.
- Riverside County's own parcel site blocks automated reading, so the city's copy is used instead.
- The aerial photo is the newest public one (2022 here); newer buildings are not in it.

## What it is not

Zoning and the general plan say what is allowed today. Changing a use goes through the city (general plan
amendment, zone change or specific plan, with public hearings). Parcel outlines are the assessor's drawings, not a
boundary survey. Anything this tool suggests is a starting point for the people whose job it is to decide: the
owner, his engineer and the city's planners.

## Build order

1. The app: cities, lands, My lands and each land's own pages. *(done)*
2. Land-use mix with reasons, adjustable by hand. *(done)*
3. The plan on the land, as a map and in 3D. *(done)*
4. Costs and returns, with imported cost lines. *(done, from starting figures)*
5. Buyers and builders per use, from the city's project lists. *(done)*
6. Traffic, entrances, signals; jobs, residents and taxes. *(done)*
7. Next: the owner's real parcel and real quotes; the zone-by-zone table of allowed uses; a second city.

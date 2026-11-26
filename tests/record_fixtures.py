"""Record what the public services answer, so the tests can run with no network.

    python tests/record_fixtures.py        (needs the internet; re-records everything into tests/fixtures/menifee.json)
    python tests/record_fixtures.py plan   (needs the internet; records only the "land-use plan" questions)
    python tests/record_fixtures.py forecast   (needs the internet; records only the "forecast" questions)
    python tests/record_fixtures.py temecula   (needs the internet; records the second city into tests/fixtures/temecula.json)

It runs the Menifee adapter for real once, and keeps every answer the services gave, keyed by the exact question.
Answers already in the fixture file are kept; a question asked again gets its new answer, and the rest are added.
To keep the file small, bulky answers are thinned in ways that do not change their shape:
  - elevation samples keep only their number and value (the service also sends each point back);
  - the neighbouring outlines keep the first 80 parcels.
The tests replay these answers through tools/menifee.py's one network function (get_json).
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from landplanner.cities import SITE_PARTS  # noqa: E402
from landplanner.cities.menifee import Menifee, tool  # noqa: E402

OUT = Path(__file__).resolve().parent / "fixtures" / "menifee.json"
EXAMPLE = "372100001"      # 142.1 acres, EDC-CC
UNKNOWN = "999999999"      # no such parcel
KEEP_NEIGHBOURS = 80
PLAN_POINT = (-117.166542, 33.652383)          # lon, lat of the example point for the land-use plan sources
PLAN_BOX = (-117.1715, 33.6500, -117.1615, 33.6550)   # west, south, east, north


def key(url, params):
    text = url + "?" + json.dumps(params or {}, sort_keys=True)
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def thin(url, params, answer):
    if url == tool.SAMPLES and "samples" in answer:
        return {"samples": [{"locationId": s.get("locationId"), "value": s.get("value")} for s in answer["samples"]]}
    if url.endswith("/query") and "APN,Zoning,Acres" == (params or {}).get("outFields"):
        return {"features": answer.get("features", [])[:KEEP_NEIGHBOURS]}
    return answer


def record_adapter():
    city = Menifee()
    print("large parcels:", len(city.large_parcels()))
    print("zoning names:", len(city.zone_names()))
    parcel = city.parcel(EXAMPLE)
    for part in SITE_PARTS:
        value = city.site_part(part, parcel)
        print(f"  {part}: {'ok' if value else 'nothing'}")
    try:
        city.parcel(UNKNOWN)
    except Exception as e:  # noqa: BLE001 - "no such parcel" is the answer being recorded
        print("unknown parcel:", e)


def record_plan_sources():
    """Every question the functions under "what a land-use plan starts from" ask, with their default arguments.
    A service that does not answer is reported and skipped (never faked); the rest are still kept. Returns the
    names that did not answer."""
    lon, lat = PLAN_POINT
    steps = {
        "records_updated": lambda: tool.records_updated(),
        "photo_date": lambda: tool.photo_date(lon, lat),
        "parcels_in_box": lambda: len(tool.parcels_in_box(*PLAN_BOX)["parcels"]),
        "streets_near": lambda: len(tool.streets_near(lon, lat)["streets"]),
        "signals_near": lambda: len(tool.signals_near(lon, lat)["signals"]),
        "schools_near": lambda: len(tool.schools_near(lon, lat)["schools"]),
        "projects_near": lambda: len(tool.projects_near(lon, lat)["projects"]),
        "people_near": lambda: tool.people_near(lon, lat)["rings"],
    }
    # and exactly what the adapter asks for the example parcel (its own centre, its reach) for the land-use plan
    city = Menifee()
    parcel = city.parcel(EXAMPLE)
    centre = parcel["centre"]
    for part in SITE_PARTS:
        if SITE_PARTS[part] == "market":
            steps[f"adapter {part}"] = lambda part=part: bool(city.site_part(part, parcel))
    steps["adapter records_updated"] = lambda: city.records_updated()
    steps["adapter photo_date"] = lambda: city.photo_date(round(centre["lon"], 2), round(centre["lat"], 2))
    missing = []
    for name, fn in steps.items():
        try:
            print(f"{name}:", fn())
        except tool.SourceError as e:
            print(f"{name}: DID NOT ANSWER ({e})")
            missing.append(name)
    return missing


def record_forecast_sources():
    """Every question the functions under "what a forecast starts from" ask, with their default arguments, and
    exactly what the adapter asks for the example parcel. Returns the names that did not answer."""
    lon, lat = PLAN_POINT
    steps = {
        "people_before": lambda: tool.people_before(lon, lat)["rings"],
        "regional_plan": lambda: sorted(k for k, v in tool.regional_plan(lon, lat).items() if v),
        "tracts_near": lambda: len(tool.tracts_near(lon, lat)["tracts"]),
    }
    city = Menifee()
    parcel = city.parcel(EXAMPLE)
    for part in SITE_PARTS:
        if SITE_PARTS[part] == "trend":
            steps[f"adapter {part}"] = lambda part=part: bool(city.site_part(part, parcel))
    missing = []
    for name, fn in steps.items():
        try:
            print(f"{name}:", fn())
        except tool.SourceError as e:
            print(f"{name}: DID NOT ANSWER ({e})")
            missing.append(name)
    return missing


TEMECULA_OUT = Path(__file__).resolve().parent / "fixtures" / "temecula.json"
TEMECULA_EXAMPLE = "921300013"     # 19.9 acres, CC (Community Commercial), no buildings on record
TEMECULA_BOX = (-117.1515, 33.5075, -117.1465, 33.5120)
KEEP_TEMECULA = 40


def record_temecula():
    """The second city, recorded the same way into its own file (tests/fixtures/temecula.json): the list of large
    parcels, the zoning names, the example parcel, the parts its Zoning and Plan pages read, and one map view.
    To keep the file small each parcel answer keeps its first 40 parcels and says there are no more, and each
    zoning-map answer keeps the zones those parcels' centres fall in. Nothing else is changed."""
    from landplanner.cities.temecula import Temecula
    real, book, centres = tool.get_json, {}, []

    def box(rings):
        xs, ys = [p[0] for r in rings for p in r], [p[1] for r in rings for p in r]
        return min(xs), min(ys), max(xs), max(ys)

    def thin_city(url, params, answer):
        feats = answer.get("features") if isinstance(answer, dict) else None
        if "temeculaca.gov" not in url or not feats or not url.endswith("/query"):
            return answer
        fields = (params or {}).get("outFields") or ""
        if "/FeatureServer/2/" in url or "/FeatureServer/8/" in url:          # parcels, streets
            kept = feats[:KEEP_TEMECULA]
            centres.extend((f["centroid"]["x"], f["centroid"]["y"]) for f in kept if f.get("centroid"))
            return {**answer, "features": kept, "exceededTransferLimit": False}
        if "/FeatureServer/5/" in url and fields == "ZONING" and (params or {}).get("returnGeometry") == "true":
            kept = []
            for f in feats:
                if not (f.get("geometry") or {}).get("rings"):
                    continue                                  # a zone the city's map has no shape for
                rings = f["geometry"]["rings"]
                west, south, east, north = box(rings)
                if any(west <= x <= east and south <= y <= north and tool.inside(rings, x, y) for x, y in centres):
                    kept.append(f)
            return {**answer, "features": kept}
        return answer

    def recording(url, params=None, timeout=30, tries=2, post=False):
        answer = real(url, params, timeout=timeout, tries=tries, post=post)
        book[key(url, params)] = {"url": url, "answer": thin_city(url, params, thin(url, params, answer))}
        return answer

    tool.get_json = recording
    missing = []
    try:
        city = Temecula()
        print("large parcels:", len(city.large_parcels()))
        print("zoning names:", len(city.zone_names()))
        parcel = city.parcel(TEMECULA_EXAMPLE)
        for part in SITE_PARTS:
            if SITE_PARTS[part] in ("quick", "market"):
                try:
                    print(f"  {part}: {'ok' if city.site_part(part, parcel) else 'nothing'}")
                except tool.SourceError as e:
                    print(f"  {part}: DID NOT ANSWER ({e})")
                    missing.append(part)
        print("map view:", len(city.parcels_in_box(*TEMECULA_BOX)["parcels"]))
        try:
            city.parcel(UNKNOWN)
        except Exception as e:  # noqa: BLE001 - "no such parcel" is the answer being recorded
            print("unknown parcel:", e)
    finally:
        tool.get_json = real
    TEMECULA_OUT.write_text(json.dumps(book, separators=(",", ":"), sort_keys=True), encoding="utf-8", newline="\n")
    print(f"Wrote {TEMECULA_OUT} ({TEMECULA_OUT.stat().st_size // 1024} KB, {len(book)} answers)")
    if missing:
        print("Run it again for:", ", ".join(missing))
    return 1 if missing else 0


def main(argv=None):
    args = argv if argv is not None else sys.argv[1:]
    if "temecula" in args:
        return record_temecula()
    only_plan, only_forecast = "plan" in args, "forecast" in args
    real = tool.get_json
    # keep what is already recorded: the recorder adds to the file
    book = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}

    def recording(url, params=None, timeout=30, tries=2, post=False):
        answer = real(url, params, timeout=timeout, tries=tries, post=post)
        book[key(url, params)] = {"url": url, "answer": thin(url, params, answer)}
        return answer

    tool.get_json = recording
    try:
        if not only_plan and not only_forecast:
            record_adapter()
        missing = [] if only_forecast else record_plan_sources()
        if not only_plan:
            missing += record_forecast_sources()
    finally:
        tool.get_json = real
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(book, separators=(",", ":"), sort_keys=True), encoding="utf-8", newline="\n")
    print(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB, {len(book)} answers)")
    if missing:
        print("Run it again for:", ", ".join(missing))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

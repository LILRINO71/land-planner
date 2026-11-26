"""Record what the public services answer, so the tests can run with no network.

    python tests/record_fixtures.py        (needs the internet; rewrites tests/fixtures/menifee.json)

It runs the Menifee adapter for real once, and keeps every answer the services gave, keyed by the exact question.
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


def key(url, params):
    text = url + "?" + json.dumps(params or {}, sort_keys=True)
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def thin(url, params, answer):
    if url == tool.SAMPLES and "samples" in answer:
        return {"samples": [{"locationId": s.get("locationId"), "value": s.get("value")} for s in answer["samples"]]}
    if url.endswith("/query") and "APN,Zoning,Acres" == (params or {}).get("outFields"):
        return {"features": answer.get("features", [])[:KEEP_NEIGHBOURS]}
    return answer


def main():
    real, book = tool.get_json, {}

    def recording(url, params=None, timeout=30, tries=2, post=False):
        answer = real(url, params, timeout=timeout, tries=tries, post=post)
        book[key(url, params)] = {"url": url, "answer": thin(url, params, answer)}
        return answer

    tool.get_json = recording
    try:
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
    finally:
        tool.get_json = real
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(book, separators=(",", ":"), sort_keys=True), encoding="utf-8", newline="\n")
    print(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB, {len(book)} answers)")


if __name__ == "__main__":
    main()

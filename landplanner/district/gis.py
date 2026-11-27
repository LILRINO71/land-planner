"""GIS layers for trade areas, competitors and parcels (FR-51): GeoJSON as it is, or a zipped shapefile turned into
GeoJSON here (.shp geometry and .dbf attributes, read with struct). Points, lines, polygons and multipoints, with
or without Z and M (which are dropped). Coordinates are not reprojected: a shapefile that is not in latitude and
longitude is still converted, and the answer says so, so it can be exported again in WGS 84 (EPSG:4326).
"""
import io
import json
import math
import struct
import zipfile
from pathlib import PurePosixPath

from . import Problem

MAX_FEATURES = 200000
_SHAPES = {1: "Point", 3: "LineString", 5: "Polygon", 8: "MultiPoint",
           11: "Point", 13: "LineString", 15: "Polygon", 18: "MultiPoint",
           21: "Point", 23: "LineString", 25: "Polygon", 28: "MultiPoint"}
_GEOMS = {"Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon", "GeometryCollection"}


def _bad(text):
    return Problem(400, "bad-request", text)


# ---------------------------------------------------------------- GeoJSON

def _walk_coords(c, out):
    if isinstance(c, (list, tuple)) and c and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in c):
        if len(c) < 2 or not all(math.isfinite(x) for x in c):
            raise _bad("A coordinate in the layer is not a pair of finite numbers.")
        out.append((float(c[0]), float(c[1])))
        return
    if not isinstance(c, (list, tuple)):
        raise _bad("A geometry's coordinates are not lists of numbers.")
    for x in c:
        _walk_coords(x, out)


def _geometry_points(g, out):
    if g is None:
        return
    if not isinstance(g, dict) or g.get("type") not in _GEOMS:
        raise _bad("A feature's geometry is not a GeoJSON geometry.")
    if g["type"] == "GeometryCollection":
        for x in g.get("geometries") or []:
            _geometry_points(x, out)
    else:
        _walk_coords(g.get("coordinates"), out)


def summarise(fc):
    """Check a FeatureCollection; returns {features, geometry_types, bbox, warnings}."""
    if isinstance(fc, dict) and fc.get("type") == "Feature":
        fc = {"type": "FeatureCollection", "features": [fc]}
    if not isinstance(fc, dict) or fc.get("type") != "FeatureCollection" or not isinstance(fc.get("features"), list):
        raise _bad("The file is not a GeoJSON FeatureCollection.")
    if len(fc["features"]) > MAX_FEATURES:
        raise _bad(f"The layer has more than {MAX_FEATURES:,} features.")
    pts, kinds = [], {}
    for f in fc["features"]:
        if not isinstance(f, dict) or f.get("type") != "Feature":
            raise _bad("Something in the layer's features is not a GeoJSON Feature.")
        if f.get("properties") is not None and not isinstance(f["properties"], dict):
            raise _bad("A feature's properties are not a set of named values.")
        _geometry_points(f.get("geometry"), pts)
        t = (f.get("geometry") or {}).get("type") or "none"
        kinds[t] = kinds.get(t, 0) + 1
    warnings = []
    bbox = None
    if pts:
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        bbox = [min(xs), min(ys), max(xs), max(ys)]
        if bbox[0] < -180 or bbox[2] > 180 or bbox[1] < -90 or bbox[3] > 90:
            warnings.append("The coordinates are not latitude and longitude (some are outside ±180/±90), so the layer "
                            "will not sit on the map. Export it again in WGS 84 (EPSG:4326).")
    return {"features": len(fc["features"]), "geometry_types": kinds, "bbox": bbox, "warnings": warnings}, fc


def from_geojson(data):
    try:
        fc = json.loads(data.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        raise _bad("The file is not readable GeoJSON.") from None
    try:
        json.dumps(fc, allow_nan=False)
    except ValueError:
        raise _bad("The layer holds numbers that are not finite.") from None
    return summarise(fc)


# ---------------------------------------------------------------- shapefile

def _dbf(data):
    if len(data) < 32:
        raise _bad("The shapefile's .dbf (attributes) is too short to read.")
    n, header_len, record_len = struct.unpack("<IHH", data[4:12])
    fields, pos = [], 32
    while pos + 32 <= header_len and data[pos] != 0x0D:
        raw = data[pos:pos + 32]
        name = raw[:11].split(b"\x00", 1)[0].decode("latin-1").strip()
        fields.append((name, chr(raw[11]), raw[16], raw[17]))
        pos += 32
    rows, at = [], header_len
    for _ in range(n):
        rec = data[at:at + record_len]
        at += record_len
        if len(rec) < record_len:
            break
        if rec[:1] == b"*":          # deleted
            rows.append(None)
            continue
        off, row = 1, {}
        for name, kind, size, decimals in fields:
            raw = rec[off:off + size]
            off += size
            try:
                text = raw.decode("utf-8").strip()
            except UnicodeDecodeError:
                text = raw.decode("cp1252", "replace").strip()
            if kind in "NF":
                try:
                    v = float(text) if text and text.strip("*") else None
                    row[name] = (int(v) if v is not None and decimals == 0 and v.is_integer() else v) \
                        if v is not None and math.isfinite(v) else None
                except ValueError:
                    row[name] = None
            elif kind == "L":
                row[name] = True if text[:1] in "YyTt" else False if text[:1] in "NnFf" else None
            elif kind == "D" and len(text) == 8 and text.isdigit():
                row[name] = f"{text[:4]}-{text[4:6]}-{text[6:]}"
            else:
                row[name] = text
        rows.append(row)
    return rows


def _ring_area(ring):
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:]))


def _shape(rec):
    """One .shp record's content -> a GeoJSON geometry (or None for a null shape)."""
    if len(rec) < 4:
        return None
    kind = struct.unpack("<i", rec[:4])[0]
    if kind == 0:
        return None
    name = _SHAPES.get(kind)
    if name is None:
        raise _bad(f"The shapefile holds shape type {kind}, which this app does not read (multipatch).")
    if name == "Point":
        x, y = struct.unpack("<2d", rec[4:20])
        return {"type": "Point", "coordinates": [x, y]}
    if name == "MultiPoint":
        n = struct.unpack("<i", rec[36:40])[0]
        pts = struct.unpack(f"<{2 * n}d", rec[40:40 + 16 * n])
        return {"type": "MultiPoint", "coordinates": [[pts[i], pts[i + 1]] for i in range(0, 2 * n, 2)]}
    nparts, npoints = struct.unpack("<2i", rec[36:44])
    parts = list(struct.unpack(f"<{nparts}i", rec[44:44 + 4 * nparts]))
    base = 44 + 4 * nparts
    flat = struct.unpack(f"<{2 * npoints}d", rec[base:base + 16 * npoints])
    pts = [[flat[i], flat[i + 1]] for i in range(0, 2 * npoints, 2)]
    pieces = [pts[s:e] for s, e in zip(parts, parts[1:] + [npoints])]
    if name == "LineString":
        return {"type": "LineString", "coordinates": pieces[0]} if len(pieces) == 1 else \
            {"type": "MultiLineString", "coordinates": pieces}
    # polygons: outer rings run clockwise in a shapefile (negative area here), holes counter-clockwise
    polys = []
    for ring in pieces:
        if _ring_area(ring) <= 0 or not polys:
            polys.append([list(reversed(ring))])        # GeoJSON wants outer rings counter-clockwise
        else:
            polys[-1].append(list(reversed(ring)))
    return {"type": "Polygon", "coordinates": polys[0]} if len(polys) == 1 else \
        {"type": "MultiPolygon", "coordinates": polys}


def _shp(data):
    if len(data) < 100 or struct.unpack(">i", data[:4])[0] != 9994:
        raise _bad("The .shp file is not a shapefile.")
    out, pos = [], 100
    while pos + 8 <= len(data):
        _, words = struct.unpack(">2i", data[pos:pos + 8])
        rec = data[pos + 8:pos + 8 + 2 * words]
        pos += 8 + 2 * words
        try:
            out.append(_shape(rec))
        except struct.error:
            raise _bad("The .shp file is cut short or damaged.") from None
        if len(out) > MAX_FEATURES:
            raise _bad(f"The layer has more than {MAX_FEATURES:,} features.")
    return out


def from_shapefile_zip(data):
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise _bad("The file is not a zip file.") from None
    with z:
        names = [n for n in z.namelist() if not n.endswith("/") and "__MACOSX" not in n]
        shps = [n for n in names if n.lower().endswith(".shp")]
        if len(shps) != 1:
            raise _bad("A zipped shapefile must hold exactly one .shp file (with its .dbf beside it)."
                       if shps else "The zip holds no .shp file.")
        stem = str(PurePosixPath(shps[0]).with_suffix("")).lower()
        part = {n.lower()[len(stem):]: n for n in names if n.lower().startswith(stem + ".")}
        if ".dbf" not in part:
            raise _bad("The zip has a .shp but no .dbf beside it (the attributes).")
        if sum(i.file_size for i in z.infolist()) > 500 * 1024 * 1024:
            raise _bad("The zipped shapefile expands to far too much data.")
        geoms = _shp(z.read(shps[0]))
        rows = _dbf(z.read(part[".dbf"]))
        prj = z.read(part[".prj"]).decode("latin-1", "replace") if ".prj" in part else ""
    feats = []
    for i, g in enumerate(geoms):
        props = rows[i] if i < len(rows) else {}
        if props is None:
            continue
        feats.append({"type": "Feature", "geometry": g, "properties": props})
    info, fc = summarise({"type": "FeatureCollection", "features": feats})
    if not prj:
        info["warnings"].append("The shapefile came without a .prj, so its coordinate system is not known.")
    elif "PROJCS" in prj.upper():
        name = prj.split('"')[1] if '"' in prj else "a projected system"
        info["warnings"].append(f"The shapefile is in {name}, not latitude and longitude; it was not reprojected. "
                                "Export it again in WGS 84 (EPSG:4326) to place it on the map.")
    if len(geoms) != len(rows):
        info["warnings"].append(f"The .shp has {len(geoms)} shapes but the .dbf has {len(rows)} rows.")
    return info, fc


def read_layer(filename, data):
    """(summary, FeatureCollection) from an uploaded .geojson, .json or zipped shapefile."""
    name = str(filename or "").lower()
    if name.endswith(".zip") or data[:4] == b"PK\x03\x04":
        return from_shapefile_zip(data)
    if name.endswith((".geojson", ".json")) or data.lstrip()[:1] == b"{":
        return from_geojson(data)
    raise _bad("A GIS layer is a .geojson file or a zipped shapefile (.zip with .shp, .dbf and .prj).")

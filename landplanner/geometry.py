"""Flat-ground geometry for one parcel: areas, cutting an outline into pieces of chosen sizes, distances to lines.

Everything works in feet on a flat sheet centred on the parcel (fine at parcel size). Standard library only.
A polygon here is a list of (x, y) points, not closed (the last point joins the first).
"""
import math

FT_LAT = 364000.0
SQ_FT_PER_ACRE = 43560.0


class Frame:
    """Turns longitude/latitude into feet east/north of a centre point, and back."""

    def __init__(self, lon0, lat0):
        self.lon0, self.lat0 = lon0, lat0
        self.kx, self.ky = FT_LAT * math.cos(math.radians(lat0)), FT_LAT

    def xy(self, lon, lat):
        return ((lon - self.lon0) * self.kx, (lat - self.lat0) * self.ky)

    def ll(self, x, y):
        return [round(self.lon0 + x / self.kx, 7), round(self.lat0 + y / self.ky, 7)]

    def ring(self, ring):
        pts = [self.xy(p[0], p[1]) for p in ring]
        if len(pts) > 1 and pts[0] == pts[-1]:
            pts.pop()
        return pts

    def ring_ll(self, poly):
        out = [self.ll(x, y) for x, y in poly]
        return out + out[:1]


def rings_acres(rings):
    """The area an outline in longitude/latitude encloses, in acres (holes taken out), or None with no outline."""
    pts = [p for r in rings or [] for p in r]
    if len(pts) < 3:
        return None
    frame = Frame(sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    return abs(sum(signed_area(frame.ring(r)) for r in rings if len(r) >= 4)) / SQ_FT_PER_ACRE


def differs(recorded, measured, share=0.25):
    """True when a recorded size and the size its outline measures are too far apart to be the same land."""
    if not recorded or not measured:
        return False
    return abs(recorded - measured) > share * max(recorded, measured)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def unit(v, fallback=(0.0, 1.0)):
    n = math.hypot(v[0], v[1])
    return (v[0] / n, v[1] / n) if n > 1e-9 else fallback


def perp(v):
    return (-v[1], v[0])


def signed_area(poly):
    return sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
               for i in range(len(poly))) / 2.0 if len(poly) >= 3 else 0.0


def area(poly):
    return abs(signed_area(poly))


def centroid(poly):
    a = signed_area(poly)
    if abs(a) < 1e-9:
        n = max(1, len(poly))
        return (sum(p[0] for p in poly) / n, sum(p[1] for p in poly) / n)
    cx = cy = 0.0
    for i in range(len(poly)):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % len(poly)]
        w = x0 * y1 - x1 * y0
        cx += (x0 + x1) * w
        cy += (y0 + y1) * w
    return (cx / (6 * a), cy / (6 * a))


def inside(poly, p):
    hit = False
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        if (a[1] > p[1]) != (b[1] > p[1]) and p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0]:
            hit = not hit
    return hit


def clip(poly, n, c):
    """The part of the polygon on the side of the line where p.n >= c."""
    out = []
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        da, db = dot(a, n) - c, dot(b, n) - c
        if da >= 0:
            out.append(a)
        if (da >= 0) != (db >= 0):
            t = da / (da - db)
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def extent(poly, n):
    values = [dot(p, n) for p in poly]
    return (min(values), max(values)) if values else (0.0, 0.0)


def split(poly, n, front_area):
    """Cut the polygon with a line at right angles to `n` so that the piece on the +n side has `front_area`.
    Returns (front piece, back piece, c) where the cut line is p.n = c."""
    low, high = extent(poly, n)
    total = area(poly)
    front_area = max(0.0, min(total, front_area))
    lo, hi = low, high
    for _ in range(48):
        mid = (lo + hi) / 2
        if area(clip(poly, n, mid)) > front_area:
            lo = mid
        else:
            hi = mid
    c = (lo + hi) / 2
    return clip(poly, n, c), clip(poly, (-n[0], -n[1]), -c), c


def chord(poly, n, c):
    """The two outermost points where the line p.n = c crosses the polygon's edge, or None."""
    along, hits = perp(n), []
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        da, db = dot(a, n) - c, dot(b, n) - c
        if (da >= 0) != (db >= 0):
            t = da / (da - db)
            hits.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    if len(hits) < 2:
        return None
    hits.sort(key=lambda p: dot(p, along))
    return hits[0], hits[-1]


def near_on_segment(a, b, p):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dy * dy
    t = 0.0 if length < 1e-12 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length))
    q = (a[0] + dx * t, a[1] + dy * t)
    return math.hypot(p[0] - q[0], p[1] - q[1]), q


def near_on_path(path, p):
    """(distance, nearest point) from p to a line made of several points."""
    best = (float("inf"), path[0] if path else p)
    for a, b in zip(path, path[1:]):
        found = near_on_segment(a, b, p)
        if found[0] < best[0]:
            best = found
    return best


def near_on_edge(poly, p):
    return near_on_path(list(poly) + list(poly[:1]), p)


def crossing(a, b, c, d):
    """The point where segment a-b crosses segment c-d, or None."""
    r, s = (b[0] - a[0], b[1] - a[1]), (d[0] - c[0], d[1] - c[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-12:
        return None
    t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den
    u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
    return (a[0] + r[0] * t, a[1] + r[1] * t) if 0 <= t <= 1 and 0 <= u <= 1 else None


def path_to_poly(path, poly):
    """(shortest distance, point on the polygon's edge, point on the path) between a line and a polygon's edge.
    A line that crosses the edge is zero away, at the crossing."""
    best = (float("inf"), None, None)
    edge = list(poly) + list(poly[:1])
    for a, b in zip(path, path[1:]):
        for c, d in zip(edge, edge[1:]):
            hit = crossing(a, b, c, d)
            if hit:
                return 0.0, hit, hit
    for p in path:                      # path points against the edge
        d, q = near_on_path(edge, p)
        if d < best[0]:
            best = (d, q, p)
    for p in poly:                      # corners against the path
        d, q = near_on_path(path, p)
        if d < best[0]:
            best = (d, p, q)
    return best


def layout(poly, items, front, side=None):
    """Divide the polygon among `items` by straight cuts.

    items: [{"id": .., "area": sq ft, "pull": (x, y)}] where `pull` says which way the item wants to sit
    (for example shops pull toward the main street). Areas are scaled to fill the polygon exactly.
    Returns (pieces, cuts): pieces = [{"id", "poly"}], cuts = [((x, y), (x, y)), ...] the cut lines inside the
    polygon (the plan's main internal streets follow them).
    """
    front = unit(front)
    side = unit(side) if side else perp(front)
    items = [dict(i) for i in items if i["area"] > 0]
    pieces, cuts = [], []
    if not items or area(poly) <= 0:
        return pieces, cuts
    scale = area(poly) / sum(i["area"] for i in items)
    for i in items:
        i["area"] *= scale

    def go(shape, group):
        if len(group) == 1 or area(shape) <= 1:
            pieces.append({"id": group[0]["id"], "poly": shape})
            return
        best = None
        for axis in (front, side):
            lo, hi = extent(shape, axis)
            olo, ohi = extent(shape, perp(axis))
            ordered = sorted(group, key=lambda i: -dot(i["pull"], axis))
            values = [dot(i["pull"], axis) for i in ordered]
            # where the wishes differ most is the natural place to cut; a cut across the long way keeps pieces compact
            gap, k = max((values[j - 1] - values[j], j) for j in range(1, len(ordered)))
            score = gap + 0.3 * ((hi - lo) / ((hi - lo) + (ohi - olo) + 1e-9))
            if best is None or score > best[0]:
                best = (score, axis, ordered, k)
        _, axis, ordered, k = best
        first, rest = ordered[:k], ordered[k:]
        a, b, c = split(shape, axis, sum(i["area"] for i in first))
        line = chord(shape, axis, c)
        if line:
            cuts.append(line)
        go(a, first)
        go(b, rest)

    go(list(poly), items)
    return pieces, cuts

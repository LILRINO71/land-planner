"""Shared helpers for the district finance engine (landplanner/district/finance.py and its finance_*.py helpers).

Everything here is pure: plain numbers, dicts and lists in, plain numbers, dicts and lists out. No file, no network.

House rules the whole engine follows:
  * a key ending _usd is dollars, _sf square feet, _ac acres, _pct a percent (3.5 means 3.5%), _mo a month count or a
    monthly figure, _yr a yearly figure. A rent says which one it is (rent_per_sf_yr, rent_per_unit_mo): never both silently.
  * a number that cannot be worked out is None, with a `why` text beside it. Never NaN, never Infinity.
  * an unknown input stays unknown (None) and is counted; it is never turned into zero.
"""
import functools
import math

SF_PER_AC = 43560.0
MONTHS_PER_YEAR = 12

DISCLAIMER = ("Economic calculation under the stated assumptions. It is not an appraisal, a market value opinion, "
              "or a promise of any price, approval or return.")

PUBLIC = []          # the names of the public functions, filled by @public


# ---------------------------------------------------------------- numbers

def num(value, default=None):
    """A finite float from a number or a numeric string ('$1,200', '3.5%'); anything else gives `default`."""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else default
    if isinstance(value, str):
        text = value.replace(",", "").replace("$", "").replace("%", "").strip()
        try:
            out = float(text)
        except ValueError:
            return default
        return out if math.isfinite(out) else default
    return default


def div(a, b):
    """a / b, or None when either is missing or b is zero."""
    a, b = num(a), num(b)
    if a is None or b is None or b == 0:
        return None
    out = a / b
    return out if math.isfinite(out) else None


def pct_of(a, b):
    """a as a percent of b (a / b x 100), or None."""
    d = div(a, b)
    return None if d is None else d * 100.0


def mul(*factors):
    """The product, or None when any factor is missing."""
    out = 1.0
    for f in factors:
        f = num(f)
        if f is None:
            return None
        out *= f
    return out if math.isfinite(out) else None


def add(*terms):
    """The sum, or None when any term is missing."""
    out = 0.0
    for t in terms:
        t = num(t)
        if t is None:
            return None
        out += t
    return out if math.isfinite(out) else None


def frac(pct):
    """A percent as a fraction (3.5 -> 0.035); None stays None."""
    p = num(pct)
    return None if p is None else p / 100.0


def rnd(value, digits=2):
    v = num(value)
    return None if v is None else round(v, digits)


def usd(value):
    return rnd(value, 2)


def pct4(value):
    return rnd(value, 4)


def as_dict(value):
    return value if isinstance(value, dict) else {}


def as_list(value):
    return list(value) if isinstance(value, (list, tuple)) else []


def total_known(values):
    """(sum of the known numbers, how many are unknown, how many in all). An unknown is None or not a number."""
    total, unknown, count = 0.0, 0, 0
    for v in values:
        count += 1
        n = num(v)
        if n is None:
            unknown += 1
        else:
            total += n
    return total, unknown, count


def known_total_text(known_usd, unknown_count):
    """A line that says how much is known and how many items are not (never shows an unknown as $0)."""
    if unknown_count:
        return f"${known_usd:,.0f} known; {unknown_count} item{'s' if unknown_count != 1 else ''} not known"
    return f"${known_usd:,.0f}"


def clean(obj):
    """A copy of an answer with every non-finite number turned into None and tuples turned into lists."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    return obj


def public(fn):
    """Marks a function as part of the public finance API (docs/district-finance.md lists each) and cleans its answer."""
    PUBLIC.append(fn.__name__)

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return clean(fn(*args, **kwargs))
        except (OverflowError, ZeroDivisionError, RecursionError, MemoryError) as e:     # absurd numbers: say so, do not crash a screen
            return {"failed": True, "why": f"The numbers given are too large or cannot be worked with ({type(e).__name__}).", "function": fn.__name__}
    return wrapper


def cap_int(value, default, low, high):
    """An int from a number, held to [low, high] (a huge or missing number cannot make a loop run for ever)."""
    v = num(value)
    if v is None:
        v = default
    return int(max(low, min(high, v)))


def clamp(value, low, high):
    return max(low, min(high, value))


# ---------------------------------------------------------------- present value and rate of return

def npv(rate, flows):
    """Present value of end-of-period flows, flow 0 undiscounted. `rate` is a fraction (0.08), not a percent. None if it cannot be done."""
    r = num(rate)
    if r is None or r <= -1.0:
        return None
    total = 0.0
    try:
        for t, f in enumerate(flows):
            total += (num(f, 0.0)) / ((1.0 + r) ** t)
    except (OverflowError, ZeroDivisionError):
        return None
    return total if math.isfinite(total) else None


def _npv_and_slope(cf, r):
    base = 1.0 + r
    if base <= 0:
        return None, None
    f = d = 0.0
    try:
        for t, c in enumerate(cf):
            disc = base ** t
            f += c / disc
            if t:
                d -= t * c / (disc * base)
    except (OverflowError, ZeroDivisionError):
        return None, None
    if not (math.isfinite(f) and math.isfinite(d)):
        return None, None
    return f, d


def _rate_grid():
    grid = [-0.99 + 0.01 * i for i in range(0, 100)]          # -0.99 .. 0.00
    grid += [0.01 * i for i in range(1, 101)]                  # 0.01 .. 1.00
    grid += [1.0 + 0.1 * i for i in range(1, 91)]              # 1.1 .. 10.0
    r = 10.0
    while r < 1000:
        r *= 1.25
        grid.append(r)
    return grid


def irr(flows, guess=0.10, tol=1e-10, max_iter=100):
    """Internal rate of return of equally spaced flows (flow 0 now, then one per period).

    Newton-Raphson from `guess`; if it does not converge, scan a grid of rates for a change of sign and bisect.
    Returns {irr (fraction), irr_pct, converged, method ('newton' | 'bisection' | None), iterations, residual_npv_usd,
    sign_changes, why}. Never raises, never returns NaN.
    """
    cf = [num(f, 0.0) for f in as_list(flows)]
    signs = [1 if c > 0 else -1 for c in cf if c != 0]
    changes = sum(1 for a, b in zip(signs, signs[1:]) if a != b)
    out = {"irr": None, "irr_pct": None, "converged": False, "method": None, "iterations": 0,
           "residual_npv_usd": None, "sign_changes": changes, "why": None}
    if not any(c < 0 for c in cf) or not any(c > 0 for c in cf):
        out["why"] = "A rate of return needs at least one outflow and one inflow."
        return out
    scale = max(1.0, sum(abs(c) for c in cf))

    def accept(rate, method, iterations):
        f, _ = _npv_and_slope(cf, rate)
        if f is None or abs(f) > 1e-6 * scale:
            return False
        out.update({"irr": rate, "irr_pct": rate * 100.0, "converged": True, "method": method,
                    "iterations": iterations, "residual_npv_usd": f})
        return True

    r = num(guess, 0.1)
    for i in range(1, max_iter + 1):
        f, d = _npv_and_slope(cf, r)
        if f is None or d is None or d == 0:
            break
        new = r - f / d
        if new <= -0.999:
            new = (r - 0.999) / 2.0
        if new > 1e6:
            break
        if abs(new - r) < 1e-13 or abs(f) < tol * scale:
            r = new if abs(new - r) < 1e-13 else r
            if accept(r, "newton", i):
                return out
            break
        r = new
    # bisection fallback on the bracket nearest the guess
    grid = _rate_grid()
    vals = [_npv_and_slope(cf, g)[0] for g in grid]
    brackets = []
    for lo, hi, flo, fhi in zip(grid, grid[1:], vals, vals[1:]):
        if flo is None or fhi is None:
            continue
        if flo == 0:
            brackets.append((lo, lo))
        elif flo * fhi < 0:
            brackets.append((lo, hi))
    if not brackets:
        out["why"] = "No rate between -99% and about 1,000% makes the present value zero."
        return out
    lo, hi = min(brackets, key=lambda b: abs((b[0] + b[1]) / 2.0 - num(guess, 0.1)))
    flo = _npv_and_slope(cf, lo)[0]
    iterations = 0
    for iterations in range(1, 201):
        mid = (lo + hi) / 2.0
        fmid = _npv_and_slope(cf, mid)[0]
        if fmid is None:
            break
        if fmid == 0 or (hi - lo) < 1e-13:
            lo = hi = mid
            break
        if flo * fmid < 0:
            hi = mid
        else:
            lo, flo = mid, fmid
    if accept((lo + hi) / 2.0, "bisection", iterations):
        return out
    out["why"] = "The rate search did not settle."
    return out


def equity_multiple(flows):
    """Money back divided by money put in: sum of inflows / sum of outflows. None if nothing went out."""
    cf = [num(f, 0.0) for f in as_list(flows)]
    out_ = -sum(c for c in cf if c < 0)
    in_ = sum(c for c in cf if c > 0)
    return div(in_, out_) if out_ > 0 else None

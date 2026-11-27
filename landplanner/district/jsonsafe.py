"""JSON that never holds NaN or Infinity, and divisions that never make them."""
import json
import math


def ratio(a, b):
    """a / b, or None when either is missing or b is 0 (never NaN, never Infinity)."""
    try:
        if a is None or b is None or b == 0:
            return None
        out = float(a) / float(b)
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None
    return out if math.isfinite(out) else None


def pct(a, b):
    r = ratio(a, b)
    return None if r is None else r * 100.0


def finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def clean(obj):
    """A copy with every NaN and Infinity replaced by None (tuples and sets become lists)."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [clean(v) for v in obj]
    return obj


def dumps(obj, **kw):
    """JSON text; refuses non-finite numbers after cleaning, so one can never slip out."""
    return json.dumps(clean(obj), allow_nan=False, ensure_ascii=False, **kw)

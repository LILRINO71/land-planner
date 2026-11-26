"""The cities the app knows. Adding a city: write its adapter (see base.py), then add it to ADAPTERS below."""
from .base import CityAdapter, NotFound, SourceError, SITE_PARTS  # noqa: F401
from .menifee import Menifee

ADAPTERS = (Menifee,)


def all_cities():
    """One instance of every adapter, in the order they are listed (the first is the one the app opens on)."""
    return {cls.id: cls() for cls in ADAPTERS}

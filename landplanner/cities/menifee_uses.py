"""Menifee: how Land Planner's six kinds of use are matched to the use names in the city's Development Code.

This is the one place the match is made. The Zoning page shows it, so the owner can see how each was matched and
say if a different row should lead.

The code's tables (Title 9, Article 3; kept in records/menifee_allowed_uses.json, read by tools/record_allowed_uses.py)
list well over a hundred uses by name. Land Planner plans in six broad kinds. For each kind:

  lead   the one row of the code that decides how that kind stands in a zone: allowed outright (P), allowed with
         a conditional use permit (C) or not allowed (--). Two spellings are listed where two tables word the
         same use differently. A table that has no such row does not allow the use: the code's own "Unlisted
         Uses" rule says a use the table does not list is not permitted.
  also   rows that are close relatives. They never change the answer; they are shown beside it, because a zone
         that prohibits the lead row may still allow one of these (a restaurant where general retail is not).
  why    the reason this row was picked to lead.

The names must match the city's wording exactly (capitals, extra spaces and a closing full stop aside). A test
checks every name here against the recorded tables, so a row the city renames is noticed when the code is re-read.
"""
from pathlib import Path

from ..uses import UseTable

FILE = Path(__file__).resolve().parent / "records" / "menifee_allowed_uses.json"

USE_MATCH = {
    "retail": {
        "lead": ("General retail",),
        "also": ("Restaurant", "Restaurants", "Grocery Store", "Grocery Store, Drug Store", "Specialized Retail",
                 "Department stores", "Fast food/quick service, without drive-through",
                 "Convenience stores, not including the sale of motor vehicle fuel"),
        "why": "A shopping centre is leased to ordinary shops first; the code's row for those is “General retail”.",
    },
    "office": {
        "lead": ("Offices, professional and medical", "Offices (professional and medical)"),
        "also": ("Clinics, including but not limited to medical and urgent care", "Banks and financial institutions",
                 "Business services"),
        "why": "Land Planner's “Offices and medical” is this row by name.",
    },
    "apartments": {
        "lead": ("Multiple family", "Multi-family dwellings"),
        "also": ("Multi-family dwellings in commercial zones per AB 2011 & SB 6", "Duplex (two-family dwelling)",
                 "Live/work units", "Live/work units (2)"),
        "why": "Apartments and townhomes are the code's multiple-family dwellings. The state-law route for housing in "
               "commercial zones (AB 2011 and SB 6) has conditions of its own, so it is shown beside the answer "
               "and does not decide it.",
    },
    "homes": {
        "lead": ("Single- family detached", "Single-family residences"),
        "also": ("Manufactured Home", "Accessory Dwelling Unit (ADU)", "Accessory dwelling units"),
        "why": "Houses on their own lots are the code's single-family detached residences.",
    },
    "business": {
        "lead": ("Manufacturing, Light-Intensity",),
        "also": ("Manufacturing, Handcraft", "Manufacturing, Medium-Intensity",
                 "Research & Development (except noxious, explosives, or dangerous materials)",
                 "Research and development (except noxious, explosives, or dangerous materials)",
                 "Fulfillment Center", "Warehousing, logistics and distribution facility",
                 "Wholesale stores and distributors"),
        "why": "A business park is built for light industry first; warehousing and research are shown beside it "
               "because the code treats them differently from zone to zone.",
    },
    "park": {
        "lead": ("Parks and recreation areas", "Park and recreation areas"),
        "also": ("Waterbodies, flood control facilities, including drainage channels, basins and any other drainage "
                 "infrastructure improvements", "Community recreation facilities as a part of a development"),
        "why": "Land Planner's parks are mostly the open space and drainage basins a project has to provide. Where "
               "the table lists parks as a use of their own, that row is read; where it does not, the page says so.",
    },
}

_table = None


def table():
    """The recorded table, read from the file once. Raises OSError or ValueError when the file is missing or broken."""
    global _table
    if _table is None:
        _table = UseTable.from_file(FILE, USE_MATCH)
    return _table

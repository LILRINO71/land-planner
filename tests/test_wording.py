"""The words the engine writes: counted nouns agree with their number, and no sentence on the recorded example holds a
"(s)", a plural after the number 1, an em dash or a word of planners' jargon. Nothing here reaches the network."""
import re
import tempfile
import unittest
from unittest import mock

import support
from support import EXAMPLE, Clock
from landplanner import forecast as F
from landplanner import plan as P
from landplanner.cities.menifee import Menifee
from landplanner.planner import LandPlanner
from landplanner.words import counted, plural_of

import test_forecast as TF
import test_outlook_routes as OR

PLURALS = r"(?:acres|homes|signals|trips|miles|years|projects|tracts|parcels|jobs|lots|units|districts|stations|streets|entrances|buildings|people|apartments)"
ONE_PLURAL = re.compile(r"(?<![\d.,/-])1(?:\.0+)? (?:[\w-]+ ){0,2}" + PLURALS + r"\b", re.I)
BANNED_WORDS = re.compile(r"pipeline|absorption|entitlement|build-out|buildout|take-up|takeup", re.I)
# what the city wrote or the owner typed is not the engine's sentence: project titles and descriptions, names, quotes
CITY_TEXT = {"projects", "description", "title", "builder", "where", "quote", "plain", "source_name", "status", "named", "list", "name",
             "zone_names", "address", "zoning_name", "label"}


def sentences(answer, path=""):
    """Every string in an answer the engine built, with where it sits; city-written text is left out."""
    if isinstance(answer, str):
        yield path, answer
    elif isinstance(answer, dict):
        for key, value in answer.items():
            if key not in CITY_TEXT:
                yield from sentences(value, f"{path}/{key}")
    elif isinstance(answer, (list, tuple)):
        for i, value in enumerate(answer):
            yield from sentences(value, f"{path}[{i}]")


def faults(name, answer):
    found = []
    for path, text in sentences(answer):
        for what, rule in (("a (s)", re.compile(r"\(s\)")), ("a plural after 1", ONE_PLURAL), ("an em dash", re.compile("—")),
                           ("a banned word", BANNED_WORDS)):
            if rule.search(text):
                found.append(f"{name}{path} has {what}: {text[:160]}")
    return found


class Counted(unittest.TestCase):
    def test_the_noun_agrees_with_the_number_as_shown(self):
        self.assertEqual(counted(1, "acre"), "1 acre")
        self.assertEqual(counted(1.0, "acre"), "1 acre")
        self.assertEqual(counted(2, "acre"), "2 acres")
        self.assertEqual(counted(0.5, "acre"), "0.5 acres")
        self.assertEqual(counted(0, "acre"), "0 acres")
        self.assertEqual(counted(1.5, "mile"), "1.5 miles")
        self.assertEqual(counted(17545, "trip"), "17,545 trips")
        self.assertEqual(counted(1, "new signal"), "1 new signal")
        self.assertEqual(counted(2, "new signal"), "2 new signals")

    def test_a_size_that_rounds_to_one_is_singular_because_the_reader_sees_one(self):
        self.assertEqual(counted(0.96, "acre", digits=0), "1 acre")
        self.assertEqual(counted(1.04, "acre", digits=0), "1 acre")
        self.assertEqual(counted(0.996, "acre"), "1 acre")
        self.assertEqual(counted(1.004, "acre"), "1 acre")
        self.assertEqual(counted(1.4, "acre", digits=0), "1 acre")
        self.assertEqual(counted(1.4, "acre", digits=1), "1.4 acres")
        self.assertEqual(counted(1.0, "acre", digits=1), "1.0 acre")

    def test_irregular_and_ordinary_plurals(self):
        self.assertEqual(counted(2, "city", "cities"), "2 cities")
        self.assertEqual(counted(2, "city"), "2 cities")
        self.assertEqual(counted(1, "city"), "1 city")
        self.assertEqual(counted(2, "school district"), "2 school districts")
        self.assertEqual(plural_of("bus"), "buses")
        self.assertEqual(plural_of("day"), "days")
        self.assertEqual(plural_of("tract"), "tracts")

    def test_only_the_noun_when_the_sentence_writes_the_number(self):
        self.assertEqual(counted(1, "acre", with_number=False), "acre")
        self.assertEqual(counted(3, "acre", with_number=False), "acres")


class TheRulesFindWhatTheyLookFor(unittest.TestCase):
    def test_each_rule_catches_its_case_and_leaves_alone_a_good_one(self):
        bad = ["2 new signal(s) to study", "about 1 acres", "1 new homes", "1.0 acres", "At build-out", "the take-up is slow",
               "a pipeline of homes", "a plan — and more", "absorption", "entitlement"]
        for text in bad:
            self.assertTrue(faults("x", {"a": text}), text)
        good = ["142.1 acres", "11 years", "about 1 acre", "1 new signal", "2.1 acres of 21 acres", "12,100 homes", "1/2 acres", "taken up"]
        for text in good:
            self.assertEqual(faults("x", {"a": text}), [], text)

    def test_city_written_text_is_left_alone(self):
        self.assertEqual(faults("x", {"projects": [{"description": "1 acres, entitlement"}]}), [])


class EverySentenceOnTheRecordedExample(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patch = support.offline()
        cls.patch.start()
        cls.folder = tempfile.TemporaryDirectory()
        app = LandPlanner({"menifee": Menifee()}, cls.folder.name, clock=Clock())
        cls.answers = {"plan": app.plan("menifee", EXAMPLE), "best": app.plan("menifee", EXAMPLE, settings={"mode": "best"}),
                       "forecast": app.forecast("menifee", [EXAMPLE])}
        place = OR.made_up_place()
        place["hazards"].update(fossils="Hb", dam_flooding=True)
        economy = OR.made_up_economy()
        with mock.patch.object(Menifee, "economy_part", lambda self, part, year: economy[part]), \
                mock.patch.object(Menifee, "outlook_part", lambda self, part, parcel, tracts=None: place[part]):
            cls.answers["outlook"] = app.outlook("menifee", [EXAMPLE])

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()
        cls.folder.cleanup()

    def test_there_are_sentences_to_look_at(self):
        for name, answer in self.answers.items():
            self.assertGreater(len(list(sentences(answer))), 50, name)

    def test_no_sentence_has_a_bracketed_s_a_plural_after_one_an_em_dash_or_jargon(self):
        found = [f for name, answer in self.answers.items() for f in faults(name, answer)]
        self.assertEqual(found, [])

    def test_the_fossil_rating_is_in_words(self):
        text = " ".join(t for _, t in sentences(self.answers["outlook"]))
        self.assertIn("high (class B)", text)
        self.assertNotRegex(text, r"\bhb\b")


class SmallSitesAreWordedRight(unittest.TestCase):
    """A site of one acre, one home, one signal: the cases where a plural slips through."""

    def plans(self):
        return [{"uses": [TF.use("retail", "Shops", 1.0, sq_ft=7000), TF.use("office", "Offices", 1.0, sq_ft=12700),
                          TF.use("homes", "Houses", 1.0, homes=1), TF.use("park", "Parks", 1.0)],
                 "traffic": {"by_use": {"retail": 100, "office": 50, "homes": 10}}}]

    def test_one_acre_and_one_home_read_as_singular_in_the_forecast(self):
        out = TF.forecast(plans=self.plans(), settings=TF.mine(ready_years=0, capture_pct=100))
        self.assertEqual(faults("forecast", out), [])
        text = " ".join(t for _, t in sentences(out))
        self.assertRegex(text, r"1 acre\b")
        self.assertNotRegex(text, r"\b1 acres")

    def test_one_new_signal_and_one_acre_in_the_checklist(self):
        import test_outlook as TO
        site = dict(TO.site(), acres=1.0)
        plans = [TO.plan(TO.use("homes", "Houses", 1.0, homes=1), signals=1)]
        out = TO.todo(site_=site, fc=TO.forecast(trips=10), plans=plans)
        self.assertEqual(faults("todo", out), [])
        why = next(x["why"] for x in out["steps"] if x["what"] == "Traffic study")
        self.assertIn("and 1 new signal to study at the entrances.", why)
        self.assertIn("on this 1 acre", next(x["why"] for x in out["steps"] if x["what"].startswith("Meet the city")))


class PlanWordsForSmallLand(unittest.TestCase):
    def test_a_one_acre_parcel_and_a_one_acre_zone_read_as_singular(self):
        import test_plan as TP
        out = TP.make(TP.make_parcel(1.0, "RR1", zoning_name="Rural Residential, 1-acre minimum"), TP.rich_parts(1.0))
        self.assertEqual(faults("plan", out), [])
        fig = next(f for f in out["figures"] if f["id"] == "homes_per_acre")
        self.assertIn("at least 1 acre, so at most 1 home an acre", fig["basis"])


if __name__ == "__main__":
    unittest.main()

"""The answer cache and the My lands file."""
import json
import tempfile
import threading
import unittest
from pathlib import Path

from support import Clock, SQUARE, row
from landplanner.cache import Cache
from landplanner.saved import SavedLands


class Caching(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.clock = Clock()
        self.cache = Cache(self.folder.name, self.clock)
        self.calls = 0

    def load(self):
        self.calls += 1
        return {"answer": self.calls}

    def test_a_young_copy_is_not_asked_for_again(self):
        first, meta = self.cache.get("k", 60, self.load)
        self.clock.now += 59
        again, meta2 = self.cache.get("k", 60, self.load)
        self.assertEqual((first, again, self.calls), ({"answer": 1}, {"answer": 1}, 1))
        self.assertEqual(meta2, {"fetched": meta["fetched"], "stale": False})

    def test_an_old_copy_is_asked_for_again(self):
        self.cache.get("k", 60, self.load)
        self.clock.now += 61
        value, meta = self.cache.get("k", 60, self.load)
        self.assertEqual((value, self.calls, meta["fetched"]), ({"answer": 2}, 2, self.clock.now))

    def test_fresh_asks_even_when_the_copy_is_young(self):
        self.cache.get("k", 60, self.load)
        self.assertEqual(self.cache.get("k", 60, self.load, fresh=True)[0], {"answer": 2})

    def test_when_the_source_fails_the_old_copy_is_served_and_marked_stale(self):
        _, meta = self.cache.get("k", 60, self.load)
        self.clock.now += 3600

        def broken():
            raise OSError("down")

        value, later = self.cache.get("k", 60, broken)
        self.assertEqual((value, later), ({"answer": 1}, {"fetched": meta["fetched"], "stale": True}))

    def test_when_the_source_fails_and_there_is_no_copy_the_error_comes_through(self):
        with self.assertRaises(OSError):
            self.cache.get("k", 60, lambda: (_ for _ in ()).throw(OSError("down")))
        self.assertIsNone(self.cache.peek("k"))

    def test_copies_survive_a_restart(self):
        self.cache.get("menifee/large parcels?", 60, self.load)
        reopened = Cache(self.folder.name, self.clock)
        self.assertEqual(reopened.get("menifee/large parcels?", 60, self.load)[0], {"answer": 1})
        self.assertEqual(self.calls, 1)

    def test_an_empty_answer_is_still_an_answer(self):
        self.cache.get("k", 60, lambda: None)
        self.assertEqual(self.cache.get("k", 60, self.load), (None, {"fetched": self.clock.now, "stale": False}))
        self.assertEqual(self.calls, 0)

    def test_different_keys_do_not_collide_and_a_damaged_file_is_ignored(self):
        self.cache.get("a/b", 60, lambda: 1)
        self.cache.get("a-b", 60, lambda: 2)
        self.assertEqual((self.cache.peek("a/b")[0], self.cache.peek("a-b")[0]), (1, 2))
        for f in Path(self.folder.name).glob("*.json"):
            f.write_text("{not json", encoding="utf-8")
        self.assertIsNone(Cache(self.folder.name, self.clock).peek("a/b"))

    def test_two_requests_at_once_ask_the_source_once(self):
        gate, results = threading.Event(), []

        def slow():
            gate.wait(2)
            return self.load()

        threads = [threading.Thread(target=lambda: results.append(self.cache.get("k", 60, slow)[0])) for _ in range(4)]
        for t in threads:
            t.start()
        gate.set()
        for t in threads:
            t.join(5)
        self.assertEqual((self.calls, results), (1, [{"answer": 1}] * 4))

    def test_forget(self):
        self.cache.get("k", 60, self.load)
        self.cache.forget("k")
        self.assertIsNone(Cache(self.folder.name, self.clock).peek("k"))


class MyLands(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "data" / "my-lands.json"
        self.saved = SavedLands(self.path)

    def test_empty_to_start_with_and_no_file_is_written_by_reading(self):
        self.assertEqual(self.saved.all(), [])
        self.assertFalse(self.path.exists())

    def test_save_then_list_newest_first(self):
        self.saved.save("menifee", "372100001", row("372100001", 142.1, "EDC-CC"), now="2026-11-25T10:00:00-08:00")
        self.saved.save("menifee", "372110008", row("372110008", 120.87, "EDC-CC"), now="2026-11-25T11:00:00-08:00")
        self.assertEqual([x["apn"] for x in self.saved.all()], ["372110008", "372100001"])
        self.assertTrue(self.saved.has("menifee", "372100001"))
        self.assertFalse(self.saved.has("elsewhere", "372100001"))

    def test_saved_lands_survive_a_restart_with_their_facts_and_outline(self):
        self.saved.save("menifee", "372100001", row("372100001", 142.1, "EDC-CC"))
        reopened = SavedLands(self.path).all()
        self.assertEqual(len(reopened), 1)
        self.assertEqual((reopened[0]["parcel"]["acres"], reopened[0]["parcel"]["rings"]), (142.1, SQUARE))
        self.assertTrue(reopened[0]["saved_at"])

    def test_saving_twice_keeps_one_entry_and_its_first_date(self):
        self.saved.save("menifee", "372100001", row("372100001", 142.1, "EDC-CC"), now="2026-11-25T10:00:00-08:00")
        self.saved.save("menifee", "372100001", row("372100001", 142.5, "EDC-CC"), now="2026-12-01T10:00:00-08:00")
        only = self.saved.all()
        self.assertEqual(len(only), 1)
        self.assertEqual((only[0]["saved_at"], only[0]["parcel"]["acres"]), ("2026-11-25T10:00:00-08:00", 142.5))

    def test_remove(self):
        self.saved.save("menifee", "372100001", row("372100001", 142.1, "EDC-CC"))
        self.assertTrue(self.saved.remove("menifee", "372100001"))
        self.assertFalse(self.saved.remove("menifee", "372100001"))
        self.assertEqual(SavedLands(self.path).all(), [])

    def test_the_same_number_in_two_cities_is_two_lands(self):
        self.saved.save("menifee", "100000001", row("100000001", 50, "R-1"))
        self.saved.save("tinytown", "100000001", row("100000001", 50, "R-1"))
        self.saved.remove("menifee", "100000001")
        self.assertEqual([(x["city"], x["apn"]) for x in self.saved.all()], [("tinytown", "100000001")])

    def test_an_unreadable_file_is_set_aside_not_written_over(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{this is not json", encoding="utf-8")
        self.assertEqual(self.saved.all(), [])
        self.assertEqual(self.path.with_suffix(".unreadable.json").read_text(encoding="utf-8"), "{this is not json")
        self.saved.save("menifee", "372100001", row("372100001", 142.1, "EDC-CC"))
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["version"], 1)

    def test_many_saves_at_once_all_land(self):
        threads = [threading.Thread(target=self.saved.save, args=("menifee", f"10000000{i}", row(f"10000000{i}", 10 + i, "R-1")))
                   for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)
        self.assertEqual(len(SavedLands(self.path).all()), 8)


if __name__ == "__main__":
    unittest.main()

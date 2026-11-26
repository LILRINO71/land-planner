"""landplanner/sources/fetch.py and tools/menifee.py get_json: a reply that fails halfway is a source that did not answer
(a SourceError), whatever the network does. No network: urllib's urlopen is replaced."""
import http.client
import io
import unittest
import urllib.error
from unittest import mock

import support  # noqa: F401  (puts the project folder on the import path)
from landplanner.cities import SourceError
from landplanner.cities.menifee import tool
from landplanner.sources import fetch


def reply(body=b"hello", error=None):
    """What urlopen returns: a context manager whose read gives the body, or raises `error`."""
    r = mock.MagicMock()
    r.__enter__.return_value.read.side_effect = error if error else (lambda n=-1: body)
    return r


FAILURES = (http.client.IncompleteRead(b"partial"), http.client.RemoteDisconnected("closed"), http.client.BadStatusLine("x"),
            http.client.HTTPException("odd"), ConnectionResetError("reset"), ConnectionError("gone"), OSError("down"),
            TimeoutError("slow"), urllib.error.URLError("no route"))


class GetBytes(unittest.TestCase):
    def setUp(self):
        patch = mock.patch("time.sleep")
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_good_reply_is_its_body(self):
        with mock.patch("urllib.request.urlopen", return_value=reply(b"abc")):
            self.assertEqual(fetch.get_bytes("https://example.test/f"), b"abc")

    def test_every_way_a_reply_can_fail_is_a_source_error(self):
        for error in FAILURES:
            with self.subTest(error=type(error).__name__), mock.patch("urllib.request.urlopen", return_value=reply(error=error)):
                with self.assertRaises(SourceError) as caught:
                    fetch.get_bytes("https://example.test/f", tries=2)
                self.assertIn(type(error).__name__, str(caught.exception))

    def test_a_failure_when_connecting_is_a_source_error_too(self):
        for error in FAILURES:
            with self.subTest(error=type(error).__name__), mock.patch("urllib.request.urlopen", side_effect=error):
                with self.assertRaises(SourceError):
                    fetch.get_bytes("https://example.test/f", tries=1)

    def test_a_cut_reply_is_asked_again_and_the_second_try_can_answer(self):
        with mock.patch("urllib.request.urlopen", side_effect=[reply(error=http.client.IncompleteRead(b"x")), reply(b"whole")]) as opened:
            self.assertEqual(fetch.get_bytes("https://example.test/f", tries=2), b"whole")
        self.assertEqual(opened.call_count, 2)

    def test_a_file_over_the_limit_is_a_source_error_and_is_not_asked_again(self):
        with mock.patch("urllib.request.urlopen", return_value=reply(b"x" * 11)) as opened:
            with self.assertRaises(SourceError):
                fetch.get_bytes("https://example.test/f", limit=10, tries=3)
        self.assertEqual(opened.call_count, 1)

    def test_get_text_fails_the_same_way(self):
        with mock.patch("urllib.request.urlopen", return_value=reply(error=http.client.IncompleteRead(b"x"))):
            with self.assertRaises(SourceError):
                fetch.get_text("https://example.test/f", tries=1)


class GetJson(unittest.TestCase):
    def setUp(self):
        patch = mock.patch("time.sleep")
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_good_reply_is_its_json(self):
        with mock.patch("urllib.request.urlopen", return_value=reply(b'{"a": 1}')):
            self.assertEqual(tool.get_json("https://example.test/j"), {"a": 1})

    def test_every_way_a_reply_can_fail_is_a_source_error(self):
        for error in FAILURES:
            with self.subTest(error=type(error).__name__), mock.patch("urllib.request.urlopen", return_value=reply(error=error)):
                with self.assertRaises(tool.SourceError):
                    tool.get_json("https://example.test/j", tries=2)

    def test_a_reply_that_is_not_json_is_a_source_error(self):
        with mock.patch("urllib.request.urlopen", return_value=reply(b"<html>")):
            with self.assertRaises(tool.SourceError):
                tool.get_json("https://example.test/j", tries=1)

    def test_the_sources_wrapper_turns_a_cut_reply_into_the_apps_source_error(self):
        with mock.patch("urllib.request.urlopen", return_value=reply(error=http.client.IncompleteRead(b"x"))):
            with self.assertRaises(SourceError):
                fetch.get_json("https://example.test/j", tries=1)


if __name__ == "__main__":
    unittest.main()

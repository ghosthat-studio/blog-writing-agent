import tempfile
import unittest
from unittest import mock

from core import search


def _fake_results(n=3, prefix="r"):
    return {"results": [
        {"title": f" {prefix}{i} ", "url": f"http://e/{prefix}{i}", "content": "c" * 400}
        for i in range(n)
    ]}


class SearchTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        cache_patch = mock.patch.object(search, "_CACHE_DIR", self._tmp.name)
        cache_patch.start()
        self.addCleanup(cache_patch.stop)
        self.addCleanup(self._tmp.cleanup)
        pace_patch = mock.patch.object(search.time, "sleep")
        self.sleep = pace_patch.start()
        self.addCleanup(pace_patch.stop)


class TestSearch(SearchTestCase):
    def test_returns_shaped_results_capped_at_n(self):
        with mock.patch.object(search, "_fetch", return_value=_fake_results(8)):
            out = search.search("q", n=5)
        self.assertEqual(len(out), 5)
        self.assertEqual(out[0]["title"], "r0")            # stripped
        self.assertEqual(out[0]["url"], "http://e/r0")
        self.assertIn("content", out[0])

    def test_second_identical_query_served_from_cache(self):
        with mock.patch.object(search, "_fetch", return_value=_fake_results()) as f:
            search.search("cached-q")
            search.search("cached-q")
        self.assertEqual(f.call_count, 1)

    def test_returns_empty_list_when_engine_never_answers(self):
        with mock.patch.object(search, "_fetch", return_value={}) as f:
            out = search.search("q", retries=2)
        self.assertEqual(out, [])
        self.assertEqual(f.call_count, 3)  # initial + 2 retries

    def test_fetch_error_degrades_to_empty_not_raise(self):
        with mock.patch.object(search, "_fetch", side_effect=OSError("down")):
            self.assertEqual(search.search("q", retries=1), [])

    def test_empty_results_are_not_cached(self):
        with mock.patch.object(search, "_fetch", return_value={}):
            search.search("flaky-q", retries=0)
        with mock.patch.object(search, "_fetch", return_value=_fake_results()) as f:
            out = search.search("flaky-q", retries=0)
        self.assertEqual(f.call_count, 1)   # cache miss -> engine hit
        self.assertEqual(len(out), 3)


class TestGrounding(SearchTestCase):
    def test_formats_sourced_blocks_per_query(self):
        with mock.patch.object(search, "_fetch", return_value=_fake_results(2)):
            text = search.grounding(["what is x", "price of y"])
        self.assertIn("### Results for: what is x", text)
        self.assertIn("### Results for: price of y", text)
        self.assertIn("http://e/r0", text)

    def test_snippets_are_trimmed(self):
        with mock.patch.object(search, "_fetch", return_value=_fake_results(1)):
            text = search.grounding(["q"])
        self.assertNotIn("c" * 400, text)  # 400-char content trimmed to 300

    def test_queries_with_no_results_are_skipped(self):
        with mock.patch.object(search, "_fetch", return_value={}):
            self.assertEqual(search.grounding(["nope"]), "")


if __name__ == "__main__":
    unittest.main()

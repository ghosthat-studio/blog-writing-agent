import json
import tempfile
import unittest
from pathlib import Path

from core import datapool


class TestDatapool(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_load_missing_file_returns_default(self):
        self.assertEqual(datapool.load_json(self.dir, "nope.json", {"ideas": []}),
                         {"ideas": []})

    def test_load_missing_file_returns_empty_dict_without_default(self):
        self.assertEqual(datapool.load_json(self.dir, "nope.json"), {})

    def test_save_then_load_round_trips(self):
        datapool.save_json(self.dir, "pool.json", {"published": ["a", "b"]})
        self.assertEqual(datapool.load_json(self.dir, "pool.json"),
                         {"published": ["a", "b"]})

    def test_save_creates_directory(self):
        deep = str(Path(self.dir) / "memory")
        datapool.save_json(deep, "pool.json", {"x": 1})
        self.assertEqual(datapool.load_json(deep, "pool.json"), {"x": 1})

    def test_saved_file_is_readable_json_with_unicode(self):
        datapool.save_json(self.dir, "pool.json", {"title": "café — naïve"})
        raw = (Path(self.dir) / "pool.json").read_text(encoding="utf-8")
        self.assertIn("café", raw)  # ensure_ascii off: file stays human-readable
        self.assertEqual(json.loads(raw), {"title": "café — naïve"})


if __name__ == "__main__":
    unittest.main()

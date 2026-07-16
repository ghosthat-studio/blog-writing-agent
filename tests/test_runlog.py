import datetime
import json
import tempfile
import unittest
from pathlib import Path

from core import runlog


class TestRunlog(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _logfile(self):
        day = datetime.date.today().isoformat()
        return Path(self.dir) / f"agent-{day}.jsonl"

    def test_log_appends_one_json_line(self):
        runlog.log(self.dir, "agent", "draft", slug="my-post")
        lines = self._logfile().read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        self.assertEqual(rec["agent"], "agent")
        self.assertEqual(rec["kind"], "draft")
        self.assertEqual(rec["slug"], "my-post")
        self.assertIn("ts", rec)

    def test_two_logs_append_two_lines(self):
        runlog.log(self.dir, "agent", "draft")
        runlog.log(self.dir, "agent", "revise")
        lines = self._logfile().read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(l)["kind"] for l in lines], ["draft", "revise"])

    def test_log_creates_directory(self):
        deep = str(Path(self.dir) / "runs")
        runlog.log(deep, "agent", "draft")
        day = datetime.date.today().isoformat()
        self.assertTrue((Path(deep) / f"agent-{day}.jsonl").exists())

    def test_log_returns_the_record(self):
        rec = runlog.log(self.dir, "agent", "factcheck", report="r.md")
        self.assertEqual(rec["report"], "r.md")


if __name__ == "__main__":
    unittest.main()

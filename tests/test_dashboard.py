import json
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from dashboard import server as dash


def _post(url, data):
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read())


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read().decode("utf-8")


class DashboardTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)
        cfg = {
            "name": "Testa",
            "model": {"utility": {"backend": "ollama", "url": "http://x", "model": "m"}},
            "search": {"enabled": False},
            "state_dir": "state",
            "publish": {"dir": str(Path(self.root, "published"))},
        }
        Path(self.root, "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        Path(self.root, "instructions.md").write_text("M", encoding="utf-8")
        self.drafts = Path(self.root, "state", "drafts")
        self.drafts.mkdir(parents=True)
        self.srv = dash.make_server(self.root, port=0)
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]
        import threading
        t = threading.Thread(target=self.srv.serve_forever, daemon=True)
        t.start()
        self.addCleanup(self.srv.shutdown)

    def _wait_for_job(self, job_id, timeout=5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, body = _get(self.base + "/api/jobs")
            job = next(j for j in json.loads(body)["jobs"] if j["id"] == job_id)
            if job["status"] != "running":
                return job
            time.sleep(0.05)
        raise AssertionError("job never finished")


class TestPages(DashboardTestCase):
    def test_root_serves_the_dashboard_page(self):
        status, body = _get(self.base + "/")
        self.assertEqual(status, 200)
        self.assertIn("<title>", body)

    def test_unknown_path_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            _get(self.base + "/nope")
        self.assertEqual(ctx.exception.code, 404)


class TestState(DashboardTestCase):
    def test_state_reports_name_and_drafts(self):
        (self.drafts / "a-post.html").write_text("<h1>A</h1>", encoding="utf-8")
        status, body = _get(self.base + "/api/state")
        d = json.loads(body)
        self.assertEqual(d["name"], "Testa")
        self.assertEqual([x["file"] for x in d["drafts"]], ["a-post.html"])
        self.assertFalse(d["drafts"][0]["approved"])

    def test_working_files_are_not_listed_as_drafts(self):
        (self.drafts / "a-post.html").write_text("x", encoding="utf-8")
        (self.drafts / "a-post-draft.html").write_text("x", encoding="utf-8")
        (self.drafts / "a-post-review.md").write_text("x", encoding="utf-8")
        _, body = _get(self.base + "/api/state")
        self.assertEqual([x["file"] for x in json.loads(body)["drafts"]], ["a-post.html"])


class TestDraftContent(DashboardTestCase):
    def test_reads_a_draft(self):
        (self.drafts / "a.html").write_text("<h1>Hello</h1>", encoding="utf-8")
        status, body = _get(self.base + "/api/draft?file=a.html")
        self.assertIn("Hello", body)

    def test_path_traversal_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            _get(self.base + "/api/draft?file=../config.json")
        self.assertEqual(ctx.exception.code, 400)

    def test_missing_draft_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            _get(self.base + "/api/draft?file=nope.html")
        self.assertEqual(ctx.exception.code, 404)


class TestRunJob(DashboardTestCase):
    def test_draft_job_runs_and_reports_its_output(self):
        def fake_draft(cfg, root, idea, review=False, do_search=True):
            p = Path(root, "state", "drafts", "new-post.html")
            p.write_text("<h1>%s</h1>" % idea, encoding="utf-8")
            return str(p)
        with mock.patch.object(dash.agent, "draft", fake_draft):
            _, resp = _post(self.base + "/api/run", {"mode": "draft", "idea": "an idea"})
            job = self._wait_for_job(resp["job_id"])
        self.assertEqual(job["status"], "done")
        self.assertIn("new-post.html", job["output"])

    def test_failed_job_reports_the_error_plainly(self):
        def boom(cfg, root, idea, review=False, do_search=True):
            raise RuntimeError("Could not reach your model at http://x — is it running?")
        with mock.patch.object(dash.agent, "draft", boom):
            _, resp = _post(self.base + "/api/run", {"mode": "draft", "idea": "i"})
            job = self._wait_for_job(resp["job_id"])
        self.assertEqual(job["status"], "error")
        self.assertIn("is it running", job["error"])

    def test_unknown_mode_is_400(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            _post(self.base + "/api/run", {"mode": "banana"})
        self.assertEqual(ctx.exception.code, 400)


class TestApprove(DashboardTestCase):
    def test_approve_marks_and_publishes(self):
        (self.drafts / "a.html").write_text("<h1>A</h1>", encoding="utf-8")
        status, resp = _post(self.base + "/api/approve", {"file": "a.html"})
        self.assertTrue(resp["approved"])
        self.assertTrue((self.drafts / "a.html.approved").exists())
        self.assertEqual(Path(self.root, "published", "a.html").read_text(encoding="utf-8"),
                         "<h1>A</h1>")
        _, body = _get(self.base + "/api/state")
        self.assertTrue(json.loads(body)["drafts"][0]["approved"])

    def test_approve_without_publish_dir_still_marks(self):
        cfg = json.loads(Path(self.root, "config.json").read_text(encoding="utf-8"))
        del cfg["publish"]
        Path(self.root, "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        (self.drafts / "b.html").write_text("x", encoding="utf-8")
        _, resp = _post(self.base + "/api/approve", {"file": "b.html"})
        self.assertTrue(resp["approved"])
        self.assertTrue((self.drafts / "b.html.approved").exists())


class TestRunlogEndpoint(DashboardTestCase):
    def test_runlog_returns_recent_records(self):
        from core import runlog
        runlog.log(str(Path(self.root, "state", "runs")), "testa", "draft", slug="s")
        _, body = _get(self.base + "/api/runlog")
        recs = json.loads(body)["records"]
        self.assertEqual(recs[-1]["kind"], "draft")


if __name__ == "__main__":
    unittest.main()

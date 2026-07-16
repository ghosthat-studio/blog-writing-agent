import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agent
from core import llm, search

DRAFT_HTML = "<!-- slug: test-post -->\n<h1>Post</h1><p>Qwen 9.9 costs $5.</p>"
CLEAN_FACTS = "CLAIM Qwen 9.9 -> VERIFIED (source)"
BAD_FACTS = "CLAIM Qwen 9.9 -> WRONG (it is Qwen 3.5, source)"
FIXED_HTML = "<!-- slug: test-post -->\n<h1>Post</h1><p>Qwen 3.5 costs $5.</p>"


def _cfg(root, search_enabled=True):
    cfg = {
        "name": "Testa",
        "instructions": "instructions.md",
        "voice": "voice.md",
        "model": {
            "utility": {"backend": "ollama", "url": "http://u", "model": "small"},
            "draft": {"backend": "openai", "base_url": "http://d", "model": "big"},
        },
        "search": {"enabled": search_enabled, "url": "http://s"},
        "state_dir": "state",
    }
    Path(root, "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    Path(root, "instructions.md").write_text("Mission: write posts.", encoding="utf-8")
    return cfg


def _fake_generate(responses):
    """Return a llm.generate stand-in that answers by matching prompt content.
    responses: list of (substring_of_prompt, reply)."""
    def gen(tier, prompt, system=None, temperature=None):
        for needle, reply in responses:
            if needle in prompt:
                return reply
        raise AssertionError("unexpected prompt: %s..." % prompt[:80])
    return gen


class ModeTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)
        self.cfg = _cfg(self.root)


class TestAskTiering(ModeTestCase):
    def test_utility_and_draft_route_to_their_tiers(self):
        seen = []
        def gen(tier, prompt, system=None, temperature=None):
            seen.append(tier["model"])
            return "ok"
        with mock.patch.object(llm, "generate", gen):
            agent._ask(self.cfg, self.root, "task", tier="utility")
            agent._ask(self.cfg, self.root, "task", tier="draft")
        self.assertEqual(seen, ["small", "big"])

    def test_draft_tier_falls_back_to_utility_loudly(self):
        def gen(tier, prompt, system=None, temperature=None):
            if tier["model"] == "big":
                raise RuntimeError("Could not reach your model at http://d")
            return "fallback prose"
        with mock.patch.object(llm, "generate", gen):
            with mock.patch.object(agent, "_warn") as warn:
                out = agent._ask(self.cfg, self.root, "task", tier="draft")
        self.assertEqual(out, "fallback prose")
        warn.assert_called_once()
        self.assertIn("big", warn.call_args[0][0])


class TestSelfReview(ModeTestCase):
    def test_clean_facts_ship_the_draft_untouched(self):
        gen = _fake_generate([
            ("web-search queries", "q1\nq2"),
            ("Fact-check the following draft", CLEAN_FACTS),
        ])
        with mock.patch.object(llm, "generate", gen), \
             mock.patch.object(search, "grounding", return_value="### Results"):
            notes, out = agent._self_review(self.cfg, self.root, DRAFT_HTML)
        self.assertEqual(out, DRAFT_HTML)
        self.assertIn("VERIFIED", notes)

    def test_fact_issues_trigger_a_surgical_fix(self):
        gen = _fake_generate([
            ("web-search queries", "q1"),
            ("Fact-check the following draft", BAD_FACTS),
            ("Apply these fact-check findings", FIXED_HTML),
        ])
        with mock.patch.object(llm, "generate", gen), \
             mock.patch.object(search, "grounding", return_value="### Results"):
            notes, out = agent._self_review(self.cfg, self.root, DRAFT_HTML)
        self.assertEqual(out, FIXED_HTML)
        self.assertIn("WRONG", notes)

    def test_search_disabled_skips_the_factcheck(self):
        cfg = _cfg(self.root, search_enabled=False)
        with mock.patch.object(llm, "generate") as gen:
            notes, out = agent._self_review(cfg, self.root, DRAFT_HTML)
        gen.assert_not_called()
        self.assertEqual(out, DRAFT_HTML)
        self.assertIn("skipped", notes)


class TestDraftMode(ModeTestCase):
    def test_draft_writes_the_file_and_the_runlog(self):
        gen = _fake_generate([("Write the full blog post", DRAFT_HTML)])
        with mock.patch.object(llm, "generate", gen):
            path = agent.draft(self.cfg, self.root, "an idea", review=False)
        self.assertTrue(path.endswith("test-post.html"))
        self.assertEqual(Path(path).read_text(encoding="utf-8"), DRAFT_HTML)
        runs = list(Path(self.root, "state", "runs").glob("*.jsonl"))
        self.assertEqual(len(runs), 1)
        rec = json.loads(runs[0].read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(rec["kind"], "draft")
        self.assertEqual(rec["slug"], "test-post")

    def test_reviewed_draft_keeps_the_original_for_diffing(self):
        gen = _fake_generate([
            ("Write the full blog post", DRAFT_HTML),
            ("web-search queries", "q1"),
            ("Fact-check the following draft", BAD_FACTS),
            ("Apply these fact-check findings", FIXED_HTML),
        ])
        with mock.patch.object(llm, "generate", gen), \
             mock.patch.object(search, "grounding", return_value="### Results"):
            path = agent.draft(self.cfg, self.root, "an idea", review=True)
        drafts = Path(self.root, "state", "drafts")
        self.assertEqual(Path(path).read_text(encoding="utf-8"), FIXED_HTML)
        self.assertEqual((drafts / "test-post-draft.html").read_text(encoding="utf-8"), DRAFT_HTML)
        self.assertIn("WRONG", (drafts / "test-post-review.md").read_text(encoding="utf-8"))


class TestFactcheckMode(ModeTestCase):
    def test_factcheck_writes_a_report(self):
        src = Path(self.root, "post.html")
        src.write_text(DRAFT_HTML, encoding="utf-8")
        gen = _fake_generate([
            ("web-search queries", "q1"),
            ("Fact-check the following draft", CLEAN_FACTS),
        ])
        with mock.patch.object(llm, "generate", gen), \
             mock.patch.object(search, "grounding", return_value="### Results"):
            report = agent.factcheck(self.cfg, self.root, str(src))
        self.assertIn("VERIFIED", Path(report).read_text(encoding="utf-8"))

    def test_missing_file_fails_plainly(self):
        with self.assertRaises(RuntimeError) as ctx:
            agent.factcheck(self.cfg, self.root, str(Path(self.root, "nope.html")))
        self.assertIn("nope.html", str(ctx.exception))


class TestReviseMode(ModeTestCase):
    def test_revise_writes_rev_file_and_keeps_original(self):
        src = Path(self.root, "post.html")
        src.write_text(DRAFT_HTML, encoding="utf-8")
        gen = _fake_generate([
            ("web-search queries", "q1"),
            ("Fact-check the following draft", BAD_FACTS),
            ("Apply these fact-check findings", FIXED_HTML),
        ])
        with mock.patch.object(llm, "generate", gen), \
             mock.patch.object(search, "grounding", return_value="### Results"):
            out = agent.revise(self.cfg, self.root, str(src))
        self.assertTrue(out.endswith("post-rev.html"))
        self.assertEqual(Path(out).read_text(encoding="utf-8"), FIXED_HTML)
        self.assertEqual(src.read_text(encoding="utf-8"), DRAFT_HTML)


class TestApplyMode(ModeTestCase):
    def test_apply_overwrites_in_place_with_backup(self):
        src = Path(self.root, "post.html")
        src.write_text(DRAFT_HTML, encoding="utf-8")
        cfg = _cfg(self.root, search_enabled=False)
        gen = _fake_generate([("Apply the following change", FIXED_HTML)])
        with mock.patch.object(llm, "generate", gen):
            agent.apply_note(cfg, self.root, str(src), "fix the version number")
        self.assertEqual(src.read_text(encoding="utf-8"), FIXED_HTML)
        self.assertEqual(Path(str(src) + ".bak").read_text(encoding="utf-8"), DRAFT_HTML)


if __name__ == "__main__":
    unittest.main()

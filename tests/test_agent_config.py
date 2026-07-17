import json
import tempfile
import unittest
from pathlib import Path

import agent


def _write_config(root, cfg=None):
    cfg = cfg if cfg is not None else {
        "name": "Blog Writing Agent",
        "instructions": "instructions.md",
        "voice": "voice.md",
        "model": {
            "utility": {"backend": "ollama", "url": "http://x", "model": "small"},
            "draft": {"backend": "openai", "base_url": "http://y", "model": "big"},
        },
        "search": {"enabled": True, "url": "http://s"},
        "state_dir": "state",
    }
    Path(root, "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return cfg


class ConfigTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)


class TestLoadConfig(ConfigTestCase):
    def test_loads_config_json(self):
        _write_config(self.root)
        cfg = agent.load_config(self.root)
        self.assertEqual(cfg["name"], "Blog Writing Agent")

    def test_missing_config_says_copy_the_example(self):
        with self.assertRaises(RuntimeError) as ctx:
            agent.load_config(self.root)
        self.assertIn("config.example.json", str(ctx.exception))

    def test_invalid_json_names_the_file_plainly(self):
        Path(self.root, "config.json").write_text("{not json", encoding="utf-8")
        with self.assertRaises(RuntimeError) as ctx:
            agent.load_config(self.root)
        self.assertIn("config.json", str(ctx.exception))


class TestSystemPrompt(ConfigTestCase):
    def test_prompt_carries_name_instructions_and_voice(self):
        cfg = _write_config(self.root)
        Path(self.root, "instructions.md").write_text("MISSION TEXT", encoding="utf-8")
        Path(self.root, "voice.md").write_text("VOICE SAMPLES", encoding="utf-8")
        prompt = agent.system_prompt(cfg, self.root)
        self.assertIn("Blog Writing Agent", prompt)
        self.assertIn("MISSION TEXT", prompt)
        self.assertIn("VOICE SAMPLES", prompt)

    def test_missing_voice_file_is_fine(self):
        cfg = _write_config(self.root)
        Path(self.root, "instructions.md").write_text("MISSION", encoding="utf-8")
        prompt = agent.system_prompt(cfg, self.root)
        self.assertIn("MISSION", prompt)
        self.assertNotIn("voice", prompt.lower().split("mission")[0])  # no empty voice block

    def test_missing_instructions_says_copy_the_example(self):
        cfg = _write_config(self.root)
        with self.assertRaises(RuntimeError) as ctx:
            agent.system_prompt(cfg, self.root)
        self.assertIn("instructions.example.md", str(ctx.exception))

    def test_renaming_her_changes_the_prompt(self):
        cfg = _write_config(self.root)
        cfg["name"] = "Imogen"
        Path(self.root, "instructions.md").write_text("M", encoding="utf-8")
        self.assertIn("Imogen", agent.system_prompt(cfg, self.root))

    def test_she_knows_todays_date(self):
        import datetime
        cfg = _write_config(self.root)
        Path(self.root, "instructions.md").write_text("M", encoding="utf-8")
        prompt = agent.system_prompt(cfg, self.root)
        today = datetime.date.today()
        self.assertIn(today.strftime("%B"), prompt)   # month name
        self.assertIn(str(today.year), prompt)        # current year


class TestHelpers(unittest.TestCase):
    def test_slug_extracted_from_html_comment(self):
        self.assertEqual(agent._slug_of("<!-- slug: my-post -->\n<h1>x</h1>"), "my-post")

    def test_slug_falls_back_when_absent(self):
        self.assertEqual(agent._slug_of("<h1>x</h1>", fallback="fb"), "fb")

    def test_fact_issues_detected(self):
        self.assertTrue(agent._has_fact_issues("CLAIM -> WRONG (correction)"))
        self.assertTrue(agent._has_fact_issues("CLAIM -> UNVERIFIED"))

    def test_clean_factcheck_has_no_issues(self):
        self.assertFalse(agent._has_fact_issues("CLAIM -> VERIFIED (source)"))
        self.assertFalse(agent._has_fact_issues(None))
        self.assertFalse(agent._has_fact_issues(""))


if __name__ == "__main__":
    unittest.main()

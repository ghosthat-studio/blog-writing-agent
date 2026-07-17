import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agent


def _write_setup(root, search_enabled=True):
    cfg = {
        "name": "Testa",
        "instructions": "instructions.md",
        "model": {
            "utility": {"backend": "ollama", "url": "http://u", "model": "small"},
            "draft": {"backend": "openai", "base_url": "http://d", "model": "big"},
        },
        "search": {"enabled": search_enabled, "url": "http://s"},
        "state_dir": "state",
    }
    Path(root, "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    Path(root, "instructions.md").write_text("M", encoding="utf-8")
    return cfg


def _result(checks, name):
    return next(c for c in checks if c[0] == name)


class DoctorTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)


class TestDoctorConfig(DoctorTestCase):
    def test_missing_config_fails_with_the_copy_instruction(self):
        checks = agent.doctor(self.root)
        name, ok, detail = _result(checks, "config")
        self.assertFalse(ok)
        self.assertIn("config.example.json", detail)

    def test_missing_instructions_fails_plainly(self):
        _write_setup(self.root)
        Path(self.root, "instructions.md").unlink()
        with mock.patch.object(agent, "_get_json", return_value={}):
            checks = agent.doctor(self.root)
        name, ok, detail = _result(checks, "instructions")
        self.assertFalse(ok)
        self.assertIn("instructions.example.md", detail)


class TestDoctorModels(DoctorTestCase):
    def test_unreachable_backend_says_is_it_running(self):
        _write_setup(self.root)
        with mock.patch.object(agent, "_get_json", side_effect=OSError("refused")):
            checks = agent.doctor(self.root)
        name, ok, detail = _result(checks, "model:utility")
        self.assertFalse(ok)
        self.assertIn("running", detail)

    def test_model_name_missing_from_ollama_is_caught(self):
        _write_setup(self.root)
        tags = {"models": [{"name": "other:7b"}], "data": [{"id": "big"}]}
        with mock.patch.object(agent, "_get_json", return_value=tags):
            checks = agent.doctor(self.root)
        name, ok, detail = _result(checks, "model:utility")
        self.assertFalse(ok)
        self.assertIn("small", detail)
        self.assertIn("pull", detail.lower())

    def test_reachable_backend_with_model_passes(self):
        _write_setup(self.root)
        tags = {"models": [{"name": "small"}], "data": [{"id": "big"}]}
        with mock.patch.object(agent, "_get_json", return_value=tags):
            checks = agent.doctor(self.root)
        self.assertTrue(_result(checks, "model:utility")[1])
        self.assertTrue(_result(checks, "model:draft")[1])


class TestDoctorSearch(DoctorTestCase):
    def test_json_format_disabled_names_the_settings_fix(self):
        _write_setup(self.root)
        def get(url, timeout=5):
            if "/search" in url:
                raise RuntimeError("HTTP 403 from http://s")
            return {"models": [{"name": "small"}], "data": [{"id": "big"}]}
        with mock.patch.object(agent, "_get_json", get):
            checks = agent.doctor(self.root)
        name, ok, detail = _result(checks, "search")
        self.assertFalse(ok)
        self.assertIn("formats", detail)
        self.assertIn("json", detail)

    def test_search_disabled_is_a_pass_with_a_note(self):
        _write_setup(self.root, search_enabled=False)
        with mock.patch.object(agent, "_get_json", return_value={"models": [], "data": []}):
            checks = agent.doctor(self.root)
        name, ok, detail = _result(checks, "search")
        self.assertTrue(ok)
        self.assertIn("disabled", detail)


class TestDoctorState(DoctorTestCase):
    def test_all_good_reports_python_and_state(self):
        _write_setup(self.root)
        tags = {"models": [{"name": "small"}], "data": [{"id": "big"}]}
        with mock.patch.object(agent, "_get_json", return_value=tags):
            checks = agent.doctor(self.root)
        self.assertTrue(_result(checks, "python")[1])
        self.assertTrue(_result(checks, "state")[1])


if __name__ == "__main__":
    unittest.main()

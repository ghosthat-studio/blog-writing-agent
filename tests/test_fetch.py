import unittest

from core import fetch


class TestHtmlToText(unittest.TestCase):
    def test_strips_tags_scripts_and_entities(self):
        raw = ("<html><head><title>x</title></head><body><script>evil()</script>"
               "<nav>menu</nav><h1>OpenClaw &amp; friends</h1><p>It runs locally.</p>"
               "<footer>foot</footer></body></html>")
        text = fetch.html_to_text(raw)
        self.assertIn("OpenClaw & friends", text)
        self.assertIn("It runs locally.", text)
        self.assertNotIn("evil", text)
        self.assertNotIn("menu", text)
        self.assertNotIn("foot", text)

    def test_caps_length(self):
        self.assertEqual(len(fetch.html_to_text("<p>" + "a" * 500 + "</p>", max_chars=100)), 100)

    def test_empty_input_is_empty(self):
        self.assertEqual(fetch.html_to_text(""), "")


class TestFetchText(unittest.TestCase):
    def test_unreachable_url_degrades_to_empty(self):
        self.assertEqual(fetch.fetch_text("http://127.0.0.1:1/nope", timeout=1), "")


if __name__ == "__main__":
    unittest.main()

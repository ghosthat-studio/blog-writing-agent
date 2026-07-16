import unittest
from unittest import mock

from core import llm


class TestOllamaPayload(unittest.TestCase):
    def test_minimal_payload(self):
        p = llm.ollama_payload("write", "qwen3:4b")
        self.assertEqual(p["model"], "qwen3:4b")
        self.assertEqual(p["prompt"], "write")
        self.assertFalse(p["stream"])
        self.assertIn("temperature", p["options"])
        self.assertNotIn("system", p)
        self.assertNotIn("think", p)
        self.assertNotIn("keep_alive", p)
        self.assertNotIn("num_ctx", p["options"])

    def test_full_payload(self):
        p = llm.ollama_payload("write", "m", system="you are x", temperature=0.2,
                               num_ctx=8192, keep_alive="10m", think=False)
        self.assertEqual(p["system"], "you are x")
        self.assertEqual(p["options"]["temperature"], 0.2)
        self.assertEqual(p["options"]["num_ctx"], 8192)
        self.assertEqual(p["keep_alive"], "10m")
        self.assertIs(p["think"], False)


class TestOpenAIPayload(unittest.TestCase):
    def test_minimal_payload(self):
        p = llm.openai_payload("write", "some-model")
        self.assertEqual(p["messages"], [{"role": "user", "content": "write"}])
        self.assertFalse(p["stream"])
        self.assertNotIn("max_tokens", p)
        self.assertNotIn("chat_template_kwargs", p)

    def test_system_message_comes_first(self):
        p = llm.openai_payload("write", "m", system="you are x")
        self.assertEqual(p["messages"][0], {"role": "system", "content": "you are x"})
        self.assertEqual(p["messages"][1]["role"], "user")

    def test_think_flag_maps_to_chat_template_kwargs(self):
        p = llm.openai_payload("write", "m", think=False)
        self.assertEqual(p["chat_template_kwargs"], {"enable_thinking": False})

    def test_max_tokens_included_when_set(self):
        p = llm.openai_payload("write", "m", max_tokens=400)
        self.assertEqual(p["max_tokens"], 400)


class TestGenerate(unittest.TestCase):
    def test_ollama_backend_routes_and_extracts(self):
        tier = {"backend": "ollama", "url": "http://localhost:11434", "model": "qwen3:4b"}
        with mock.patch.object(llm, "_post", return_value={"response": " hi \n"}) as post:
            out = llm.generate(tier, "prompt")
        self.assertEqual(out, "hi")
        url = post.call_args[0][0]
        self.assertEqual(url, "http://localhost:11434/api/generate")

    def test_openai_backend_routes_and_extracts(self):
        tier = {"backend": "openai", "base_url": "http://localhost:1234", "model": "m"}
        resp = {"choices": [{"message": {"content": " hello "}}]}
        with mock.patch.object(llm, "_post", return_value=resp) as post:
            out = llm.generate(tier, "prompt")
        self.assertEqual(out, "hello")
        self.assertEqual(post.call_args[0][0], "http://localhost:1234/v1/chat/completions")

    def test_call_site_temperature_beats_config_default(self):
        tier = {"backend": "ollama", "url": "http://x", "model": "m", "temperature": 0.7}
        with mock.patch.object(llm, "_post", return_value={"response": "ok"}) as post:
            llm.generate(tier, "p", temperature=0.2)
        body = post.call_args[0][1]
        self.assertEqual(body["options"]["temperature"], 0.2)

    def test_config_temperature_used_when_call_site_silent(self):
        tier = {"backend": "openai", "base_url": "http://x", "model": "m", "temperature": 0.4}
        with mock.patch.object(llm, "_post", return_value={"choices": [{"message": {"content": "ok"}}]}) as post:
            llm.generate(tier, "p")
        self.assertEqual(post.call_args[0][1]["temperature"], 0.4)

    def test_unreachable_backend_raises_plain_language_error(self):
        tier = {"backend": "ollama", "url": "http://localhost:11434", "model": "m"}
        with mock.patch.object(llm, "_post", side_effect=OSError("connection refused")):
            with self.assertRaises(RuntimeError) as ctx:
                llm.generate(tier, "p")
        msg = str(ctx.exception)
        self.assertIn("http://localhost:11434", msg)
        self.assertIn("running", msg)

    def test_unknown_backend_raises_plain_language_error(self):
        with self.assertRaises(RuntimeError) as ctx:
            llm.generate({"backend": "banana", "model": "m"}, "p")
        self.assertIn("banana", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

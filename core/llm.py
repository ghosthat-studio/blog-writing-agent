"""Model interface. Talks to Ollama or any OpenAI-compatible server, stdlib only.

The model is config, not code: swap Ollama for LM Studio, llama.cpp's server,
vLLM, or a hosted key by editing config.json. Two tiers: a small fast model for
utility work (queries, lists, judging), the good model for prose. Same code, one
config block apart.

A tier is a dict from config.json:
  {"backend": "ollama", "url": "http://localhost:11434", "model": "qwen3:4b", ...}
  {"backend": "openai", "base_url": "http://localhost:1234", "model": "...", ...}
"""
import json
import urllib.error
import urllib.request

DEFAULT_TEMPERATURE = 0.7


def ollama_payload(prompt, model, system=None, temperature=DEFAULT_TEMPERATURE,
                   num_ctx=None, keep_alive=None, think=None):
    options = {"temperature": temperature}
    if num_ctx:
        options["num_ctx"] = num_ctx
    body = {"model": model, "prompt": prompt, "stream": False, "options": options}
    if system:
        body["system"] = system
    if think is not None:
        body["think"] = think  # reasoning models: False skips the slow think pass
    if keep_alive is not None:
        body["keep_alive"] = keep_alive  # keep the model resident between jobs
    return body


def openai_payload(prompt, model, system=None, temperature=DEFAULT_TEMPERATURE,
                   max_tokens=None, think=None):
    body = {
        "model": model,
        "messages": ([{"role": "system", "content": system}] if system else [])
                    + [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "stream": False,
    }
    if max_tokens:
        body["max_tokens"] = max_tokens
    if think is not None:
        body["chat_template_kwargs"] = {"enable_thinking": bool(think)}
    return body


def _post(url, body, timeout):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def generate(tier, prompt, system=None, temperature=None):
    """One completion from the tier's backend. Returns the text, stripped.

    temperature passed here is the call site's tuned value (a per-task dial);
    it beats the tier's configured default, which beats the library default.
    """
    backend = tier.get("backend")
    temp = temperature if temperature is not None else tier.get("temperature", DEFAULT_TEMPERATURE)
    think = tier.get("think")
    timeout = tier.get("timeout", 900)
    if backend == "ollama":
        base = tier.get("url", "http://localhost:11434").rstrip("/")
        url = base + "/api/generate"
        body = ollama_payload(prompt, tier["model"], system=system, temperature=temp,
                              num_ctx=tier.get("num_ctx"), keep_alive=tier.get("keep_alive"),
                              think=think)
    elif backend == "openai":
        base = tier.get("base_url", "http://localhost:1234").rstrip("/")
        url = base + "/v1/chat/completions"
        body = openai_payload(prompt, tier["model"], system=system, temperature=temp,
                              max_tokens=tier.get("max_tokens"), think=think)
    else:
        raise RuntimeError(
            "Unknown model backend %r in config.json. Use \"ollama\" for Ollama, or "
            "\"openai\" for anything with an OpenAI-compatible API (LM Studio, "
            "llama.cpp's llama-server, vLLM, a hosted key)." % backend
        )
    try:
        d = _post(url, body, timeout)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        raise RuntimeError("Your model server at %s returned HTTP %s: %s" % (base, e.code, detail))
    except Exception as e:
        raise RuntimeError(
            "Could not reach your model at %s; is it running? "
            "(started Ollama / LM Studio / your server?) Underlying error: %s" % (base, e)
        )
    if backend == "ollama":
        return d["response"].strip()
    return d["choices"][0]["message"]["content"].strip()

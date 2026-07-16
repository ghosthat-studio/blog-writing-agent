"""Web search via a self-hosted SearXNG instance (JSON API). stdlib only.

No API key, no rate card, nobody logging your queries. Gentle by design — the
consumer engines SearXNG aggregates rate-limit and CAPTCHA a self-hosted scraper
if you burst at them, so this module:
  - paces requests (a minimum gap between calls), sipping like a human;
  - retries with backoff when a call comes back empty;
  - caches hits on disk, so repeated queries don't re-hit the engines.
When it genuinely cannot get results, search() returns [] and callers degrade
gracefully — they must never fabricate a result.

Engine selection: the default set is led by engines verified to serve
self-hosted instances; the commonly-blocked ones stay in the list and rejoin
for free if they recover.

Optional env knobs:
  AGENT_SEARCH_ENGINES       comma-separated SearXNG engines (default below)
  AGENT_SEARCH_MIN_INTERVAL  seconds between requests (default 3)
  AGENT_SEARCH_NOCACHE       set to any value to disable the on-disk cache
"""
import hashlib
import json
import os
import tempfile
import time
import urllib.parse
import urllib.request

_DEFAULT_ENGINES = "bing,yahoo,presearch,duckduckgo,brave,startpage,google"
_last_request = [0.0]
_CACHE_DIR = os.path.join(tempfile.gettempdir(), "blog-agent-search-cache")
_CACHE_TTL = 6 * 3600  # seconds


def _engines():
    return (os.environ.get("AGENT_SEARCH_ENGINES") or _DEFAULT_ENGINES).strip()


def _min_interval():
    try:
        return float(os.environ.get("AGENT_SEARCH_MIN_INTERVAL", "3"))
    except ValueError:
        return 3.0


def _cache_on():
    return not os.environ.get("AGENT_SEARCH_NOCACHE")


def _cache_file(key):
    return os.path.join(_CACHE_DIR, hashlib.sha1(key.encode("utf-8")).hexdigest()[:16] + ".json")


def _cache_get(key):
    if not _cache_on():
        return None
    p = _cache_file(key)
    try:
        if os.path.exists(p) and time.time() - os.path.getmtime(p) < _CACHE_TTL:
            return json.load(open(p, encoding="utf-8"))
    except Exception:
        pass
    return None


def _cache_put(key, val):
    if not _cache_on() or not val:
        return
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        json.dump(val, open(_cache_file(key), "w", encoding="utf-8"))
    except Exception:
        pass


def _pace():
    gap = _min_interval() - (time.time() - _last_request[0])
    if gap > 0:
        time.sleep(gap)
    _last_request[0] = time.time()


def _fetch(url, query, timeout):
    qs = urllib.parse.urlencode({"q": query, "format": "json", "engines": _engines()})
    req = urllib.request.Request(
        url.rstrip("/") + "/search?" + qs,
        headers={"User-Agent": "Mozilla/5.0 (compatible; BlogAgentResearch/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def search(query, url="http://localhost:8888", n=5, timeout=20, retries=2):
    """Up to n results as [{title, url, content}]. Paced, cached, and retried
    with backoff. Returns [] if it genuinely cannot get results."""
    key = url + "|" + query
    cached = _cache_get(key)
    if cached is not None:
        return cached[:n]
    for attempt in range(retries + 1):
        _pace()
        try:
            d = _fetch(url, query, timeout)
        except Exception:
            d = {}
        results = d.get("results") or []
        if results:
            out = [{"title": (i.get("title") or "").strip(),
                    "url": (i.get("url") or "").strip(),
                    "content": (i.get("content") or "").strip()} for i in results[:n]]
            _cache_put(key, out)
            return out
        if attempt < retries:
            time.sleep(2 + attempt * 3)  # backoff: 2s, then 5s
    return []


def grounding(queries, url="http://localhost:8888", per=4):
    """Run several queries and return one text block of sourced snippets,
    suitable to paste into a prompt. Empty string if nothing came back."""
    blocks = []
    for q in queries:
        res = search(q, url=url, n=per)
        if not res:
            continue
        lines = ["### Results for: " + q]
        for r in res:
            lines.append("- %s (%s): %s" % (r["title"], r["url"], r["content"][:300]))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)

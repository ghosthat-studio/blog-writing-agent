"""Fetch a web page and return readable text. stdlib only.

A researcher can't judge a page from a search snippet — the names and the real
facts live in the body ("best agents of the year" lists, comparison pages, docs).
This turns a URL into plain text the model can read. Public pages only; size-
capped and best-effort (returns "" on any failure so callers degrade gracefully).
"""
import html
import re
import urllib.error
import urllib.request

_UA = "Mozilla/5.0 (compatible; BlogAgentResearch/1.0)"
_DROP = re.compile(r"(?is)<(script|style|noscript|svg|head|nav|footer)\b.*?</\1>")
_COMMENT = re.compile(r"(?s)<!--.*?-->")
_TAG = re.compile(r"(?s)<[^>]+>")
_WS = re.compile(r"\s+")


def html_to_text(raw, max_chars=None):
    """Strip HTML to readable text. Pure function (no network) so it's unit-testable."""
    if not raw:
        return ""
    t = _DROP.sub(" ", raw)
    t = _COMMENT.sub(" ", t)
    t = _TAG.sub(" ", t)
    t = html.unescape(t)
    t = _WS.sub(" ", t).strip()
    return t[:max_chars]


def fetch_text(url, timeout=15, max_chars=None, max_bytes=2_000_000):
    """GET a URL and return readable text, or '' on any failure / non-text content."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ctype = (r.headers.get_content_type() or "").lower()
            if "html" not in ctype and "text" not in ctype and ctype != "":
                return ""
            raw = r.read(max_bytes)
    except (urllib.error.URLError, ValueError, TimeoutError, OSError):
        return ""
    try:
        return html_to_text(raw.decode("utf-8", "ignore"), max_chars=max_chars)
    except Exception:
        return ""

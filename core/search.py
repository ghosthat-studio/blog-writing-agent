"""Web search via a self-hosted SearXNG instance (JSON API). stdlib only.

No API key, no rate card, nobody logging your queries. Gentle by design: paced
requests, retries with backoff, an on-disk cache. When it genuinely cannot get
results it returns nothing and the caller degrades gracefully — it never
fabricates a result.

Skeleton — implementation lands with the agent core.
"""

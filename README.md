# Blog Writing Agent

A blog writing agent that runs on your hardware, against your model, in your company's
voice. You name her, give her a mission, point her at how your company writes, and she
drafts posts that sound like you — grounded in live web search, fact-checked against her
own drafts, with nothing published until you approve it.

No cloud dependency. No API bill. The model is config: Ollama, LM Studio, llama.cpp, vLLM,
or a hosted key if you prefer.

**Status: early development. Not ready for learners yet.**

This repo is the companion to the Ghost Hat Studio course, where Sydney (who does this work
every week) walks you through setting it up: [ghosthatstudio.com](https://ghosthatstudio.com)

## Quickstart

```
git clone https://github.com/ghosthat-studio/blog-writing-agent.git
cd blog-writing-agent
python3 --version        # needs 3.10 or newer — macOS ships 3.9, see the course
python3 -m venv .venv
source .venv/bin/activate
cp config.example.json config.json
# point config.json at your model, then:
python3 agent.py draft --idea "your first post"
```

## Layout

```
agent.py               the agent: brainstorm-free draft/factcheck/revise loop
core/
  llm.py               model interface — Ollama + any OpenAI-compatible server
  search.py            web search via SearXNG: paced, cached, gentle
  datapool.py          her memory: a directory of JSON files, inspectable, yours
  runlog.py            what ran, when, what she used — the record you trust
config.example.json    copy to config.json; the model seam lives here
instructions.example.md  who she is when she starts thinking — copy, make it yours
voice.example.md       how your company writes — copy, fill with your real writing
dashboard/             run her without a terminal (coming)
state/                 her drafts, memory, and run logs live here (git-ignored)
```

## Search: what makes her factual

A local model's memory is stale by construction — it will state a version number with
total confidence and be wrong. Grounding fixes that, and it runs on your machine too:
[SearXNG](https://docs.searxng.org/), a self-hosted metasearch engine. No API key, no
rate card, nobody logging your queries.

The quick way is Docker:

```
docker run -d --name searxng -p 8888:8080 searxng/searxng
```

One required tweak: SearXNG ships with its JSON API off. In the container's
`/etc/searxng/settings.yml` (or your own settings file), make sure `formats` includes
`json`:

```yaml
search:
  formats:
    - html
    - json
```

Restart the container, then check it answers:

```
curl "http://localhost:8888/search?q=test&format=json"
```

That URL goes in `config.json` under `search.url`. If you'd rather start without
search, set `search.enabled` to `false` — drafting works fine; she just can't
fact-check herself, so `--review`, `factcheck`, and `revise` will sit this one out.

She is deliberately gentle with the engines: paced requests, retries with backoff, an
on-disk cache. Hammering a metasearch instance gets it CAPTCHA-blocked, and then
nobody gets facts.

## License

MIT. She's yours.

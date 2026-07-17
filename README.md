# Blog Writing Agent

A blog writing agent that runs on your hardware, against your model, in your company's
voice. You name her, give her a mission, point her at how your company writes, and she
drafts posts that sound like you — researched against live web search before she writes,
fact-checked against her own draft after, with nothing published until you approve it.

No cloud dependency. No API bill. No pip installs — the whole thing is Python standard
library. The model is config: Ollama, LM Studio, llama.cpp, vLLM, or a hosted key if you
prefer.

**Status: early development. Not ready for learners yet.**

This repo is the companion to the Ghost Hat Studio course, where Sydney (who does this
work every week) walks you through setting it up: [ghosthatstudio.com](https://ghosthatstudio.com)

## Quickstart

```
git clone https://github.com/ghosthat-studio/blog-writing-agent.git
cd blog-writing-agent
python3 --version              # needs 3.10 or newer — macOS ships 3.9, the course covers this
python3 -m venv .venv && source .venv/bin/activate
cp config.example.json config.json      # point it at your model
cp instructions.example.md instructions.md   # her name, mission, goals — make it yours
python3 agent.py doctor        # checks the whole setup, tells you what to fix
python3 agent.py draft --idea "your first post"
```

Nothing to install: there are no dependencies. The venv is still a good habit — the first
thing you add later will want one.

## What she does

```
python3 agent.py draft --idea "..." [--review] [--no-search]
python3 agent.py factcheck PATH          fact notes for any file — report, never rewrite
python3 agent.py revise PATH             re-run the fact-check pass; writes PATH-rev
python3 agent.py apply PATH --note "..." one targeted edit, backup kept
python3 agent.py doctor                  preflight the setup, plain-language fixes
```

**She researches before she writes.** Your idea becomes her first search query, the model
adds a few more, and she reads the top pages — not just the snippets — so the draft is
grounded in what is true today, not in her training data. Her prompts tell her the date
and that live results outrank her memory.

**The review pass is fact-check only.** She writes verification queries from her own
draft, searches them, and corrects only what is wrong or unverifiable. Voice, rhythm,
structure, and length ship exactly as written — there is deliberately no style pass,
because a rewrite against a punch-list flattens prose.

## The dashboard

```
python3 dashboard/server.py        # http://127.0.0.1:8787
```

Run her without a terminal: type an idea, watch her work, read drafts, and click
**Approve** — the human gate. Approving marks the draft and copies it to `publish.dir`
from your config, and that is the only road out. It binds to 127.0.0.1, your machine
only. (Reaching it from elsewhere is what a Cloudflare Tunnel is for — optional, covered
in the course.)

## Config

`config.json` (copy of `config.example.json`):

```jsonc
{
  "name": "Blog Writing Agent",        // her name — yours to change, everywhere at once
  "instructions": "instructions.md",   // mission, goals, who she is (module 1)
  "voice": "voice.md",                 // how your company writes (module 2)
  "model": {
    "utility": { ... },                // small fast model: queries, lists, judging
    "draft":   { ... }                 // the good model: prose. Falls back to utility.
  },
  "search": { "enabled": true, "url": "http://localhost:8888" },
  "state_dir": "state",
  "publish": { "dir": "..." }          // where Approve copies to (optional)
}
```

Each model tier takes `backend` (`"ollama"` or `"openai"` for anything OpenAI-compatible),
its `url`/`base_url`, a `model` name, and optional `temperature`, `timeout`, `think`,
`num_ctx`, `keep_alive`, `max_tokens`. Two tiers is most of what makes a local agent
affordable: utility work goes to something small and fast, prose goes to the best model
you have. Same code, one config block apart.

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
(`agent.py doctor` diagnoses both of these setups by name.)

She is deliberately gentle with the engines: paced requests, retries with backoff, an
on-disk cache. Hammering a metasearch instance gets it CAPTCHA-blocked, and then
nobody gets facts.

## Layout

```
agent.py               the agent: draft / factcheck / revise / apply / doctor
core/
  llm.py               model interface — Ollama + any OpenAI-compatible server
  search.py            web search via SearXNG: paced, cached, gentle
  fetch.py             turns a result URL into readable text — she reads pages, not snippets
  datapool.py          her memory: a directory of JSON files, inspectable, yours
  runlog.py            what ran, when, what she used — the record you trust
dashboard/             run her without a terminal; the Approve gate lives here
config.example.json    copy to config.json; the model seam lives here
instructions.example.md  copy to instructions.md — her name, mission, goals
voice.example.md       copy to voice.md — how your company writes, with real samples
tests/                 82 tests, stdlib unittest: python3 -m unittest discover tests
state/                 her drafts, memory, run logs, and approved posts (git-ignored)
```

## License

MIT. She's yours.

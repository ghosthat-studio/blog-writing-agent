#!/usr/bin/env python3
"""Your blog writing agent.

Modes:
  python3 agent.py draft --idea "..." [--review] [--no-search]
  python3 agent.py factcheck PATH          fact notes only (web search)
  python3 agent.py revise PATH [--no-search]
  python3 agent.py apply PATH --note "..."   targeted edit, backup kept

The review pass corrects facts and refuses to touch your prose. It verifies
claims against live search and fixes only what is wrong or unverifiable; voice,
rhythm, structure, and length ship exactly as written. There is deliberately no
style pass, because a rewrite against a punch-list flattens prose.

When anything about the setup feels wrong:
  python3 agent.py doctor                  every known trap, with its fix

Nothing publishes without you.
"""
import argparse
import datetime
import json
import os
import re
import shutil
import sys

if sys.version_info < (3, 10):
    raise SystemExit(
        "This agent needs Python 3.10 or newer; you are running %d.%d.\n"
        "macOS ships 3.9 as 'python3'. Install a current Python from python.org "
        "or Homebrew, then recreate your venv with it."
        % (sys.version_info.major, sys.version_info.minor)
    )

from core import fetch, llm, search, runlog  # noqa: E402  (after the version guard on purpose)

ROOT = os.path.dirname(os.path.abspath(__file__))

FACTCHECK_QUERIES = (
    "List 3 to 6 short web-search queries that would verify the factual claims, product "
    "names, prices, statistics, dates, and company details in this draft. Output one query "
    "per line, no numbering and no commentary.\n\nDRAFT:\n\n{draft}"
)

FACTCHECK_TASK = (
    "Fact-check the following draft using the search results below, preferring primary "
    "sources. For every factual claim, product or model name, price, statistic, date, or "
    "company detail, output a line: CLAIM -> VERIFIED (source) / UNVERIFIED / WRONG "
    "(correction + source). Note whether something has actually shipped versus only been "
    "announced. If the sources don't cover a claim, mark it UNVERIFIED. Do not rewrite the "
    "draft; just report.\n\nSEARCH RESULTS:\n\n{results}\n\nDRAFT:\n\n{draft}"
)

FACT_FIX_PROMPT = (
    "Apply these fact-check findings to the document below. Correct anything marked WRONG "
    "using the given correction and source; soften or qualify anything UNVERIFIED; remove "
    "invented specifics that could not be confirmed. When a model, product, price, version, "
    "or date is involved, use the REAL current fact from the findings, never your own "
    "memory. Change ONLY what the findings require, and keep the document's voice, structure, "
    "length, and every other line exactly as they are. If the document is HTML return valid "
    "HTML; if markdown, markdown. Return the full document and nothing else.\n\n"
    "FACT-CHECK FINDINGS:\n{facts}\n\nDOCUMENT:\n{doc}"
)

APPLY_NOTE_PROMPT = (
    "Apply the following change to the document, in your own voice and to your writing "
    "standard.\n\n"
    "Judge the size of the change. If the note is a small tweak (a fact, a line, a word), "
    "change only what it calls for and leave the rest as it is. But if the note asks for "
    "something substantive (reversing the position, changing the argument, a different "
    "angle, a new title), then make EVERY change required for the document to honestly "
    "reflect the new direction. A half-applied flip that leaves the old position quietly "
    "standing is wrong. Commit to the new direction fully and believe it while you write "
    "it.\n\n"
    "Use the EXACT names, numbers, models, versions, and facts the note gives you, "
    "verbatim. The note is ground truth: never replace a specific it states with a "
    "different one from your own memory.\n\n"
    "Keep your voice and the format. If the document is HTML, return valid HTML; if "
    "markdown, return markdown. Return the full updated document and nothing else.\n\n"
    "CHANGE REQUESTED:\n{note}\n\nDOCUMENT:\n{doc}"
)

DRAFT_QUERIES = (
    "This is an idea for a blog post. List 3 to 5 short web-search queries that would "
    "gather the current facts needed to write it properly. Every query must be about the "
    "idea's own subject. Do not introduce products, devices, or topics the idea does not "
    "mention. When a query asks for the latest, top, or current anything, include the "
    "current year from your instructions, never a past year. Output one query per line, "
    "no numbering and no commentary.\n\nIDEA:\n\n{idea}"
)

DRAFT_TASK = (
    "Write the full blog post for this idea, as a single clean block of HTML (no page "
    "wrapper; <h1> title; <h2> sections). On the very first line put the slug as an HTML "
    "comment: <!-- slug: my-post -->\n\n"
    "{research}"
    "The idea:\n\n{idea}"
)

DRAFT_RESEARCH_BLOCK = (
    "Here is live web search on this idea. This is YOUR research and it is already done. "
    "Ground the post in it: take every name, version, price, and date from it, lead with "
    "what is current in it, and never present something it contradicts. Your own memory of "
    "products and models is stale by construction: where the research and your memory "
    "disagree, the research wins.\n\n{ground}\n\n"
)


def load_config(root):
    p = os.path.join(root, "config.json")
    if not os.path.exists(p):
        raise RuntimeError(
            "No config.json found. Copy config.example.json to config.json and "
            "point it at your model. That is the first setup step."
        )
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            "config.json is not valid JSON (%s). A missing comma or quote is the "
            "usual culprit; check line %d." % (e.msg, e.lineno)
        )


def system_prompt(cfg, root):
    """Who she is when she starts thinking: her name, your instructions, and,
    once you write it, your company's voice."""
    ip = os.path.join(root, cfg.get("instructions", "instructions.md"))
    if not os.path.exists(ip):
        raise RuntimeError(
            "No instructions file at %s. Copy instructions.example.md to "
            "instructions.md and make it yours. Her name, mission, and goals "
            "live there." % ip
        )
    instr = open(ip, encoding="utf-8").read()
    parts = [
        "You are %s, this company's blog writing agent. Today is %s. Your training "
        "data is older than that: treat live search results as the present and your "
        "own memory of products, models, and versions as history."
        % (cfg.get("name", "Blog Writing Agent"),
           datetime.date.today().strftime("%B %d, %Y").replace(" 0", " ")),
        instr,
    ]
    vp = os.path.join(root, cfg.get("voice", "voice.md"))
    if os.path.exists(vp):
        parts.append(
            "# How this company writes: your voice\n\n"
            "Write the way the samples below write. They are the standard; match "
            "their register, rhythm, and warmth.\n\n" + open(vp, encoding="utf-8").read()
        )
    return "\n\n---\n\n".join(parts)


def _warn(msg):
    print("WARN: " + msg, file=sys.stderr)


def _ask(cfg, root, task, tier="utility", temp=None):
    """One completion. Utility work (queries, lists, judging) goes to the small
    fast tier; prose goes to the draft tier. Writing IS her job, so it gets the
    best model you have. If the draft tier is unreachable she falls back to the
    utility model, loudly, rather than dying mid-run."""
    tiers = cfg.get("model", {})
    system = system_prompt(cfg, root)
    if tier == "draft" and tiers.get("draft", {}).get("model"):
        try:
            return llm.generate(tiers["draft"], task, system=system, temperature=temp)
        except RuntimeError as e:
            _warn("draft model %s unavailable (%s). Falling back to %s."
                  % (tiers["draft"].get("model"), e, tiers.get("utility", {}).get("model")))
    return llm.generate(tiers.get("utility", {}), task, system=system, temperature=temp)


def _state(cfg, root, *parts):
    p = os.path.join(root, cfg.get("state_dir", "state"), *parts)
    os.makedirs(p, exist_ok=True)
    return p


def _read(path):
    if not os.path.exists(path):
        raise RuntimeError("No such file: %s" % path)
    return open(path, encoding="utf-8").read()


def _slug_of(text, fallback=None):
    m = re.search(r"slug:\s*([a-z0-9\-]+)", text)
    return m.group(1) if m else (fallback or "draft-" + datetime.date.today().isoformat())


def _has_fact_issues(facts):
    return bool(facts) and bool(re.search(r"\b(WRONG|UNVERIFIED)\b", facts))


def _fact_notes(cfg, root, draft_text):
    """Search-grounded fact-check: she writes her own verification queries from
    the draft, searches them, and judges the draft against what came back."""
    s = cfg.get("search", {})
    qraw = _ask(cfg, root, FACTCHECK_QUERIES.format(draft=draft_text), temp=0.2)
    queries = [q.strip(" -*•\t") for q in qraw.splitlines() if q.strip()][:6]
    ground = search.grounding(queries, url=s.get("url", "http://localhost:8888")) if queries else ""
    results = ground or "(no search results were returned)"
    return _ask(cfg, root, FACTCHECK_TASK.format(results=results, draft=draft_text), temp=0.3)


def _self_review(cfg, root, draft_text):
    """Fact-check, applied surgically. Facts clean -> the draft ships exactly as
    written. Issues -> correct ONLY what the findings require; voice, rhythm,
    structure, and length stay untouched."""
    if not cfg.get("search", {}).get("enabled"):
        return "FACT-CHECK: (skipped: search is disabled in config.json)", draft_text
    facts = _fact_notes(cfg, root, draft_text)
    notes = "FACT-CHECK:\n" + facts
    if not _has_fact_issues(facts):
        return notes, draft_text
    revised = _ask(cfg, root, FACT_FIX_PROMPT.format(facts=facts, doc=draft_text),
                   tier="draft", temp=0.3)
    return notes, revised


def draft(cfg, root, idea, review=False, do_search=True, checkpoint=None):
    """Write a post. She researches the idea FIRST, so the draft is written from
    current facts rather than her stale memory; with review she then fact-checks
    her own result and corrects only what is wrong. Returns the final path.

    checkpoint, if given, is called with what she gathered (queries, sources)
    AFTER research and BEFORE writing, and she does not write until it returns.
    This is the pause-and-yield gate: the caller decides how long to hold her."""
    research = ""
    queries, sources = [], []
    if do_search and cfg.get("search", {}).get("enabled"):
        qraw = _ask(cfg, root, DRAFT_QUERIES.format(idea=idea), temp=0.2)
        # The idea itself is always the first query. The model's queries can
        # wander off-topic (a stale small model will), but this one cannot.
        queries = [idea.strip()[:120]]
        queries += [q.strip(" -*•\t") for q in qraw.splitlines() if q.strip()][:5]
        url = cfg["search"].get("url", "http://localhost:8888")
        ground = search.grounding(queries, url=url)
        # Snippets carry titles, not contents: a "best agents of 2026" page
        # surfaces as a headline without its list. Read the top pages too.
        pages = []
        for r in search.search(queries[0], url=url, n=3)[:2]:
            text = fetch.fetch_text(r["url"], max_chars=2500)
            if text:
                pages.append("### From the page: %s (%s)\n%s" % (r["title"], r["url"], text))
                sources.append({"title": r["title"], "url": r["url"]})
        ground = "\n\n".join([b for b in [ground] + pages if b])
        if ground:
            research = DRAFT_RESEARCH_BLOCK.format(ground=ground)
    if checkpoint:
        checkpoint({"queries": queries, "sources": sources,
                    "research_chars": len(research)})
    initial = _ask(cfg, root, DRAFT_TASK.format(research=research, idea=idea),
                   tier="draft", temp=0.6)
    slug = _slug_of(initial)
    ddir = _state(cfg, root, "drafts")
    changed, notes, final = False, None, initial
    if review:
        review_cfg = cfg if do_search else {**cfg, "search": {**cfg.get("search", {}), "enabled": False}}
        notes, final = _self_review(review_cfg, root, initial)
        changed = final.strip() != initial.strip()
        if changed:
            open(os.path.join(ddir, slug + "-draft.html"), "w", encoding="utf-8").write(initial)
        open(os.path.join(ddir, slug + "-review.md"), "w", encoding="utf-8").write(notes)
    path = os.path.join(ddir, slug + ".html")
    open(path, "w", encoding="utf-8").write(final)
    runlog.log(_state(cfg, root, "runs"), _agent_slug(cfg), "draft", slug=slug, path=path,
               reviewed=bool(review), searched=bool(review and do_search), changed=changed)
    return path


def factcheck(cfg, root, path):
    """Fact notes only: report, never rewrite. Returns the report path."""
    notes = _fact_notes(cfg, root, _read(path))
    fdir = _state(cfg, root, "factchecks")
    rp = os.path.join(fdir, os.path.basename(path).rsplit(".", 1)[0] + "-factcheck.md")
    open(rp, "w", encoding="utf-8").write(notes)
    runlog.log(_state(cfg, root, "runs"), _agent_slug(cfg), "factcheck", draft=path, report=rp)
    return rp


def revise(cfg, root, path, do_search=True):
    """Re-run the fact-check pass on an existing file. Writes PATH-rev, keeps
    the original. Returns the revised path."""
    original = _read(path)
    review_cfg = cfg if do_search else {**cfg, "search": {**cfg.get("search", {}), "enabled": False}}
    notes, revised = _self_review(review_cfg, root, original)
    changed = revised.strip() != original.strip()
    base = path[:-5] if path.endswith(".html") else path
    rp = base + "-rev.html"
    open(rp, "w", encoding="utf-8").write(revised)
    runlog.log(_state(cfg, root, "runs"), _agent_slug(cfg), "revise", source=path, output=rp,
               searched=bool(do_search), changed=changed)
    print(notes)
    return rp


def apply_note(cfg, root, path, note):
    """Targeted edit: apply ONLY the note, leave everything else intact.
    Overwrites the file in place, keeping a .bak copy. New claims that arrive
    with feedback get the same fact-check a fresh draft gets."""
    doc = _read(path)
    out = _ask(cfg, root, APPLY_NOTE_PROMPT.format(note=note, doc=doc), tier="draft", temp=0.4)
    fact_checked = False
    if cfg.get("search", {}).get("enabled"):
        facts = _fact_notes(cfg, root, out)
        if _has_fact_issues(facts):
            out = _ask(cfg, root, FACT_FIX_PROMPT.format(facts=facts, doc=out),
                       tier="draft", temp=0.4)
            fact_checked = True
    shutil.copy(path, path + ".bak")
    open(path, "w", encoding="utf-8").write(out)
    runlog.log(_state(cfg, root, "runs"), _agent_slug(cfg), "apply", path=path,
               note=note[:160], fact_checked=fact_checked)
    return path


def _agent_slug(cfg):
    return re.sub(r"[^a-z0-9]+", "-", cfg.get("name", "agent").lower()).strip("-") or "agent"


def _get_json(url, timeout=5):
    """GET a URL and parse JSON. Raises RuntimeError('HTTP <code> ...') on HTTP
    errors so callers can tell a closed port from a refusing server."""
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": "agent-doctor"}),
                timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError("HTTP %d from %s" % (e.code, url))


def _check_tier(name, tier):
    """One (name, ok, detail) row for a model tier: is the server up, and is the
    named model actually available on it. A tier with no model chosen yet is not
    an error; it is simply not in use (drafts fall back to the utility tier)."""
    backend = tier.get("backend")
    model = tier.get("model", "")
    if not model:
        if name.endswith("draft"):
            return (name, True,
                    "no model chosen yet; drafts use the utility tier until you "
                    "pick one (module 4 is where the tiers split).")
        return (name, False,
                "no model set. She needs at least a utility model; put the name "
                "of one you have in config.json.")
    if backend == "ollama":
        base = tier.get("url", "http://localhost:11434").rstrip("/")
        probe = base + "/api/tags"
    elif backend == "openai":
        base = tier.get("base_url", "http://localhost:1234").rstrip("/")
        probe = base + "/v1/models"
    else:
        return (name, False, "unknown backend %r. Use \"ollama\" or \"openai\"" % backend)
    try:
        d = _get_json(probe)
    except Exception as e:
        return (name, False,
                "cannot reach %s (%s); is your model server running? Start Ollama / "
                "LM Studio / your server, then run doctor again." % (base, e))
    if backend == "ollama":
        have = [m.get("name", "") for m in d.get("models", [])]
        if model and not any(h == model or h.split(":")[0] == model for h in have):
            return (name, False,
                    "server at %s is up but has no model named %r. Pull it first "
                    "(ollama pull %s) or pick one you have: %s"
                    % (base, model, model, ", ".join(have[:6]) or "(none)"))
    else:
        have = [m.get("id", "") for m in d.get("data", [])]
        if model and have and model not in have:
            return (name, False,
                    "server at %s is up but does not list model %r. Loaded models: %s"
                    % (base, model, ", ".join(have[:6])))
    return (name, True, "%s at %s, model %s" % (backend, base, model or "(unset)"))


def doctor(root):
    """Preflight the whole setup. Returns [(check, ok, detail)]: every known
    9pm install failure, checked, with the fix in the message."""
    checks = [("python", True, "%d.%d.%d at %s"
               % (sys.version_info[:3] + (sys.executable,)))]
    try:
        cfg = load_config(root)
        checks.append(("config", True, "config.json parsed"))
    except RuntimeError as e:
        checks.append(("config", False, str(e)))
        return checks
    ip = os.path.join(root, cfg.get("instructions", "instructions.md"))
    if os.path.exists(ip):
        checks.append(("instructions", True, ip))
    else:
        checks.append(("instructions", False,
                       "no instructions file at %s. Copy instructions.example.md to "
                       "instructions.md and make it yours." % ip))
    vp = os.path.join(root, cfg.get("voice", "voice.md"))
    checks.append(("voice", True, vp if os.path.exists(vp) else
                   "no voice.md yet. She will write without your company voice "
                   "until you add one (module 3)."))
    for tier_name in ("utility", "draft"):
        tier = cfg.get("model", {}).get(tier_name)
        if tier:
            checks.append(_check_tier("model:" + tier_name, tier))
        else:
            checks.append(("model:" + tier_name, tier_name == "draft",
                           "no %s tier in config.json%s" % (tier_name,
                           ". Drafts will use the utility model" if tier_name == "draft"
                           else ". She needs at least a utility model")))
    s = cfg.get("search", {})
    if not s.get("enabled"):
        checks.append(("search", True,
                       "disabled in config.json. Drafting works; fact-checking is off."))
    else:
        surl = s.get("url", "http://localhost:8888").rstrip("/")
        try:
            _get_json(surl + "/search?q=doctor&format=json")
            checks.append(("search", True, "SearXNG answering at " + surl))
        except Exception as e:
            msg = str(e)
            if "403" in msg or "HTTP 4" in msg:
                checks.append(("search", False,
                               "SearXNG at %s refused the JSON API (%s). Its settings.yml "
                               "ships with json off. Add it under search: formats: "
                               "[html, json], then restart. See the README." % (surl, msg)))
            else:
                checks.append(("search", False,
                               "cannot reach SearXNG at %s (%s); is the container "
                               "running? docker start searxng, or set search.enabled "
                               "to false to draft without fact-checking." % (surl, msg)))
    try:
        sd = _state(cfg, root)
        probe = os.path.join(sd, ".doctor")
        open(probe, "w").close()
        os.remove(probe)
        checks.append(("state", True, sd + " is writable"))
    except OSError as e:
        checks.append(("state", False, "cannot write the state directory: %s" % e))
    return checks


def main():
    ap = argparse.ArgumentParser(description="Your blog writing agent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft", help="write a post")
    d.add_argument("--idea", required=True)
    d.add_argument("--review", action="store_true",
                   help="fact-check the draft (facts only; never touches voice)")
    d.add_argument("--no-search", action="store_true")
    fc = sub.add_parser("factcheck", help="fact notes for an existing file")
    fc.add_argument("path")
    rv = sub.add_parser("revise", help="re-run the fact-check pass on a file")
    rv.add_argument("path")
    rv.add_argument("--no-search", action="store_true")
    a2 = sub.add_parser("apply", help="apply one editing note to a file")
    a2.add_argument("path")
    a2.add_argument("--note")
    a2.add_argument("--note-file")
    sub.add_parser("doctor", help="check the whole setup and say what to fix")
    args = ap.parse_args()
    if args.cmd == "doctor":
        checks = doctor(ROOT)
        for name, ok, detail in checks:
            print("%s %-14s %s" % ("ok " if ok else "FIX", name, detail))
        bad = [c for c in checks if not c[1]]
        raise SystemExit(1 if bad else 0)
    try:
        cfg = load_config(ROOT)
        if args.cmd == "draft":
            path = draft(cfg, ROOT, args.idea, review=args.review,
                         do_search=not args.no_search)
            print(open(path, encoding="utf-8").read())
            print("\n[final draft saved to %s]" % path)
        elif args.cmd == "factcheck":
            rp = factcheck(cfg, ROOT, args.path)
            print(open(rp, encoding="utf-8").read())
            print("\n[fact-check saved to %s]" % rp)
        elif args.cmd == "revise":
            rp = revise(cfg, ROOT, args.path, do_search=not args.no_search)
            print("\n[revised draft saved to %s; original untouched]" % rp)
        elif args.cmd == "apply":
            note = args.note
            if args.note_file:
                note = open(args.note_file, encoding="utf-8").read()
            if not note:
                raise SystemExit('Pass --note "..." or --note-file PATH')
            apply_note(cfg, ROOT, args.path, note)
            print("[applied note; updated %s (backup at %s.bak)]" % (args.path, args.path))
    except RuntimeError as e:
        raise SystemExit("\n%s" % e)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Your blog writing agent.

Modes (being built — this is a skeleton, the working agent lands shortly):
  python3 agent.py draft --idea "..." [--review] [--no-search]
  python3 agent.py factcheck PATH        fact notes only (web search)
  python3 agent.py revise PATH           re-run the fact-check pass on a file

The review pass is FACT-CHECK ONLY: it verifies claims against live search and
corrects only what is wrong or unverifiable, leaving voice, rhythm, structure,
and length exactly as written. Nothing publishes without you.
"""
import sys

if sys.version_info < (3, 10):
    raise SystemExit(
        "This agent needs Python 3.10 or newer; you are running %d.%d.\n"
        "macOS ships 3.9 as 'python3' — install a current Python from python.org "
        "or Homebrew, then recreate your venv with it."
        % (sys.version_info.major, sys.version_info.minor)
    )


def main():
    raise SystemExit(
        "The agent is under construction — modes land here shortly.\n"
        "Watch the repo, or take the course at ghosthatstudio.com."
    )


if __name__ == "__main__":
    main()

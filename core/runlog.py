"""The run log: every action appends one JSON line: what ran, when, what it
used, what it decided, what it produced. The run log is how you come to trust
your agent. Not vibes, a record.
"""
import datetime
import json
import os


def log(runs_dir, agent, kind, **data):
    os.makedirs(runs_dir, exist_ok=True)
    rec = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "agent": agent,
        "kind": kind,
        **data,
    }
    fn = os.path.join(runs_dir, f"{agent}-{datetime.date.today().isoformat()}.jsonl")
    with open(fn, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec

"""Her memory: a directory of JSON files. Inspectable, versionable, yours.

That is the entire technology, and it does not need a vector database. An agent
without memory is a chatbot on a cron job — this is what she remembers between
runs (published titles, idea backlog, what you dismissed).
"""
import json
import os


def load_json(dirpath, name, default=None):
    p = os.path.join(dirpath, name)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else {}


def save_json(dirpath, name, data):
    os.makedirs(dirpath, exist_ok=True)
    with open(os.path.join(dirpath, name), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

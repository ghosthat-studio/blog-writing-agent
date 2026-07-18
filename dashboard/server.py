#!/usr/bin/env python3
"""Her dashboard: run her without a terminal, watch her work, read the log.

The dashboard is how an agent stops being a script and starts being staff. It
binds to 127.0.0.1, your machine only, and the human gate is built in:
nothing publishes without you clicking Approve.

  python3 dashboard/server.py            http://127.0.0.1:8787
  python3 dashboard/server.py --port N
"""
import json
import os
import shutil
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import agent  # noqa: E402

_MODES = {"draft", "factcheck", "revise", "apply"}


def _safe_name(name):
    """A draft file parameter must be a plain filename inside the drafts dir."""
    return name and os.path.basename(name) == name and not name.startswith(".")


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, root, addr):
        super().__init__(addr, Handler)
        self.root = root
        self.jobs = []
        self.jobs_lock = threading.Lock()
        self._job_seq = 0

    # --- jobs -----------------------------------------------------------
    def start_job(self, kind, fn):
        """fn receives its own job dict, so a run can park itself on a
        checkpoint (status 'waiting', yielded state visible) and resume when
        /api/resume sets its event. Keys starting with _ never leave the box."""
        with self.jobs_lock:
            self._job_seq += 1
            job = {"id": self._job_seq, "kind": kind, "status": "running",
                   "output": None, "error": None, "yielded": None}
            self.jobs.append(job)
            self.jobs = self.jobs[-20:]

        def _run():
            try:
                job["output"] = fn(job)
                job["status"] = "done"
            except Exception as e:
                job["error"] = str(e)
                job["status"] = "error"

        threading.Thread(target=_run, daemon=True).start()
        return job["id"]

    def job_by_id(self, job_id):
        with self.jobs_lock:
            return next((j for j in self.jobs if j["id"] == job_id), None)

    def jobs_public(self):
        with self.jobs_lock:
            return [{k: v for k, v in j.items() if not k.startswith("_")}
                    for j in self.jobs[::-1]]

    # --- state ----------------------------------------------------------
    def cfg(self):
        return agent.load_config(self.root)

    def drafts_dir(self):
        c = self.cfg()
        return os.path.join(self.root, c.get("state_dir", "state"), "drafts")

    def list_drafts(self):
        d = self.drafts_dir()
        out = []
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d)):
                if not fn.endswith(".html") or fn.endswith("-draft.html"):
                    continue
                p = os.path.join(d, fn)
                out.append({
                    "file": fn,
                    "slug": fn[:-5],
                    "mtime": int(os.path.getmtime(p)),
                    "approved": os.path.exists(p + ".approved"),
                })
        out.sort(key=lambda x: -x["mtime"])
        return out

    def runlog_records(self, limit=50):
        c = self.cfg()
        runs = os.path.join(self.root, c.get("state_dir", "state"), "runs")
        recs = []
        if os.path.isdir(runs):
            for fn in sorted(os.listdir(runs)):
                if fn.endswith(".jsonl"):
                    with open(os.path.join(runs, fn), encoding="utf-8") as f:
                        for line in f:
                            try:
                                recs.append(json.loads(line))
                            except ValueError:
                                pass
        recs.sort(key=lambda r: r.get("ts", ""))
        return recs[-limit:]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    # --- plumbing ---------------------------------------------------------
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n)) if n else {}
        except ValueError:
            return {}

    # --- GET ----------------------------------------------------------------
    def do_GET(self):
        srv = self.server
        parsed = urllib.parse.urlparse(self.path)
        path, q = parsed.path, urllib.parse.parse_qs(parsed.query)
        if path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), encoding="utf-8") as f:
                return self._send(200, f.read(), ctype="text/html")
        if path == "/api/state":
            c = srv.cfg()
            return self._json(200, {
                "name": c.get("name", "Blog Writing Agent"),
                "search_enabled": bool(c.get("search", {}).get("enabled")),
                "drafts": srv.list_drafts(),
                "jobs": srv.jobs_public(),
            })
        if path == "/api/jobs":
            return self._json(200, {"jobs": srv.jobs_public()})
        if path == "/api/runlog":
            return self._json(200, {"records": srv.runlog_records()})
        if path == "/api/draft":
            fn = (q.get("file") or [""])[0]
            if not _safe_name(fn):
                return self._json(400, {"error": "bad file name"})
            p = os.path.join(srv.drafts_dir(), fn)
            if not os.path.exists(p):
                return self._json(404, {"error": "no such draft"})
            with open(p, encoding="utf-8") as f:
                return self._send(200, f.read(), ctype="text/plain")
        return self._json(404, {"error": "not found"})

    # --- POST -----------------------------------------------------------------
    def do_POST(self):
        srv = self.server
        body = self._body()
        if self.path == "/api/run":
            mode = body.get("mode")
            if mode not in _MODES:
                return self._json(400, {"error": "unknown mode %r" % mode})
            try:
                job_id = self._start_mode(srv, mode, body)
            except ValueError as e:
                return self._json(400, {"error": str(e)})
            return self._json(200, {"job_id": job_id})
        if self.path == "/api/resume":
            job = srv.job_by_id(body.get("job_id"))
            if not job:
                return self._json(404, {"error": "no such job"})
            ev = job.get("_resume")
            if job["status"] == "waiting" and ev:
                ev.set()
                return self._json(200, {"resumed": True})
            return self._json(200, {"resumed": False,
                                    "note": "job is not waiting on a checkpoint"})
        if self.path == "/api/approve":
            fn = body.get("file", "")
            if not _safe_name(fn):
                return self._json(400, {"error": "bad file name"})
            p = os.path.join(srv.drafts_dir(), fn)
            if not os.path.exists(p):
                return self._json(404, {"error": "no such draft"})
            open(p + ".approved", "w", encoding="utf-8").write("")
            c = srv.cfg()
            pub = c.get("publish", {}).get("dir")
            published_to = None
            if pub:
                os.makedirs(pub, exist_ok=True)
                shutil.copy(p, os.path.join(pub, fn))
                published_to = os.path.join(pub, fn)
            return self._json(200, {"approved": True, "published_to": published_to})
        return self._json(404, {"error": "not found"})

    def _start_mode(self, srv, mode, body):
        cfg, root = srv.cfg(), srv.root

        def draft_path(field="file"):
            fn = body.get(field, "")
            if not _safe_name(fn):
                raise ValueError("bad file name")
            return os.path.join(srv.drafts_dir(), fn)

        if mode == "draft":
            idea = (body.get("idea") or "").strip()
            if not idea:
                raise ValueError("an idea is required")
            review = bool(body.get("review"))
            pause = bool(body.get("pause"))

            def run(job):
                checkpoint = None
                if pause:
                    ev = threading.Event()
                    job["_resume"] = ev

                    def checkpoint(info):
                        # Park this thread: yield what she gathered, wait for
                        # the human click. Nothing is lost by waiting.
                        job["yielded"] = info
                        job["status"] = "waiting"
                        ev.wait()
                        job["status"] = "running"
                return agent.draft(cfg, root, idea, review=review,
                                   do_search=not body.get("no_search"),
                                   checkpoint=checkpoint)
            return srv.start_job("draft", run)
        if mode == "factcheck":
            p = draft_path()
            return srv.start_job("factcheck", lambda job: agent.factcheck(cfg, root, p))
        if mode == "revise":
            p = draft_path()
            return srv.start_job("revise", lambda job: agent.revise(cfg, root, p))
        note = (body.get("note") or "").strip()
        if not note:
            raise ValueError("a note is required")
        p = draft_path()
        return srv.start_job("apply", lambda job: agent.apply_note(cfg, root, p, note))


def make_server(root, port=8787):
    return DashboardServer(root, ("127.0.0.1", port))


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Your agent's dashboard")
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()
    root = os.path.dirname(HERE)
    srv = make_server(root, port=args.port)
    name = srv.cfg().get("name", "Blog Writing Agent")
    print("%s's dashboard: http://127.0.0.1:%d  (Ctrl-C to stop)"
          % (name, srv.server_address[1]))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

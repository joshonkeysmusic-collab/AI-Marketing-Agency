"""Engine dashboard — localhost-only owner cockpit (DASHBOARD-PLAN.md P1).

  python dashboard/server.py          -> http://127.0.0.1:8765

Read-only over the repo's own files, plus ONE safe verb (POST /api/tenant/<t>/poll).
No send / approve / mark verbs exist here by design: Telegram is the only approval
surface. Binds 127.0.0.1 only; state contains third-party data, never expose this.
"""
import csv, json, subprocess, sys, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8765


def load(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def tenants():
    out = {}
    for cfg in sorted(ROOT.glob("tenants/*/config.json")):
        c = load(cfg, {})
        if c.get("tenant"):
            out[c["tenant"]] = c
    return out


def tenant_state(c):
    return load(ROOT / c.get("state", "approvals/state.json"), {})


def summary(name, c):
    state = tenant_state(c)
    today = time.strftime("%Y-%m-%d")
    pending = ready = sent_today = 0
    last = ""
    for b in state.values():
        for it in b.get("items", {}).values():
            st = it.get("status")
            if st == "pending":
                pending += 1
            if st in ("approved", "edited") and not it.get("sent"):
                ready += 1
            if it.get("sent") and str(it.get("sent_at", "")).startswith(today):
                sent_today += 1
            last = max(last, str(it.get("sent_at") or ""), str(it.get("decided_at") or ""))
    tok, days_left = c.get("publish", {}).get("linkedin_token"), None
    if tok:
        t = load(ROOT / tok, {})
        if t.get("expires_at"):
            days_left = round((t["expires_at"] - time.time()) / 86400, 1)
    return {"tenant": name, "platform": c.get("platform"), "identity": c.get("account_identity"),
            "caps": c.get("caps", {}), "windows": c.get("windows_local", []),
            "pending": pending, "ready": ready, "sent_today": sent_today,
            "batches": len(state), "last_activity": last or None, "token_days_left": days_left,
            "paused": bool(c.get("paused", False))}


def log_tail(rows):
    p = ROOT / "leads" / "engagement-log.csv"
    if not p.exists():
        return []
    with p.open(encoding="utf-8", errors="replace", newline="") as f:
        recs = list(csv.DictReader(f))
    return recs[-rows:][::-1]


class H(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        parts = [x for x in u.path.split("/") if x]
        q = urllib.parse.parse_qs(u.query)
        ts = tenants()
        if u.path in ("/", "/index.html"):
            body = (ROOT / "dashboard" / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/api/tenants":
            self._json([summary(n, c) for n, c in ts.items()])
        elif len(parts) == 4 and parts[:2] == ["api", "tenant"] and parts[3] == "state" and parts[2] in ts:
            self._json(tenant_state(ts[parts[2]]))
        elif u.path == "/api/spill":
            self._json(load(ROOT / "approvals" / "decisions-spill.json", []))
        elif u.path == "/api/log":
            self._json(log_tail(int(q.get("rows", ["50"])[0])))
        elif u.path == "/api/opportunities":
            p = ROOT / "leads" / "opportunities.csv"
            self._json(list(csv.DictReader(p.open(encoding="utf-8", errors="replace", newline=""))) if p.exists() else [])
        elif u.path == "/api/insights/latest":
            files = sorted(ROOT.glob("insights/weekly-*.md"))
            self._json({"file": files[-1].name if files else None,
                        "markdown": files[-1].read_text(encoding="utf-8", errors="replace") if files else ""})
        elif u.path == "/api/health":
            self._json({"tenants": [summary(n, c) for n, c in ts.items()],
                        "spill_entries": len(load(ROOT / "approvals" / "decisions-spill.json", []))})
        else:
            self._json({"error": "not found"}, 404)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_POST(self):
        parts = [x for x in self.path.split("/") if x]
        ts = tenants()
        if len(parts) >= 3 and parts[:2] == ["api", "tenant"] and parts[2] in ts:
            name, c = parts[2], ts[parts[2]]
            cfg_path = ROOT / "tenants" / name / "config.json"
            if len(parts) == 4 and parts[3] == "poll":
                r = subprocess.run([sys.executable, str(ROOT / "approvals" / "telegram_approvals.py"),
                                    "poll", "--tenant", str(cfg_path)],
                                   capture_output=True, text=True, timeout=120, cwd=ROOT)
                return self._json({"ok": r.returncode == 0, "output": (r.stdout + r.stderr).strip()})
            if len(parts) == 4 and parts[3] == "pause":
                c["paused"] = not c.get("paused", False)
                cfg_path.write_text(json.dumps(c, indent=2, ensure_ascii=False), encoding="utf-8")
                return self._json({"ok": True, "paused": c["paused"]})
            if len(parts) == 6 and parts[3] == "batch" and parts[5] == "resend":
                bid = urllib.parse.unquote(parts[4])
                state = tenant_state(c)
                if bid in state and any(it.get("sent") for it in state[bid]["items"].values()):
                    return self._json({"ok": False, "error": "batch has sent items; resend would reset them"}, 409)
                bf = ROOT / c.get("batches_dir", "approvals/batches") / f"{bid}.json"
                if not bf.exists():
                    return self._json({"ok": False, "error": f"batch file not found: {bf.name}"}, 404)
                r = subprocess.run([sys.executable, str(ROOT / "approvals" / "telegram_approvals.py"),
                                    "send", str(bf), "--tenant", str(cfg_path)],
                                   capture_output=True, text=True, timeout=300, cwd=ROOT)
                return self._json({"ok": r.returncode == 0, "output": (r.stdout + r.stderr).strip()})
            if len(parts) == 7 and parts[3] == "item" and parts[6] == "edit":
                bid, iid = urllib.parse.unquote(parts[4]), urllib.parse.unquote(parts[5])
                text = str(self._body().get("text", "")).strip()
                sp = ROOT / c.get("state", "approvals/state.json")
                state = load(sp, {})
                it = state.get(bid, {}).get("items", {}).get(iid)
                if not it:
                    return self._json({"ok": False, "error": "item not found"}, 404)
                if it.get("sent"):
                    return self._json({"ok": False, "error": "item already sent; not editable"}, 409)
                if not text:
                    return self._json({"ok": False, "error": "empty text"}, 400)
                it["final_text"] = text
                it["note"] = (it.get("note", "") + " · edited via dashboard").strip(" ·")
                sp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
                return self._json({"ok": True})
        self._json({"error": "not found"}, 404)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"Dashboard on http://127.0.0.1:{PORT} (localhost only)")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()

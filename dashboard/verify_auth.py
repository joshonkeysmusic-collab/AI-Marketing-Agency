"""Verification for room auth + tenant isolation. Run with the server up:

  python dashboard/verify_auth.py [--base http://127.0.0.1:8765] [--keep]

Proves: /room and every API are locked without a session; wrong tokens are refused; a client
("Tropics Medspa") can onboard on its own, sees only its own workspace, cannot read or decide
josh-linkedin items; the admin still sees josh-linkedin unchanged. The admin token is read from
dashboard/auth.local.json on this machine and never printed. The test tenant is deleted at the
end unless --keep is given. Exit code 0 only if every check passes.
"""
import http.cookiejar, json, shutil, sys, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--base=")), "http://127.0.0.1:8765")
KEEP = "--keep" in sys.argv
results = []


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface 302s instead of following them, so redirects can be asserted."""
    def redirect_request(self, *a, **k):
        return None


def client():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), NoRedirect())


def call(op, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with op.open(req, timeout=30) as r:
            raw = r.read().decode(errors="replace")
            return r.status, (json.loads(raw) if raw.startswith(("{", "[")) else raw), r.headers
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        return e.code, (json.loads(raw) if raw.startswith(("{", "[")) else raw), e.headers


def check(name, cond, detail=""):
    cond = bool(cond)
    results.append(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not cond else ""))


anon, admin, tropics = client(), client(), client()

# 1. locked without a session
s, _, h = call(anon, "GET", "/room")
check("anonymous /room redirects to /login", s == 302 and "/login" in (h.get("Location") or ""), f"status {s}")
s, _, h = call(anon, "GET", "/")
check("anonymous dashboard redirects to /login", s == 302, f"status {s}")
s, j, _ = call(anon, "GET", "/api/room/state")
check("anonymous /api/room/state is 401", s == 401, f"status {s}")
s, j, _ = call(anon, "POST", "/api/room/decide", {"batch": "x", "item": "y", "decision": "approved"})
check("anonymous decide is 401", s == 401, f"status {s}")
s, j, _ = call(anon, "POST", "/api/room/message", {"text": "hi"})
check("anonymous message is 401", s == 401, f"status {s}")
s, j, _ = call(anon, "POST", "/api/login", {"token": "definitely-not-a-token"})
check("wrong token is refused", s == 401 and not j.get("ok"), f"status {s}")

# 2. admin baseline (token read locally, never printed)
admin_token = json.loads((ROOT / "dashboard" / "auth.local.json").read_text(encoding="utf-8"))["admin_token"]
s, j, _ = call(admin, "POST", "/api/login", {"token": admin_token})
check("admin login sets a session", s == 200 and j.get("role") == "admin" and j.get("tenant") == "josh-linkedin", f"status {s}")
s, before, _ = call(admin, "GET", "/api/room/state")
check("admin sees josh-linkedin", s == 200 and before.get("tenant") == "josh-linkedin", f"status {s}")
josh_batches = sorted({it["batch"] for it in before.get("pending", []) + before.get("queued", []) + before.get("recent", [])})
josh_sig = (len(before.get("pending", [])), len(before.get("queued", [])), len(before.get("inbox", [])))

# 3. client onboarding, independently
auth_local = json.loads((ROOT / "dashboard" / "auth.local.json").read_text(encoding="utf-8"))
profile = {"name": "Dr Sarah Mensah", "company": "Tropics Medspa", "platform": "linkedin",
           "invite_code": auth_local.get("onboard_invite_code") or "",
           "profile_url": "https://www.linkedin.com/company/tropics-medspa", "audience": "women 30-55 in Lagos and Abuja comparing aesthetic clinics",
           "regions": ["Africa"], "tone": ["Warm", "Expert", "Premium"], "avoid": ["discounts", "before/after shock images"],
           "pillars": ["Safe, evidence-led treatments", "What to ask a clinic before you book", "Client stories (with consent)"],
           "team": {"amara": {"name": "Ngozi Adeyemi", "title": "Front desk · your first call", "tone": "teal"},
                    "tomas": {"name": "Kofi Mensah", "title": "Content lead · treatments & stories", "tone": "violet"}}}
s, j, _ = call(tropics, "POST", "/api/onboard", profile)
slug = j.get("tenant") if isinstance(j, dict) else None
check("Tropics Medspa onboards and gets a token", s == 200 and j.get("ok") and slug and slug.startswith("tropics-medspa") and j.get("token"), f"status {s} {j if not isinstance(j, dict) else j.get('error')}")
tdir = ROOT / "tenants" / (slug or "none")
check("tenant folder isolated (own config, team, state, inbox, batches)", slug is not None and all((tdir / p).exists() for p in ("config.json", "team.json", "state/state.json", "state/inbox.json", "batches")))
cfg = json.loads((tdir / "config.json").read_text(encoding="utf-8")) if slug else {}
check("new tenant starts paused with its own state path", cfg.get("paused") is True and cfg.get("state") == f"tenants/{slug}/state/state.json")
check("custom team names saved", slug is not None and any(m["name"] == "Ngozi Adeyemi" and m["tone"] == "teal" for m in json.loads((tdir / "team.json").read_text(encoding="utf-8"))))

# 4. client isolation
s, j, _ = call(tropics, "GET", "/api/room/state")
check("client sees only its own workspace", s == 200 and j.get("tenant") == slug and j.get("role") == "client" and j.get("pending") == [] and j.get("owner_first") == "Sarah", f"status {s} tenant {j.get('tenant') if isinstance(j, dict) else j}")
s, j, _ = call(tropics, "GET", "/api/room/state?tenant=josh-linkedin")
check("client cannot switch to josh-linkedin via query", s == 200 and j.get("tenant") == slug, f"got {j.get('tenant') if isinstance(j, dict) else j}")
check("client state carries no josh engagement data", j.get("engagement") == {} and j.get("log") == [])
if josh_batches:
    s, j, _ = call(tropics, "POST", "/api/room/decide", {"tenant": "josh-linkedin", "batch": josh_batches[0], "item": "r1", "decision": "approved"})
    check("client decide on a josh batch is refused", s == 403, f"status {s}")
    s, j, _ = call(tropics, "POST", "/api/room/decide", {"batch": josh_batches[0], "item": "r1", "decision": "approved"})
    check("client decide on a josh batch id in own workspace is 'no such batch'", s == 404, f"status {s}")
for path in ("/api/tenants", "/api/log", "/api/opportunities", "/api/health", "/api/tenant/josh-linkedin/state"):
    s, j, _ = call(tropics, "GET", path)
    check(f"client blocked from admin API {path}", s == 403, f"status {s}")
s, j, _ = call(tropics, "POST", "/api/room/message", {"text": "Hello from Tropics Medspa"})
check("client message lands in its own inbox", s == 200 and j.get("ok") and j.get("at"), f"status {s}")
own_inbox = json.loads((tdir / "state" / "inbox.json").read_text(encoding="utf-8")) if slug else []
josh_inbox = json.loads((ROOT / "approvals" / "inbox.json").read_text(encoding="utf-8"))
check("message is in the client inbox, not in josh's", any(m.get("text") == "Hello from Tropics Medspa" for m in own_inbox) and not any(m.get("text") == "Hello from Tropics Medspa" for m in josh_inbox))
s2, j2, _ = call(client(), "POST", "/api/login", {"token": json.loads((tdir / "auth.local.json").read_text(encoding="utf-8"))["token"]}) if slug else (0, {}, None)
check("client token signs in again from a fresh browser", s2 == 200 and j2.get("tenant") == slug, f"status {s2}")

# 5. admin unchanged
s, after, _ = call(admin, "GET", "/api/room/state")
after_sig = (len(after.get("pending", [])), len(after.get("queued", [])), len(after.get("inbox", [])))
check("josh-linkedin pending/queued/inbox unchanged by the client's onboarding", after_sig == josh_sig, f"{josh_sig} -> {after_sig}")
s, j, _ = call(admin, "GET", f"/api/room/state?tenant={slug}")
check("admin can open the client workspace", s == 200 and j.get("tenant") == slug)
s, j, _ = call(admin, "POST", "/api/logout")
s, j, _ = call(admin, "GET", "/api/room/state")
check("admin logout ends the session", s == 401, f"status {s}")

# cleanup
if slug and not KEEP:
    shutil.rmtree(tdir, ignore_errors=True)
    print(f"cleaned up test tenant {slug} (use --keep to keep it)")
elif slug:
    print(f"kept test tenant {slug}")
print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)

"""Verification for /api/sync/state and its conflict guard. Run with the server up:

  python dashboard/verify_sync.py [--base http://127.0.0.1:8765] [--keep]

All loopback — no tunnel, no external host, proves the mechanism works before it's ever
pointed at a real hosted URL. Creates a throwaway tenant, issues it a sync token, and
checks: a fresh push creates new items; a *stale* push (snapshot older than a room-side
decision) cannot overwrite that decision; a *current* push can still land a `sent`
confirmation on top of an approved item; sent never un-sets; the inbox merge is
deduplicated; auth is enforced. Exit code 0 only if every check passes.
"""
import json, shutil, sys, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dashboard"))
import sync, tenancy  # noqa: E402

BASE = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--base=")), "http://127.0.0.1:8765")
KEEP = "--keep" in sys.argv
results = []


def check(name, cond, detail=""):
    cond = bool(cond)
    results.append(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not cond else ""))


def call(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except ValueError:
            return e.code, {}


# --- set up a throwaway tenant, direct (no HTTP — onboarding itself is verify_auth.py's job) ---
slug, cfg, _team = tenancy.create_tenant({
    "name": "Sync Test", "company": f"Sync Test Co {int(time.time())}", "platform": "linkedin",
})
token = sync.issue_sync_token(slug)
state_p = ROOT / cfg["state"]
inbox_p = ROOT / cfg["inbox"]
check("test tenant created with its own state file", state_p.exists() and json.loads(state_p.read_text()) == {})

# --- auth ---
s, j = call("POST", "/api/sync/state", {"tenant": slug, "batches": {}}, token=None)
check("push with no token is refused", s == 401 and not j.get("ok"), f"status {s}")
s, j = call("POST", "/api/sync/state", {"tenant": slug, "batches": {}}, token="not-the-real-token")
check("push with wrong token is refused", s == 401 and not j.get("ok"), f"status {s}")
s, j = call("POST", "/api/sync/state", {"tenant": "no-such-tenant", "batches": {}}, token="anything")
check("push for an unknown tenant is refused", s == 401 and not j.get("ok"), f"status {s}")

# --- fresh push: new items are accepted ---
t0 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
batch1 = {"b1": {"title": "First batch", "items": {
    "i1": {"type": "comment", "target": "Someone's post", "text": "Draft one", "status": "pending"},
    "i2": {"type": "connect", "target": "Someone else", "text": "Hi, connecting", "status": "pending"},
}}}
s, j = call("POST", "/api/sync/state", {"tenant": slug, "snapshot_at": t0, "batches": batch1}, token=token)
check("fresh push of 2 new items is accepted", s == 200 and j.get("ok") and j.get("accepted") == 2 and j.get("rejected_stale") == 0, f"{s} {j}")
state = json.loads(state_p.read_text())
check("both items landed on disk with the pushed text", state.get("b1", {}).get("items", {}).get("i1", {}).get("text") == "Draft one"
      and state["b1"]["items"]["i2"]["status"] == "pending")

# --- simulate a real room decision on i1 (this is what the Approve button in the room writes) ---
# timestamps here are second-resolution (matching telegram_approvals.py's own _stamp()), so
# sleep past a second boundary or "stale" and "current" can compare equal, not less-than.
time.sleep(1.1)
t_decided = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
state["b1"]["items"]["i1"].update(status="approved", decided_via="room", decided_at=t_decided)
state_p.write_text(json.dumps(state, indent=2))

# --- STALE push (snapshot before the room's decision) must not overwrite it ---
stale_push = {"b1": {"title": "First batch", "items": {"i1": {"status": "rejected", "text": "stale local rewrite"}}}}
s, j = call("POST", "/api/sync/state", {"tenant": slug, "snapshot_at": t0, "batches": stale_push}, token=token)
after = json.loads(state_p.read_text())["b1"]["items"]["i1"]
check("stale push is flagged rejected_stale, not applied", s == 200 and j.get("rejected_stale") == 1 and j.get("accepted") == 0, f"{j}")
check("room's approved decision survives the stale push", after["status"] == "approved" and after["text"] == "Draft one", f"got {after}")

# --- CURRENT push (snapshot after the decision) landing a sent confirmation ---
time.sleep(1.1)
t1 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
sent_push = {"b1": {"title": "First batch", "items": {"i1": {"sent": True, "sent_at": "2026-09-30 12:00"}}}}
s, j = call("POST", "/api/sync/state", {"tenant": slug, "snapshot_at": t1, "batches": sent_push}, token=token)
after = json.loads(state_p.read_text())["b1"]["items"]["i1"]
check("current push can mark an approved item sent", s == 200 and j.get("accepted") == 1 and after.get("sent") is True and after.get("sent_at") == "2026-09-30 12:00", f"got {after}")
check("the approved status/text are untouched by the sent-only push", after["status"] == "approved" and after["text"] == "Draft one")

# --- sent is one-way: cannot be unset through this route ---
s, j = call("POST", "/api/sync/state", {"tenant": slug, "snapshot_at": t1, "batches": {"b1": {"items": {"i1": {"sent": False}}}}}, token=token)
after = json.loads(state_p.read_text())["b1"]["items"]["i1"]
check("sent cannot be unset by a later push", after.get("sent") is True)

# --- a pending item (never decided in the room) can still be freely updated by any push ---
s, j = call("POST", "/api/sync/state", {"tenant": slug, "snapshot_at": t0, "batches": {"b1": {"items": {"i2": {"text": "Revised draft"}}}}}, token=token)
after = json.loads(state_p.read_text())["b1"]["items"]["i2"]
check("an undecided item accepts an update from any snapshot time", s == 200 and j.get("accepted") == 1 and after["text"] == "Revised draft", f"got {after}")

# --- inbox: appended and deduplicated ---
msg = {"at": "2026-09-30T09:00:00Z", "text": "hello from the engine", "source": "engine"}
s, j1 = call("POST", "/api/sync/state", {"tenant": slug, "batches": {}, "inbox": [msg]}, token=token)
s, j2 = call("POST", "/api/sync/state", {"tenant": slug, "batches": {}, "inbox": [msg]}, token=token)
inbox = json.loads(inbox_p.read_text())
check("inbox message added once, deduped on replay", j1.get("inbox_added") == 1 and j2.get("inbox_added") == 0 and len(inbox) == 1, f"{j1} {j2} inbox={inbox}")

# cleanup
if not KEEP:
    shutil.rmtree(ROOT / "tenants" / slug, ignore_errors=True)
    print(f"cleaned up test tenant {slug} (use --keep to keep it)")
else:
    print(f"kept test tenant {slug}")
print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)

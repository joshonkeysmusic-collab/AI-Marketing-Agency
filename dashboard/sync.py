"""Local-to-hosted state sync — PUSH ONLY, one direction (local engine -> hosted room).

This is half of a real two-way sync. It lets a local engine (wherever
`approvals/telegram_approvals.py` actually runs and drives the browser — see
ENGINE-PLAN.md's "operated service, not a binary" note) push newly-drafted items and
"sent" confirmations up to a hosted room. It does NOT pull decisions back down: an
approval made in a hosted room does not by itself reach a remote engine. See
dashboard/verify_sync.py's summary for why that half isn't built here, and the sketch
of what it would take.

No new broadcast channel is needed for what this DOES do: the room already re-reads
state.json/inbox.json on every ~3s poll (dashboard/chatroom.html), so once a push is
merged into a tenant's files the room shows it on its next tick.

Conflict guard (why a stale local push can never clobber a live decision):
  - A brand-new item (batch/id the hosted copy has never seen) is always accepted.
  - Once an item has been decided *in the room* (`decided_via == "room"`), an incoming
    push may change its status/text only if the push's own `snapshot_at` is at or after
    that item's `decided_at` — i.e. the local engine had already seen the room's
    decision before it took this snapshot. An older snapshot cannot overwrite a newer
    room decision; it's recorded as "rejected_stale" instead, and the file isn't touched.
  - `sent` / `sent_at` from the engine is always accepted once an item is approved or
    edited (only the engine knows whether the post actually went out), and `sent` is
    one-way: nothing can ever flip it back to false through this route.
"""
"""
Pull direction (room -> local engine), added for the decision half of the sync:
  GET /api/sync/decisions?tenant=<slug>&since=<watermark>
Returns items decided since `since` — approved/rejected/edited, from EITHER surface (a
Telegram tap or a room button; the local engine needs to learn about a decision no matter
which one it came from) — plus any room-authored inbox message ("user feedback") since then.
The room is ground truth for a decision: apply_decisions() layers the decided fields onto
the local copy without touching anything else about that item (its target/text/image are
local business, not the room's).
"""
import json, secrets, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SYNCABLE_FIELDS = ("status", "final_text", "decided_at", "decided_via", "note", "type", "target", "text", "image")


def _auth_path(slug):
    return ROOT / "tenants" / slug / "auth.local.json"


def issue_sync_token(slug):
    """Create (or replace) the machine-to-machine token for this tenant's local worker.
    Distinct from the client's own login token, so leaking one doesn't leak the other."""
    p = _auth_path(slug)
    d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    d["sync_token"] = secrets.token_urlsafe(24)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")
    return d["sync_token"]


def sync_token(slug):
    try:
        return json.loads(_auth_path(slug).read_text(encoding="utf-8")).get("sync_token")
    except (OSError, ValueError):
        return None


def merge_items(existing, incoming, snapshot_at):
    """existing, incoming: {item_id: item dict} for one batch. Returns
    (merged_items, accepted_ids, rejected_stale_ids)."""
    merged = dict(existing)
    accepted, rejected = [], []
    for iid, inc in incoming.items():
        cur = existing.get(iid)
        if cur is None:
            merged[iid] = inc
            accepted.append(iid)
            continue
        room_decided = cur.get("decided_via") == "room" and cur.get("decided_at")
        stale = bool(room_decided and (not snapshot_at or snapshot_at < cur["decided_at"]))
        out = dict(cur)
        if not stale:
            for f in SYNCABLE_FIELDS:
                if f in inc:
                    out[f] = inc[f]
        # A "sent" confirmation is the engine's own fact (it just posted the thing) and is
        # always layered on top of an approved/edited item, even over a "stale" push — the
        # engine sent what it saw as approved; that fact doesn't stop being true. It never
        # downgrades a rejection, and never unsets an existing True.
        if inc.get("sent") and out.get("status") in ("approved", "edited") and not out.get("sent"):
            out["sent"] = True
            out["sent_at"] = inc.get("sent_at") or time.strftime("%Y-%m-%d %H:%M")
        merged[iid] = out
        (rejected if stale else accepted).append(iid)
    return merged, accepted, rejected


def merge_batches(state, incoming_batches, snapshot_at):
    """state: the full tenant state dict (loaded from state.json), mutated in place.
    incoming_batches: {batch_id: {"title": str, "items": {item_id: item dict}}}.
    Returns (accepted_count, rejected_stale_count)."""
    accepted = rejected = 0
    for bid, payload in incoming_batches.items():
        state.setdefault(bid, {"title": payload.get("title", bid), "items": {}})
        merged, acc, rej = merge_items(state[bid].get("items", {}), payload.get("items", {}), snapshot_at)
        state[bid]["items"] = merged
        accepted += len(acc)
        rejected += len(rej)
    return accepted, rejected


def merge_inbox(inbox, incoming):
    """Append-only, de-duplicated by the message's `at` stamp."""
    have = {m.get("at") for m in inbox}
    added = [m for m in incoming if m.get("at") not in have]
    return inbox + added, len(added)


DECISION_FIELDS = ("status", "final_text", "decided_at", "decided_via", "note", "sent", "sent_at")


def decisions_since(state, since):
    """state: a tenant's full state dict. Returns ({batch_id: {title, items}}, as_of) —
    every item with a decided_at at or after `since` (empty `since` = everything decided so
    far, for a worker's first pull), and as_of, the watermark to pass as `since` next time."""
    out, newest = {}, since or ""
    for bid, b in state.items():
        items = {}
        for iid, it in b.get("items", {}).items():
            d = it.get("decided_at")
            if d and (not since or d > since):
                items[iid] = {k: it[k] for k in DECISION_FIELDS if k in it}
                newest = max(newest, d)
        if items:
            out[bid] = {"title": b.get("title", bid), "items": items}
    return out, (newest or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


def apply_decisions(local_state, batches):
    """Layer room decisions onto the local copy — creates the item if the local engine never
    had it (rare: a decision on something it doesn't know about yet), otherwise only touches
    the decided fields, leaving target/text/image/type as the local engine's own business.
    Mutates local_state in place. Returns how many items were touched."""
    n = 0
    for bid, payload in batches.items():
        local_state.setdefault(bid, {"title": payload.get("title", bid), "items": {}})
        for iid, dec in payload.get("items", {}).items():
            local_state[bid]["items"].setdefault(iid, {})
            local_state[bid]["items"][iid].update(dec)
            n += 1
    return n

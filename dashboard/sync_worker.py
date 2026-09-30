"""Local sync worker: two independent loops between a local engine's files and a hosted
room. Push watches local state/inbox by mtime and sends new/changed items up; pull polls
the room for decisions and layers them onto the local copy. See dashboard/sync.py's
docstring for the exact rules each direction follows.

  python dashboard/sync_worker.py --tenant tenants/josh-linkedin/config.json \
      --url https://your-hosted-room.example.com

Needs a sync token (--token or the SYNC_TOKEN env var) — issue one first:
  python -c "import sys; sys.path.insert(0,'dashboard'); import sync; print(sync.issue_sync_token('SLUG'))"
Test against a local server before pointing this at a real host: --url http://127.0.0.1:8765

Flags:
  --push-interval   seconds between checking local files for changes to push (default 5)
  --pull-interval   seconds between polling the room for decisions (default 3)
  --local-state     where pulled decisions are applied (default: the tenant's own state path
                     from --tenant's config — override this to point at a genuinely separate
                     local mirror, e.g. when testing, or when this engine's own working copy
                     isn't the same file the room reads from)
  --no-push / --no-pull   run only one direction
  --once            one push check + one pull check, then exit (for testing)
"""
import argparse, json, os, sys, threading, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save(p, data):
    Path(p).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def request(method, url, token, body=None, timeout=20):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def push_once(base_url, token, slug, state_p, inbox_p, pushed_ats, log):
    state = load(state_p, {})
    inbox_all = load(inbox_p, [])
    new_inbox = [m for m in inbox_all if m.get("at") not in pushed_ats]
    snapshot_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        res = request("POST", base_url.rstrip("/") + "/api/sync/state", token,
                      {"tenant": slug, "snapshot_at": snapshot_at, "batches": state, "inbox": new_inbox})
        pushed_ats.update(m.get("at") for m in new_inbox if m.get("at"))
        log(f"push ok: accepted={res.get('accepted')} rejected_stale={res.get('rejected_stale')} inbox+={res.get('inbox_added')}")
    except urllib.error.HTTPError as e:
        log(f"push refused: {e.code} {e.read().decode(errors='replace')[:200]}")
    except (urllib.error.URLError, TimeoutError) as e:
        log(f"push failed (will retry): {e}")


def pull_once(base_url, token, slug, local_state_p, since, log):
    url = base_url.rstrip("/") + "/api/sync/decisions?" + urllib.parse.urlencode({"tenant": slug, "since": since})
    try:
        res = request("GET", url, token)
    except urllib.error.HTTPError as e:
        log(f"pull refused: {e.code} {e.read().decode(errors='replace')[:200]}")
        return since
    except (urllib.error.URLError, TimeoutError) as e:
        log(f"pull failed (will retry): {e}")
        return since
    batches = res.get("batches") or {}
    if batches:
        local = load(local_state_p, {})
        n = 0
        for bid, payload in batches.items():
            local.setdefault(bid, {"title": payload.get("title", bid), "items": {}})
            for iid, dec in payload.get("items", {}).items():
                local[bid]["items"].setdefault(iid, {})
                local[bid]["items"][iid].update(dec)
                n += 1
        save(local_state_p, local)
        log(f"pull ok: applied {n} decision(s), now at {res.get('as_of')}")
    return res.get("as_of") or since


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", required=True, help="path to the tenant's config.json")
    ap.add_argument("--url", required=True, help="hosted room base URL (or http://127.0.0.1:PORT to test locally)")
    ap.add_argument("--push-interval", type=float, default=5.0)
    ap.add_argument("--pull-interval", type=float, default=3.0)
    ap.add_argument("--local-state", help="override where pulled decisions are written (default: the tenant's own state path)")
    ap.add_argument("--token")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--no-pull", action="store_true")
    ap.add_argument("--once", action="store_true", help="one push check + one pull check, then exit")
    a = ap.parse_args()

    cfg = load(a.tenant, {})
    slug = cfg.get("tenant")
    if not slug:
        sys.exit(f"no \"tenant\" field in {a.tenant}")
    token = a.token or os.environ.get("SYNC_TOKEN")
    if not token:
        sys.exit("no sync token: pass --token or set SYNC_TOKEN (see this file's docstring to issue one)")

    state_p = (ROOT / cfg.get("state", "approvals/state.json")).resolve()
    inbox_p = (ROOT / cfg.get("inbox", "approvals/inbox.json")).resolve()
    local_state_p = Path(a.local_state).resolve() if a.local_state else state_p

    def log(tag, msg):
        print(f"[{time.strftime('%H:%M:%S')}] {tag}: {msg}", flush=True)

    print(f"tenant '{slug}' <-> {a.url}\n  push: {state_p.name}/{inbox_p.name} (every {a.push_interval}s)"
          f"\n  pull: -> {local_state_p} (every {a.pull_interval}s)", flush=True)

    stop = threading.Event()

    def push_loop():
        pushed_ats, seen = set(), (None, None)
        while not stop.is_set():
            m = (state_p.stat().st_mtime if state_p.exists() else None,
                 inbox_p.stat().st_mtime if inbox_p.exists() else None)
            if m != seen:
                push_once(a.url, token, slug, state_p, inbox_p, pushed_ats, lambda s: log("push", s))
                seen = m
            if a.once:
                return
            stop.wait(a.push_interval)

    def pull_loop():
        since = ""
        while not stop.is_set():
            since = pull_once(a.url, token, slug, local_state_p, since, lambda s: log("pull", s))
            if a.once:
                return
            stop.wait(a.pull_interval)

    threads = []
    if not a.no_push:
        threads.append(threading.Thread(target=push_loop, daemon=True))
    if not a.no_pull:
        threads.append(threading.Thread(target=pull_loop, daemon=True))
    if not threads:
        sys.exit("both --no-push and --no-pull given; nothing to do")
    for t in threads:
        t.start()
    try:
        if a.once:
            for t in threads:
                t.join()
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()

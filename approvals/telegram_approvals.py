"""Telegram approval gate for the LinkedIn Growth Engine.

Agents never send anything to LinkedIn until Josh approves it here.

Setup (once):
  1. In Telegram, message @BotFather -> /newbot -> copy the bot token.
  2. Store the token as a user environment variable (never in chat or in this repo):
       setx TELEGRAM_BOT_TOKEN "<token>"      (then open a new terminal)
  3. Open your new bot in Telegram and send /start.
  4. python telegram_approvals.py setup     -> locks the bot to your chat only.

Use:
  python telegram_approvals.py send batch.json   # push a batch to Telegram
  python telegram_approvals.py poll              # collect button taps (via n8n when n8n_decisions_url is set)
  python telegram_approvals.py status [batch_id] # show decisions
  python telegram_approvals.py approved [batch_id]  # JSON of items cleared to send (not yet sent)
  python telegram_approvals.py mark <batch_id> <item_id> sent   # record that an item went out
  python telegram_approvals.py notify "text"     # plain message to Josh (reports, alerts)
  python telegram_approvals.py inbox [todo|clear] # free-text/voice messages Josh sent (not an item edit)
  python telegram_approvals.py sync-context [--force]  # push a project snapshot to the n8n bot

Multi-tenant (ENGINE-PLAN.md): every command accepts `--tenant tenants/<name>/config.json`
(or TENANT_CONFIG env var). Default is tenants/josh-linkedin/config.json, which points at
the original approvals/ files, so plain invocations behave exactly as before.

batch.json:
  {"batch_id": "2026-09-28-am", "title": "Monday morning",
   "items": [{"id": "c1", "type": "comment", "target": "Asim Khan · post on scaling",
              "text": "Processes, almost every time...", "image": null}]}
"""
import calendar, hashlib, json, os, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def _load_tenant():
    """Multi-tenant support (ENGINE-PLAN.md step 1). Resolution order: --tenant <path>
    flag, TENANT_CONFIG env var, tenants/josh-linkedin/config.json, else legacy
    single-tenant defaults. Paths inside the config are repo-root-relative."""
    p = None
    if "--tenant" in sys.argv:
        i = sys.argv.index("--tenant")
        p = Path(sys.argv[i + 1])
        del sys.argv[i:i + 2]
    elif os.environ.get("TENANT_CONFIG"):
        p = Path(os.environ["TENANT_CONFIG"])
    else:
        default = ROOT / "tenants" / "josh-linkedin" / "config.json"
        p = default if default.exists() else None
    if p is None:
        return {}
    if not p.is_absolute():
        p = ROOT / p
    if not p.exists():
        sys.exit(f"Tenant config not found: {p}")
    cfg = json.loads(p.read_text(encoding="utf-8"))
    local = p.parent / "approval.local.json"
    if local.exists():  # sensitive wiring (chat id, n8n URLs) lives out of git
        for k, v in json.loads(local.read_text(encoding="utf-8")).items():
            if isinstance(v, dict):
                cfg.setdefault(k, {}).update({a: b for a, b in v.items() if b is not None})
            else:
                cfg[k] = v
    return cfg


TENANT = _load_tenant()


def _tpath(key, default):
    v = TENANT.get(key)
    return (ROOT / v) if v else default


CONF = _tpath("conf", HERE / "telegram.json")   # chat id + update offset (no secrets)
STATE = _tpath("state", HERE / "state.json")    # every batch and decision
API = "https://api.telegram.org/bot{token}/{method}"
LABEL = {"post": "📝 Post", "comment": "💬 Comment", "reply": "↩️ Reply",
         "dm": "✉️ DM", "connect": "🤝 Connection request", "lead": "📄 PDF delivery"}


def token():
    env_name = (TENANT.get("bot_token_env")
                or TENANT.get("approval", {}).get("bot_token_env")
                or "TELEGRAM_BOT_TOKEN")
    t = os.environ.get(env_name)
    if not t and os.name == "nt":  # saved via the Windows dialog but this process started earlier
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                t = winreg.QueryValueEx(k, env_name)[0]
        except OSError:
            t = None
    if not t:
        sys.exit(f"{env_name} is not set. See setup steps at the top of this file.")
    return t


def load(p, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def save(p, data):
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def call(method, params=None, files=None):
    url = API.format(token=token(), method=method)
    if files:  # multipart upload for photos / documents
        boundary = "----li" + str(int(time.time() * 1000))
        body = b""
        for k, v in (params or {}).items():
            body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
        for k, path in files.items():
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{Path(path).name}\"\r\n"
                     "Content-Type: application/octet-stream\r\n\r\n").encode() + Path(path).read_bytes() + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    else:
        data = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
                                       for k, v in (params or {}).items()}).encode()
        req = urllib.request.Request(url, data=data)
    for attempt in range(4):  # retry slow or dropped connections
        try:
            with urllib.request.urlopen(req, timeout=300 if files else 30) as r:
                res = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            # Cosmetic calls (button acknowledgements, button relabels) may fail on old taps; carry on.
            if method in ("answerCallbackQuery", "editMessageReplyMarkup"):
                return None
            sys.exit(f"Telegram rejected {method}: {e.code} {e.read().decode(errors='replace')}")
        except (TimeoutError, OSError) as e:
            if attempt == 3:
                sys.exit(f"Telegram unreachable on {method}: {e}")
            time.sleep(3 * (attempt + 1))
    if not res.get("ok"):
        sys.exit(f"Telegram error on {method}: {res}")
    return res["result"]


def chat_id():
    c = TENANT.get("approval", {}).get("chat_id") or load(CONF, {}).get("chat_id")
    if not c:
        sys.exit("No chat_id in the tenant config or conf file. Run `setup` first "
                 "(send /start to your bot), or set approval.chat_id in the tenant config.")
    return c


def keyboard(batch_id, item_id, approve_label="✅ Approve"):
    # n8n mode now supports Edit too: tapping it arms "awaitingEdit" in the workflow's
    # static data, and Josh's next plain-text message becomes the new text for that item.
    return {"inline_keyboard": [[
        {"text": approve_label, "callback_data": f"a|{batch_id}|{item_id}"},
        {"text": "✏️ Edit", "callback_data": f"e|{batch_id}|{item_id}"},
        {"text": "❌ Reject", "callback_data": f"r|{batch_id}|{item_id}"}]]}


def cmd_setup():
    updates = call("getUpdates", {"timeout": 0})
    starts = [u["message"] for u in updates if u.get("message", {}).get("chat", {}).get("type") == "private"]
    if not starts:
        sys.exit("No message found. Open your bot in Telegram, send /start (or 'hi'), then run setup again.")
    m = starts[-1]
    conf = {"chat_id": m["chat"]["id"], "owner": m["from"].get("first_name", ""),
            "offset": updates[-1]["update_id"] + 1}
    save(CONF, conf)
    call("sendMessage", {"chat_id": conf["chat_id"],
                         "text": "✅ Connected. I'll send LinkedIn approvals here. Only this chat can approve."})
    print(f"Locked to chat {conf['chat_id']} ({conf['owner']}).")


def cmd_send(path):
    batch = json.loads(Path(path).read_text(encoding="utf-8"))
    state = load(STATE, {})
    bid, cid = batch["batch_id"], chat_id()
    state[bid] = {"title": batch.get("title", bid), "items": {}}
    n = len(batch["items"])
    call("sendMessage", {"chat_id": cid, "parse_mode": "HTML",
                         "text": f"<b>{batch.get('title', bid)}</b>\n{n} item(s) waiting for approval.\n"
                                 "Tap a button under each one. Reply /approveall to approve everything left."})
    for it in batch["items"]:
        head = f"{LABEL.get(it['type'], it['type'])} · {it.get('target', '')}".strip(" ·")
        body = f"{head}\n\n{it['text']}"
        kb = keyboard(bid, it["id"], it.get("approve_label", "✅ Approve"))
        if it.get("video"):
            vid = (Path(path).resolve().parent / it["video"]).resolve()  # paths are relative to the batch file
            params = {"chat_id": cid, "caption": body[:1024], "reply_markup": json.dumps(kb), "supports_streaming": "true"}
            for k in ("width", "height", "duration"):  # tell Telegram the true shape so it doesn't guess
                if it.get(k):
                    params[k] = it[k]
            files = {"video": str(vid)}
            if it.get("image"):  # optional cover shown before playback
                files["thumbnail"] = str((Path(path).resolve().parent / it["image"]).resolve())
            msg = call("sendVideo", params, files=files)
            if len(body) > 1024:
                call("sendMessage", {"chat_id": cid, "text": body})
        elif it.get("image"):
            img = (Path(path).resolve().parent / it["image"]).resolve()  # paths are relative to the batch file
            msg = call("sendPhoto", {"chat_id": cid, "caption": body[:1024], "reply_markup": json.dumps(kb)},
                       files={"photo": str(img)})
            if len(body) > 1024:  # long post text goes in a follow-up message
                call("sendMessage", {"chat_id": cid, "text": body})
        else:
            msg = call("sendMessage", {"chat_id": cid, "text": body, "reply_markup": kb})
        state[bid]["items"][it["id"]] = {**it, "status": "pending", "message_id": msg["message_id"]}
        save(STATE, state)  # save after each item so a failure never loses what was sent
    print(f"Sent {n} item(s) for batch {bid}.")


def set_status(state, bid, iid, status, cid, note=None):
    item = state[bid]["items"][iid]
    item["status"] = status
    if note:
        item["final_text"] = note
    tag = {"approved": "✅ Approved", "rejected": "❌ Rejected", "edited": "✏️ Approved with your edit",
           "awaiting_edit": "✏️ Waiting for your new text"}[status]
    try:
        call("editMessageReplyMarkup", {"chat_id": cid, "message_id": item["message_id"],
                                        "reply_markup": {"inline_keyboard": [[{"text": tag, "callback_data": "noop"}]]}})
    except SystemExit:
        pass


INBOX = _tpath("inbox", HERE / "inbox.json")  # free-text messages Josh sends that aren't an edit reply


SPILL = ROOT / "approvals" / "decisions-spill.json"  # taps for OTHER tenants sharing this bot


def cmd_poll_n8n(url):
    """Taps and free-text messages are received by the n8n workflow 'Telegram Two-Way
    Approval Gate'; collect both here. Because several tenants can share one bot and
    the decisions endpoint clears on read, any tap whose batch isn't in THIS tenant's
    state is parked in a shared spill file for the owning tenant's next poll."""
    state = load(STATE, {})
    for attempt in range(4):  # retry network blips
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                payload = json.loads(r.read())
            decisions, messages = payload.get("decisions", []), payload.get("messages", [])
            break
        except (TimeoutError, OSError) as e:
            if attempt == 3:
                sys.exit(f"n8n unreachable: {e}")
            time.sleep(3 * (attempt + 1))
    spill = load(SPILL, [])
    ours_from_spill = [d for d in spill if d.get("batch_id") in state]
    keep_spilled = [d for d in spill if d.get("batch_id") not in state]
    decisions = ours_from_spill + decisions
    applied, parked = 0, 0
    for d in decisions:
        if d.get("batch_id") not in state:
            key = (d.get("batch_id"), d.get("item_id"), d.get("at"))
            if key not in {(s.get("batch_id"), s.get("item_id"), s.get("at")) for s in keep_spilled}:
                keep_spilled.append(d)
                parked += 1
            continue
        item = state.get(d.get("batch_id"), {}).get("items", {}).get(d.get("item_id"))
        if not item or item["status"] != "pending":
            continue
        if d.get("decision") in ("approved", "rejected"):
            item["status"] = d["decision"]
            item["decided_at"] = d.get("at")
            applied += 1
        elif d.get("decision") == "edited":
            item["status"] = "edited"
            item["final_text"] = d.get("text", "")
            item["decided_at"] = d.get("at")
            applied += 1
    save(STATE, state)
    save(SPILL, keep_spilled[-100:])
    if messages:
        # The n8n bot may re-send a message later with its reply flags; merge by timestamp
        # and never bring back one that was already cleared.
        inbox, cleared = load(INBOX, []), set(load(CONF, {}).get("cleared_msg_ats", []))
        by_at = {m.get("at"): m for m in inbox}
        for m in messages:
            if m.get("at") in cleared:
                continue
            if m.get("at") in by_at:
                by_at[m["at"]].update(m)
            else:
                inbox.append(m)
                by_at[m.get("at")] = m
        save(INBOX, inbox)
    print(f"n8n: {len(decisions)} tap(s) received, {applied} decision(s) applied, "
          f"{len(messages)} free-text message(s) received."
          + (f" {parked} parked for another tenant." if parked else "")
          + (f" {len(ours_from_spill)} picked up from spill." if ours_from_spill else ""))
    for m in messages:
        print(f"  [msg] {m.get('at', '')}: {m.get('text', '')}".encode(
            sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8"))


def cmd_poll():
    conf, state = load(CONF, {}), load(STATE, {})
    decisions_url = TENANT.get("approval", {}).get("n8n_decisions_url") or conf.get("n8n_decisions_url")
    if decisions_url:
        return cmd_poll_n8n(decisions_url)
    cid = chat_id()
    updates = call("getUpdates", {"offset": conf.get("offset", 0), "timeout": 0})
    pending_edit = conf.get("pending_edit")
    for u in updates:
        conf["offset"] = u["update_id"] + 1
        if "callback_query" in u:
            q = u["callback_query"]
            if q["from"]["id"] != cid and q["message"]["chat"]["id"] != cid:
                continue  # ignore anyone else
            call("answerCallbackQuery", {"callback_query_id": q["id"]})
            parts = q.get("data", "").split("|")
            if len(parts) != 3 or parts[1] not in state or parts[2] not in state[parts[1]]["items"]:
                continue
            action, bid, iid = parts
            if action == "a":
                set_status(state, bid, iid, "approved", cid)
            elif action == "r":
                set_status(state, bid, iid, "rejected", cid)
            elif action == "e":
                set_status(state, bid, iid, "awaiting_edit", cid)
                pending_edit = [bid, iid]
                call("sendMessage", {"chat_id": cid, "text": "Send the new text as your next message."})
        elif "message" in u and u["message"]["chat"]["id"] == cid:
            text = u["message"].get("text", "")
            if text.startswith("/approveall"):
                for bid, b in state.items():
                    for iid, it in b["items"].items():
                        if it["status"] == "pending":
                            set_status(state, bid, iid, "approved", cid)
                call("sendMessage", {"chat_id": cid, "text": "✅ Everything pending is approved."})
            elif pending_edit and text and not text.startswith("/"):
                bid, iid = pending_edit
                set_status(state, bid, iid, "edited", cid, note=text)
                pending_edit = None
                call("sendMessage", {"chat_id": cid, "text": "✏️ Saved. That version will be used."})
    conf["pending_edit"] = pending_edit
    save(CONF, conf)
    save(STATE, state)
    print(f"Processed {len(updates)} update(s).")


def cmd_status(bid=None):
    for b, data in load(STATE, {}).items():
        if bid and b != bid:
            continue
        print(f"\n{b} · {data['title']}")
        for iid, it in data["items"].items():
            print(f"  {iid:<6} {it['type']:<8} {it['status']:<14} {it.get('target', '')}")


def cmd_approved(bid=None):
    out = [{**it, "text": it.get("final_text", it["text"])}
           for b, data in load(STATE, {}).items() if not bid or b == bid
           for it in data["items"].values() if it["status"] in ("approved", "edited") and not it.get("sent")]
    print(json.dumps(out, indent=2, ensure_ascii=False))


def cmd_mark(bid, iid, what):
    state = load(STATE, {})
    item = state[bid]["items"][iid]
    item["sent"] = what == "sent"
    item["sent_at"] = time.strftime("%Y-%m-%d %H:%M")
    save(STATE, state)
    print(f"{bid}/{iid} marked {what}.")


def cmd_notify(text):
    call("sendMessage", {"chat_id": chat_id(), "text": text})
    print("Sent.")


BOT_GRACE_SECONDS = 180  # how long the n8n bot gets to answer before the local task steps in


def msg_age(m):
    try:
        return time.time() - calendar.timegm(time.strptime(m.get("at", "")[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return 1e9


def needs_local(m):
    """True when the scheduled task should answer: the bot handed it off, failed, or never finished."""
    if m.get("handoff"):
        return True
    if m.get("bot_replied"):
        return False
    return not m.get("bot_pending") or msg_age(m) > BOT_GRACE_SECONDS


def cmd_inbox(mode=None):
    """Free-text messages Josh sent that weren't an edit reply to a pending item.
    inbox        list everything, with what the n8n bot already did
    inbox todo   only messages the scheduled task still has to answer (the bot handed off or failed)
    inbox clear  clear everything except messages the bot is still answering"""
    inbox = load(INBOX, [])
    shown = [m for m in inbox if needs_local(m)] if mode == "todo" else inbox
    if not shown:
        print("Nothing for the scheduled task to answer." if mode == "todo" else "Inbox empty.")
    for m in shown:
        tag = ("handoff" if m.get("handoff") else "bot replied" if m.get("bot_replied")
               else "bot answering" if not needs_local(m) else "unanswered")
        voice = " (voice)" if m.get("voice") else ""
        line = f"  {m.get('at', '')} [{tag}]{voice}: {m.get('text', '')}"
        if m.get("bot_reply"):
            line += f"\n      bot said: {m['bot_reply']}"
        enc = sys.stdout.encoding or "utf-8"
        print(line.encode(enc, errors="replace").decode(enc))
    if mode == "clear":
        keep = [m for m in inbox if not needs_local(m) and not m.get("bot_replied")]
        done = [m for m in inbox if m not in keep]
        conf = load(CONF, {})
        conf["cleared_msg_ats"] = (conf.get("cleared_msg_ats", []) + [m.get("at") for m in done])[-300:]
        save(CONF, conf)
        save(INBOX, keep)
        print(f"Cleared {len(done)} message(s)." + (f" Kept {len(keep)} the bot is still answering." if keep else ""))


# What the n8n bot knows about the project: the files that answer Josh's usual questions.
CONTEXT_FILES = ["RUNBOOK.md", "strategy/proof-library.md", "strategy/engagement-playbook.md",
                 "strategy/content-backlog-oct-2026.md", "strategy/gap-analysis-*.md",
                 "posts/*.md", "queue/*.json", "leads/opportunities.csv", "leads/lead-magnets.csv"]


def build_context():
    root = HERE.parent
    parts, seen = [], set()

    def add(f, label=None, text=None):
        seen.add(f)
        body = text if text is not None else f.read_text(encoding="utf-8", errors="replace")
        parts.append(f"===== {label or f.relative_to(root).as_posix()} =====\n{body}")

    for pattern in CONTEXT_FILES:
        for f in sorted(root.glob(pattern)):
            if f.is_file() and f not in seen:
                add(f)
    for report in sorted((root / "insights").glob("weekly-*.md"))[-1:]:  # latest Insights report
        add(report)
    log = root / "leads" / "engagement-log.csv"
    if log.exists():
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        add(log, "leads/engagement-log.csv (header + last 40 rows)", "\n".join(lines[:1] + lines[1:][-40:]))
    rows = []
    for bid, b in sorted(load(STATE, {}).items())[-8:]:
        counts = {}
        for it in b["items"].values():
            s = it["status"] + (" (sent)" if it.get("sent") else "")
            counts[s] = counts.get(s, 0) + 1
        rows.append(f"{bid} · {b['title']}: " + ", ".join(f"{v} {k}" for k, v in counts.items()))
    parts.append("===== approval batches (last 8, from approvals/state.json) =====\n" + "\n".join(rows))
    return f"Snapshot taken {time.strftime('%Y-%m-%d %H:%M')} (Josh's local time).\n\n" + "\n\n".join(parts)


def cmd_sync_context(force=False):
    """Push a text snapshot of the project to the n8n bot, only when it changed."""
    conf = load(CONF, {})
    url, tok = conf.get("n8n_context_url"), conf.get("n8n_context_token")
    if not url or not tok:
        sys.exit("n8n_context_url / n8n_context_token missing from approvals/telegram.json.")
    text = build_context()
    digest = hashlib.sha256(text.split("\n", 1)[1].encode()).hexdigest()  # ignore the timestamp line
    if not force and conf.get("context_hash") == digest:
        print("Context unchanged; not synced.")
        return
    req = urllib.request.Request(url, data=json.dumps({"token": tok, "text": text}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read() or b"{}")
    except (TimeoutError, OSError) as e:
        sys.exit(f"n8n unreachable: {e}")
    if not res.get("ok"):
        sys.exit(f"n8n refused the context sync: {res}")
    conf["context_hash"] = digest
    save(CONF, conf)
    print(f"Context synced ({res.get('chars')} chars).")


if __name__ == "__main__":
    a = sys.argv[1:] or ["help"]
    {"setup": lambda: cmd_setup(), "send": lambda: cmd_send(a[1]), "poll": lambda: cmd_poll(),
     "status": lambda: cmd_status(a[1] if len(a) > 1 else None),
     "approved": lambda: cmd_approved(a[1] if len(a) > 1 else None),
     "mark": lambda: cmd_mark(a[1], a[2], a[3]), "notify": lambda: cmd_notify(" ".join(a[1:])),
     "inbox": lambda: cmd_inbox(a[1] if len(a) > 1 else None),
     "sync-context": lambda: cmd_sync_context("--force" in a)}.get(a[0], lambda: print(__doc__))()


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

batch.json:
  {"batch_id": "2026-09-28-am", "title": "Monday morning",
   "items": [{"id": "c1", "type": "comment", "target": "Asim Khan · post on scaling",
              "text": "Processes, almost every time...", "image": null}]}
"""
import json, os, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONF = HERE / "telegram.json"   # chat id + update offset (no secrets)
STATE = HERE / "state.json"     # every batch and decision
API = "https://api.telegram.org/bot{token}/{method}"
LABEL = {"post": "📝 Post", "comment": "💬 Comment", "reply": "↩️ Reply",
         "dm": "✉️ DM", "connect": "🤝 Connection request", "lead": "📄 PDF delivery"}


def token():
    t = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not t and os.name == "nt":  # saved via the Windows dialog but this process started earlier
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                t = winreg.QueryValueEx(k, "TELEGRAM_BOT_TOKEN")[0]
        except OSError:
            t = None
    if not t:
        sys.exit("TELEGRAM_BOT_TOKEN is not set. See setup steps at the top of this file.")
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
    c = load(CONF, {}).get("chat_id")
    if not c:
        sys.exit("Run `setup` first (send /start to your bot, then run setup).")
    return c


def keyboard(batch_id, item_id, approve_label="✅ Approve"):
    if load(CONF, {}).get("n8n_decisions_url"):  # n8n mode: approve / reject only
        return {"inline_keyboard": [[
            {"text": approve_label, "callback_data": f"a|{batch_id}|{item_id}"},
            {"text": "❌ Reject", "callback_data": f"r|{batch_id}|{item_id}"}]]}
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


def cmd_poll_n8n(url):
    """Taps are received by the n8n workflow 'Telegram Two-Way Approval Gate'; collect them here."""
    state = load(STATE, {})
    for attempt in range(4):  # retry network blips
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                decisions = json.loads(r.read()).get("decisions", [])
            break
        except (TimeoutError, OSError) as e:
            if attempt == 3:
                sys.exit(f"n8n unreachable: {e}")
            time.sleep(3 * (attempt + 1))
    applied = 0
    for d in decisions:
        item = state.get(d.get("batch_id"), {}).get("items", {}).get(d.get("item_id"))
        if item and item["status"] == "pending" and d.get("decision") in ("approved", "rejected"):
            item["status"] = d["decision"]
            item["decided_at"] = d.get("at")
            applied += 1
    save(STATE, state)
    print(f"n8n: {len(decisions)} tap(s) received, {applied} decision(s) applied.")


def cmd_poll():
    conf, state = load(CONF, {}), load(STATE, {})
    if conf.get("n8n_decisions_url"):
        return cmd_poll_n8n(conf["n8n_decisions_url"])
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


if __name__ == "__main__":
    a = sys.argv[1:] or ["help"]
    {"setup": lambda: cmd_setup(), "send": lambda: cmd_send(a[1]), "poll": lambda: cmd_poll(),
     "status": lambda: cmd_status(a[1] if len(a) > 1 else None),
     "approved": lambda: cmd_approved(a[1] if len(a) > 1 else None),
     "mark": lambda: cmd_mark(a[1], a[2], a[3]), "notify": lambda: cmd_notify(" ".join(a[1:]))}.get(a[0], lambda: print(__doc__))()


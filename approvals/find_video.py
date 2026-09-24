"""Find the latest video Josh sent to the bot and download it (without consuming approval updates)."""
import json, sys, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import telegram_approvals as t

conf = t.load(t.CONF, {})
ups = t.call("getUpdates", {"offset": conf.get("offset", 0), "timeout": 0})
vids = []
for u in ups:
    m = u.get("message") or {}
    if m.get("chat", {}).get("id") != conf["chat_id"]:
        continue
    doc = m.get("document") or {}
    v = m.get("video") or m.get("video_note") or (doc if str(doc.get("mime_type", "")).startswith("video") else None)
    if v:
        vids.append({"date": m["date"], "file_id": v["file_id"], "size": v.get("file_size"),
                     "duration": v.get("duration"), "mime": v.get("mime_type"), "caption": m.get("caption", "")})
print(f"pending updates: {len(ups)}, videos: {len(vids)}")
if not vids:
    sys.exit(0)
latest = vids[-1]
print(json.dumps(latest, indent=1))
if (latest["size"] or 0) > 20 * 1024 * 1024:
    sys.exit("Video is over 20 MB: the Telegram bot API can't download it.")
f = t.call("getFile", {"file_id": latest["file_id"]})
out = Path(__file__).resolve().parent.parent / "assets" / "video-inbox"
out.mkdir(parents=True, exist_ok=True)
dest = out / f"telegram-{latest['date']}{Path(f['file_path']).suffix or '.mp4'}"
urllib.request.urlretrieve(f"https://api.telegram.org/file/bot{t.token()}/{f['file_path']}", dest)
print("saved:", dest)

"""LinkedIn publisher for the Growth Engine - official API, no cookies, no scraping.

Posts ONLY items that Josh has already approved in the Telegram gate
(approvals/state.json: status approved/edited, not yet sent). Reports
success/failure back to state.json and to Josh on Telegram.

One-time setup (Josh does this, ~10 min):
  1. https://developer.linkedin.com -> Create app (name: "Growth Engine",
     LinkedIn page: optional, logo: anything).
  2. App -> Products: add "Share on LinkedIn" and
     "Sign In with LinkedIn using OpenID Connect".
  3. App -> Auth: add redirect URL exactly:  http://localhost:8330/callback
  4. Copy Client ID and Client Secret from the Auth tab, then in a terminal:
       setx LINKEDIN_CLIENT_ID "<client id>"
       setx LINKEDIN_CLIENT_SECRET "<client secret>"
     (open a NEW terminal afterwards so the variables load)
  5. python publish/linkedin_api.py auth   -> sign in, allow. Token saved
     to publish/linkedin_token.json (gitignored). Tokens last ~60 days,
     then re-run auth.

Use:
  python publish/linkedin_api.py whoami                    # check token
  python publish/linkedin_api.py test  <batch_id> <item>   # dry run, posts nothing
  python publish/linkedin_api.py post  <batch_id> <item>   # publish one approved item

Notes:
  - The API cannot schedule for later (that is UI-only). The Posting Manager
    runs `post` at the slot time instead.
  - Instagram: needs a Business/Creator IG linked to the Meta Graph API -
    not set up; ask Josh whether the brand has an IG account first.
"""
import json, os, secrets, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def _load_tenant():
    """Same tenant resolution as the gateway (ENGINE-PLAN step 2): --tenant flag,
    TENANT_CONFIG env, default tenants/josh-linkedin/config.json, else legacy."""
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
    # so subprocesses (e.g. the Telegram notify) resolve the same tenant
    os.environ["TENANT_CONFIG"] = str(p)
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
PUB = TENANT.get("publish", {})


def _tpath(value, default):
    return (ROOT / value) if value else default


TOKEN = _tpath(PUB.get("linkedin_token"), HERE / "linkedin_token.json")
STATE = _tpath(TENANT.get("state"), ROOT / "approvals" / "state.json")
BATCHES = _tpath(TENANT.get("batches_dir"), ROOT / "approvals" / "batches")
REDIRECT = "http://localhost:8330/callback"
SCOPES = "openid profile w_member_social"


def creds():
    cid = os.environ.get(PUB.get("client_id_env", "LINKEDIN_CLIENT_ID"))
    sec = os.environ.get(PUB.get("client_secret_env", "LINKEDIN_CLIENT_SECRET"))
    if not (cid and sec) and os.name == "nt":  # set via setx but this shell is older
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                cid = cid or winreg.QueryValueEx(k, PUB.get("client_id_env", "LINKEDIN_CLIENT_ID"))[0]
                sec = sec or winreg.QueryValueEx(k, PUB.get("client_secret_env", "LINKEDIN_CLIENT_SECRET"))[0]
        except OSError:
            pass
    if not (cid and sec):
        sys.exit("LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET not set. See setup steps at the top of this file.")
    return cid, sec


def load(p, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def save(p, data):
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def api(url, payload=None, headers=None, method=None, raw=None):
    h = {"Authorization": f"Bearer {load(TOKEN, {}).get('access_token', '')}",
         "X-Restli-Protocol-Version": "2.0.0"}
    h.update(headers or {})
    data = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
    if payload is not None:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            body = r.read()
            return r.status, dict(r.headers), (json.loads(body) if body.strip() else {})
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), {"error": e.read().decode(errors="replace")}


def token_ok():
    t = load(TOKEN, {})
    if not t.get("access_token"):
        sys.exit("No token. Run: python publish/linkedin_api.py auth")
    if time.time() > t.get("expires_at", 0):
        sys.exit("Token expired (~60 day lifetime). Run: python publish/linkedin_api.py auth")
    return t


def notify(text):
    try:
        subprocess.run([sys.executable, str(ROOT / "approvals" / "telegram_approvals.py"), "notify", text],
                       cwd=ROOT, timeout=60)
    except Exception as e:
        print(f"(Telegram notify failed: {e})")


def cmd_auth():
    cid, sec = creds()
    state = secrets.token_urlsafe(16)
    url = "https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode(
        {"response_type": "code", "client_id": cid, "redirect_uri": REDIRECT,
         "scope": SCOPES, "state": state})
    print("Open this URL, sign in as Josh Forkwa, and click Allow:\n\n" + url + "\n")
    got = {}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if self.path.startswith("/callback") and q.get("state", [""])[0] == state:
                got["code"] = q.get("code", [""])[0]
                msg = b"Done. You can close this tab and go back to the terminal."
            else:
                msg = b"Waiting for LinkedIn callback..."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(msg)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("localhost", 8330), H)
    srv.timeout = 300
    while "code" not in got:
        srv.handle_request()
    srv.server_close()
    if not got["code"]:
        sys.exit("No authorization code received.")
    data = urllib.parse.urlencode({"grant_type": "authorization_code", "code": got["code"],
                                   "redirect_uri": REDIRECT, "client_id": cid, "client_secret": sec}).encode()
    with urllib.request.urlopen(urllib.request.Request(
            "https://www.linkedin.com/oauth/v2/accessToken", data=data), timeout=60) as r:
        tok = json.loads(r.read())
    t = {"access_token": tok["access_token"], "expires_at": time.time() + tok.get("expires_in", 0) - 3600}
    save(TOKEN, t)
    st, _, me = api("https://api.linkedin.com/v2/userinfo")
    if st != 200:
        sys.exit(f"Token saved but userinfo failed: {me}")
    t["person_urn"] = f"urn:li:person:{me['sub']}"
    t["name"] = me.get("name", "")
    save(TOKEN, t)
    days = int((t["expires_at"] - time.time()) / 86400)
    print(f"Authorized as {t['name']} ({t['person_urn']}). Token valid ~{days} days.")


def cmd_whoami():
    t = token_ok()
    st, _, me = api("https://api.linkedin.com/v2/userinfo")
    days = int((t["expires_at"] - time.time()) / 86400)
    print(f"{me.get('name', '?')} · {t.get('person_urn', '?')} · token ok, ~{days} days left"
          if st == 200 else f"Token invalid: {me}")


def get_item(bid, iid):
    state = load(STATE, {})
    item = state.get(bid, {}).get("items", {}).get(iid)
    if not item:
        sys.exit(f"{bid}/{iid} not found in approvals/state.json")
    if item["status"] not in ("approved", "edited"):
        sys.exit(f"REFUSED: {bid}/{iid} status is '{item['status']}', not approved. "
                 "Nothing publishes without Josh's approval in the Telegram gate.")
    if item.get("sent"):
        sys.exit(f"REFUSED: {bid}/{iid} was already sent at {item.get('sent_at')}. No duplicates.")
    text = item.get("final_text", item["text"])
    img = (BATCHES / item["image"]).resolve() if item.get("image") else None
    if img and not img.exists():
        sys.exit(f"Image not found: {img}")
    return state, item, text, img


def upload_image(person_urn, img):
    st, _, reg = api("https://api.linkedin.com/v2/assets?action=registerUpload", payload={
        "registerUploadRequest": {
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
            "owner": person_urn,
            "serviceRelationships": [{"relationshipType": "OWNER",
                                      "identifier": "urn:li:userGeneratedContent"}]}})
    if st != 200:
        sys.exit(f"registerUpload failed ({st}): {reg}")
    up = reg["value"]["uploadMechanism"]["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]
    asset = reg["value"]["asset"]
    st, _, res = api(up, raw=img.read_bytes(), method="PUT",
                     headers={"Content-Type": "application/octet-stream"})
    if st not in (200, 201):
        sys.exit(f"Image upload failed ({st}): {res}")
    return asset


def cmd_post(bid, iid, dry=False):
    t = token_ok()
    state, item, text, img = get_item(bid, iid)
    print(f"Item {bid}/{iid} · {item['type']} · approved · image={'yes' if img else 'no'}")
    print("--- text ---\n" + text + "\n------------")
    if dry:
        print("DRY RUN: nothing posted. Token, approval status and files all check out.")
        return
    media = []
    if img:
        media = [{"status": "READY", "media": upload_image(t["person_urn"], img)}]
        print("Image uploaded.")
    body = {"author": t["person_urn"], "lifecycleState": "PUBLISHED",
            "specificContent": {"com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "IMAGE" if media else "NONE",
                **({"media": media} if media else {})}},
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}}
    st, hdr, res = api("https://api.linkedin.com/v2/ugcPosts", payload=body)
    if st == 201:
        urn = hdr.get("x-restli-id", hdr.get("X-RestLi-Id", ""))
        item["sent"] = True
        item["sent_at"] = time.strftime("%Y-%m-%d %H:%M")
        item["post_urn"] = urn
        item["published_via"] = "linkedin_api"
        save(STATE, state)
        link = f"https://www.linkedin.com/feed/update/{urn}/" if urn else "(check your profile)"
        notify(f"Published via LinkedIn API: {bid}/{iid}. {link}")
        print(f"SUCCESS: published. {link}")
    else:
        notify(f"LinkedIn API publish FAILED for {bid}/{iid} (HTTP {st}). Item left unsent.")
        sys.exit(f"FAILED ({st}): {res}")


if __name__ == "__main__":
    a = sys.argv[1:] or ["help"]
    {"auth": lambda: cmd_auth(), "whoami": lambda: cmd_whoami(),
     "test": lambda: cmd_post(a[1], a[2], dry=True),
     "post": lambda: cmd_post(a[1], a[2])}.get(a[0], lambda: print(__doc__))()

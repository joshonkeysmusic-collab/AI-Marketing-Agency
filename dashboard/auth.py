"""Authentication for the dashboard and Virtual Room.

Two kinds of credential, both random and both kept out of git:
  admin token   dashboard/auth.local.json   -> role "admin", tenant josh-linkedin, may open any tenant
  client token  tenants/<slug>/auth.local.json -> role "client", locked to that tenant
A successful login creates a cookie session (HttpOnly, SameSite=Lax, 30 days) stored in
dashboard/auth.local.json. Tokens are compared in constant time; failed logins are throttled per IP.
Nothing in this module prints or logs a token.
"""
import hmac, json, secrets, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUTH_FILE = ROOT / "dashboard" / "auth.local.json"
ADMIN_TENANT = "josh-linkedin"
COOKIE = "room_session"
SESSION_SECONDS = 30 * 86400
MAX_ATTEMPTS, WINDOW = 8, 900          # failed logins per IP per 15 minutes
_lock = threading.Lock()
_attempts = {}


def _load():
    try:
        return json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(d):
    AUTH_FILE.write_text(json.dumps(d, indent=2), encoding="utf-8")


def ensure_admin():
    """Create the admin token on first run. Returns True when it was just created."""
    with _lock:
        d = _load()
        if d.get("admin_token"):
            return False
        d["admin_token"] = secrets.token_urlsafe(32)
        d.setdefault("sessions", {})
        d.setdefault("onboard_invite_code", None)   # set a string here to gate /onboard when public
        _save(d)
        return True


def invite_code():
    return _load().get("onboard_invite_code") or None


def issue_tenant_token(slug):
    tok = secrets.token_urlsafe(24)
    (ROOT / "tenants" / slug / "auth.local.json").write_text(
        json.dumps({"token": tok, "issued_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, indent=2), encoding="utf-8")
    return tok


def _tenant_tokens():
    out = {}
    for f in ROOT.glob("tenants/*/auth.local.json"):
        try:
            t = json.loads(f.read_text(encoding="utf-8")).get("token")
        except (OSError, ValueError):
            t = None
        if t:
            out[f.parent.name] = t
    return out


def throttled(ip):
    now = time.time()
    with _lock:
        recent = [t for t in _attempts.get(ip, []) if now - t < WINDOW]
        _attempts[ip] = recent
        return len(recent) >= MAX_ATTEMPTS


def record_failure(ip):
    with _lock:
        _attempts.setdefault(ip, []).append(time.time())


def login(token, ip):
    """Return (session_id, session) for a valid token, else (None, None)."""
    if throttled(ip):
        return None, None
    token = (token or "").strip()
    role = tenant = None
    admin = _load().get("admin_token") or ""
    if token and hmac.compare_digest(token, admin):
        role, tenant = "admin", ADMIN_TENANT
    else:
        for slug, t in _tenant_tokens().items():
            if token and hmac.compare_digest(token, t):
                role, tenant = "client", slug
                break
    if not role:
        record_failure(ip)
        return None, None
    sid = secrets.token_urlsafe(32)
    now = time.time()
    sess = {"tenant": tenant, "role": role, "created": now, "expires": now + SESSION_SECONDS}
    with _lock:
        d = _load()
        d["sessions"] = {k: v for k, v in d.get("sessions", {}).items() if v.get("expires", 0) > now}
        d["sessions"][sid] = sess
        _save(d)
    return sid, sess


def session(sid):
    if not sid:
        return None
    s = _load().get("sessions", {}).get(sid)
    return s if s and s.get("expires", 0) > time.time() else None


def logout(sid):
    with _lock:
        d = _load()
        if d.get("sessions", {}).pop(sid, None) is not None:
            _save(d)


def cookie_sid(cookie_header):
    for part in (cookie_header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE:
            return v.strip()
    return None

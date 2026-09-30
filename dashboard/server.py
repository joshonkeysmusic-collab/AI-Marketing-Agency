"""Engine dashboard + Virtual Room — owner cockpit and per-client rooms (DASHBOARD-PLAN.md P1).

  python dashboard/server.py                 -> http://127.0.0.1:8765
      /            dashboard (admin only)          /room     the team chat for the signed-in tenant
      /login       token sign-in                   /onboard  front-desk onboarding for new clients

Auth (dashboard/auth.py): the admin token (dashboard/auth.local.json, created on first run) opens
josh-linkedin and may switch to any tenant; a client token (tenants/<slug>/auth.local.json,
issued by onboarding) is locked to its own tenant. Every state read or mutation resolves the
tenant from the session, never from the request, so no tenant can see or decide another's items.
Decisions and messages still run approvals/telegram_approvals.py (`decide`, `say`) with the
tenant's own config, so a room decision is recorded exactly like a Telegram tap. Nothing here
sends to LinkedIn. Bind stays 127.0.0.1 unless HOST is set; put a TLS tunnel in front for public use.
"""
import csv, hmac, json, mimetypes, os, subprocess, sys, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auth, sync, tenancy  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))
GATEWAY = ROOT / "approvals" / "telegram_approvals.py"
ASSETS = (ROOT / "assets").resolve()
ONBOARD_LIMIT, ONBOARD_WINDOW = 5, 3600     # new workspaces per IP per hour
_onboards = {}


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
            local = load(cfg.parent / "approval.local.json", {})   # sensitive wiring, merged like the gateway does
            for k, v in local.items():
                if isinstance(v, dict):
                    c.setdefault(k, {}).update({a: b for a, b in v.items() if b is not None})
                else:
                    c[k] = v
            out[c["tenant"]] = c
    return out


def tenant_state(c):
    return load(ROOT / c.get("state", "approvals/state.json"), {})


def tenant_inbox(c):
    return load(ROOT / c.get("inbox", "approvals/inbox.json"), [])


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


def log_path(name, c):
    """The engagement log is per tenant; only the admin tenant has the legacy shared file."""
    if c.get("engagement_log"):
        return ROOT / c["engagement_log"]
    return ROOT / "leads" / "engagement-log.csv" if name == auth.ADMIN_TENANT else None


def log_rows(name, c):
    p = log_path(name, c)
    if not p or not p.exists():
        return []
    with p.open(encoding="utf-8", errors="replace", newline="") as f:
        return list(csv.DictReader(f))


def week_counts(name, c):
    out, cutoff = {}, time.time() - 7 * 86400
    for r in log_rows(name, c):
        try:
            ts = time.mktime(time.strptime(str(r.get("date", ""))[:10], "%Y-%m-%d"))
        except ValueError:
            continue
        if ts >= cutoff:
            a = (r.get("action") or "").strip()
            out[a] = out.get(a, 0) + 1
    return out


def asset_url(path):
    if not path:
        return None
    try:
        p = (ROOT / path).resolve()
        if p.is_file() and str(p).startswith(str(ASSETS)):
            return "/asset/" + urllib.parse.quote(p.relative_to(ASSETS).as_posix())
    except (OSError, ValueError):
        pass
    return None


def room_items(c):
    pending, queued, recent = [], [], []
    for bid, b in tenant_state(c).items():
        for iid, it in b.get("items", {}).items():
            row = {"batch": bid, "batch_title": b.get("title", ""), "id": iid, "type": it.get("type"),
                   "target": it.get("target"), "text": it.get("text"), "final_text": it.get("final_text"),
                   "image": asset_url(it.get("image")), "status": it.get("status"), "sent": bool(it.get("sent")),
                   "sent_at": it.get("sent_at"), "decided_at": it.get("decided_at"),
                   "decided_via": it.get("decided_via"), "note": it.get("note")}
            if row["status"] == "pending":
                pending.append(row)
            elif row["status"] in ("approved", "edited") and not row["sent"]:
                queued.append(row)
            else:
                recent.append(row)
    recent.sort(key=lambda r: str(r.get("sent_at") or r.get("decided_at") or ""), reverse=True)
    return pending, queued, recent[:15]


def health(c):
    env_name = c.get("bot_token_env") or c.get("approval", {}).get("bot_token_env") or "TELEGRAM_BOT_TOKEN"
    has_token = bool(os.environ.get(env_name))
    if not has_token and os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                has_token = bool(winreg.QueryValueEx(k, env_name)[0])
        except OSError:
            has_token = False
    conf = load(ROOT / c.get("conf", "approvals/telegram.json"), {})
    url = c.get("approval", {}).get("n8n_decisions_url") or conf.get("n8n_decisions_url") or ""
    return {"telegram": has_token, "n8n": bool(url) and not url.startswith("TODO")}   # booleans only


def room_state(name, c, sess):
    pending, queued, recent = room_items(c)
    inbox = [{k: m.get(k) for k in ("at", "text", "source", "bot_reply", "room_reply", "bot_replied", "handoff", "voice")}
             for m in tenant_inbox(c)[-40:]]
    owner = c.get("owner_name") or ("Joshua" if name == auth.ADMIN_TENANT else (c.get("account_identity") or "there"))
    words = [w for w in owner.replace("·", " ").split() if w.rstrip(".").lower() not in ("dr", "mr", "mrs", "ms", "miss", "prof")]
    return {"tenant": name, "platform": c.get("platform"), "identity": c.get("account_identity"),
            "owner_first": (words or ["there"])[0], "role": sess["role"], "paused": bool(c.get("paused", False)),
            "team": tenancy.load_team(name), "pillars": c.get("pillars", []),
            "pending": pending, "queued": queued, "recent": recent, "inbox": inbox,
            "engagement": week_counts(name, c), "log": log_rows(name, c)[-8:][::-1], "health": health(c),
            "served_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def gateway(cfg_path, *args, timeout=120):
    r = subprocess.run([sys.executable, str(GATEWAY), *args, "--tenant", str(cfg_path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, cwd=ROOT)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


class H(BaseHTTPRequestHandler):
    # ---- plumbing ----------------------------------------------------------------------
    def _headers(self, code, ctype, length, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or []):
            self.send_header(k, v)
        self.end_headers()

    def _json(self, obj, code=200, extra=None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._headers(code, "application/json; charset=utf-8", len(body), extra)
        self.wfile.write(body)

    def _file(self, path, ctype):
        body = Path(path).read_bytes()
        self._headers(200, ctype, len(body))
        self.wfile.write(body)

    def _redirect(self, loc):
        self.send_response(302)
        self.send_header("Location", loc)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _ip(self):
        fwd = self.headers.get("X-Forwarded-For", "")
        return fwd.split(",")[0].strip() or self.client_address[0]

    def _secure(self):
        return os.environ.get("ROOM_SECURE_COOKIES") == "1" or self.headers.get("X-Forwarded-Proto", "") == "https"

    def _cookie(self, sid, clear=False):
        v = f"{auth.COOKIE}={'' if clear else sid}; Path=/; HttpOnly; SameSite=Lax; Max-Age={0 if clear else auth.SESSION_SECONDS}"
        return ("Set-Cookie", v + ("; Secure" if self._secure() else ""))

    def _sess(self):
        return auth.session(auth.cookie_sid(self.headers.get("Cookie")))

    def _tenant_for(self, sess, requested, ts):
        """Clients are locked to their own tenant; the admin may switch to any existing one."""
        if sess["role"] == "admin" and requested in ts:
            return requested, ts[requested]
        name = sess["tenant"]
        return name, ts.get(name)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}") if n else {}
        except ValueError:
            return {}

    # ---- GET ---------------------------------------------------------------------------
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        parts = [x for x in u.path.split("/") if x]
        q = urllib.parse.parse_qs(u.query)
        page = ROOT / "dashboard"
        # public
        if u.path in ("/login", "/login/"):
            return self._file(page / "login.html", "text/html; charset=utf-8")
        if u.path in ("/onboard", "/onboard/"):
            return self._file(page / "onboard.html", "text/html; charset=utf-8")
        if u.path == "/api/onboard/config":
            return self._json({"invite_required": bool(auth.invite_code()), "platforms": sorted(tenancy.PRESETS)})
        if u.path == "/api/sync/decisions":
            # Pull side, machine-to-machine like the push route: bearer sync token, no cookie.
            slug = (q.get("tenant") or [""])[0]
            hdr = self.headers.get("Authorization", "")
            given = hdr[len("Bearer "):] if hdr.startswith("Bearer ") else ""
            expected = slug and sync.sync_token(slug)
            if not expected or not given or not hmac.compare_digest(given, expected):
                return self._json({"ok": False, "error": "missing or invalid sync token"}, 401)
            c = tenants().get(slug)
            if not c:
                return self._json({"ok": False, "error": "unknown tenant"}, 404)
            since = (q.get("since") or [""])[0]
            batches, as_of = sync.decisions_since(tenant_state(c), since)
            msgs = [m for m in tenant_inbox(c) if m.get("source") == "room" and (not since or (m.get("at") or "") > since)]
            return self._json({"ok": True, "as_of": as_of, "batches": batches, "inbox": msgs})
        sess = self._sess()
        if not sess:
            if u.path in ("/", "/index.html", "/room", "/room/", "/room.html"):
                return self._redirect("/login?next=" + urllib.parse.quote(u.path))
            return self._json({"error": "sign in required"}, 401)
        ts = tenants()
        # any signed-in tenant
        if u.path in ("/room", "/room/", "/room.html"):
            return self._file(page / "chatroom.html", "text/html; charset=utf-8")
        if u.path == "/api/me":
            name, c = self._tenant_for(sess, (q.get("tenant") or [None])[0], ts)
            return self._json({"tenant": name, "role": sess["role"], "identity": (c or {}).get("account_identity")})
        if u.path == "/api/room/state":
            name, c = self._tenant_for(sess, (q.get("tenant") or [None])[0], ts)
            return self._json(room_state(name, c, sess) if c else {"error": "tenant not found"}, 200 if c else 404)
        if u.path.startswith("/asset/"):
            rel = urllib.parse.unquote(u.path[len("/asset/"):])
            p = (ASSETS / rel).resolve()
            if p.is_file() and str(p).startswith(str(ASSETS)):
                return self._file(p, mimetypes.guess_type(str(p))[0] or "application/octet-stream")
            return self._json({"error": "not found"}, 404)
        # admin only from here
        if sess["role"] != "admin":
            return self._json({"error": "admin only"}, 403)
        if u.path in ("/", "/index.html"):
            self._file(page / "index.html", "text/html; charset=utf-8")
        elif u.path == "/api/tenants":
            self._json([summary(n, c) for n, c in ts.items()])
        elif len(parts) == 4 and parts[:2] == ["api", "tenant"] and parts[3] == "state" and parts[2] in ts:
            self._json(tenant_state(ts[parts[2]]))
        elif u.path == "/api/spill":
            self._json(load(ROOT / "approvals" / "decisions-spill.json", []))
        elif u.path == "/api/log":
            self._json(log_rows(auth.ADMIN_TENANT, ts.get(auth.ADMIN_TENANT, {}))[-int(q.get("rows", ["50"])[0]):][::-1])
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

    # ---- POST --------------------------------------------------------------------------
    def do_POST(self):
        parts = [x for x in self.path.split("/") if x]
        b = self._body()
        # public
        if self.path == "/api/login":
            sid, sess = auth.login(b.get("token"), self._ip())
            if not sid:
                code = 429 if auth.throttled(self._ip()) else 401
                return self._json({"ok": False, "error": "Too many attempts; try again in 15 minutes." if code == 429 else "That token isn't recognised."}, code)
            return self._json({"ok": True, "tenant": sess["tenant"], "role": sess["role"]}, extra=[self._cookie(sid)])
        if self.path == "/api/sync/state":
            # Machine-to-machine push from a local engine (dashboard/sync_worker.py). Not a
            # user session: authenticated by a per-tenant bearer token (dashboard/sync.py),
            # separate from the client's own login token.
            slug = str(b.get("tenant", ""))
            hdr = self.headers.get("Authorization", "")
            given = hdr[len("Bearer "):] if hdr.startswith("Bearer ") else ""
            expected = slug and sync.sync_token(slug)
            if not expected or not given or not hmac.compare_digest(given, expected):
                return self._json({"ok": False, "error": "missing or invalid sync token"}, 401)
            ts = tenants()
            c = ts.get(slug)
            if not c:
                return self._json({"ok": False, "error": "unknown tenant"}, 404)
            snapshot_at = str(b.get("snapshot_at") or "")
            sp = ROOT / c.get("state", "approvals/state.json")
            state = load(sp, {})
            accepted, rejected = sync.merge_batches(state, b.get("batches") or {}, snapshot_at)
            sp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
            inbox_added = 0
            if b.get("inbox"):
                ip = ROOT / c.get("inbox", "approvals/inbox.json")
                inbox, inbox_added = sync.merge_inbox(load(ip, []), b["inbox"])
                ip.write_text(json.dumps(inbox, indent=2, ensure_ascii=False), encoding="utf-8")
            return self._json({"ok": True, "accepted": accepted, "rejected_stale": rejected, "inbox_added": inbox_added})
        if self.path == "/api/logout":
            auth.logout(auth.cookie_sid(self.headers.get("Cookie")))
            return self._json({"ok": True}, extra=[self._cookie("", clear=True)])
        if self.path == "/api/onboard":
            ip, now = self._ip(), time.time()
            _onboards[ip] = [t for t in _onboards.get(ip, []) if now - t < ONBOARD_WINDOW]
            if len(_onboards[ip]) >= ONBOARD_LIMIT:
                return self._json({"ok": False, "error": "Too many new workspaces from this address; try again later."}, 429)
            code = auth.invite_code()
            if code and (b.get("invite_code") or "") != code:
                return self._json({"ok": False, "error": "That invite code isn't right."}, 403)
            try:
                slug, cfg, team = tenancy.create_tenant(b)
            except ValueError as e:
                return self._json({"ok": False, "error": str(e)}, 400)
            _onboards[ip].append(now)
            token = auth.issue_tenant_token(slug)
            sid, sess = auth.login(token, "onboard:" + slug)      # sign the new client straight in
            return self._json({"ok": True, "tenant": slug, "identity": cfg["account_identity"], "team": team,
                               "token": token, "room": "/room"}, extra=[self._cookie(sid)])
        sess = self._sess()
        if not sess:
            return self._json({"error": "sign in required"}, 401)
        ts = tenants()
        # room verbs: tenant from the session (admin may name one; clients never can)
        if self.path in ("/api/room/decide", "/api/room/message"):
            if sess["role"] != "admin" and b.get("tenant") and b.get("tenant") != sess["tenant"]:
                return self._json({"ok": False, "error": "not your workspace"}, 403)
            name, c = self._tenant_for(sess, b.get("tenant"), ts)
            if not c:
                return self._json({"ok": False, "error": "tenant not found"}, 404)
            cfg_path = ROOT / "tenants" / name / "config.json"
            if self.path == "/api/room/decide":
                bid, iid, decision = str(b.get("batch", "")), str(b.get("item", "")), str(b.get("decision", ""))
                if decision not in ("approved", "rejected", "edited") or not bid or not iid:
                    return self._json({"ok": False, "error": "batch, item and a valid decision are required"}, 400)
                if bid not in tenant_state(c):
                    return self._json({"ok": False, "error": "no such batch in this workspace"}, 404)
                args = ["decide", bid, iid, decision] + ([str(b.get("text", ""))] if decision == "edited" else [])
                ok, out = gateway(cfg_path, *args)
                return self._json({"ok": ok, "output": out, "tagged": "card tagged" in out}, 200 if ok else 409)
            text = str(b.get("text", "")).strip()
            if not text:
                return self._json({"ok": False, "error": "empty message"}, 400)
            ok, out = gateway(cfg_path, "say", text)
            try:
                m = json.loads(out.splitlines()[-1])
            except (ValueError, IndexError):
                m = {}
            return self._json({"ok": ok, "at": m.get("at"), "text": m.get("text"), "output": out}, 200 if ok else 500)
        # admin only from here
        if sess["role"] != "admin":
            return self._json({"error": "admin only"}, 403)
        if len(parts) >= 3 and parts[:2] == ["api", "tenant"] and parts[2] in ts:
            name, c = parts[2], ts[parts[2]]
            cfg_path = ROOT / "tenants" / name / "config.json"
            if len(parts) == 4 and parts[3] == "poll":
                ok, out = gateway(cfg_path, "poll")
                return self._json({"ok": ok, "output": out})
            if len(parts) == 4 and parts[3] == "pause":
                raw = load(cfg_path, {})
                raw["paused"] = not raw.get("paused", False)
                cfg_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
                return self._json({"ok": True, "paused": raw["paused"]})
            if len(parts) == 6 and parts[3] == "batch" and parts[5] == "resend":
                bid = urllib.parse.unquote(parts[4])
                state = tenant_state(c)
                if bid in state and any(it.get("sent") for it in state[bid]["items"].values()):
                    return self._json({"ok": False, "error": "batch has sent items; resend would reset them"}, 409)
                bf = ROOT / c.get("batches_dir", "approvals/batches") / f"{bid}.json"
                if not bf.exists():
                    return self._json({"ok": False, "error": f"batch file not found: {bf.name}"}, 404)
                ok, out = gateway(cfg_path, "send", str(bf), timeout=300)
                return self._json({"ok": ok, "output": out})
            if len(parts) == 7 and parts[3] == "item" and parts[6] == "edit":
                bid, iid = urllib.parse.unquote(parts[4]), urllib.parse.unquote(parts[5])
                text = str(b.get("text", "")).strip()
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
    created = auth.ensure_admin()
    print(f"Dashboard on http://{HOST}:{PORT}  ·  room /room  ·  sign-in /login  ·  new clients /onboard", flush=True)
    print(("Admin token CREATED in " if created else "Admin token in ") + str(auth.AUTH_FILE.relative_to(ROOT)) + " (open the file; it is never printed)", flush=True)
    if HOST not in ("127.0.0.1", "localhost", "::1"):
        print("WARNING: bound to a non-loopback address. Put a TLS tunnel in front and set ROOM_SECURE_COOKIES=1.", flush=True)
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()

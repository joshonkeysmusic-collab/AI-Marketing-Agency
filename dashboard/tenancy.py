"""Tenant provisioning for the front-desk onboarding chat (/onboard).

Follows the conventions of engine/new_tenant.py exactly: tenants/<slug>/config.json with its
own state/, batches/ and inbox (all gitignored), the platform presets and hard rules from the
scaffolder, and paused=true until the owner verifies the setup. Adds team.json (the client's
custom agent names, titles and avatars) and a proof.md seeded from the brand answers.
No secrets are written here; the client's login token is issued separately by auth.py.
"""
import json, re, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
from new_tenant import PRESETS, HARD_RULES  # noqa: E402  (same presets as the CLI scaffolder)

DEFAULT_TEAM = [
    {"id": "amara", "name": "Amara Osei", "title": "Host · front-desk team leader", "role": "Host / Concierge", "tone": "green"},
    {"id": "daniel", "name": "Daniel Reyes", "title": "Insight Lead · profile & positioning", "role": "Insight Lead", "tone": "blue"},
    {"id": "priya", "name": "Priya Nair", "title": "Research Director · audience & market", "role": "Research Director", "tone": "violet"},
    {"id": "tomas", "name": "Tomás Ferreira", "title": "Content Strategist · campaigns & posts", "role": "Content Strategist", "tone": "warn"},
    {"id": "grace", "name": "Grace Whitfield", "title": "Publishing Manager · execution & schedule", "role": "Publishing Manager", "tone": "hot"},
]
TONES = {"green", "blue", "violet", "warn", "hot", "teal"}
RESERVED = {"josh-linkedin", "josh-ig-gigs", "intake", "admin", "room", "api"}


def clean(s, n):
    return re.sub(r"\s+", " ", str(s or "")).strip()[:n]


def clean_list(xs, n, limit):
    out = []
    for x in (xs or []):
        v = clean(x, n)
        if v and v not in out:
            out.append(v)
    return out[:limit]


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s or "").lower()).strip("-")[:40]


def create_tenant(p):
    """p: the onboarding chat's answers. Returns (slug, config, team). Raises ValueError for bad input."""
    name, company = clean(p.get("name"), 80), clean(p.get("company"), 80)
    if not name or not company:
        raise ValueError("Your name and company are both needed.")
    platform = p.get("platform") if p.get("platform") in PRESETS else "linkedin"
    base = slugify(company) or slugify(name)
    if not base or base in RESERVED:
        raise ValueError("That company name can't be used as a workspace id.")
    slug, k = base, 2
    while (ROOT / "tenants" / slug).exists():
        slug, k = f"{base}-{k}", k + 1

    preset = PRESETS[platform]
    voice = dict(preset["voice"])
    voice["tone"] = clean_list(p.get("tone"), 30, 6)
    voice["banned"] = list(dict.fromkeys(list(voice["banned"]) + clean_list(p.get("avoid"), 60, 10)))
    pillars = clean_list(p.get("pillars"), 120, 6)
    env_name = slug.upper().replace("-", "_") + "_TG_TOKEN"
    cfg = {
        "tenant": slug, "platform": platform, "account_identity": f"{name} · {company}",
        "owner_name": name, "company": company, "profile_url": clean(p.get("profile_url"), 200),
        "browser": "claude-builtin", "paused": True,
        "persona": {"targets": clean(p.get("audience"), 300) or "TODO: who this tenant engages",
                    "signals": ["TODO"], "regions": clean_list(p.get("regions"), 40, 6) or ["TODO"]},
        "discovery": {"method": "leader-engagers", "leaders_hint": "TODO", "fallback": "keyword"},
        "voice": voice, "pillars": pillars,
        "proof_library": f"tenants/{slug}/proof.md",
        "caps": preset["caps"], "windows_local": preset["windows_local"],
        "approval": {"bot_token_env": env_name, "chat_id": None,
                     "n8n_request_url": "TODO: set up in the client's n8n (engine/gateway/N8N-SETUP.md)",
                     "n8n_decisions_url": "TODO", "batch_prefix": f"{slug}-"},
        "bot_token_env": env_name,
        "conf": f"tenants/{slug}/state/runtime.json",
        "state": f"tenants/{slug}/state/state.json",
        "inbox": f"tenants/{slug}/state/inbox.json",
        "batches_dir": f"tenants/{slug}/batches",
        "hard_rules": HARD_RULES,
        "onboarded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "onboarded_via": "front-desk",
    }
    team = []
    custom = p.get("team") if isinstance(p.get("team"), dict) else {}
    for a in DEFAULT_TEAM:
        o = custom.get(a["id"]) if isinstance(custom.get(a["id"]), dict) else {}
        nm = clean(o.get("name"), 40) or a["name"]
        team.append({"id": a["id"], "name": nm, "first": nm.split()[0], "title": clean(o.get("title"), 80) or a["title"],
                     "role": a["role"], "tone": o.get("tone") if o.get("tone") in TONES else a["tone"]})

    tdir = ROOT / "tenants" / slug
    (tdir / "state").mkdir(parents=True)
    (tdir / "batches").mkdir()
    (tdir / "config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    (tdir / "team.json").write_text(json.dumps(team, indent=2, ensure_ascii=False), encoding="utf-8")
    (tdir / "state" / "state.json").write_text("{}", encoding="utf-8")
    (tdir / "state" / "inbox.json").write_text("[]", encoding="utf-8")
    (tdir / "proof.md").write_text(
        f"# Proof library — {name} · {company}\n\nOnly claims listed here may appear in posts, comments or DMs.\n"
        "[CONFIRM] items are drafts until the owner confirms them.\n\n"
        f"## Brand voice\n- Tone: {', '.join(voice['tone']) or '[CONFIRM]'}\n- Avoid: {', '.join(voice['banned'])}\n\n"
        "## Content pillars\n" + ("".join(f"- {x}\n" for x in pillars) or "- [CONFIRM]\n") +
        "\n## Confirmed proof\n- [CONFIRM] (real experience, real results, nameable clients — fill with the owner)\n",
        encoding="utf-8")
    return slug, cfg, team


def load_team(slug):
    try:
        return json.loads((ROOT / "tenants" / slug / "team.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

"""Tenant scaffolder (ENGINE-PLAN step 6).

  python engine/new_tenant.py --slug acme --platform linkedin \
      --identity "Jane Doe" [--chat-id 123456789] [--n8n-base https://x.app.n8n.cloud]

Creates tenants/<slug>/ (config.json, proof.md, state/, batches/), renders the n8n
workflow from the template, and prints the remaining human steps. Never touches
secrets: bot tokens go into an env var whose NAME goes in the config.
New tenants start PAUSED until onboarding is verified.
"""
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PRESETS = {
    "linkedin": {
        "voice": {"formula": "notice-value-question",
                  "banned": ["bullet points", "long dashes", "corporate fluff", "artificial praise", "pitch", "DM me"],
                  "words": [20, 40]},
        "caps": {"comments_day": 3, "connects_day": 15, "items_per_run": 2},
        "windows_local": ["07:30-10:00", "13:00-15:00"],
    },
    "instagram": {
        "voice": {"formula": "notice-value-question",
                  "banned": ["corporate fluff", "artificial praise", "pitch walls", "link drops"],
                  "words": [10, 30]},
        "caps": {"comments_day": 3, "dms_day": 5, "items_per_run": 2},
        "windows_local": ["12:00-14:00", "18:00-21:00"],
    },
}

HARD_RULES = [
    "Nothing posted, commented, messaged or invited without the owner's tap in the Telegram gate",
    "No invented numbers, results or client names; proof only from proof_library ([CONFIRM] items need owner sign-off first)",
    "Official platform APIs only; never cookie/session automation",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True, help="kebab-case tenant id, e.g. acme")
    ap.add_argument("--platform", choices=["linkedin", "instagram", "other"], default="linkedin")
    ap.add_argument("--identity", required=True, help="account display identity")
    ap.add_argument("--chat-id", type=int, default=None, help="owner's Telegram chat id (can be filled later via `setup`)")
    ap.add_argument("--n8n-base", default=None, help="e.g. https://acme.app.n8n.cloud (webhook URLs derived from it)")
    a = ap.parse_args()

    slug = a.slug.lower().strip()
    if not slug.replace("-", "").isalnum():
        sys.exit("slug must be kebab-case alphanumeric")
    tdir = ROOT / "tenants" / slug
    if tdir.exists():
        sys.exit(f"Refusing to overwrite existing tenant: {tdir}")

    preset = PRESETS.get(a.platform, PRESETS["linkedin"])
    env_name = slug.upper().replace("-", "_") + "_TG_TOKEN"
    base = (a.n8n_base or "").rstrip("/")
    url = lambda p: f"{base}/webhook/{p}-{slug}" if base else f"TODO: https://<n8n>/webhook/{p}-{slug}"

    cfg = {
        "tenant": slug,
        "platform": a.platform,
        "account_identity": a.identity,
        "browser": "claude-builtin",
        "paused": True,
        "persona": {"targets": "TODO: who this tenant engages (filled in onboarding call)",
                    "signals": ["TODO"], "regions": ["TODO"]},
        "discovery": {"method": "leader-engagers", "leaders_hint": "TODO", "fallback": "keyword"},
        "voice": preset["voice"],
        "proof_library": f"tenants/{slug}/proof.md",
        "caps": preset["caps"],
        "windows_local": preset["windows_local"],
        "approval": {"bot_token_env": env_name, "chat_id": None,
                     "n8n_request_url": "in approval.local.json (gitignored)",
                     "n8n_decisions_url": "in approval.local.json (gitignored)",
                     "batch_prefix": f"{slug}-"},
        "bot_token_env": env_name,
        "conf": f"tenants/{slug}/state/runtime.json",
        "state": f"tenants/{slug}/state/state.json",
        "inbox": f"tenants/{slug}/state/inbox.json",
        "batches_dir": f"tenants/{slug}/batches",
        "hard_rules": HARD_RULES,
    }

    (tdir / "state").mkdir(parents=True)
    (tdir / "batches").mkdir()
    (tdir / "config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    # Sensitive wiring stays out of git; the loaders merge this file at runtime.
    (tdir / "approval.local.json").write_text(json.dumps({"approval": {
        "chat_id": a.chat_id,
        "n8n_request_url": url("approval-request"),
        "n8n_decisions_url": url("approval-decisions")}}, indent=2), encoding="utf-8")
    (tdir / "proof.md").write_text(
        f"# Proof library — {a.identity}\n\nOnly claims listed here may appear in comments/DMs.\n"
        "[CONFIRM] items are drafts until the owner confirms them.\n\n"
        "## Confirmed\n- [CONFIRM] (fill during onboarding: real experience, real results, nameable clients)\n",
        encoding="utf-8")

    wf = (ROOT / "engine" / "gateway" / "n8n-template.json").read_text(encoding="utf-8")
    wf = wf.replace("{{TENANT_SLUG}}", slug)
    wf = wf.replace("{{OWNER_CHAT_ID}}", str(a.chat_id) if a.chat_id else "{{OWNER_CHAT_ID}}")
    (tdir / "n8n-workflow.json").write_text(wf, encoding="utf-8")

    print(f"Tenant scaffolded: {tdir}")
    print(f"""
Next steps (see engine/gateway/N8N-SETUP.md for detail):
 1. Owner: @BotFather -> /newbot -> token. Then on this machine:
      setx {env_name} "<token>"        (new terminal afterwards)
    Owner opens the bot and sends /start.
 2. {"chat_id already set." if a.chat_id else f"Fill chat_id: python approvals/telegram_approvals.py setup --tenant tenants/{slug}/config.json"}
 3. Import tenants/{slug}/n8n-workflow.json into the tenant's n8n; attach their bot
    credential to the 4 Telegram nodes; publish."""
          + ("" if a.chat_id else f"\n    (n8n-workflow.json still contains {{{{OWNER_CHAT_ID}}}} — replace after step 2.)")
          + f"""
 4. {"URLs derived from --n8n-base; confirm they match the published workflow." if base else "Paste the two webhook URLs into config.json -> approval block."}
 5. Run the verification loop in N8N-SETUP.md (test batch -> tap -> poll).
 6. Fill persona/proof TODOs with the owner, then set "paused": false to go live.""")


if __name__ == "__main__":
    main()

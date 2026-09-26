# Engagement Engine — multi-tenant transformation plan (26 Sep 2026)

Goal: turn the current single-account engagement system into a modular, multi-tenant workflow engine that can run (a) Josh's internal tenants — LinkedIn B2B and @joshonkeysmusic gig bookings — and (b) packaged deployments for external clients.

## 1. Audit of what exists today

| Component | Where it lives | Form | Reusable as software? |
|---|---|---|---|
| Targeting logic | `strategy/engagement-playbook.md`, RUNBOOK ROI section | Markdown rules executed by Claude in-session (persona, pain signals, leader-engager discovery, caps, windows) | As prompt/config templates, yes. Not standalone code. |
| Comment generation | Playbook §2 (notice → value → question formula, voice bans), proof library | Markdown + Claude drafting | Same: prompt template + per-tenant voice config. |
| Approval gateway | `approvals/telegram_approvals.py` + n8n "Telegram Two-Way Approval Gate" + `approvals/state.json` | Real code. Hardcoded single tenant (one bot, one chat id <owner-chat-id>, one state file, one n8n URL pair) | **Yes — the crown jewel.** Needs parameterisation. |
| Publisher | `publish/linkedin_api.py` (official API, gate-enforcing) | Real code, single token/tenant | Yes, parameterise. |
| Execution layer | Claude Code sessions + scheduled tasks (`telegram-auto-reply`, `linkedin-reply-watch`) + built-in browser | Operator-run, session-bound | **No.** This is the honest constraint: browsing/commenting is done by Claude driving a signed-in browser. It ships as an *operated service*, not a binary. |

Hard truths the design must respect:
- LinkedIn's public API cannot comment on other people's posts; Instagram engagement is similar. So the Comment Engine's *execution* stays human/operator-in-the-loop — which is also the brand's whole thesis (Human Veto). Package it as productised service, not self-serve SaaS.
- Secrets discipline already established (env vars, gitignored state) must become per-tenant isolation: one bot, one chat, one state dir per tenant; no shared credentials ever.

## 2. Three-module architecture with tenant configs

```
engine/
  discovery/PROMPT.md        # Target Discovery template (variables: persona, leaders, signals, caps)
  comments/PROMPT.md         # Comment Engine template (variables: voice rules, formula, proof path)
  gateway/telegram_gateway.py# generalised telegram_approvals.py: --tenant <path>
  gateway/n8n-template.json  # parameterised export, imported per tenant with their credentials
  publish/linkedin_api.py    # --tenant aware
tenants/
  josh-linkedin/config.json  # internal tenant 1 (B2B)
  josh-ig-gigs/config.json   # internal tenant 2 (@joshonkeysmusic bookings)
  <client>/config.json       # external tenants
```

`tenants/<name>/config.json` (secrets stay in env vars named IN the config, never values):
```json
{
  "tenant": "josh-linkedin",
  "platform": "linkedin",
  "account_identity": "Josh Forkwa",
  "browser": "claude-builtin",
  "persona": {"targets": "...", "signals": ["..."], "regions": ["UK","EU","US"]},
  "discovery": {"method": "leader-engagers", "leaders": ["..."], "fallback": "keyword"},
  "voice": {"formula": "notice-value-question", "banned": ["bullets","em-dashes","praise"], "words": [20,40]},
  "proof_library": "tenants/josh-linkedin/proof.md",
  "caps": {"comments_day": 3, "connects_day": 15},
  "windows_local": ["07:30-10:00","13:00-15:00"],
  "approval": {"bot_token_env": "TG_TOKEN_JOSH", "chat_id": <owner-chat-id>,
               "n8n_request_url": "...", "n8n_decisions_url": "...",
               "state_dir": "tenants/josh-linkedin/state"},
  "hard_rules": ["nothing sent without owner tap", "no invented numbers"]
}
```

- **Module A — Target Discovery**: input = tenant config; output = `candidates.json` (person, post ref, signal quote, fit reason). Engine prompt is generic; persona/leaders come from config.
- **Module B — Comment Engine**: input = candidate + voice + proof; output = batch JSON in the existing schema. Pure drafting; never sends.
- **Module C — Approval Gateway**: generalised script; every command takes `--tenant tenants/<x>/config.json`; state/inbox/watch files live under the tenant's `state_dir`; one Telegram bot + one n8n workflow instance per tenant (imported from the template with that tenant's credentials — full isolation, a client tap can never touch another tenant's queue).

## 3. Deployment blueprint

**Internal (Josh):** two tenant dirs; same operator (Claude sessions + scheduled tasks per tenant). `josh-ig-gigs` persona: Dubai event planners, wedding coordinators, venues, corporate event bookers; voice = musician-first; approval via the same personal bot but its own batch prefix and state dir (or a second bot if separation feels cleaner).

**External clients (productised service, not self-serve):**
- Package = tenant dir template + gateway script + n8n template + `SETUP.md` (client creates their own Telegram bot via BotFather, their own n8n cloud account or a workflow in Josh's with their credentials, taps approvals on their own phone).
- Execution options, in order of viability: (1) Josh operates runs for them from his machine with their signed-in browser profile — highest touch, ships today; (2) client installs Claude Code + this repo template and self-operates with Josh's configs — mid; (3) API-only tier (LinkedIn publishing via their OAuth token through `linkedin_api.py`) — the only piece that runs unattended, offered as add-on.
- Never stored for clients: their passwords or session cookies. Their bot token goes into *their* env; their approval chat is *their* phone. Josh's veto architecture becomes the client's veto.

## 4. Step-by-step implementation plan

1. **Restructure (no behaviour change):** create `engine/` + `tenants/josh-linkedin/`; move state file paths behind a config loader in `telegram_approvals.py`; keep a shim so existing commands work unchanged. Verify: send/poll/status round-trip on the live batch flow. ✅ **Done 26 Sep 2026** — `--tenant` flag / `TENANT_CONFIG` env / default `tenants/josh-linkedin/config.json` (points at original approvals/ files); `bot_token_env` indirection in `token()`; verified: status identical default vs explicit tenant, live n8n poll, inbox, getMe on the resolved token. Scheduled tasks unaffected (same CLI, same default).
2. **Tenant config v1:** JSON schema above; `telegram_approvals.py` → `engine/gateway/telegram_gateway.py --tenant`; port `linkedin_api.py` the same way. Verify with the current live tenant before touching anything else. ✅ **Done 26 Sep 2026** — `josh-linkedin/config.json` now carries persona/discovery/voice/caps/windows + approval block (chat_id, n8n URLs, bot env) + publish block; gateway resolves chat_id/decisions-URL/token-env tenant-first with conf fallback; `engine/gateway/telegram_gateway.py` forwards to the canonical script (direction flips at step 6); publisher fully tenant-aware (state/batches/token paths, cred env names, TENANT_CONFIG propagated to subprocesses). Verified: live poll, engine-entry status identical, chat_id <owner-chat-id> from config, publisher path resolution. `telegram.json` is now runtime-only (offset, pending_edit, cleared list, context sync).
3. **Prompt extraction:** lift playbook targeting + comment rules into `engine/discovery/PROMPT.md` and `engine/comments/PROMPT.md` with {{variables}}; `strategy/engagement-playbook.md` stays the human-readable source, prompts reference it. ✅ **Done 26 Sep 2026** — both templates written (inbox-first, read-only discovery, candidate/batch schemas, voice formula, proof-library gating baked in) + `engine/render_prompt.py` (dotted-key substitution, lists joined, missing keys warn on stderr). All four tenant×module renders verified clean; the same comments template correctly yields 20–40-word no-emoji LinkedIn voice vs 10–30-word musician IG voice purely from config.
4. **Second internal tenant (the real test):** `tenants/josh-ig-gigs/` — new persona/voice config, own state dir, batches flowing through the same gateway. First gig-booking engagement run on IG proves multi-tenancy end to end. ✅ **Done 26 Sep 2026** — config (UAE event-booker persona, IG voice 10–30 words, own windows/caps, `ig-` batch prefix), `proof.md` with confirmed items + [CONFIRM] gaps for Josh, isolated `state/` + `batches/` dirs (gitignored). Shared-bot safety: gateway now parks taps for batches it doesn't own in `approvals/decisions-spill.json`; the owning tenant's next poll consumes them (offline simulation verified: LI poll parked the IG tap, IG poll applied it, spill emptied). Live loop closed 11:19Z: Josh's tap was intercepted by the *scheduled auto-reply task* (default LinkedIn tenant), parked in the spill, and recovered+applied by the IG tenant's next poll — the exact concurrent-tenant race the spill was designed for, proven in production unscripted. Status `approved` in IG state, batch invisible to LinkedIn state. Multi-tenancy is real.
5. **n8n parameterisation:** export current workflow → template with credential placeholders; document per-tenant import. Decide per-tenant bot (default: yes, one bot each). ✅ **Done 26 Sep 2026** — `engine/gateway/n8n-template.json`: the approval CORE only (11 nodes; request→card→tap/edit/message capture→decisions-out), two placeholders (`{{TENANT_SLUG}}` in name+3 webhook paths, `{{OWNER_CHAT_ID}}` in 3 send nodes + owner check), credentials stripped (importer attaches their own), Josh's voice/Claude-assistant/context-sync branch deliberately excluded as personal tooling. Validated: JSON parses, connection graph complete, no unreachable nodes, no credential/chat-id/instance leaks, rendered sample parses with numeric owner id. `N8N-SETUP.md`: per-tenant import runbook + verification loop + live-learned gotchas (republish fix, clearing endpoint, one-trigger-per-bot). **Decision ratified: one bot per tenant; spill file is only for deliberately shared bots (Josh's two internal tenants).**
6. **Client packaging:** `SETUP.md` + a `new-tenant.py` scaffolder (asks questions, writes config, prints BotFather + n8n steps). Dry-run by onboarding a fictional tenant start to finish. ✅ **Done 26 Sep 2026** — `engine/new_tenant.py` (flags-driven; platform presets for voice/caps/windows; renders the tenant's n8n workflow from the template; derives webhook URLs from `--n8n-base`; new tenants start **paused**; refuses overwrites; prints the human steps) + `engine/SETUP.md` (trust model, onboarding hour, per-run operating loop, API-publish add-on, client boundaries). Dry run `acme-demo` verified end to end: full structure, config sane, workflow rendered with zero template placeholders left and correct owner guard, both prompts render clean, gateway guards fire correctly (empty state, missing-token refusal names `ACME_DEMO_TG_TOKEN`); fictional tenant removed after. **Engine build complete — steps 1–6 all done; step 7 (external pilot) is a business action, not a build.**
7. **Pilot external client** (candidate pool already exists: Tammy, Aatasam, Ahmed conversations) — operated model first; charge for operation + the veto architecture, not for software.

Rules that never change per tenant: approval-gate before anything leaves; no invented numbers; official APIs only, no cookie automation.

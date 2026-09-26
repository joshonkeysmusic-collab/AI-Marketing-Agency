# Engagement Engine — client package setup

What this is: a **human-in-the-loop engagement system**, delivered as an operated service.
Agents research, draft and prepare; every outbound item lands on the owner's phone in
Telegram with Approve / ✏️ Edit / ❌ Reject; nothing reaches any platform without the tap.
It is NOT unattended posting software, and it never uses cookie/session automation.

## Trust model (what the client holds vs what the operator holds)
- Client holds: their Telegram bot token (their env var / their n8n credential UI), their
  approval phone, their platform logins. These are never pasted into chat, files or repos.
- Operator (Claude session driven by Josh) holds: the drafts, the state files, the browser
  session the CLIENT signs in themselves when engagement runs happen.
- Never stored by anyone: passwords, session cookies, card details.
- External client deployments live in their OWN copy of this repo template, not in Josh's
  working repo.

## Onboarding a tenant (≈1 hour incl. the owner call)
1. `python engine/new_tenant.py --slug <name> --platform linkedin|instagram --identity "<Owner / handle>" [--chat-id N] [--n8n-base https://<their>.app.n8n.cloud]`
   Creates `tenants/<slug>/` (config with platform presets, proof.md skeleton, state/,
   batches/, rendered n8n workflow). New tenants start **paused**.
2. Follow the printed steps + `engine/gateway/N8N-SETUP.md`: bot, chat id, workflow import,
   credential attach, publish, URLs into config.
3. Run the verification loop (test batch → tap → poll → edit → free text). Do not skip.
4. Onboarding call with the owner: fill `persona` (targets/signals/regions),
   `discovery.leaders_hint`, and `proof.md` (only claims they can defend). Confirm caps
   and posting windows.
5. Set `"paused": false`. The tenant is live.

## Operating a tenant (each run)
1. Inbox first — notifications, replies, DMs (RUNBOOK rule).
2. `python engine/render_prompt.py discovery --tenant tenants/<slug>/config.json` → run it.
3. `python engine/render_prompt.py comments --tenant ...` → draft → gateway `send`.
4. Owner taps in Telegram → gateway `poll` → execute ONLY approved items → `mark ... sent`.
5. Log every send. The dashboard (`python dashboard/server.py`, localhost) shows all
   tenants' queues; it can pause tenants and poll taps but can never send or approve.

## Optional add-on: API publishing (LinkedIn)
`publish/linkedin_api.py --tenant ...` posts approved POST items via LinkedIn's official
API with the client's own OAuth app + 60-day token (docstring has the client-side setup).
This is the only unattended-capable piece, and it still refuses anything unapproved.

## Boundaries stated to every client up front
- Commenting/DM execution is operator-run (no platform API exists for it); cadence is
  bounded by the per-tenant caps, not by wishes.
- The engine never promises engagement numbers; it promises process, veto and logs.
- A paused tenant is skipped by every agent and scheduled task, immediately.

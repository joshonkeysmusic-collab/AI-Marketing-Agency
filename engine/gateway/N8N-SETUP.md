# Per-tenant n8n approval gate — setup (ENGINE-PLAN step 5)

**Decision: one Telegram bot per tenant** (ratified 26 Sep 2026). Full isolation — a
client's taps physically cannot reach another tenant's queue, and no client ever touches
Josh's bot. The `decisions-spill.json` mechanism exists ONLY for the special case of
several tenants deliberately sharing one bot (Josh's two internal tenants); new tenants
and all clients get their own bot and never need it.

The template (`n8n-template.json`) is the **approval core only**: request-in → Telegram
card with Approve/Edit/Reject → tap/message capture → decisions-out. Josh's live workflow
additionally has a voice-transcription + Claude-assistant + context-sync branch — that is
personal tooling and is NOT part of the client package.

## Import steps (per tenant, ~15 min)

1. **Bot** (tenant owner does this on their own phone):
   - Telegram → @BotFather → `/newbot` → name it (e.g. "Acme Approvals") → copy the token.
   - On the machine that runs the gateway: `setx <TENANT>_TG_TOKEN "<token>"` (never in chat,
     never in a repo). Put that env-var NAME in the tenant config's `bot_token_env`.
   - Owner opens the bot and sends `/start`.
2. **Template render:** copy `n8n-template.json`, replace ALL occurrences of:
   - `{{TENANT_SLUG}}` → short slug, e.g. `acme` (appears in workflow name + 3 webhook paths)
   - `{{OWNER_CHAT_ID}}` → the owner's numeric Telegram id (appears in the 3 send nodes as
     a string and in Record Decision as a number). Get it from the gateway: point the tenant
     config at the new bot token, have the owner send /start, run `... setup --tenant <cfg>`.
3. **Import:** n8n → Workflows → Import from file. Open each of the 4 Telegram nodes and
   attach a NEW credential holding this tenant's bot token (created in n8n's credential UI
   by the person who owns the token — the token is never pasted into chat or files).
4. **Publish** the workflow. n8n auto-registers the bot's webhook (only ONE Telegram
   trigger may exist per bot across all workflows — one bot per tenant makes this a non-issue).
5. **Wire the tenant config** (`tenants/<name>/config.json` → `approval` block):
   - `n8n_request_url`: `https://<instance>/webhook/approval-request-<slug>`
   - `n8n_decisions_url`: `https://<instance>/webhook/approval-decisions-<slug>`
   - `chat_id`, `bot_token_env`, `batch_prefix` (only needed if sharing a bot).

## Verification loop (run after every import — no LinkedIn/IG involvement)
1. `python approvals/telegram_approvals.py send <test batch> --tenant <cfg>` → card appears
   on the owner's phone with three buttons.
2. Owner taps Approve → `poll --tenant <cfg>` shows `1 decision(s) applied`.
3. Owner taps Edit on a second test item, sends replacement text → poll shows `edited`
   with `final_text`.
4. Owner sends a free-text message → poll captures it into the tenant inbox.
5. `curl` the decisions URL directly → `{"decisions":[],"messages":[]}` (cleared).
If step 2 ever shows the tap arriving but not applying, check the workflow's Executions
tab; if taps produce NO execution at all, unpublish + republish (re-registers the bot
webhook — this exact failure happened on 25 Sep and that was the fix).

## Known gotchas (learned live)
- Telegram registers `allowed_updates: [callback_query, message]` from the trigger node;
  changing the trigger's update types requires republish.
- The decisions endpoint CLEARS on read. Only the owning tenant's gateway may poll it.
- n8n free tier: watch the executions quota; every send item + tap + poll is one execution.

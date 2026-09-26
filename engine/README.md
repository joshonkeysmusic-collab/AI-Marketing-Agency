# Engine

Modular core of the engagement system (see `ENGINE-PLAN.md` at repo root).

- `gateway/` — tenant-aware Telegram approval gateway (step 2 moves the script here; today it still lives at `approvals/telegram_approvals.py` with tenant support built in)
- `discovery/`, `comments/` — prompt templates with tenant variables (step 3)

Every command accepts `--tenant tenants/<name>/config.json` (or `TENANT_CONFIG` env var); with neither, it defaults to `tenants/josh-linkedin/config.json`, which reproduces the original single-tenant behaviour exactly.

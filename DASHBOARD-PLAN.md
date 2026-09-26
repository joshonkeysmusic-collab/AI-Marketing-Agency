# Web Dashboard — execution plan (26 Sep 2026)

Owner cockpit for the multi-tenant engagement engine: one place to see every tenant's
pipeline, approvals, sends and results. **Not** a second approval surface — approving
stays in Telegram only, by design (the Human Veto lives on the owner's phone).

## 1. Repo audit: what the dashboard can already feed on

| Data | Source | Freshness |
|---|---|---|
| Tenant registry | `tenants/*/config.json` (glob) | live |
| Batches + item statuses (pending/approved/edited/rejected, sent, decided_at, post_urn) | per-tenant `state` file (`approvals/state.json`, `tenants/josh-ig-gigs/state/state.json`) | live |
| Cross-tenant parked taps | `approvals/decisions-spill.json` | live |
| Owner free-text inbox | per-tenant `inbox` file | live |
| Outbound activity history | `leads/engagement-log.csv` | appended per send |
| Opportunities / lead magnets | `leads/opportunities.csv`, `leads/lead-magnets.csv` | appended |
| Weekly insights (3Ps findings) | `insights/weekly-*.md` | weekly |
| Post-performance metrics | `analytics/latest.json` | **does not exist yet** (Scheduler agent output) — charts wait for it |
| Content queue | `queue/week-*.json`, `posts/*.md` | per cycle |
| LinkedIn API token health | `publish/linkedin_token.json` `expires_at` (never the token value) | live |
| Brand look | `brand-tokens.json` (palette, fonts) | static |

Constraints from the audit: state files hold third-party PII (gitignored) → dashboard must
be **localhost-only** until a client-facing tier exists; repo is deliberately zero-dependency
Python → dashboard should match (stdlib server, vanilla JS, no build step).

## 2. Architecture

```
dashboard/
  server.py     # stdlib http.server, binds 127.0.0.1:8765 ONLY. JSON API + static file.
  index.html    # single page, brand-tokens styling, vanilla JS fetch, 30s auto-refresh
.claude/launch.json  # "dashboard" entry so it runs/previews in the built-in browser pane
```

API (read-only + one safe verb):
- `GET /api/tenants` — configs minus approval URLs; adds computed: pending count, unsent-approved count, last activity
- `GET /api/tenant/<t>/state` — batches/items
- `GET /api/spill` · `GET /api/log?rows=50` · `GET /api/opportunities` · `GET /api/insights/latest` (markdown passed through, rendered client-side minimal)
- `GET /api/health` — token days-left per tenant, scheduled-task last-run stamps if readable
- `POST /api/tenant/<t>/poll` — the only action: shells `telegram_approvals.py poll --tenant …` and returns its stdout. Nothing that sends, approves or marks exists in this API.

Security: bind 127.0.0.1; escape all rendered strings (state contains third-party text);
never read or emit token/secret values; no external assets except Google Fonts (matches
existing asset pipeline).

## 3. Phases

- **P1 — MVP (one session):** server + page with: tenant cards (pending / approved-unsent /
  sent-today counters, token badge), batch table per tenant with item drill-down, spill
  viewer, engagement-log tail. Verify in the browser pane via launch.json. ✅ **Done 26 Sep 2026** —
  `dashboard/server.py` + `index.html`, launch.json entry, running at 127.0.0.1:8765.
  Verified: counters match state-file truth exactly for both tenants (LI 14/0/12/22,
  IG 0/0/1/1); API exposes only GET reads + POST poll (checked programmatically); poll
  endpoint round-trips the gateway live. Both tenant cards, batch drill-down, spill and
  log render in the pane.
- **P2 — Operator comforts:** Poll-now button per tenant; inbox panel; insights viewer;
  auto-refresh; "stale pending" highlight (pending > 24h) as tap reminders.
  **Partially done 26 Sep (interactive refactor, owner-directed):** clickable tenant cards
  filter batches (log stays global — rows carry no tenant tag yet); per-card Poll-taps +
  Pause/Resume (writes `paused` into tenant config; RUNBOOK: agents must skip paused
  tenants); per-batch Resend-to-Telegram (refused if the batch has sent items); drawer
  editing writes `final_text` for unsent items only (sent items locked). Guards verified
  via API: edit-sent → 409, resend-with-sent → 409, edit-unsent → applied, pause round-trip
  persists. Still open from P2: inbox panel, insights viewer, auto-refresh, stale-pending
  highlight.
- **P3 — Results (blocked on `analytics/latest.json`):** impressions/engagement charts per
  post using brand palette; follower-growth line from insights snapshots; opportunities board.
- **P4 — Client tier (only when an external tenant exists):** per-tenant read-only view with
  per-tenant access token + HTTPS on a real host. Explicitly out of scope until then; the
  localhost dashboard must never be exposed as-is.

## 4. Verification per phase
P1/P2: launch through the pane, drive with the built-in browser, confirm counters against
`status` CLI output for both tenants (they must agree exactly — the CLI stays the source of
truth). P3: numbers cross-checked against the analytics JSON. Every phase: confirm the API
surface still contains no send/approve/mark verbs.

# LinkedIn Growth Engine: runbook for scheduled runs

Folder: `C:\Users\jfork\linkedin-growth-engine`. Every scheduled run reads this file first.

## Who and what
- Account: **Josh Forkwa** (Joshua), AI Automation Specialist, based in Dubai and London. Target market: **UK, Europe, USA**.
- Rules and voice: `brand-guidelines.md`, `brand-tokens.json`, `strategy/proof-library.md` (the only claimable experience), `strategy/engagement-playbook.md`, `creator-agent.md`, `scheduler-agent.md`, `insights-agent.md`.
- Visual assets: build as HTML in `assets/<topic>/src/`, render with headless Chrome (`C:\Program Files\Google\Chrome\Application\chrome.exe --headless=new --screenshot` / `--print-to-pdf`). Fonts: Bricolage Grotesque (headings) + Plus Jakarta Sans (text). Dark brand colours from `brand-tokens.json`.

## Headshot
- Official photo: `assets\brand\headshot-original.webp`; square face crop for circles and avatars: `assets\brand\headshot-square.jpg`. Use it wherever the brand allows a face (carousel end slides, author footers, banner photo versions).

## Video
- Videos Josh sends to the Telegram bot: `python approvals\find_video.py` downloads the latest one (max 20 MB) to `assets\video-inbox\`.
- ffmpeg (for frames and thumbnails): `C:\Users\jfork\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin\ffmpeg.exe`
- No speech transcription is installed yet, so captions come from what the frames show plus Josh's own caption.

## LinkedIn access
- Use the **Claude in Chrome** tools. Call `list_connected_browsers`, then `select_browser` with the browser named **"Linkedin Agent"** (it may show as "Browser 1" after reconnecting; if only one local browser is connected, use it). Confirm the feed shows **Josh Forkwa** before doing anything. If that browser isn't connected or shows someone else, stop and notify Josh (see below).
- If screenshots fail with "0 width", the window is minimised: close the tab group (`tabs_close_mcp`) and call `tabs_context_mcp` with `createIfEmpty: true` to open a fresh window.
- Connection requests (including to large accounts that show "Follow" by default; always connect, never follow): open `https://www.linkedin.com/preload/custom-invite/?vanityName=<vanity>`. Check the dialog names the right person before clicking.

## Approval gate: now via n8n (24 Sep 2026)
- n8n Cloud workflow **"Telegram Two-Way Approval Gate"** (<n8n editor URL — owner bookmark>) owns the bot's incoming taps. Only Josh's chat (<owner-chat-id>) is accepted.
- `send` still posts drafts straight to Telegram (so local images and videos work), with Approve / Reject buttons.
- `poll` now collects taps from `<n8n webhook — see tenants/<x>/approval.local.json>` (each call hands over and clears them).
- **Edits (fixed 25 Sep 2026):** tapping ✏️ Edit arms the workflow to treat Josh's *next plain-text Telegram message* as the new text for that item (`status: edited`). Any other free-text message he sends (not preceded by an Edit tap) is captured as a general note — `poll` prints it and appends it to `approvals\inbox.json`; check unread ones any time with `python approvals\telegram_approvals.py inbox` (add `clear` to clear them).
- **Instant replies + voice notes (added 25 Sep 2026):** the n8n workflow answers Josh's Telegram messages itself within seconds, typed or voice (voice notes are transcribed by OpenAI Whisper in n8n; replies come from Claude via the Anthropic API in n8n). The bot can't see this folder, so it answers from a project snapshot that `python approvals\telegram_approvals.py sync-context` pushes to `/webhook/bot-context` (only when files change; URL + token live in `approvals\telegram.json`). For real work (drafts, live LinkedIn checks, file changes) the bot says it's passing it on and flags the message `handoff`.
- **Reply watcher (added 26 Sep 2026):** the scheduled task `linkedin-reply-watch` runs every 30 min (07:00–22:00): read-only LinkedIn check for unanswered DM replies and new comment/notification activity, Telegram-notifies Josh only on new items (state in `approvals\watch-state.json`). It never acts on LinkedIn.
- **Auto-reply task:** the scheduled task `telegram-auto-reply` runs every ~5 min: `sync-context`, `poll`, then `inbox todo` lists only messages the bot handed off or failed to answer. It handles those, replies via `notify`, then `inbox clear`. It's strictly read-only toward LinkedIn — it never posts/comments/connects/sends, and any new draft still goes through the normal `send`-a-batch approval queue.
- Text or public-URL media can also be sent through n8n: POST `{batch_id, item_id, type, target, text, media_url?, media_type?}` to `/webhook/approval-request`.
- Don't use Telegram `getUpdates` any more. The bot's webhook belongs to n8n.

## Approval gate (never skip)
Nothing is posted, commented, liked, messaged or invited on LinkedIn unless Josh approved that exact item in Telegram.
- Script: `python approvals\telegram_approvals.py <command>` (run from the folder root).
  - `send approvals\batches\<batch_id>.json`: push drafts for approval
  - `poll`: collect Josh's taps and edits (always run this first)
  - `approved`: approved items not yet sent (use `text`, which already includes Josh's edits)
  - `mark <batch_id> <item_id> sent`: after an item has actually gone out
  - `notify "message"`: plain message to Josh (reports, problems)
  - `inbox [todo|clear]`: Josh's free-text/voice messages and what the n8n bot already did with them
  - `sync-context [--force]`: refresh the n8n bot's project snapshot
- Batch file format: see `approvals/sample-batch.json`. Item `type`: post · comment · reply · dm · connect · lead. `batch_id` = `YYYY-MM-DD-<slot>`.

## API publishing (added 26 Sep 2026)
- `publish/linkedin_api.py` posts via LinkedIn's **official** Share API — no cookies, no scraping, no Puppeteer (owner rejected cookie automation for ban-risk reasons; never rebuild it).
- It refuses anything not `approved`/`edited` in `approvals/state.json` and anything already `sent` — the Telegram gate stays in charge. On success it marks the item sent and notifies Josh on Telegram.
- One-time setup + commands: docstring at the top of the file. Token lasts ~60 days (`auth` to renew). The API can't schedule for later; the Posting Manager runs `post` at the slot time.
- Instagram is NOT set up (needs a Business/Creator IG + Meta app — confirm with Josh whether the brand has an IG first).

## Sending: manual, in a session only
Josh chose manual sending (23 Sep 2026). No scheduled task sends anything to LinkedIn. When Josh says **"send approved"** in a session:
1. `poll`, then `approved`. Show Josh the list you're about to act on (type, target, text).
2. Act only on those items: posts go through LinkedIn's **Schedule** option at the time in `target`; comments, replies, DMs, invitations and PDF deliveries are sent as approved, a few minutes apart.
3. `mark` each item sent only after it has actually gone, and log lead deliveries in `leads/lead-magnets.csv`.
4. Report back what went out and anything skipped.

## Insights Agent (added 25 Sep 2026)
- Role: studies Josh's own account performance (never the audience) through a **3Ps lens** (Problem, People, Promise — same framework as the Creator Agent's gap analysis) and reports what to double down on vs. stop. Full brief: `insights-agent.md`.
- Runs weekly, before the Creator Agent's cycle. Output: `insights/weekly-YYYY-MM-DD.md` (and `insights/latest.md` pointing at the newest one).
- Sends the owner a short summary on Telegram via `python approvals\telegram_approvals.py notify "..."` — this is a report, not an approval item, so no Approve/Reject buttons.
- Hands 2–4 named Problem/People/Promise combinations to the Research Analyst each week, plus what to avoid.

## Dashboard + paused flag (added 26 Sep 2026)
- Owner cockpit: `python dashboard/server.py` → http://127.0.0.1:8765 (or the "dashboard" launch entry). Read-only + poll/pause/resend-to-Telegram/edit-draft; **no send/approve/mark verbs exist in it** — Telegram stays the only approval surface. Localhost only, never expose.
- **Paused flag:** if a tenant's `config.json` has `"paused": true` (toggled from the dashboard), every agent and scheduled run must SKIP that tenant entirely — no discovery, no drafting, no sending — until resumed.

## Job Scout (added 27 Sep 2026)
- Brief: `job-scout-agent.md`. Scans LinkedIn Jobs (recommended + UAE/UK/remote searches), scores High / Medium / Stretch against `strategy/proof-library.md`, logs to `leads/opportunities.csv`, and sends each role to Telegram as a `type: "apply"` item with a tailored application note.
- Nothing is applied for without Josh approving that specific job. External applications: Josh submits. Easy Apply: show Josh the final screen before Submit.

## ROI focus (Josh, 24–25 Sep 2026)
Every engagement run serves client acquisition first:
- **Targets:** founders, owners and operations decision-makers in the UK, Europe and USA whose posts show a problem Josh solves (manual work, follow-ups, CRM mess, scaling pain) — **in any industry, not just med spas/clinics** (owner instruction, 25 Sep). Filter by the pain signal, not the vertical. Skip ads, generic promo, full-time job posts and low-intent posts.
- **Persona sharpened (owner instruction, 26 Sep):** hands-on entrepreneurs and business owners **navigating AI integration** — people struggling to keep marketing/admin workflows consistent manually, especially those describing their own messy AI adoption. Content and comments address real implementation struggles (mess, early productivity spikes, maintenance overhead), never AI as a magic bullet.
- **Opportunity scan:** each run, also look for freelance/contract/project posts matching AI automation, agents, n8n, CRM or voice-agent builds. Log them in `leads/opportunities.csv` (date, who, link, what they need, fit notes) and include the best ones in the Telegram batch as `dm` or `connect` drafts.
- **Inbox first (owner instruction, 26 Sep):** every engagement deployment STARTS by checking LinkedIn notifications, replies to Josh's comments, comments on his posts, and DMs — before sourcing any new targets. Draft responses through the approval gate; report anything notable to Josh.
- **Discovery (owner instruction, 26 Sep):** find prospects by scanning who engages with key industry leaders' posts (then vetting those engagers' own activity), not by generic keyword search — see `strategy/engagement-playbook.md`.
- **Fail forward, within limits:** if a search returns junk, try a different query and note it in the run summary. Never work around a blocked permission or the approval gate; report it instead.

## Engagement rules
- **Check comments are open before drafting (29 Sep 2026):** many small accounts set "Only connections can comment on this post" (Stenell Myers, Brandon Giella, Shazil Raza, Daniel England all failed with "Your comment could not be created at this time"). While Josh is not connected to someone, pick posts whose existing comments include 2nd/3rd-degree people, or larger creators' posts, which are usually open. Likes always work. Later that day even open posts (Bernard Marr) failed the same way, so it may be an account-wide comment limit: only 1 of 7 comments went through on 29 Sep. If two comments in a row fail, stop commenting for the day and tell Josh.
- Comments and replies: **brief and direct (~20–40 words)**, formula = what you notice → one thing from real build experience → a question that opens debate on a Problem, Person or Promise (`strategy/engagement-playbook.md` §2). No bullet points, no long dashes, no corporate fluff, no artificial praise, no pitch, no emoji strings, no "DM me" in comments.
- Send at most **2 engagement items per run**, with a pause of a few minutes between them. Runs are spread through the day, so activity spreads across 6–8 hours.
- Lead magnet ("Comment WORKFLOW"): follow `strategy/engagement-playbook.md` §5. Say "Sent, check your messages" only after the DM has actually gone. Log in `leads/lead-magnets.csv`.
- Never invent numbers, results or client names. Stop messaging anyone who asks.

## Daily connection targets
- 5–10 similar accounts with **5,000+ followers** (AI automation / agents / no-code / ops creators, UK-EU-US audience), each with a personal note referencing one of their recent posts.
- Plus buyers from the playbook. Skip anyone already connected, pending, or listed in `approvals\state.json`.
- **No fixed daily cap (Josh, 26 Sep 2026: "No caps").** But LinkedIn silently drops invites after a burst: on 26 Sep, after ~11 invites in a day, 7 further sends closed the dialog with no error and never reached Sent. So pace them (a few minutes apart, roughly 6–8 per session), and **always confirm each in `invitation-manager/sent/` before marking it sent**. If sends stop appearing, stop and resume the next morning rather than retrying.
- **Weekly limit hit (29 Sep 2026):** LinkedIn showed "You have reached the weekly limit for connection invitations. Please try again next week." Until about **Mon 5 Oct 2026**, draft NO new `connect` items; comments and replies only. Approved-but-unsent invites (batch `2026-09-29-round22`, plus Liam Ottley, Nick Saraev, Allie K. Miller, Bernard Marr, Justin Welsh from `2026-09-29-am`) go out first once it resets, max ~5 a day, and stop at the first failure. After that, keep the weekly total well under ~100 (so roughly 10–12 a day at most). Silent drops (the dialog closes but the invite never reaches Sent) are the early sign of this limit.
- Prefer people likely to accept (Josh, 29 Sep): 2nd-degree, a plain Connect button and a mutual connection, over large Follow-first accounts.
- People with **Follow** as their main button hide Connect under "More", and some invites never send (Matt Johnson, 26 Sep). After two failed attempts, move on.

## Timing
Posting windows (UK time): 07:30–10:00 and 13:00–15:00. Posts go out through LinkedIn's own scheduler ("Schedule" in the post composer), never posted twice.

## When something goes wrong
Don't guess or retry blindly. Send Josh one `notify` message saying what failed and what's needed, then stop.

## Virtual Room (local approval surface, added 30 Sep 2026)
- Start: `python dashboard/server.py` → open http://127.0.0.1:8765/room (localhost only; the published artifact copy runs on demo data).
- The room reads `approvals/state.json` through the server and shows every **pending** item as a card. Approve / Edit / Reject call `telegram_approvals.py decide`, which records the decision exactly like a Telegram tap (status, `decided_at`, `decided_via: room`) and tags the matching Telegram card ✅/❌/✏️, so phone and room never disagree. Decisions made on Telegram show up in the room within ~3 s.
- Typing in the room runs `telegram_approvals.py say` → the message joins `approvals/inbox.json` with `source: room`. The `telegram-auto-reply` task answers it with `telegram_approvals.py answer <at> "<text>"`, which writes `room_reply` back (Telegram-sourced messages are answered on Telegram). `inbox clear` keeps answered room messages for an hour so the room can display the reply.
- The room never sends anything to LinkedIn: approved items still go out on the engine's next approved run, which marks them `sent`.

## Room sign-in and client onboarding (added 30 Sep 2026)
- `python dashboard/server.py` creates `dashboard/auth.local.json` (gitignored) with the **admin token** on first run; open that file to read it, it is never printed or sent anywhere. Sign in at http://127.0.0.1:8765/login. The admin session opens `josh-linkedin` and can switch tenants with `?tenant=`.
- Unauthenticated visits to `/` or `/room` redirect to `/login`; every `/api/*` call answers 401 without a session. Wrong tokens are throttled (8 per IP per 15 min).
- New clients start at `/onboard`: Amara collects name, company, platform + profile, audience and regions, brand voice (tone, avoid list), pillars and their five-agent team (names, titles, colours). The server creates `tenants/<slug>/` with its own `config.json`, `team.json`, `proof.md`, `state/state.json`, `state/inbox.json` and `batches/` (same layout as `engine/new_tenant.py`), `paused: true`, issues a **client token** (`tenants/<slug>/auth.local.json`, shown once on screen) and signs them in. Their room reads and writes only their own files; the gateway is always called with their `--tenant` config.
- To gate onboarding when the server is public, set `"onboard_invite_code": "<code>"` in `dashboard/auth.local.json`. Public exposure: keep `HOST` on 127.0.0.1 and put a TLS tunnel (Cloudflare Tunnel / ngrok) in front; set `ROOM_SECURE_COOKIES=1`.
- Verify: `python dashboard/verify_auth.py` (server must be running) — proves `/room` is locked, a client onboarded as "Tropics Medspa" sees only its own workspace, and `josh-linkedin` is unchanged.

## Two-way state sync (local engine <-> hosted room, added 30 Sep 2026)
Push (`dashboard/sync.py`, `POST /api/sync/state`) and pull (`GET /api/sync/decisions`) let a
local engine and a hosted room stay in sync without sharing a filesystem. Both sides are
authenticated by a per-tenant **sync token** (`tenants/<slug>/auth.local.json`, separate from
the client's login token) — issue one with:
  python -c "import sys; sys.path.insert(0,'dashboard'); import sync; print(sync.issue_sync_token('SLUG'))"
- **Push** (engine -> room): the engine's new/changed items are merged in. A room-side decision
  (`decided_via: "room"`) can't be overwritten by a push whose `snapshot_at` predates that
  decision — it's counted as `rejected_stale`, not applied. A `sent` confirmation always lands
  on an approved/edited item and can never be unset through this route.
- **Pull** (room -> engine): the engine asks for everything decided since its last watermark
  (`since`) and layers just the decided fields onto its own local copy — the item's other
  content (target/text/image) stays whatever the engine already had.
- `dashboard/sync_worker.py` runs both loops (`--push-interval` 5s, `--pull-interval` 3s
  default) against `--url <hosted room>`. Test against `http://127.0.0.1:8765` before ever
  pointing it at a real host.
- Verify: `python dashboard/verify_sync.py` (13 checks) and `python dashboard/verify_pull.py`
  (7 checks, runs the real worker subprocess and times the pull) — both loopback-only.
- **What this is not**: sync moves *data* between two copies of state. It does not, by itself,
  make the engine "run in the cloud" — LinkedIn browsing/posting is still a human-supervised
  Claude Code session (ENGINE-PLAN.md). Sync is the plumbing a real remote engine would need;
  nothing today actually runs remotely and acts on a pulled decision.
- A sync token for **josh-linkedin** was issued on 30 Sep 2026 (in its `auth.local.json`); the
  worker was not started against the real tenant — only proven against throwaway test tenants.

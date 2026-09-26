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

## ROI focus (Josh, 24–25 Sep 2026)
Every engagement run serves client acquisition first:
- **Targets:** founders, owners and operations decision-makers in the UK, Europe and USA whose posts show a problem Josh solves (manual work, follow-ups, CRM mess, scaling pain) — **in any industry, not just med spas/clinics** (owner instruction, 25 Sep). Filter by the pain signal, not the vertical. Skip ads, generic promo, full-time job posts and low-intent posts.
- **Persona sharpened (owner instruction, 26 Sep):** hands-on entrepreneurs and business owners **navigating AI integration** — people struggling to keep marketing/admin workflows consistent manually, especially those describing their own messy AI adoption. Content and comments address real implementation struggles (mess, early productivity spikes, maintenance overhead), never AI as a magic bullet.
- **Opportunity scan:** each run, also look for freelance/contract/project posts matching AI automation, agents, n8n, CRM or voice-agent builds. Log them in `leads/opportunities.csv` (date, who, link, what they need, fit notes) and include the best ones in the Telegram batch as `dm` or `connect` drafts.
- **Inbox first (owner instruction, 26 Sep):** every engagement deployment STARTS by checking LinkedIn notifications, replies to Josh's comments, comments on his posts, and DMs — before sourcing any new targets. Draft responses through the approval gate; report anything notable to Josh.
- **Discovery (owner instruction, 26 Sep):** find prospects by scanning who engages with key industry leaders' posts (then vetting those engagers' own activity), not by generic keyword search — see `strategy/engagement-playbook.md`.
- **Fail forward, within limits:** if a search returns junk, try a different query and note it in the run summary. Never work around a blocked permission or the approval gate; report it instead.

## Engagement rules
- Comments and replies: **brief and direct (~20–40 words)**, formula = what you notice → one thing from real build experience → a question that opens debate on a Problem, Person or Promise (`strategy/engagement-playbook.md` §2). No bullet points, no long dashes, no corporate fluff, no artificial praise, no pitch, no emoji strings, no "DM me" in comments.
- Send at most **2 engagement items per run**, with a pause of a few minutes between them. Runs are spread through the day, so activity spreads across 6–8 hours.
- Lead magnet ("Comment WORKFLOW"): follow `strategy/engagement-playbook.md` §5. Say "Sent, check your messages" only after the DM has actually gone. Log in `leads/lead-magnets.csv`.
- Never invent numbers, results or client names. Stop messaging anyone who asks.

## Daily connection targets
- 5–10 similar accounts with **5,000+ followers** (AI automation / agents / no-code / ops creators, UK-EU-US audience), each with a personal note referencing one of their recent posts.
- Plus buyers from the playbook, **max 15 invitations a day in total**. Skip anyone already connected, pending, or listed in `approvals\state.json`.

## Timing
Posting windows (UK time): 07:30–10:00 and 13:00–15:00. Posts go out through LinkedIn's own scheduler ("Schedule" in the post composer), never posted twice.

## When something goes wrong
Don't guess or retry blindly. Send Josh one `notify` message saying what failed and what's needed, then stop.

# LinkedIn Growth Engine: runbook for scheduled runs

Folder: `C:\Users\jfork\linkedin-growth-engine`. Every scheduled run reads this file first.

## Who and what
- Account: **Josh Forkwa** (Joshua), AI Automation Specialist, based in Dubai and London. Target market: **UK, Europe, USA**.
- Rules and voice: `brand-guidelines.md`, `brand-tokens.json`, `strategy/proof-library.md` (the only claimable experience), `strategy/engagement-playbook.md`, `creator-agent.md`, `scheduler-agent.md`.
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
- n8n Cloud workflow **"Telegram Two-Way Approval Gate"** (https://j4kwa.app.n8n.cloud/workflow/aV6caQQHylD2dFQU) owns the bot's incoming taps. Only Josh's chat (7406832850) is accepted.
- `send` still posts drafts straight to Telegram (so local images and videos work), with Approve / Reject buttons.
- `poll` now collects taps from `https://j4kwa.app.n8n.cloud/webhook/approval-decisions` (each call hands over and clears them). Edits are made by Josh in chat, not via a Telegram button.
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
- Batch file format: see `approvals/sample-batch.json`. Item `type`: post · comment · reply · dm · connect · lead. `batch_id` = `YYYY-MM-DD-<slot>`.

## Sending: manual, in a session only
Josh chose manual sending (23 Sep 2026). No scheduled task sends anything to LinkedIn. When Josh says **"send approved"** in a session:
1. `poll`, then `approved`. Show Josh the list you're about to act on (type, target, text).
2. Act only on those items: posts go through LinkedIn's **Schedule** option at the time in `target`; comments, replies, DMs, invitations and PDF deliveries are sent as approved, a few minutes apart.
3. `mark` each item sent only after it has actually gone, and log lead deliveries in `leads/lead-magnets.csv`.
4. Report back what went out and anything skipped.

## ROI focus (Josh, 24 Sep 2026)
Every engagement run serves client acquisition first:
- **Targets:** founders, owners and operations decision-makers in the UK, Europe and USA whose posts show a problem Josh solves (manual work, follow-ups, CRM mess, scaling pain). Skip ads, generic promo, full-time job posts and low-intent posts.
- **Opportunity scan:** each run, also look for freelance/contract/project posts matching AI automation, agents, n8n, CRM or voice-agent builds. Log them in `leads/opportunities.csv` (date, who, link, what they need, fit notes) and include the best ones in the Telegram batch as `dm` or `connect` drafts.
- **Inbox:** triage replies and DMs; draft natural, value-first responses that move warm leads toward a call.
- **Fail forward, within limits:** if a search returns junk, try a different query and note it in the run summary. Never work around a blocked permission or the approval gate; report it instead.

## Engagement rules
- Comments and replies: **20–30 words max**, specific, human, from real experience; no filler praise, no pitch, no emoji strings, no "DM me" in comments.
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

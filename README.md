# AI Marketing Agency — LinkedIn Growth Engine

A four-agent system that researches, writes, schedules and engages on LinkedIn for Josh Forkwa (AI Automation Specialist). Nothing reaches LinkedIn without a human approval.

## The agents

| Agent | Job |
|---|---|
| **Research Analyst** | Scans followed and large (10k+) accounts, writes a weekly research brief |
| **Content Creator** | Turns each angle into a post (hook → body → CTA → hashtags) plus one visual |
| **Posting Manager** | Posts now or schedules in the audience's active windows, then measures |
| **Engagement Manager** | Comments, replies, connection requests and lead-magnet delivery |

Full instructions: [`RUNBOOK.md`](RUNBOOK.md) · [`creator-agent.md`](creator-agent.md) · [`scheduler-agent.md`](scheduler-agent.md)

## The approval gate

Every post, comment, DM and connection request is drafted, then sent to Telegram with **Approve / Reject** buttons. Only approved items are sent.

- `approvals/telegram_approvals.py` — sends batches, collects decisions
- `n8n/telegram-two-way-approval-gate.json` — the n8n Cloud workflow that receives button taps

## Layout

```
brand-guidelines.md      Brand rules: voice, palette, formats, CTA library
brand-tokens.json        The same rules, machine-readable
strategy/                Proof library (claimable experience), gap analyses, playbooks
posts/                   Weekly drafts
queue/                   What is scheduled, and its status
assets/                  Rendered visuals + the HTML they are built from
approvals/               Telegram approval gate
n8n/                     n8n workflow export
```

## Building visuals

Visuals are written as HTML and rendered with headless Chrome:

```bash
chrome --headless=new --window-size=1080,1350 --screenshot=out.png file:///path/to/page.html
```

Fonts: Bricolage Grotesque (headings), Plus Jakarta Sans (body). Palette in `brand-tokens.json`.

## Rules that never change

- Nothing is posted, commented or messaged without the owner's approval.
- No invented numbers, results or client names — only what is in `strategy/proof-library.md`.
- Comments are 20–30 words, human, and spread across the day.

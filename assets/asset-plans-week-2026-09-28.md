# Visual asset plans — week of 28 Sep 2026

All assets: `bg #0B0F14` · `surface #141B24` · `border #243040` · `text #F2F5F8` · `text-muted #8A97A6` · `accent #19E6A1` (≤ 10% of any design) · `accent_2 #4C8DFF` (secondary flows only) · `warn #FFB547` (problem/before states).
Fonts: Space Grotesk 700 (titles) · Inter 400/500 (body) · JetBrains Mono 500 (node labels, numbers). Handle "Josh Forkwa" bottom-left, 24 px, `text-muted`.

---

## A1 — WhatsApp-to-CRM architecture diagram (Mon · G1)
- **Type:** architecture diagram · **Size:** 1080 × 1350 px · **File:** `assets/2026-09-28-whatsapp-crm.png`
- **Why it converts:** The reader sees *their own* mess (left) turned into a system (right). Recognition → "I need this" → DM.
- **Layout (top → bottom):**
  1. Title (Space Grotesk 64 px): "Your CRM is already WhatsApp." Subtitle (Inter 32 px, `text-muted`): "Here's how to give it a memory."
  2. **Before strip** (`warn` outlines, greyed): 3 phone icons labelled "Staff phone 1 / 2 / 3", with scattered chat bubbles → "Lost orders · Forgotten follow-ups".
  3. `accent` divider with the signal-line motif.
  4. **After flow** (5 `surface` nodes, radius 16, JetBrains Mono labels, `accent` arrows): `WhatsApp Business number` → `n8n: capture` → `AI agent: tag intent` → split into `CRM record` + `Task to right person` → `Shared inbox`.
  5. Small tag chips under the AI node: `enquiry` · `order` · `complaint` · `follow-up`.
  6. Footer line: "Customers change nothing. The business remembers."
- **No face.**

## A2 — 3-agent pipeline diagram (Tue · G4)
- **Type:** system diagram · **Size:** 1080 × 1350 px · **File:** `assets/2026-09-29-pipeline-diagram.png`
- **Why it converts:** It proves Josh builds real multi-agent systems, which is the credibility asset for every future pitch.
- **Layout:** Title "My 3-agent LinkedIn pipeline" (64 px). Three stacked `surface` nodes: **UI/UX Agent** ("rules") → **Creator Agent** ("strategy + drafts") → **Scheduler & Analytics Agent** ("queue + measure"). `accent` arrows down. `accent_2` feedback arrow from Scheduler back to Creator, labelled "performance data". Before a final "Publish" node, a `warn`-outlined gate labelled **"Owner approval"**. The files each agent owns appear as small mono chips (`brand-tokens.json`, `posts/`, `analytics/`).
- **No face.**

## A3 — Cost-of-manual-work worksheet carousel (Wed · G2)
- **Type:** multi-slide worksheet · **Size:** 1080 × 1350 px, 9 slides, exported as PDF · **File:** `assets/2026-09-30-manual-work-cost.pdf`
- **Why it converts:** It's save-worthy (a tool, not a take), and it pre-qualifies buyers: anyone who runs the numbers and gets a big figure is a warm lead.

| # | Content | Design notes |
|---|---|---|
| 1 | **"What is manual work actually costing you?"** Sub: "A 4-step worksheet" | Hook; "costing you" in `accent` |
| 2 | Why "it saves time" never gets budget approved: finance needs a number | `warn` quote bubble: "saves time" crossed out |
| 3 | **Step 1: Pick one repeated task.** How many times a week does it happen? | Big mono field: `Frequency / week = ___` |
| 4 | **Step 2: Time it.** Minutes per task × frequency ÷ 60 = hours per week | Formula in JetBrains Mono, `accent` on result |
| 5 | **Step 3: Cost it.** Hours × fully loaded hourly cost (salary + overheads) = weekly cost | Same formula style |
| 6 | **Step 4: Add the hidden cost.** Errors, rework, slow replies, missed leads. Estimate conservatively. | `warn` icon row |
| 7 | **Example (illustrative):** 20 enquiries/day × 6 min × 5 days = 10 hrs/week. At an example cost of 5,000/hr, that's 50,000 a week before any lost sales. | Label "EXAMPLE, ILLUSTRATIVE FIGURES" top-right in `text-muted`; no currency symbol so it reads pan-African |
| 8 | **Payback:** Build cost ÷ weekly saving = weeks to pay back. Under ~12 weeks is usually an easy yes. | Mark the "~12 weeks" rule of thumb as an opinion (confirmed by owner 23 Sep) |
| 9 | CTA: face (280 px circle, 4 px `accent` ring). "Want me to run this on one of your workflows? DM me 'WORKFLOW'." | Only slide with the face |

## A4 — Approval-gate system schema (Thu · G3)
- **Type:** system schema / flow · **Size:** 1080 × 1350 px · **File:** `assets/2026-10-01-approval-gate.png`
- **Why it converts:** It turns a fear ("AI will embarrass me") into a visible control, which lowers the barrier to hiring an automation builder.
- **Layout:** Title "Autonomy is earned." (72 px). Flow: `AI agent` → `Proposed action` → **gate diamond** (`warn` outline) "Leaves the business?" → **No** → `Act automatically` (`accent`) · **Yes** → `Human approval` → `Approve` → `Act` / `Reject` → `Feedback to agent`. All paths flow into a `Log` node → `accent_2` loop arrow labelled "track record → widen auto-approve rules" back to the gate.
- **No face.**

---

## Production
Can be produced as HTML/SVG → PNG/PDF using the exact tokens above, or rebuilt in Canva/Figma from these specs. A3's final slide needs the owner's headshot file.

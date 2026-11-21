# AUTOPILOT by WRATHOFCODE

> **A digital air forwarder that quotes every air-freight RFQ all night: exact prices from code, one human-sounding email from a single small LLM call, and a radar where a person can take the controls at any moment.**

Built in 22 hours at **START Hack Munich 2026** for the **5U AI challenge**.

---

## What it does

One mailbox (`wrathofcode@hackloop.mail`). A new air-export RFQ arrives every 6 minutes. AUTOPILOT, on its own:

1. **Reads and routes** every email: customer RFQ, carrier bid, portal reply, tariff sheet, tracking question.
2. **Prices** each RFQ from 10 airline rate sheets, the rate-portal API and 2 to 5 carrier bids, all in plain code.
3. **Quotes one option** (cheapest or fastest, whichever the customer asked for) with **one all-in total and currency**, in the customer's thread, ideally **under 2 minutes**.
4. **Books by rate ID** when the customer accepts (rate IDs expire after 15 min).
5. **Answers tracking questions** from our own CRM.

> Code flies the plane. One LLM call does the talking. A human can grab the controls at any time.

## How it works

```mermaid
flowchart LR
    MB[(Mailbox<br/>poll every 1-2 s)] --> R{Router<br/>rules first}
    R -->|RFQ| X[Extract<br/>route · pieces · kg · cm<br/>door/port · cheap/fast]
    R -->|carrier bid| BIDS[(Bids)]
    R -->|tariff sheet| T[Tariff agent<br/>versioned by validity]
    R -->|tracking| TR[Tracking agent<br/>answers from CRM]

    X --> S[Source in parallel]
    S --> SH[Rate sheets]
    S --> PO[Rate portal API]
    S --> BIDS
    T --> SH

    SH & PO & BIDS --> P[Price & pick<br/>chargeable kg · weight breaks<br/>surcharges · pickup leg]
    P --> W[Write email<br/><b>exactly 1 LLM call</b>]
    W --> Q[Reply in thread<br/>one total + currency]
    Q -->|customer accepts| B[Booking agent<br/>fresh rate ID → book]

    subgraph Control Room
      DB[(app.db<br/>rfqs · events)] --> API[FastAPI + SSE] --> UI[Agent Control Room<br/>& RFQ radar]
      UI -. Take over .-> Q
    end
    P & Q & B & TR & T -.-> DB
```

Every step writes one row to `events` and streams live to the UI, so we can see each decision and catch failed quotes. Failed quotes are the only sign that the setup has changed.

**RFQ lifecycle:** `NEW → EXTRACTED → SOURCING → PRICED → QUOTED → ACCEPTED → BOOKED → TRACKING`

## The agents

| Agent | Job | LLM? |
|---|---|---|
| **Router** | Classifies every incoming mail and hands it to the right agent | Rules first; LLM only if unsure |
| **RFQ** | Extracts, sources, prices, picks one option, writes and sends the quote | **One** call per quote (the email) |
| **Booking** | On acceptance: refreshes the rate ID if older than 15 min, books, confirms in thread | No |
| **Tracking** | Answers "where is my shipment?" from the CRM | No (template + data) |
| **Tariff** | Ingests new monthly airline tariffs as structured, versioned prices | No (parsed in code) |

## Scoring strategy

| Part | Points | How we win it |
|---|---|---|
| Price accuracy | **45** | Check *all three* sources every time. Chargeable weight = max(gross, Σvolume/6000), rounded up to 0.5 kg. Always test the next weight break up. Minimum charge, per-kg surcharges, flat fees, pickup leg for door-to-port. Quote at cost. |
| LLM cost | **40** | **Exactly one** small gateway call per quote: the email writer. Under 600 tokens in, `max_tokens` around 250, smallest model, about $0.0002. Zero calls earns zero cost points, so we never skip it. Router, extraction, pricing, tariffs and the dashboard use no LLM at all. Budget rules in `mail/README.md`. |
| Response time | **15** | Fire portal + bid requests in parallel at t=0. Quote at 2:00 if bids are in or sheets clearly win; else wait until 4:00; hard stop 5:15. |
| Tracking bonus | +10 | Every booking is logged with carrier, rate ID, status and ETA, so the answers come from data. |
| Human email bonus | +10 | The one LLM call goes where the jury reads: the customer's language, tone and thread. |

**Guardrails:** one quote per thread (unique outbox row), no acknowledgement emails, sanity gate (lb/inch mix-ups, density outside 20 to 1,000 kg/m³, price far from the portal's) sends the quote to a human for review.

## Team

| Who | Owns | Folder |
|---|---|---|
| **Amaan** | Core loop, state machine, pricing, option choice, cut-off timing | `core/` |
| **Aditi** | Mailbox poller, router, extraction, human email writing, tracking | `mail/` |
| **Aryan** | Rate sheets, portal client, carrier bids, booking, tariff ingestion | `data/` |
| **Rishabh** | Agent Control Room UI, API, dashboard, alarms, integration, pitch | `api/`, `ui/` |

## Run it

```bash
git clone https://github.com/Rishabh4691/WRATHOFCODE.git && cd WRATHOFCODE
cp .env.example .env                     # team key goes in FIVEU_API_KEY
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

uvicorn api.main:app --port 8000         # control room API, reads app.db
FAKE_DATA=1 uvicorn api.main:app --port 8000   # same, with demo traffic in fake.db

cd ui && npm install && npm run dev      # http://localhost:5173
```

Tests: `pytest` (OCR tests for scanned sheets need `brew install tesseract`)

Bot: `python -m mail.bot` (one instance only, `DRY_RUN=1` prints instead of sending)

Before every push: `./scripts/scan_secrets.sh`. Turn on the hook once per clone with `git config core.hooksPath .githooks` and git will refuse any push that fails the scan. Files uploaded on the GitHub website skip this check, so never upload `.env`-style files there.

### Control room API

| Endpoint | What it returns |
|---|---|
| `GET /api/agents` | One card per agent: light, current task, tasks done, success, avg time, LLM cost, productivity |
| `GET /api/summary` | Totals for the header: RFQs, quoted, failed, median time, LLM per quote, booked value |
| `GET /api/rfqs` | Latest RFQs with status and 6-minute deadline |
| `GET /api/rfqs/{id}` | One RFQ with breakdown, sent email and full event timeline |
| `POST /api/rfqs/{id}/takeover` | `{"on": true}` takes the controls, `false` hands back. Core must skip sending when `rfqs.human_takeover = 1` |
| `GET /api/stream` | Server-sent events, one per new row in `events` |

Productivity = 50% success rate + 30% speed (vs. a per-agent target) + 20% low LLM cost (vs. $0.10 per task).

**How to log so the dashboard works:** write one `events` row per step. Use `status` `start` when a task begins, `ok` or `fail` when it ends (with `duration_ms`), and `info` for anything in between. Put the gateway cost of the email call in `llm_cost_usd`. `ts` is Unix seconds (`time.time()`). `success`/`done`/`sent` count as ok and `failed`/`error` count as fail, so small differences won't break the dashboard. The schema is in `schema.sql`. If your code already made the tables, the API adds any missing columns on start.

## Folder structure

```
.
├── core/      # orchestrator, state machine, pricing (Amaan)
├── mail/      # poller, router, extraction, email writer, tracking (Aditi)
├── data/      # rate sheets, portal client, bids, booking, tariffs (Aryan)
├── api/       # FastAPI + server-sent events over app.db (Rishabh)
├── ui/        # React + Vite + Tailwind: Agent Control Room (Rishabh)
├── tests/     # pytest: API now, pricing next
├── schema.sql # shared app.db tables
├── docs/      # battle plan and challenge brief
└── scripts/   # helper scripts (secret scan, …)
```

Shared state: a single SQLite `app.db` (WAL mode) with tables `rfqs` and `events`
(`events`: `ts, agent, rfq_id, step, status, message, duration_ms, llm_cost_usd, data_json`; `agent` ∈ `router | rfq | booking | tracking | tariff`).

## Live status

_Last updated: Sat 21 Nov 2026_

**Done**
- [x] Repo, `.gitignore` (no `.env`, `env`, `*.db`), secret scanner
- [x] README and battle plan in `docs/`
- [x] Folder skeleton, shared `schema.sql`, LLM budget rules
- [x] Control room API: agents, RFQs, detail, takeover, SSE stream, fake-data mode
- [x] Control room UI: agent cards, RFQ list with countdown, detail drawer, take over, failure alarm
- [x] Mail layer: client, poller, router, email writer (one gateway call), single sender with outbox (`mail/`, `docs/mailbox.md`)
- [x] Sourcing: tariffs, portal client, bids, booking, tariff ingestion (Aryan, `sourcing/`)
- [x] Hardening pass: API-down banner, stream resume, missed-deadline state, operator name, 13 API tests, pre-push secret hook

**In progress**
- [ ] `mvp_bot.py`: first RFQ priced from sheets and quoted end to end (Amaan)
- [ ] RFQ extraction (`mail/extract.py`), then wire extract + pricing + writer + sender into one quote path
- [ ] Wire the real bot into `data/app.db` events (everyone)
- [ ] Remove `env.env` (real key) from the repo and get a fresh key before submission

**Next**
- [ ] Carrier bids + 50/50 price-speed pick
- [ ] Accept + booking confirmation in thread, tracking agent (`mail/tracking.py`)
- [ ] Automatic tariff ingestion
- [ ] Board watcher on `/board` + phone alarms
- [ ] Edit and send from the takeover drawer, radar view
- [ ] Pitch, rehearsal ×3, backup video (Sun 10:00 to 12:00)

## For the team

22 hours. One RFQ every 6 minutes. Every one we get right, fast and cheap is up to 100 points, and every one we miss is gone for good.

We're not trying to out-AI anyone. We win by being **exact where money is involved, human where people read, and awake when it breaks**. Ship small, commit often, keep `main` green, and when a quote fails at 3 a.m., that's the setup telling us what changed. Fix it in pairs, add a test, move on.

By 12:45 on Sunday we want a story: *"At 2 a.m. an RFQ landed, and AUTOPILOT answered it right, fast, cheap and in a human voice."*

**Autopilot engaged.**

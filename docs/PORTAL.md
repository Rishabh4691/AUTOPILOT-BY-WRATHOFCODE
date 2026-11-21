# Rate portal (from `GET /openapi.json`, "Hackathon API" 0.1.0)

Base URL `https://api.start-hack.5u.ai`. Send the team key as the `X-API-Key` header.
Client: `sourcing/portal.py` (`PortalClient`, `get_portal_options`).

| Call | What it does | Rate-limited? |
|---|---|---|
| `GET /v1/portal/ports` | every lane the portal can price: `lanes[]` → `origin`, `destination`, `airlines[{code, name}]` | no |
| `GET /v1/portal/brackets?airline=PL` | `breaks_kg` of one airline (code or name, any case). 404 = not on portal, message gives the address to email | no |
| `GET /v1/portal/rates?origin&destination&airline&weight_kg&volume_cbm` | **one** priced rate for **one** airline | **yes** |
| `POST /v1/portal/bookings` `{rate_id, team_reference}` | book | no |

## Rates

The response gives `rate_id`, `airline`, `airline_code`, `origin`, `destination`, `weight_kg`,
`chargeable_weight_kg` = max(weight, volume_cbm × 167), `total` (freight + fuel + security, 2 decimals),
`currency`, `fx_eur_per_usd` (EUR per 1 unit of `currency`, only for non-EUR prices), `transit_days`,
`valid_until` (expiry of the `rate_id`) and `dataset_version`.

- **"The portal prices the weight you ask for, in that weight's bracket."** It does *not* move you to a
  cheaper higher break. `get_portal_options` also asks for the next break up and keeps the cheaper rate:
  2 reads per airline.
- A lane missing from `/ports` is priced by email to the airline (carrier list).
- Limit: a fixed 1-minute window per team key. The number is in `X-RateLimit-Limit`, the rest in
  `X-RateLimit-Remaining`. Going over gives 429 + `Retry-After`. The client waits and retries, up to 20 s.
- 503 = unavailable. The message says where to get the rate instead (rate desk: `ratedesk@hackloop.mail`).
- A new `dataset_version` means the setup changed. The client logs it in `portal.events` for the alarms.

## Booking

`rate_id` matches `^R-[A-Za-z0-9_-]{8,40}$`. `team_reference` is our CRM id (1–128 chars). One booking per `rate_id`.

| Status | Meaning | `book_option` does |
|---|---|---|
| 201 | booked → `booking_reference` `BK-xxxxxxxx`, `price`, `currency`, `status: booked` | done |
| 200 | same `rate_id` + `team_reference` again | returns the existing booking |
| 404 | unknown `rate_id` (or another team's) | fresh rate, book once more |
| 409 | `rate_id` already booked under another `team_reference` | fresh rate, book once more |
| 410 | expired (see `valid_until`, about 15 min) | fresh rate, book once more |
| 503 | booking system down | returns a booking **email** for the airline |

Then the airline mails "Booking BK-… confirmed" (`parse_booking_confirmation`). There is no status call,
so keep the booking in our CRM.

## Mailbox and others (for Aditi and Rishabh)

- `GET /v1/mailbox/messages?since_id=0&limit=100`: oldest first. Keep `next_since_id`. Poll every 1–2 s
  (response time counts). Threads come via `references` (ids from the first mail to the parent).
- `POST /v1/mailbox/messages` `{to, subject, body, in_reply_to, attachments[]}`: reply with
  `in_reply_to` = the customer's mail id. Only the **first quote** in a customer thread counts.
  Allowed recipients: customers, carriers in the carrier list, `ratedesk@`, `tracking@`. Others get 422.
  The limit is 60 mails/min. At most 5 attachments, 10 MB each.
- `GET /v1/mailbox/messages/{id}/attachments/{attachment_id}`: raw bytes (tariff files come this way).
- Gateway: `POST /v1/gateway/openai-key {api_key}` once, then `/v1/gateway` as the OpenAI `base_url`
  (`/chat/completions`, `/responses`, `/embeddings`). `GET /v1/gateway/models` lists the allowed models.
- `GET /v1/board`: the public board. `GET /v1/board/me` (with key): per request, `verdict`
  (accepted/rejected/pending/open/no answer/voided), reason code, and points per kind. This is the
  signal for the hourly changes.

# Mailbox API

Base URL `https://api.start-hack.5u.ai`, header `X-API-Key: <team key>`. Full spec in `docs/openapi.json`.
Client: `mail/client.py`.

## Poll

`GET /v1/mailbox/messages?since_id=<n>&limit=<1..200>`

Returns mail sent **to** `wrathofcode@hackloop.mail` with `id > since_id`, oldest first.
Our own sent mails never show up here, so we keep a copy of everything we send.

```json
{
  "messages": [ ... ],
  "next_since_id": 136
}
```

Pass `next_since_id` as `since_id` next time. Ids only grow, so nothing is missed or repeated.
5U says to poll every 1-2 seconds because response time is scored.

## One mail

Real example from our mailbox (21 Nov, 14:08 UTC):

```json
{
  "id": 136,
  "from": "ratedesk@hackloop.mail",
  "to": "wrathofcode@hackloop.mail",
  "subject": "Portal rates FRA-ORD 100.0 kg",
  "body": "Hello,\n\nportal rates for FRA-ORD, 100.0 kg, 0.5 cbm (your mail \"Rate request FRA-ORD\"):\n\n- Borealis Freight Airways (BX): 418.00 EUR, 1 days, rate_id R-IaAbMkL80fahG6aO, valid until 21 Nov 2026 14:22 UTC\n- Orion Cargo Air (OR): not on the portal, email orion-cargo-air@hackloop.mail\n- Yellowtail Air Freight (YL): not on the portal, email yellowtail-air-freight@hackloop.mail\n\nBook with the rate_id on the portal or by mail to the airline.\n\nBest regards\nRate Desk\nratedesk@hackloop.mail",
  "in_reply_to": null,
  "references": [],
  "received_at": "2026-11-21T14:08:21.818425+00:00",
  "attachments": []
}
```

| Field | Meaning |
|---|---|
| `id` | Unique, always growing. Use it for `since_id` and `in_reply_to`. |
| `from` | Sender address. Decides most of the routing. |
| `to` | Always us on polled mail. |
| `subject`, `body` | Plain text. |
| `in_reply_to` | Id of the mail this one answers, or `null` for a new thread. |
| `references` | Ids of the thread from its **first mail** down to the parent. Empty for a new thread. |
| `received_at` | ISO 8601 UTC. Our 6-minute clock starts here. |
| `attachments` | `id`, `filename`, content type, size. Download with `GET /v1/mailbox/messages/{id}/attachments/{attachment_id}`. |

**Thread id** = `references[0]` if `references` is not empty, else the mail's own `id`
(`Mail.thread_id` in the client).

Note: the rate desk answer above has `in_reply_to: null`, so it is **not** threaded to our request.
Match it by the quoted subject in the body (`your mail "Rate request FRA-ORD"`) or by lane and weight.

## Send / reply

`POST /v1/mailbox/messages`, returns 201 with the stored mail (same shape as a poll item).

```json
{
  "to": "anna.kowalska@customer.mail",
  "subject": "Re: Air freight quote MUC-JFK",
  "body": "Hi Anna, ...",
  "in_reply_to": 812
}
```

- **Reply inside the thread:** set `in_reply_to` to the id of the mail we answer (usually the customer's
  latest mail in that thread). It must be a mail we sent or received, else 404.
- A quote only counts as a reply in a thread a 5U customer started, and **only our first quote in a
  thread counts**. No acknowledgements, ever.
- **Allowed recipients:** customers, airlines and truckers from `carrier-list.csv`,
  `ratedesk@hackloop.mail`, `tracking@hackloop.mail`. Anything else (other teams too) gets 422.
- Attachments: `[{"filename", "content_type", "content_base64"}]`, max 5 per mail, 10 MB each,
  pdf/xlsx/xls/csv/txt/png/jpg/docx.
- Limit: 60 mails per minute per key, then 429 with `Retry-After`.

The client retries a send only on 429 or when the connection never opened. A timeout or 5xx after the
request went out is **not** retried, because the mail may already be stored and a second copy would cost
us the thread.

## DRY_RUN and KILL_SWITCH

- `DRY_RUN=1` (the default): `send_message` prints the mail and returns a fake negative id. Nothing is sent.
- `KILL_SWITCH=1`: `send_message` refuses to send.

Only one process may send for real. Agree in the team chat who runs it.

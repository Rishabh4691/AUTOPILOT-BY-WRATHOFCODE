# Mailbox API: how to reply in thread

## Poll

`GET /v1/mailbox/messages?since_id=<last id seen>&limit=200`

- Returns messages with id greater than `since_id`, oldest first. `limit` is at most 200, default 100.
- Keep `next_since_id` and pass it as `since_id` next time.
- If you get exactly `limit` mails back, poll again right away. There may be more.

## Reply

`POST /v1/mailbox/messages` with a JSON body:

```json
{
  "to": "<original mail's from>",
  "subject": "Re: <original subject>",
  "body": "<quote text>",
  "in_reply_to": <original mail's id, integer>
}
```

- `in_reply_to` is the id of the mail we answer. Without it the quote does not count.
- A quote only counts in a thread a customer started, and only our first quote in that thread counts.
- `in_reply_to` must be a mail we sent or received, otherwise 404.
- Allowed recipients: customers, start-kit airlines and truckers, ratedesk@hackloop.mail, tracking@hackloop.mail. Anything else gets 422.
- Limit: 60 mails per minute, then 429.
- Returns 201 with the stored mail. Save its id in the database so we never reply twice.

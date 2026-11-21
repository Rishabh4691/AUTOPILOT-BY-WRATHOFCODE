# mail

Owner: Aditi

Mailbox poller, router, RFQ extraction, email writer, tracking replies.

## LLM budget (this is the only place we call the gateway)

- One call per quote, nothing else. Router and extraction are rules/regex.
- Smallest gateway model. `max_tokens` around 250, `temperature` 0.4.
- Prompt is short: the price facts as compact JSON plus the customer's last message
  (trimmed, no quoted history, no signatures). Target under 600 input tokens.
- No few-shot examples in the prompt, no retries that call the LLM again.
- If the gateway fails, send a template email and log `llm_cost_usd = 0`.
- Log tokens and cost on every call to `events.llm_cost_usd`.

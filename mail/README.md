# mail

Helpers the core bot uses for the customer-facing parts. The bot itself is `core/` (`python -m core.main`).

- `extract.py`: rule-based RFQ extraction (lane, pieces, cm/mm/in, kg/lb, cheapest/fastest, pickup zone, first name, language). Runs first via `core/agents/rules_extractor.py`, so most RFQs need no LLM call for extraction.
- `writer.py`: the quote email. One gateway call writes the words with placeholders, code fills in every number. Rejects drafts with a second price, alternatives, stiff phrases or emojis and falls back to a template in the customer's language.
- `gateway.py`: the one chat call, with `reasoning_effort` per model so the token cap is spent on the email.
- `lang.py`, `text.py`: language detection, quoted-history stripping, reply subjects.
- `lock.py`: one bot per machine (`data/bot.lock`).

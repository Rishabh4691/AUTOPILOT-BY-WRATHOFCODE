# core

The live bot (Amaan). `python -m core.main`, `DRY_RUN=1` logs instead of sending, `touch data/STOP` stops it.

Poll mailbox -> classify -> extract (rules first, LLM only if fields are missing) -> price from the portal and the rate sheets, plus trucker pickup for door-to-port -> pick cheapest or fastest -> one LLM call writes the email -> one reply in the customer's thread (outbox guard per thread and stage).

Adapters that connect the other layers: `agents/sheets.py` (Aryan's sheet prices), `agents/rules_extractor.py` and `agents/human_writer.py` (mail layer).

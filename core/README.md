# core

Owner: Amaan

Orchestrator and pricing. Runs the per-RFQ state machine
(NEW → EXTRACTED → SOURCING → PRICED → QUOTED → ACCEPTED → BOOKED → TRACKING),
picks the option the customer asked for, decides when to stop waiting for bids,
and owns the outbox (one quote per thread).

Pricing rules live here and are tested in `tests/`. No LLM calls in this folder.

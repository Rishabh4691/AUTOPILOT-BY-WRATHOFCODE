# data

Owner: Aryan

Rate sheets from the start kit, portal client (rate IDs, booking, rate limits),
carrier and trucker bid requests and parsing, pickup zones, tariff ingestion.

Tariffs are stored as structured, versioned prices (valid_from / valid_to).
Sheets are parsed in code, never with the LLM. The downloaded kit goes in
`data/kit/` (git-ignored).

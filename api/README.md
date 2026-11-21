# api

Owner: Rishabh

FastAPI over `app.db`. Serves agent stats, the RFQ list and per-RFQ detail,
and streams new events with server-sent events at `/api/stream`.
`FAKE_DATA=1` fills the database with demo traffic so the UI works without the bot.

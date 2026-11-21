# data

- `tariffs.json`: the 10 start-kit rate sheets as structured, versioned prices (built by `python -m sourcing.kit`).
- `kit/`: the start kit itself, not in git. Download with `python scripts/fetch_kit.py`.
- `app.db`: the bot's SQLite database, not in git. The Control Room reads it.

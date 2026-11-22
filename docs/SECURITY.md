# Security review

Reviewed on 22 Nov 2026 on branch `chore/polish-and-security`.

System in short: a bot that talks only to the 5U API, a local SQLite database, and a read-mostly Control Room (FastAPI and a React UI) for the team. There are no user accounts, no passwords and no public endpoints.

## Findings

| # | Item | Status | What was checked | Where |
|---|---|---|---|---|
| 1 | SQL injection | Already OK | Every query takes values as parameters. The few f-strings only insert fixed column expressions or `?` placeholders, never input. | `core/store.py`, `api/main.py`, `api/stats.py`, `core/agents/booking.py` |
| 2 | XSS | Already OK | The UI renders mail text through React, which escapes it. No `dangerouslySetInnerHTML` or `innerHTML` anywhere. | `ui/src/` |
| 3 | CSRF | Already OK | The two write routes take JSON bodies. Cross-origin JSON posts need a CORS preflight, which only our UI origins pass. Neither route sends mail or books. | `api/main.py` |
| 4 | File upload validation | Already OK | Attachments are capped at 30 MB and zip members at 25 MB. The kit unzip refuses any path outside the kit folder. Archives are read in memory, never extracted from mail. ffmpeg and OCR run with fixed argument lists in temporary folders. | `core/agents/attachments.py`, `mail/files.py`, `scripts/fetch_kit.py` |
| 5 | SSRF | Already OK | Outgoing calls go only to the configured 5U base and gateway URLs. Links in mails are never fetched. Images for the vision fallback are sent as data URLs. | `core/`, `mail/gateway.py`, `mail/files.py`, `sourcing/portal.py` |
| 6 | BOLA / IDOR | Already OK | Routes validate the id and return 404 for unknown records. There is one tenant (our team), so there is no foreign data to reach. | `api/main.py` |
| 7 | Rate limiting on our API | Not applicable | The Control Room is a local team tool with no route that sends mail or books. The bot itself respects the 5U limits (one poll per 5 s, 60 mails per minute). | `api/main.py`, `core/config.py`, `core/http.py` |
| 8 | Password hashing | Not applicable | No passwords or user accounts exist. | |
| 9 | MFA | Not applicable | No logins exist. Access to the 5U API is a server-side team key. | |
| 10 | Server-side permissions | Already OK | The UI cannot send or book: no such route exists. Take over only sets a display flag in the database; the bot does not act on it, so the UI cannot change what is sent. | `api/main.py`, `core/store.py` |
| 11 | Row-level security | Not applicable | SQLite, one local file, one tenant. | |
| 12 | Strong JWT or session secrets | Not applicable | No JWTs or sessions are used. | |
| 13 | API keys only on the server | Already OK | The team key is read from `.env` by the bot and the API. The production UI bundle contains no key; checked by building it and searching the output. Outgoing mails are blocked if they contain a key. | `api/main.py`, `core/agents/mailbox.py`, `ui/` |
| 14 | Tokens in localStorage | Already OK | Only the operator's display name is stored, no token. The UI has no auth. | `ui/src/api.js` |
| 15 | Default credentials | Already OK | None in code or config. `.env.example` has empty values. | repo |
| 16 | Strict CORS | Already OK | Only `http://localhost:5173` and `http://127.0.0.1:5173`. | `api/main.py` |
| 17 | Webhook signatures | Not applicable | No webhooks. The bot polls the mailbox. | |
| 18 | Source maps in production | Fixed | Set `build.sourcemap: false` explicitly; the build output has no map files. | `ui/vite.config.js` |
| 19 | Clean production logs | Already OK | Request headers with keys or cookies are redacted. Logs record mail ids, lengths and decisions, not mail bodies. | `core/http.py`, `core/outbound.py`, `core/agents/trucker.py` |
| 20 | Dependency audit | Already OK | `pip-audit` on the exact installed versions: no known vulnerabilities (61 packages). `npm audit`: 0 vulnerabilities. Exact versions are pinned in `uv.lock` and `ui/package-lock.json`. | `uv.lock`, `ui/package-lock.json` |

## Secrets in git history

The full history was scanned for keys and secret files. The team key that is still in use appears in two files committed earlier, `env` and `env.env`, which were later deleted. The files are no longer in the tree, but the key remains in the history.

Action: rotate the team key at the 5U booth and update `.env` on every machine that runs the bot. Rewriting history would need a force-push, which the team does not do on `main`.

## Known accepted risks

- `uvicorn --host 0.0.0.0` (used to view the live bot from a second laptop) exposes the Control Room, including customer mails, to the local network. Use it only on a trusted network.
- The Vite dev server listens on all interfaces so teammates can open the UI. It serves no secrets.
- Customer `.docx` files are parsed with the standard XML parser. It does not resolve external entities, and the bundled expat limits entity expansion.

## Hygiene

- `.env`, databases, mail files and keys are ignored by git.
- `scripts/scan_secrets.sh` runs before every push through `.githooks/pre-push`.

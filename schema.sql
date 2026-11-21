PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS rfqs (
  id            TEXT PRIMARY KEY,
  thread_id     TEXT,
  customer      TEXT,
  subject       TEXT,
  received_at   REAL NOT NULL,
  status        TEXT NOT NULL DEFAULT 'NEW',
  preference    TEXT,
  origin        TEXT,
  destination   TEXT,
  chargeable_kg REAL,
  carrier       TEXT,
  total         REAL,
  currency      TEXT,
  rate_id       TEXT,
  quoted_at     REAL,
  email_body    TEXT,
  breakdown_json TEXT,
  human_takeover INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  ts           REAL NOT NULL,
  agent        TEXT NOT NULL,
  rfq_id       TEXT,
  step         TEXT NOT NULL,
  status       TEXT NOT NULL,
  message      TEXT,
  duration_ms  INTEGER,
  llm_cost_usd REAL NOT NULL DEFAULT 0,
  data_json    TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_rfq ON events(rfq_id);
CREATE INDEX IF NOT EXISTS idx_events_agent_ts ON events(agent, ts);

CREATE TABLE IF NOT EXISTS mails (
  id           INTEGER PRIMARY KEY,
  thread_id    INTEGER NOT NULL,
  sender       TEXT NOT NULL,
  recipient    TEXT,
  subject      TEXT,
  body         TEXT,
  in_reply_to  INTEGER,
  refs_json    TEXT,
  attachments_json TEXT,
  received_at  TEXT,
  received_ts  REAL,
  direction    TEXT NOT NULL DEFAULT 'in',
  kind         TEXT,
  rfq_id       TEXT,
  state        TEXT NOT NULL DEFAULT 'new',
  attempts     INTEGER NOT NULL DEFAULT 0,
  error        TEXT,
  stored_at    REAL NOT NULL,
  done_at      REAL
);

CREATE INDEX IF NOT EXISTS idx_mails_thread ON mails(thread_id);
CREATE INDEX IF NOT EXISTS idx_mails_state ON mails(state);

CREATE TABLE IF NOT EXISTS mail_outbox (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id    INTEGER NOT NULL,
  stage        TEXT NOT NULL,
  rfq_id       TEXT,
  recipient    TEXT NOT NULL,
  in_reply_to  INTEGER,
  subject      TEXT,
  body         TEXT,
  state        TEXT NOT NULL DEFAULT 'pending',
  message_id   INTEGER,
  error        TEXT,
  created_at   REAL NOT NULL,
  sent_at      REAL,
  UNIQUE (thread_id, stage)
);

CREATE TABLE IF NOT EXISTS kv (
  key   TEXT PRIMARY KEY,
  value TEXT
);

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

CREATE TABLE IF NOT EXISTS bookings (
  rfq_id            TEXT PRIMARY KEY,
  thread_id         TEXT NOT NULL,
  customer          TEXT,
  booking_reference TEXT,
  team_reference    TEXT NOT NULL,
  rate_id           TEXT,
  carrier           TEXT,
  carrier_code      TEXT,
  origin            TEXT,
  destination       TEXT,
  price             TEXT,
  currency          TEXT,
  transit_days      INTEGER,
  ready_date        TEXT,
  eta               TEXT,
  status            TEXT NOT NULL,
  method            TEXT,
  booked_at         REAL,
  confirmed_at      REAL,
  note              TEXT
);

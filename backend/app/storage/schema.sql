PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS chat_turns (
    request_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    data_source TEXT NOT NULL CHECK(data_source IN ('demo', 'evaluation')),
    message TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('processing', 'succeeded', 'failed', 'interrupted')),
    intent TEXT,
    business_intent TEXT,
    reason_code TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    latency_ms INTEGER,
    response_json TEXT
);
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id TEXT PRIMARY KEY,
    source_request_id TEXT NOT NULL UNIQUE REFERENCES chat_turns(request_id),
    data_source TEXT NOT NULL CHECK(data_source IN ('demo', 'evaluation')),
    ticket_summary TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    order_ids_json TEXT NOT NULL DEFAULT '[]',
    issue_category TEXT NOT NULL,
    detail TEXT NOT NULL,
    original_message TEXT NOT NULL,
    urgency TEXT NOT NULL CHECK(urgency IN ('low', 'medium', 'high')),
    suggested_action TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'in_progress', 'resolved')),
    processing_note TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT,
    CHECK(status != 'resolved' OR length(trim(processing_note)) > 0)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL CHECK(event_type IN ('chat_received', 'chat_finished', 'tool_executed', 'ticket_created', 'ticket_status_changed')),
    request_id TEXT NOT NULL REFERENCES chat_turns(request_id),
    ticket_id TEXT REFERENCES tickets(ticket_id),
    data_source TEXT NOT NULL CHECK(data_source IN ('demo', 'evaluation')),
    occurred_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turns_source_date ON chat_turns(data_source, created_at);
CREATE INDEX IF NOT EXISTS idx_tickets_source_status ON tickets(data_source, status, created_at);
CREATE INDEX IF NOT EXISTS idx_events_ticket ON events(ticket_id, id);

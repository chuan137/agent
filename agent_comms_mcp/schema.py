SCHEMA_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    from_agent  TEXT NOT NULL,
    to_agent    TEXT NOT NULL,
    type        TEXT NOT NULL CHECK(type IN ('task','result','escalate')),
    content     TEXT NOT NULL,
    task_id     TEXT,
    created_at  TEXT NOT NULL,
    read_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_to_read ON messages(to_agent, read_at);
CREATE INDEX IF NOT EXISTS idx_messages_task    ON messages(task_id);

CREATE TABLE IF NOT EXISTS shared_state (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_by  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_status (
    agent_id           TEXT PRIMARY KEY,
    status             TEXT NOT NULL DEFAULT 'idle'
                       CHECK(status IN ('idle','working')),
    current_task       TEXT,
    last_active        TEXT NOT NULL,
    started_working_at TEXT
);

CREATE TABLE IF NOT EXISTS tool_metrics (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT NOT NULL,
    agent_id            TEXT NOT NULL,
    tool_name           TEXT NOT NULL,
    latency_ms          INTEGER NOT NULL,
    context_token_count INTEGER,
    model_name          TEXT,
    task_id             TEXT
);

CREATE TABLE IF NOT EXISTS turn_metrics (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp        TEXT NOT NULL,
    agent_id         TEXT NOT NULL,
    turn_duration_ms INTEGER,
    input_tokens     INTEGER,
    output_tokens    INTEGER,
    context_tokens   INTEGER,
    model_name       TEXT,
    task_id          TEXT
);
"""

CREATE_PRINT_JOBS_TABLE = """
CREATE TABLE IF NOT EXISTS print_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    order_number    TEXT NOT NULL,
    user_code       TEXT NOT NULL,
    pdf_url         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'PENDING',
    agent_id        TEXT,
    claimed_at      DATETIME,
    locked_until    DATETIME,

    retry_count     INTEGER NOT NULL DEFAULT 0,
    next_retry_at   DATETIME,
    error_message   TEXT,

    file_path       TEXT,
    file_size_bytes INTEGER,

    created_at      DATETIME NOT NULL DEFAULT (datetime('now')),
    updated_at      DATETIME NOT NULL DEFAULT (datetime('now')),
    downloaded_at   DATETIME,
    printed_at      DATETIME,

    UNIQUE(order_number, user_code)
);
"""

CREATE_AGENTS_TABLE = """
CREATE TABLE IF NOT EXISTS print_agents (
    agent_id        TEXT PRIMARY KEY,
    printer_name    TEXT,
    printer_status  TEXT NOT NULL DEFAULT 'UNKNOWN',
    details_json     TEXT NOT NULL DEFAULT '{}',
    is_online       INTEGER NOT NULL DEFAULT 0,
    last_seen_at    DATETIME,
    created_at      DATETIME NOT NULL DEFAULT (datetime('now')),
    updated_at      DATETIME NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_PRINT_JOBS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_status ON print_jobs(status);",
    "CREATE INDEX IF NOT EXISTS idx_agent_id ON print_jobs(agent_id);",
    "CREATE INDEX IF NOT EXISTS idx_locked_until ON print_jobs(locked_until);",
    "CREATE INDEX IF NOT EXISTS idx_order_number ON print_jobs(order_number);",
    "CREATE INDEX IF NOT EXISTS idx_user_code ON print_jobs(user_code);",
    "CREATE INDEX IF NOT EXISTS idx_created_at ON print_jobs(created_at);",
    "CREATE INDEX IF NOT EXISTS idx_next_retry ON print_jobs(next_retry_at) WHERE status = 'FAILED';",
]

PRINT_JOBS_MIGRATIONS = {
    "agent_id": "ALTER TABLE print_jobs ADD COLUMN agent_id TEXT;",
    "claimed_at": "ALTER TABLE print_jobs ADD COLUMN claimed_at DATETIME;",
    "locked_until": "ALTER TABLE print_jobs ADD COLUMN locked_until DATETIME;",
}

-- Initial schema for FlatScan.
-- Only file paths and processing metadata are stored; never image binaries.

CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    width_mm REAL NOT NULL,
    height_mm REAL NOT NULL,
    dpi INTEGER NOT NULL DEFAULT 300,
    format TEXT NOT NULL DEFAULT 'JPEG',
    quality INTEGER NOT NULL DEFAULT 95,
    orientation TEXT NOT NULL DEFAULT 'landscape',
    filename_prefix TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    builtin INTEGER NOT NULL DEFAULT 0,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_path TEXT,
    output_path TEXT,
    thumbnail_path TEXT,
    profile_id INTEGER REFERENCES profiles(id) ON DELETE SET NULL,
    profile_name TEXT NOT NULL DEFAULT '',
    corners TEXT NOT NULL DEFAULT '[]',
    settings TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'saved',
    error TEXT NOT NULL DEFAULT '',
    document_id TEXT,
    side TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_projects_created ON projects(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);

CREATE TABLE IF NOT EXISTS batch_jobs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    profile_name TEXT NOT NULL DEFAULT '',
    output_dir TEXT NOT NULL DEFAULT '',
    total INTEGER NOT NULL DEFAULT 0,
    succeeded INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS batch_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES batch_jobs(id) ON DELETE CASCADE,
    source_path TEXT NOT NULL,
    output_path TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    confidence REAL NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    document_id TEXT,
    side TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_batch_items_job ON batch_items(job_id);

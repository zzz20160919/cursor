from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "lab.sqlite"

P0_TABLES = (
    "runs",
    "assets",
    "market_snapshots",
    "strategy_signals",
    "opportunities",
)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT UNIQUE NOT NULL,
    run_type TEXT,
    strategy_id TEXT,
    started_at TEXT,
    finished_at TEXT,
    status TEXT,
    notes TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    asset_class TEXT,
    venue TEXT,
    description TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS market_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER,
    ts TEXT,
    source TEXT,
    price REAL,
    bid REAL,
    ask REAL,
    volume REAL,
    raw_json TEXT,
    created_at TEXT,
    FOREIGN KEY (asset_id) REFERENCES assets (id)
);

CREATE TABLE IF NOT EXISTS strategy_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    strategy_id TEXT,
    asset_id INTEGER,
    ts TEXT,
    signal TEXT,
    confidence REAL,
    reason TEXT,
    raw_json TEXT,
    created_at TEXT,
    FOREIGN KEY (run_id) REFERENCES runs (run_id),
    FOREIGN KEY (asset_id) REFERENCES assets (id)
);

CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    strategy_id TEXT,
    ts TEXT,
    venue_1 TEXT,
    venue_2 TEXT,
    instrument_1 TEXT,
    instrument_2 TEXT,
    opportunity_type TEXT,
    gross_edge REAL,
    estimated_cost REAL,
    net_edge REAL,
    executable_size REAL,
    status TEXT,
    notes TEXT,
    raw_json TEXT,
    created_at TEXT,
    FOREIGN KEY (run_id) REFERENCES runs (run_id)
);
"""


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Path = DB_PATH) -> Path:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
    return db_path


def insert_row(
    conn: sqlite3.Connection,
    table: str,
    values: dict[str, Any],
) -> int:
    columns = ", ".join(values.keys())
    placeholders = ", ".join("?" for _ in values)
    sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
    cursor = conn.execute(sql, tuple(values.values()))
    return int(cursor.lastrowid)


def get_row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in P0_TABLES:
        cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
        counts[table] = int(cursor.fetchone()[0])
    return counts

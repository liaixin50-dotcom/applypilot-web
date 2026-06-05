"""ApplyPilot Core database — single-file SQLite with full pipeline schema.

Uses a local applypilot.db in the backend directory (demo-friendly,
no dependency on ~/.applypilot).
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone

from applypilot_core.config import DB_PATH

_local = threading.local()


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """Thread-local SQLite connection in WAL mode."""
    path = str(db_path or DB_PATH)
    if not hasattr(_local, "connections"):
        _local.connections = {}
    conn = _local.connections.get(path)
    if conn is not None:
        try:
            conn.execute("SELECT 1")
            return conn
        except sqlite3.ProgrammingError:
            pass
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.row_factory = sqlite3.Row
    _local.connections[path] = conn
    return conn


def init_db(db_path: str | None = None) -> sqlite3.Connection:
    """Create the jobs table (idempotent)."""
    path = db_path or DB_PATH
    Path(str(path)).parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(str(path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            url                   TEXT PRIMARY KEY,
            title                 TEXT,
            company               TEXT,
            salary                TEXT,
            description           TEXT,
            full_description      TEXT,
            location              TEXT,
            site                  TEXT,
            strategy              TEXT,
            discovered_at         TEXT,
            fit_score             INTEGER,
            score_reasoning       TEXT,
            scored_at             TEXT,
            tailored_resume_path  TEXT,
            tailored_at           TEXT,
            cover_letter_path     TEXT,
            cover_letter_at       TEXT,
            pipeline_status       TEXT DEFAULT 'discovered',
            applied_at            TEXT,
            apply_error           TEXT
        )
    """)
    conn.commit()
    return conn


def store_jobs(conn: sqlite3.Connection, jobs: list[dict],
               site: str = "Mock", strategy: str = "mock") -> tuple[int, int]:
    """Insert jobs, skipping duplicates by URL."""
    now = datetime.now(timezone.utc).isoformat()
    new, existing = 0, 0
    for job in jobs:
        url = job.get("url")
        if not url:
            continue
        try:
            conn.execute(
                """INSERT INTO jobs (url, title, company, salary, description,
                   full_description, location, site, strategy, discovered_at, pipeline_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'discovered')""",
                (url, job.get("title"), job.get("company"), job.get("salary"),
                 job.get("description"), job.get("full_description"),
                 job.get("location"), site, strategy, now),
            )
            new += 1
        except sqlite3.IntegrityError:
            existing += 1
    conn.commit()
    return new, existing


def get_all_jobs(conn: sqlite3.Connection | None = None,
                 status: str | None = None,
                 limit: int = 100) -> list[dict]:
    """Return all jobs, optionally filtered by pipeline_status."""
    if conn is None:
        conn = get_connection()
    where = "WHERE pipeline_status = ?" if status else ""
    params = [status] if status else []
    query = f"SELECT * FROM jobs {where} ORDER BY COALESCE(fit_score, 0) DESC, discovered_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    if rows:
        cols = rows[0].keys()
        return [dict(zip(cols, r)) for r in rows]
    return []


def get_stats(conn: sqlite3.Connection | None = None) -> dict:
    """Pipeline statistics snapshot."""
    if conn is None:
        conn = get_connection()
    total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    scored = conn.execute("SELECT COUNT(*) FROM jobs WHERE fit_score IS NOT NULL").fetchone()[0]
    tailored = conn.execute("SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL").fetchone()[0]
    dist = conn.execute(
        "SELECT fit_score, COUNT(*) FROM jobs WHERE fit_score IS NOT NULL "
        "GROUP BY fit_score ORDER BY fit_score DESC"
    ).fetchall()
    return {
        "total": total,
        "scored": scored,
        "tailored": tailored,
        "score_distribution": [(r[0], r[1]) for r in dist],
    }


# Import at bottom to avoid circular dependency at module level
from pathlib import Path

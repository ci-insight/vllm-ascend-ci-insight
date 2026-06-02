"""SQLite aggregator for long-term CI trend storage.

Dual-write: SQLite (local) + JSON snapshot (GitHub Pages static deploy).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .storage import DOCS_REPORTS_DIR, write_json

DATA_DIR = Path("data")
DB_PATH = DATA_DIR / "metrics.db"
SNAPSHOT_JSON = DOCS_REPORTS_DIR / "daily-snapshots.json"


def _conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS daily_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        pipeline_type TEXT NOT NULL,
        total_runs INTEGER DEFAULT 0,
        success_runs INTEGER DEFAULT 0,
        failure_runs INTEGER DEFAULT 0,
        success_rate REAL DEFAULT 0,
        health_score REAL DEFAULT 0,
        avg_duration_sec REAL DEFAULT 0,
        metadata TEXT DEFAULT '{}',
        created_at TEXT NOT NULL,
        UNIQUE(date, pipeline_type)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS job_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL,
        job_name TEXT NOT NULL,
        workflow_name TEXT NOT NULL,
        pipeline_type TEXT NOT NULL,
        conclusion TEXT NOT NULL,
        duration_sec REAL DEFAULT 0,
        queue_sec REAL DEFAULT 0,
        started_at TEXT,
        completed_at TEXT,
        created_at TEXT NOT NULL
    )""")
    db.commit()
    return db


def save_snapshot(health_data: dict, reports: list):
    """Save daily snapshot to SQLite and regenerate static JSON.

    Args:
        health_data: Output from health.compute_health()
        reports: List of FailureReport objects (for job-level data)
    """
    now = datetime.now(timezone.utc).isoformat()
    today = now[:10]
    db = _conn()

    pipelines = health_data.get("pipelines", {})
    db.execute("DELETE FROM daily_snapshots WHERE date = ?", (today,))
    db.execute("DELETE FROM job_records WHERE date(created_at) = ?", (today,))

    for ptype, pdata in pipelines.items():
        db.execute(
            """INSERT OR REPLACE INTO daily_snapshots
               (date, pipeline_type, total_runs, success_runs, failure_runs,
                success_rate, health_score, avg_duration_sec, metadata, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                today,
                ptype,
                pdata.get("total", 0),
                pdata.get("success", 0),
                pdata.get("failure", 0),
                pdata.get("success_rate", 0),
                pdata.get("health_score"),
                0,  # avg_duration computed below
                json.dumps({
                    "rating": pdata.get("rating", ""),
                    "trend": pdata.get("trend", ""),
                    "measured_total": pdata.get("measured_total", 0),
                    "skipped": pdata.get("skipped", 0),
                    "cancelled": pdata.get("cancelled", 0),
                    "other": pdata.get("other", 0),
                }),
                now,
            ),
        )

    # Store job records for long-term analysis
    for report in reports:
        for run in report.runs:
            for job in run.jobs:
                if not job.started_at or not job.completed_at:
                    continue
                try:
                    started = datetime.fromisoformat(job.started_at.replace("Z", "+00:00"))
                    completed = datetime.fromisoformat(job.completed_at.replace("Z", "+00:00"))
                    duration = (completed - started).total_seconds()
                except (ValueError, AttributeError):
                    duration = 0

                try:
                    created = datetime.fromisoformat(run.created_at.replace("Z", "+00:00"))
                    queue = (started - created).total_seconds() if duration else 0
                except (ValueError, AttributeError):
                    queue = 0

                db.execute(
                    """INSERT OR IGNORE INTO job_records
                       (run_id, job_name, workflow_name, pipeline_type, conclusion,
                        duration_sec, queue_sec, started_at, completed_at, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run.run_id,
                        job.job_name,
                        run.workflow_name,
                        run.pipeline_type or "other",
                        job.conclusion,
                        duration,
                        max(0, queue),
                        job.started_at,
                        job.completed_at,
                        now,
                    ),
                )

    db.commit()

    # Update avg duration from job_records
    db.execute(
        """UPDATE daily_snapshots SET avg_duration_sec = (
            SELECT COALESCE(AVG(duration_sec), 0) FROM job_records
            WHERE job_records.pipeline_type = daily_snapshots.pipeline_type
            AND date(job_records.created_at) = ?
        ) WHERE date = ?""",
        (today, today),
    )
    db.commit()
    db.close()

    # Generate static JSON for GitHub Pages (last 90 days)
    write_snapshot_json()

    print(f"  Aggregator: saved {today} snapshot ({len(pipelines)} pipeline types) -> {DB_PATH}")


def write_snapshot_json():
    """Export trend data as static JSON for GitHub Pages."""
    db = _conn()
    rows = db.execute(
        """SELECT date, pipeline_type, total_runs, success_runs, failure_runs,
                  success_rate, health_score, avg_duration_sec, metadata
           FROM daily_snapshots
           ORDER BY date ASC, pipeline_type ASC"""
    ).fetchall()
    db.close()

    # Group by pipeline type for chart-friendly format
    by_type: dict[str, list[dict]] = {}
    for r in rows:
        date, pt, total, success, failure, sr, health, avg_dur, meta = r
        entry = {
            "date": date,
            "total": total,
            "success": success,
            "failure": failure,
            "success_rate": round(sr, 1),
            "health_score": round(health, 1) if health is not None else None,
            "avg_duration_sec": round(avg_dur, 1),
        }
        try:
            entry.update(json.loads(meta or "{}"))
        except json.JSONDecodeError:
            pass
        by_type.setdefault(pt, []).append(entry)

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_types": by_type,
    }

    write_json(SNAPSHOT_JSON, data)


def query_trends(pipeline_type: str, days: int = 30) -> list[dict]:
    """Query trend data from SQLite."""
    db = _conn()
    rows = db.execute(
        """SELECT date, success_rate, health_score, total_runs, success_runs, failure_runs
           FROM daily_snapshots
           WHERE pipeline_type = ? AND date >= date('now', ?)
           ORDER BY date ASC""",
        (pipeline_type, f"-{days} days"),
    ).fetchall()
    db.close()
    return [
        {
            "date": r[0],
            "success_rate": r[1],
            "health_score": r[2],
            "total": r[3],
            "success": r[4],
            "failure": r[5],
        }
        for r in rows
    ]

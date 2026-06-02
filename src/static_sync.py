"""Import static dashboard JSON snapshots into the local SQLite database."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import aggregator
from .storage import DOCS_REPORTS_DIR, read_json


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _duration_seconds(started_at: str, completed_at: str) -> float:
    started = _parse_time(started_at)
    completed = _parse_time(completed_at)
    if not started or not completed:
        return 0
    return max(0, (completed - started).total_seconds())


def _queue_seconds(created_at: str, started_at: str) -> float:
    created = _parse_time(created_at)
    started = _parse_time(started_at)
    if not created or not started:
        return 0
    return max(0, (started - created).total_seconds())


def import_static_reports(source_dir: Path | str = DOCS_REPORTS_DIR) -> dict:
    """Import static JSON report artifacts into the local SQLite database.

    This is intended for local deployments that clone the repository and want
    to reconstruct local trend/job data from committed static artifacts.
    Static JSON is treated as a snapshot, not as a live task queue.
    """
    source = Path(source_dir)
    now = datetime.now(timezone.utc).isoformat()
    db = aggregator._conn()
    imported_snapshots = _import_daily_snapshots(db, source / "daily-snapshots.json", now)
    imported_jobs = _import_ci_runs(db, source / "ci-runs.json", now)
    db.commit()
    db.close()
    aggregator.write_snapshot_json()
    return {
        "source": str(source),
        "daily_snapshots": imported_snapshots,
        "job_records": imported_jobs,
    }


def _import_daily_snapshots(db, path: Path, imported_at: str) -> int:
    data = read_json(path, default={})
    pipeline_types = data.get("pipeline_types", {}) if isinstance(data, dict) else {}
    count = 0
    for pipeline_type, entries in pipeline_types.items():
        for entry in entries or []:
            date = entry.get("date")
            if not date:
                continue
            metadata = {
                key: value
                for key, value in entry.items()
                if key not in {"date", "total", "success", "failure", "success_rate", "health_score", "avg_duration_sec"}
            }
            db.execute(
                """INSERT OR REPLACE INTO daily_snapshots
                   (date, pipeline_type, total_runs, success_runs, failure_runs,
                    success_rate, health_score, avg_duration_sec, metadata, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    date,
                    pipeline_type,
                    entry.get("total", 0),
                    entry.get("success", 0),
                    entry.get("failure", 0),
                    entry.get("success_rate", 0),
                    entry.get("health_score"),
                    entry.get("avg_duration_sec", 0),
                    json.dumps(metadata),
                    imported_at,
                ),
            )
            count += 1
    return count


def _import_ci_runs(db, path: Path, imported_at: str) -> int:
    data = read_json(path, default={})
    runs = data.get("runs", []) if isinstance(data, dict) else []
    run_ids = [run.get("run_id") for run in runs if run.get("run_id") is not None]
    for run_id in run_ids:
        db.execute("DELETE FROM job_records WHERE run_id = ?", (run_id,))

    count = 0
    for run in runs:
        run_id = run.get("run_id")
        if run_id is None:
            continue
        created_at = run.get("created_at", "")
        workflow_name = run.get("workflow_name", "")
        pipeline_type = run.get("pipeline_type", "other") or "other"
        for job in run.get("jobs", []) or []:
            job_id = job.get("job_id")
            if job_id is None:
                continue
            started_at = job.get("started_at", "")
            completed_at = job.get("completed_at", "")
            db.execute(
                """INSERT INTO job_records
                   (run_id, job_name, workflow_name, pipeline_type, conclusion,
                    duration_sec, queue_sec, started_at, completed_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    job.get("job_name", ""),
                    workflow_name,
                    pipeline_type,
                    job.get("conclusion", "unknown"),
                    _duration_seconds(started_at, completed_at),
                    _queue_seconds(created_at, started_at),
                    started_at,
                    completed_at,
                    imported_at,
                ),
            )
            count += 1
    return count

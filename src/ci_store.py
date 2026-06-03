"""SQLite-backed incremental CI run/job storage."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from . import aggregator
from .collector import classify_pipeline


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def ensure_schema(db: sqlite3.Connection) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS workflow_runs (
        run_id INTEGER PRIMARY KEY,
        workflow_name TEXT NOT NULL,
        pipeline_type TEXT NOT NULL,
        conclusion TEXT NOT NULL,
        status TEXT NOT NULL,
        branch TEXT,
        event TEXT,
        url TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT,
        jobs_collected_at TEXT,
        inventory_seen_at TEXT NOT NULL,
        raw_metadata TEXT DEFAULT '{}'
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS ci_jobs (
        job_id INTEGER PRIMARY KEY,
        run_id INTEGER NOT NULL,
        job_name TEXT NOT NULL,
        conclusion TEXT NOT NULL,
        started_at TEXT,
        completed_at TEXT,
        duration_sec REAL DEFAULT 0,
        queue_sec REAL DEFAULT 0,
        collected_at TEXT NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS collection_state (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at TEXT NOT NULL
    )""")
    db.commit()


def conn() -> sqlite3.Connection:
    db = aggregator._conn()
    ensure_schema(db)
    return db


def _run_id(run: dict) -> int | None:
    return run.get("databaseId") or run.get("run_id")


def _workflow_name(run: dict) -> str:
    return run.get("workflowName") or run.get("workflow_name") or run.get("name") or ""


def _created_at(run: dict) -> str:
    return run.get("createdAt") or run.get("created_at") or ""


def _updated_at(run: dict) -> str:
    return run.get("updatedAt") or run.get("updated_at") or ""


def _branch(run: dict) -> str:
    return run.get("headBranch") or run.get("branch") or ""


def _url(run: dict) -> str:
    return run.get("url") or run.get("html_url") or ""


def upsert_runs(db: sqlite3.Connection, runs: list[dict]) -> None:
    seen_at = _now()
    for run in runs:
        run_id = _run_id(run)
        if run_id is None:
            continue
        workflow = _workflow_name(run)
        db.execute(
            """INSERT INTO workflow_runs
               (run_id, workflow_name, pipeline_type, conclusion, status, branch,
                event, url, created_at, updated_at, inventory_seen_at, raw_metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(run_id) DO UPDATE SET
                 workflow_name = excluded.workflow_name,
                 pipeline_type = excluded.pipeline_type,
                 conclusion = excluded.conclusion,
                 status = excluded.status,
                 branch = excluded.branch,
                 event = excluded.event,
                 url = excluded.url,
                 created_at = excluded.created_at,
                 updated_at = excluded.updated_at,
                 jobs_collected_at = CASE
                   WHEN excluded.updated_at != workflow_runs.updated_at THEN NULL
                   WHEN workflow_runs.status != 'completed' AND excluded.status = 'completed' THEN NULL
                   ELSE workflow_runs.jobs_collected_at
                 END,
                 inventory_seen_at = excluded.inventory_seen_at,
                 raw_metadata = excluded.raw_metadata""",
            (
                run_id,
                workflow,
                run.get("pipeline_type") or classify_pipeline(workflow),
                run.get("conclusion") or run.get("status") or "unknown",
                run.get("status") or "",
                _branch(run),
                run.get("event") or "",
                _url(run),
                _created_at(run),
                _updated_at(run),
                seen_at,
                json.dumps(run),
            ),
        )
    db.execute(
        """INSERT INTO collection_state (key, value, updated_at)
           VALUES ('last_inventory_at', ?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
        (seen_at, seen_at),
    )


def runs_needing_jobs(db: sqlite3.Connection, runs: list[dict], force: bool = False) -> list[dict]:
    if force:
        return runs
    needed: list[dict] = []
    for run in runs:
        run_id = _run_id(run)
        if run_id is None:
            continue
        row = db.execute(
            """SELECT updated_at, jobs_collected_at, status
               FROM workflow_runs WHERE run_id = ?""",
            (run_id,),
        ).fetchone()
        if row is None:
            needed.append(run)
            continue
        stored_updated, jobs_collected_at, stored_status = row
        current_updated = _updated_at(run)
        current_status = run.get("status") or ""
        if not jobs_collected_at:
            needed.append(run)
        elif current_updated and current_updated != (stored_updated or ""):
            needed.append(run)
        elif stored_status != "completed" and current_status == "completed":
            needed.append(run)
    return needed


def runs_for_job_collection(db: sqlite3.Connection, days: int, limit: int = 500, force: bool = False) -> list[dict]:
    """Return inventoried workflow runs that still need job details."""
    where = "created_at >= ?"
    params: list[object] = [period_start(days)]
    if not force:
        where += " AND jobs_collected_at IS NULL"
    limit_sql = "" if limit <= 0 else " LIMIT ?"
    if limit > 0:
        params.append(limit)
    rows = db.execute(
        f"""SELECT run_id, workflow_name, conclusion, status, branch, event, url,
                  created_at, updated_at, pipeline_type
             FROM workflow_runs
             WHERE {where}
             ORDER BY created_at DESC, run_id DESC{limit_sql}""",
        params,
    ).fetchall()
    return [
        {
            "databaseId": run_id,
            "workflowName": workflow,
            "name": workflow,
            "conclusion": conclusion,
            "status": status,
            "headBranch": branch or "",
            "event": event or "",
            "url": url or "",
            "createdAt": created_at,
            "updatedAt": updated_at or "",
            "pipeline_type": pipeline,
        }
        for run_id, workflow, conclusion, status, branch, event, url, created_at, updated_at, pipeline in rows
    ]


def replace_run_jobs(db: sqlite3.Connection, run: dict, jobs: list[dict]) -> None:
    run_id = _run_id(run)
    if run_id is None:
        return
    collected_at = _now()
    created_at = _created_at(run)
    db.execute("DELETE FROM ci_jobs WHERE run_id = ?", (run_id,))
    for job in jobs:
        job_id = job.get("id") or job.get("job_id")
        if job_id is None:
            continue
        started_at = job.get("started_at", "")
        completed_at = job.get("completed_at", "")
        db.execute(
            """INSERT OR REPLACE INTO ci_jobs
               (job_id, run_id, job_name, conclusion, started_at, completed_at,
                duration_sec, queue_sec, collected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job_id,
                run_id,
                job.get("name") or job.get("job_name", ""),
                job.get("conclusion") or job.get("status") or "unknown",
                started_at,
                completed_at,
                _duration_seconds(started_at, completed_at),
                _queue_seconds(created_at, started_at),
                collected_at,
            ),
        )
    db.execute(
        "UPDATE workflow_runs SET jobs_collected_at = ? WHERE run_id = ?",
        (collected_at, run_id),
    )


def period_start(days: int) -> str:
    start_date = datetime.now(timezone.utc).date() - timedelta(days=max(days - 1, 0))
    return datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc).isoformat()


def inventory_counts(db: sqlite3.Connection, days: int) -> dict[str, int]:
    rows = db.execute(
        """SELECT substr(created_at, 1, 10), COUNT(*)
           FROM workflow_runs
           WHERE created_at >= ?
           GROUP BY substr(created_at, 1, 10)
           ORDER BY substr(created_at, 1, 10) DESC""",
        (period_start(days),),
    ).fetchall()
    return {date: count for date, count in rows}


def export_runs_with_jobs(db: sqlite3.Connection, days: int) -> list[dict]:
    rows = db.execute(
        """SELECT run_id, workflow_name, pipeline_type, conclusion, status, branch,
                  event, url, created_at, updated_at, jobs_collected_at
           FROM workflow_runs
           WHERE created_at >= ? AND jobs_collected_at IS NOT NULL
           ORDER BY created_at DESC, run_id DESC""",
        (period_start(days),),
    ).fetchall()
    runs: list[dict] = []
    for row in rows:
        run_id, workflow, pipeline, conclusion, status, branch, event, url, created_at, updated_at, jobs_collected_at = row
        jobs = db.execute(
            """SELECT job_id, job_name, conclusion, started_at, completed_at
               FROM ci_jobs
               WHERE run_id = ?
               ORDER BY job_id ASC""",
            (run_id,),
        ).fetchall()
        runs.append({
            "run_id": run_id,
            "workflow_name": workflow,
            "conclusion": conclusion,
            "status": status,
            "branch": branch or "",
            "created_at": created_at,
            "updated_at": updated_at or "",
            "event": event or "",
            "url": url or "",
            "pipeline_type": pipeline,
            "jobs_collected_at": jobs_collected_at,
            "jobs": [
                {
                    "job_id": job_id,
                    "job_name": job_name,
                    "conclusion": job_conclusion,
                    "started_at": started_at or "",
                    "completed_at": completed_at or "",
                }
                for job_id, job_name, job_conclusion, started_at, completed_at in jobs
            ],
        })
    return runs


def coverage(db: sqlite3.Connection, days: int, ai_analyzed: int = 0, failed_jobs: int = 0) -> dict:
    start = period_start(days)
    total_runs = db.execute(
        "SELECT COUNT(*) FROM workflow_runs WHERE created_at >= ?",
        (start,),
    ).fetchone()[0]
    job_runs = db.execute(
        "SELECT COUNT(*) FROM workflow_runs WHERE created_at >= ? AND jobs_collected_at IS NOT NULL",
        (start,),
    ).fetchone()[0]
    total_jobs = db.execute(
        """SELECT COUNT(*) FROM ci_jobs
           WHERE run_id IN (SELECT run_id FROM workflow_runs WHERE created_at >= ?)""",
        (start,),
    ).fetchone()[0]
    measured_jobs = db.execute(
        """SELECT COUNT(*) FROM ci_jobs
           WHERE conclusion IN ('success', 'failure')
           AND run_id IN (SELECT run_id FROM workflow_runs WHERE created_at >= ?)""",
        (start,),
    ).fetchone()[0]
    return {
        "generated_at": _now(),
        "period": {
            "days": days,
            "since": start,
            "until": _now(),
        },
        "run_inventory": {
            "total": total_runs,
            "complete": True,
            "by_date": inventory_counts(db, days),
        },
        "job_details": {
            "collected_runs": job_runs,
            "total_runs": total_runs,
            "coverage_percent": round(job_runs / total_runs * 100, 2) if total_runs else 0,
            "quality": "full" if total_runs and job_runs == total_runs else "partial",
        },
        "measured_jobs": {
            "measured": measured_jobs,
            "total_jobs": total_jobs,
            "coverage_percent": round(measured_jobs / total_jobs * 100, 2) if total_jobs else 0,
        },
        "ai_analysis": {
            "analyzed": ai_analyzed,
            "failed_jobs": failed_jobs,
            "coverage_percent": round(ai_analyzed / failed_jobs * 100, 2) if failed_jobs else 0,
        },
    }

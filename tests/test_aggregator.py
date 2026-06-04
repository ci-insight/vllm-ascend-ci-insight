import json
import sqlite3

from src import aggregator
from src.models import CIJob, CIRun, FailureReport


def _report(run_id: int, run_created: str, job_started: str, job_completed: str, job_created: str = "") -> FailureReport:
    return FailureReport(
        pr_number=0,
        pr_title="",
        pr_author="",
        pr_url="",
        analyzed_at="2026-06-03T00:00:00Z",
        runs=[
            CIRun(
                run_id=run_id,
                workflow_name="E2E-Light",
                conclusion="success",
                branch="main",
                pr_number=None,
                created_at=run_created,
                event="pull_request",
                pipeline_type="pr_e2e",
                jobs=[
                    CIJob(
                        job_id=run_id * 10,
                        job_name="test",
                        conclusion="success",
                        started_at=job_started,
                        completed_at=job_completed,
                        created_at=job_created,
                    )
                ],
            )
        ],
    )


def test_save_snapshot_does_not_delete_historical_jobs_collected_today(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "metrics.db"
    snapshot_path = tmp_path / "docs" / "reports" / "daily-snapshots.json"
    snapshot_path.parent.mkdir(parents=True)
    monkeypatch.setattr(aggregator, "DB_PATH", db_path)
    monkeypatch.setattr(aggregator, "SNAPSHOT_JSON", snapshot_path)

    db = aggregator._conn()
    try:
        db.execute(
            """INSERT INTO job_records
               (run_id, job_name, workflow_name, pipeline_type, conclusion,
                duration_sec, queue_sec, started_at, completed_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                1,
                "old",
                "E2E-Light",
                "pr_e2e",
                "success",
                60,
                0,
                "2026-06-01T00:00:00Z",
                "2026-06-01T00:01:00Z",
                "2026-06-03T00:00:00+00:00",
            ),
        )
        db.commit()
    finally:
        db.close()

    health_data = {
        "pipelines": {
            "pr_e2e": {
                "total": 1,
                "success": 1,
                "failure": 0,
                "success_rate": 100,
                "health_score": 90,
                "rating": "good",
                "trend": "flat",
                "measured_total": 1,
            }
        }
    }
    aggregator.save_snapshot(
        health_data,
        [_report(2, "2026-06-02T00:00:00Z", "2026-06-03T00:01:00Z", "2026-06-03T00:02:00Z", "2026-06-03T00:00:30Z")],
    )

    db = sqlite3.connect(db_path)
    try:
        rows = db.execute("SELECT run_id, job_name FROM job_records ORDER BY run_id").fetchall()
        queue = db.execute("SELECT queue_sec FROM job_records WHERE run_id = 2").fetchone()[0]
    finally:
        db.close()

    assert rows == [(1, "old"), (2, "test")]
    assert queue == 30

    exported = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert exported["execution_trends"]["pr_e2e"][0]["date"] == "2026-06-01"
    assert exported["execution_trends"]["pr_e2e"][1]["date"] == "2026-06-03"

"""Tests for importing static dashboard snapshots into SQLite."""

import json
import sqlite3

from src import aggregator
from src.static_sync import import_static_reports


def test_import_static_reports_rebuilds_local_sqlite(tmp_path, monkeypatch):
    reports_dir = tmp_path / "docs" / "reports"
    reports_dir.mkdir(parents=True)
    db_path = tmp_path / "data" / "metrics.db"
    monkeypatch.setattr(aggregator, "DB_PATH", db_path)
    monkeypatch.setattr(aggregator, "SNAPSHOT_JSON", reports_dir / "daily-snapshots.json")

    (reports_dir / "daily-snapshots.json").write_text(json.dumps({
        "generated_at": "2026-06-02T00:00:00Z",
        "pipeline_types": {
            "pr_e2e": [
                {
                    "date": "2026-06-02",
                    "total": 10,
                    "success": 8,
                    "failure": 2,
                    "success_rate": 80,
                    "health_score": 72,
                    "avg_duration_sec": 3.5,
                    "rating": "fair",
                }
            ]
        },
    }), encoding="utf-8")
    (reports_dir / "ci-runs.json").write_text(json.dumps({
        "generated_at": "2026-06-02T00:00:00Z",
        "runs": [
            {
                "run_id": 100,
                "workflow_name": "E2E-Light",
                "pipeline_type": "pr_e2e",
                "created_at": "2026-06-02T00:00:00Z",
                "jobs": [
                    {
                        "job_id": 1,
                        "job_name": "lint",
                        "conclusion": "success",
                        "started_at": "2026-06-02T00:01:00Z",
                        "completed_at": "2026-06-02T00:03:00Z",
                    },
                    {
                        "job_id": 2,
                        "job_name": "test",
                        "conclusion": "failure",
                        "started_at": "2026-06-02T00:02:00Z",
                        "completed_at": "2026-06-02T00:07:00Z",
                    },
                ],
            }
        ],
    }), encoding="utf-8")

    result = import_static_reports(reports_dir)
    result_again = import_static_reports(reports_dir)

    assert result["daily_snapshots"] == 1
    assert result["job_records"] == 2
    assert result_again["job_records"] == 2

    db = sqlite3.connect(db_path)
    try:
        snapshots = db.execute("SELECT pipeline_type, total_runs, health_score FROM daily_snapshots").fetchall()
        jobs = db.execute("SELECT run_id, job_name, conclusion, duration_sec, queue_sec FROM job_records ORDER BY job_name").fetchall()
    finally:
        db.close()

    assert snapshots == [("pr_e2e", 10, 72)]
    assert len(jobs) == 2
    assert jobs[0][:4] == (100, "lint", "success", 120)
    assert jobs[0][4] == 60

    exported = json.loads((reports_dir / "daily-snapshots.json").read_text(encoding="utf-8"))
    assert exported["trend_axes"]["execution_trends"].startswith("CI execution date")
    assert exported["execution_trends"]["pr_e2e"][0]["date"] == "2026-06-02"
    assert exported["execution_trends"]["pr_e2e"][0]["measured_total"] == 2
    assert exported["execution_trends"]["pr_e2e"][0]["success_rate"] == 50

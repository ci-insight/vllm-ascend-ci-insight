"""Tests for lightweight CI metadata health input."""

import pytest

from src import ci_metadata
from src import aggregator
from src import ci_store
from src.ci_metadata import collect_ci_metadata, metadata_to_reports
from src.health import compute_health


@pytest.fixture(autouse=True)
def isolate_metrics_db(tmp_path, monkeypatch):
    monkeypatch.setattr(aggregator, "DB_PATH", tmp_path / "data" / "metrics.db")
    monkeypatch.setattr(aggregator, "SNAPSHOT_JSON", tmp_path / "docs" / "reports" / "daily-snapshots.json")


def test_metadata_to_reports_produces_complete_health_input():
    data = {
        "generated_at": "2026-06-02T00:00:00+00:00",
        "runs": [
            {
                "run_id": 1,
                "workflow_name": "E2E-Light",
                "conclusion": "success",
                "branch": "main",
                "created_at": "2026-06-02T00:00:00Z",
                "event": "pull_request",
                "pipeline_type": "pr_e2e",
                "jobs": [
                    {"job_id": 10, "job_name": "lint", "conclusion": "success", "started_at": "", "completed_at": ""},
                    {"job_id": 11, "job_name": "e2e", "conclusion": "failure", "started_at": "", "completed_at": ""},
                ],
            }
        ],
    }

    reports = metadata_to_reports(data)
    health = compute_health(reports, complete_sample=True)

    assert len(reports) == 1
    assert health["data_quality"]["complete_success_sample"] is True
    assert health["pipelines"]["pr_e2e"]["measured_total"] == 2
    assert health["pipelines"]["pr_e2e"]["success_rate"] == 50


def test_metadata_missing_pipeline_type_is_classified():
    data = {
        "generated_at": "2026-06-02T00:00:00+00:00",
        "runs": [
            {
                "run_id": 1,
                "workflow_name": "Nightly-A2",
                "conclusion": "success",
                "branch": "main",
                "created_at": "2026-06-02T00:00:00Z",
                "event": "schedule",
                "jobs": [
                    {"job_id": 10, "job_name": "nightly", "conclusion": "success", "started_at": "", "completed_at": ""},
                ],
            }
        ],
    }

    reports = metadata_to_reports(data)
    health = compute_health(reports, complete_sample=True)

    assert "nightly" in health["pipelines"]


def test_collect_ci_metadata_stops_after_measured_targets(monkeypatch):
    runs = [
        {
            "databaseId": 1,
            "workflowName": "E2E-Light",
            "conclusion": "success",
            "status": "completed",
            "createdAt": "2026-06-02T00:00:00Z",
        },
        {
            "databaseId": 2,
            "workflowName": "Nightly-A2",
            "conclusion": "success",
            "status": "completed",
            "createdAt": "2026-06-02T00:01:00Z",
        },
        {
            "databaseId": 3,
            "workflowName": "E2E-Full",
            "conclusion": "success",
            "status": "completed",
            "createdAt": "2026-06-02T00:02:00Z",
        },
    ]
    jobs = {
        1: [{"id": 10, "name": "lint", "conclusion": "success", "started_at": "", "completed_at": ""}],
        2: [{"id": 20, "name": "nightly", "conclusion": "failure", "started_at": "", "completed_at": ""}],
        3: [{"id": 30, "name": "e2e", "conclusion": "success", "started_at": "", "completed_at": ""}],
    }
    fetched = []

    monkeypatch.setattr(ci_metadata, "list_recent_runs", lambda days, limit: runs)

    def fake_get_run_jobs(run_id):
        fetched.append(run_id)
        return jobs[run_id]

    monkeypatch.setattr(ci_metadata, "get_run_jobs", fake_get_run_jobs)

    data = collect_ci_metadata(days=7, limit=100, min_measured_per_pipeline=1)

    assert fetched == [1, 2]
    assert len(data["runs"]) == 2
    assert data["min_measured_per_pipeline"] == 1
    assert data["measured_jobs_by_pipeline"] == {"pr_e2e": 1, "nightly": 1}
    assert data["execution_dates"] == ["2026-06-02"]


def test_collect_ci_metadata_waits_for_execution_day_target(monkeypatch):
    runs = [
        {
            "databaseId": 1,
            "workflowName": "E2E-Light",
            "conclusion": "success",
            "status": "completed",
            "createdAt": "2026-06-02T00:00:00Z",
        },
        {
            "databaseId": 2,
            "workflowName": "Nightly-A2",
            "conclusion": "success",
            "status": "completed",
            "createdAt": "2026-06-02T00:01:00Z",
        },
        {
            "databaseId": 3,
            "workflowName": "E2E-Full",
            "conclusion": "success",
            "status": "completed",
            "createdAt": "2026-06-01T23:59:00Z",
        },
        {
            "databaseId": 4,
            "workflowName": "Nightly-A2",
            "conclusion": "success",
            "status": "completed",
            "createdAt": "2026-05-31T23:59:00Z",
        },
    ]
    jobs = {
        1: [{"id": 10, "name": "lint", "conclusion": "success", "started_at": "", "completed_at": "2026-06-02T00:10:00Z"}],
        2: [{"id": 20, "name": "nightly", "conclusion": "failure", "started_at": "", "completed_at": "2026-06-02T00:11:00Z"}],
        3: [{"id": 30, "name": "e2e", "conclusion": "skipped", "started_at": "", "completed_at": "2026-06-01T23:59:00Z"}],
        4: [{"id": 40, "name": "nightly", "conclusion": "success", "started_at": "", "completed_at": "2026-05-31T23:59:00Z"}],
    }
    fetched = []

    monkeypatch.setattr(ci_metadata, "list_recent_runs", lambda days, limit: runs)

    def fake_get_run_jobs(run_id):
        fetched.append(run_id)
        return jobs[run_id]

    monkeypatch.setattr(ci_metadata, "get_run_jobs", fake_get_run_jobs)

    data = collect_ci_metadata(
        days=7,
        limit=100,
        min_measured_per_pipeline=1,
        min_execution_days=2,
    )

    assert fetched == [1, 2, 3]
    assert len(data["runs"]) == 3
    assert data["min_execution_days"] == 2
    assert data["measured_jobs_by_pipeline"] == {"pr_e2e": 1, "nightly": 1}
    assert data["execution_dates"] == ["2026-06-01", "2026-06-02"]


def test_collect_ci_metadata_exhausts_limit_when_target_not_met(monkeypatch):
    runs = [
        {
            "databaseId": 1,
            "workflowName": "Nightly-A2",
            "conclusion": "skipped",
            "status": "completed",
            "createdAt": "2026-06-02T00:00:00Z",
        }
    ]
    monkeypatch.setattr(ci_metadata, "list_recent_runs", lambda days, limit: runs)
    monkeypatch.setattr(
        ci_metadata,
        "get_run_jobs",
        lambda run_id: [{"id": 10, "name": "nightly", "conclusion": "skipped", "started_at": "", "completed_at": ""}],
    )

    data = collect_ci_metadata(days=7, limit=1, min_measured_per_pipeline=1)

    assert len(data["runs"]) == 1
    assert data["measured_jobs_by_pipeline"] == {"pr_e2e": 0, "nightly": 0}


def test_date_partition_collection_records_inventory_and_job_coverage(monkeypatch):
    monkeypatch.setattr(
        ci_metadata,
        "list_runs_by_date",
        lambda days: (
            [
                {
                    "databaseId": 1,
                    "workflowName": "E2E-Light",
                    "conclusion": "success",
                    "status": "completed",
                    "createdAt": "2026-06-03T00:00:00Z",
                },
                {
                    "databaseId": 2,
                    "workflowName": "Nightly-A2",
                    "conclusion": "failure",
                    "status": "completed",
                    "createdAt": "2026-06-02T00:00:00Z",
                },
                {
                    "databaseId": 3,
                    "workflowName": "E2E-Full",
                    "conclusion": "success",
                    "status": "completed",
                    "createdAt": "2026-06-01T00:00:00Z",
                },
            ],
            {"2026-06-03": 1, "2026-06-02": 1, "2026-06-01": 1},
        ),
    )
    monkeypatch.setattr(
        ci_metadata,
        "get_run_jobs",
        lambda run_id: [{"id": run_id * 10, "name": "job", "conclusion": "success", "started_at": "", "completed_at": ""}],
    )

    data = collect_ci_metadata(
        days=3,
        collection_strategy="date_partition",
        job_detail_limit=2,
    )

    assert data["collection_strategy"] == "date_partition"
    assert data["run_inventory_count"] == 3
    assert data["run_inventory_by_date"] == {"2026-06-03": 1, "2026-06-02": 1, "2026-06-01": 1}
    assert data["job_detail_runs_collected"] == 2
    assert data["job_detail_selection"] == "balanced_by_date"
    assert data["job_detail_coverage_percent"] == 66.67
    assert [run["run_id"] for run in data["runs"]] == [1, 2]


def test_list_runs_for_window_complete_splits_capped_windows(monkeypatch):
    calls = []

    def fake_count(start, end):
        if start.hour == 0 and end.hour == 23:
            return 1500
        return 750

    def fake_list(start, end):
        calls.append((start, end))
        base = 1 if len(calls) == 1 else 100
        return [
            {
                "databaseId": base,
                "workflowName": "E2E-Light",
                "createdAt": start.isoformat(),
            }
        ]

    monkeypatch.setattr(ci_metadata, "count_runs_for_window", fake_count)
    monkeypatch.setattr(ci_metadata, "list_runs_for_window", fake_list)

    runs = ci_metadata.list_runs_for_date("2026-06-03")

    assert len(calls) == 2
    assert [run["databaseId"] for run in runs] == [1, 100]


def test_inventory_update_marks_jobs_stale_when_run_changes():
    db = ci_store.conn()
    original = {
        "databaseId": 1,
        "workflowName": "E2E-Light",
        "conclusion": "success",
        "status": "in_progress",
        "createdAt": "2026-06-03T00:00:00Z",
        "updatedAt": "2026-06-03T00:01:00Z",
    }
    updated = {
        **original,
        "status": "completed",
        "updatedAt": "2026-06-03T00:05:00Z",
    }

    ci_store.upsert_runs(db, [original])
    ci_store.replace_run_jobs(
        db,
        original,
        [{"id": 10, "name": "job", "conclusion": "success", "started_at": "", "completed_at": ""}],
    )
    db.commit()
    assert ci_store.runs_for_job_collection(db, days=1) == []

    ci_store.upsert_runs(db, [updated])
    db.commit()
    stale = ci_store.runs_for_job_collection(db, days=1)
    db.close()

    assert [run["databaseId"] for run in stale] == [1]


def test_split_collection_can_export_metadata_from_sqlite(monkeypatch):
    runs = [
        {
            "databaseId": 1,
            "workflowName": "E2E-Light",
            "conclusion": "success",
            "status": "completed",
            "createdAt": "2026-06-03T00:00:00Z",
            "updatedAt": "2026-06-03T00:01:00Z",
        },
        {
            "databaseId": 2,
            "workflowName": "Nightly-A2",
            "conclusion": "failure",
            "status": "completed",
            "createdAt": "2026-06-03T01:00:00Z",
            "updatedAt": "2026-06-03T01:01:00Z",
        },
    ]
    monkeypatch.setattr(ci_metadata, "list_recent_runs", lambda days, limit: runs)
    monkeypatch.setattr(
        ci_metadata,
        "get_run_jobs",
        lambda run_id: [{"id": run_id * 10, "name": "job", "conclusion": "success", "started_at": "", "completed_at": ""}],
    )

    inventory = ci_metadata.collect_run_inventory(days=1, limit=10)
    details = ci_metadata.collect_pending_job_details(days=1, limit=1)
    exported = ci_metadata.build_ci_metadata_from_store(days=1)

    assert inventory["run_inventory_count"] == 2
    assert details["job_detail_runs_processed"] == 1
    assert exported["run_inventory_count"] == 2
    assert exported["job_detail_runs_collected"] == 1
    assert exported["job_detail_coverage_percent"] == 50
    assert len(exported["runs"]) == 1

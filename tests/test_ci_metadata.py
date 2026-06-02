"""Tests for lightweight CI metadata health input."""

from src import ci_metadata
from src.ci_metadata import collect_ci_metadata, metadata_to_reports
from src.health import compute_health


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

"""Tests for lightweight CI metadata health input."""

from src.ci_metadata import metadata_to_reports
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

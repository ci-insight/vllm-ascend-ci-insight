"""Test health score computation."""

import json
import pytest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from src.health import _rating, compute_health
from src.models import FailureReport, CIRun, CIJob, JobAnalysis


def make_report(pr_num, wf_name, pipeline_type, conclusions, days_ago=0):
    """Helper: create a FailureReport with specific job conclusions."""
    now = datetime.now(timezone.utc)
    ts = (now - timedelta(days=days_ago)).isoformat()
    jobs = []
    for i, conclusion in enumerate(conclusions):
        jobs.append(CIJob(
            job_id=pr_num * 100 + i,
            job_name=f"test-job-{i}",
            conclusion=conclusion,
            started_at=ts,
            completed_at=ts,
        ))
    run = CIRun(
        run_id=pr_num * 10,
        workflow_name=wf_name,
        conclusion="failure" if "failure" in conclusions else "success",
        branch="main",
        pr_number=pr_num,
        created_at=ts,
        event="pull_request",
        pipeline_type=pipeline_type,
        jobs=jobs,
    )
    return FailureReport(
        pr_number=pr_num,
        pr_title=f"Test PR {pr_num}",
        pr_author="test",
        pr_url=f"https://github.com/test/{pr_num}",
        analyzed_at=now.isoformat(),
        runs=[run],
        analyses=[],
    )


def test_rating_thresholds():
    assert _rating(90) == ("good", "#16a34a")
    assert _rating(75) == ("fair", "#ca8a04")
    assert _rating(50) == ("danger", "#dc2626")
    assert _rating(0) == ("danger", "#dc2626")


def test_compute_health_all_success():
    reports = [make_report(1, "E2E-Light", "pr_e2e", ["success", "success", "success"])]
    data = compute_health(reports)
    pr = data["pipelines"]["pr_e2e"]
    assert pr["success_rate"] == 100
    assert pr["measured_total"] == 3
    assert pr["health_score"] >= 60  # good baseline


def test_compute_health_all_failure():
    reports = [make_report(1, "E2E-Light", "pr_e2e", ["failure", "failure"])]
    data = compute_health(reports)
    pr = data["pipelines"]["pr_e2e"]
    assert pr["success_rate"] == 0
    assert pr["health_score"] <= 20


def test_compute_health_consecutive_penalty():
    reports = [
        make_report(1, "E2E-Light", "pr_e2e", ["failure"]),
        make_report(2, "E2E-Light", "pr_e2e", ["failure"]),
    ]
    data = compute_health(reports)
    pr = data["pipelines"]["pr_e2e"]
    assert len(pr.get("consecutive_details", [])) > 0
    assert pr["consecutive_details"][0]["streak"] == 2


def test_multiple_failed_jobs_in_one_run_are_not_a_streak():
    reports = [make_report(1, "E2E-Light", "pr_e2e", ["failure", "failure", "failure"])]
    data = compute_health(reports)
    pr = data["pipelines"]["pr_e2e"]
    assert pr.get("consecutive_details", []) == []
    assert data["consecutive_failures"] == {}


def test_compute_health_multi_pipeline():
    reports = [
        make_report(1, "E2E-Light", "pr_e2e", ["success", "failure"]),
        make_report(2, "Nightly-A2", "nightly", ["failure"]),
    ]
    data = compute_health(reports)
    assert "pr_e2e" in data["pipelines"]
    assert "nightly" in data["pipelines"]


def test_health_score_bounds():
    """Health scores must be 0-100."""
    reports = [make_report(1, "E2E-Light", "pr_e2e", ["failure"] * 10)]
    data = compute_health(reports)
    for pt, p in data["pipelines"].items():
        assert 0 <= p["health_score"] <= 100, f"{pt} health score out of bounds: {p['health_score']}"


def test_skipped_jobs_do_not_lower_success_rate():
    reports = [make_report(1, "E2E-Light", "pr_e2e", ["success", "skipped", "cancelled"])]
    data = compute_health(reports)
    pr = data["pipelines"]["pr_e2e"]
    assert pr["total"] == 3
    assert pr["measured_total"] == 1
    assert pr["skipped"] == 1
    assert pr["cancelled"] == 1
    assert pr["success_rate"] == 100


def test_no_measured_jobs_has_no_health_score():
    reports = [make_report(1, "Nightly-A2", "nightly", ["skipped", "cancelled"])]
    data = compute_health(reports, complete_sample=True)
    nightly = data["pipelines"]["nightly"]
    assert nightly["measured_total"] == 0
    assert nightly["health_score"] is None
    assert nightly["rating"] == "insufficient_data"


def test_trend_windows_do_not_double_count_recent_jobs():
    reports = [
        make_report(1, "E2E-Light", "pr_e2e", ["success"], days_ago=0),
        make_report(2, "E2E-Light", "pr_e2e", ["failure"], days_ago=2),
        make_report(3, "E2E-Light", "pr_e2e", ["failure"], days_ago=5),
    ]
    data = compute_health(reports)
    pr = data["pipelines"]["pr_e2e"]
    assert sum(day["measured_total"] for day in pr["daily_trend"]) == 3


def test_duplicate_run_jobs_are_counted_once():
    report = make_report(1, "E2E-Light", "pr_e2e", ["failure", "success"])
    duplicate = make_report(2, "E2E-Light", "pr_e2e", [])
    duplicate.runs = report.runs
    data = compute_health([report, duplicate])
    pr = data["pipelines"]["pr_e2e"]
    assert pr["total"] == 2
    assert pr["measured_total"] == 2

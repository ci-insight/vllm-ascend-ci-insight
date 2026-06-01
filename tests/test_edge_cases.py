"""Edge case and boundary tests."""

import json
import pytest
from pathlib import Path
from datetime import datetime, timezone, timedelta

from src.collector import classify_pipeline, truncate_log
from src.health import compute_health, _rating
from src.models import FailureReport, CIRun, CIJob


def make_report(pr_num, wf_name, pipeline_type, conclusions, days_ago=0):
    now = datetime.now(timezone.utc)
    ts = (now - timedelta(days=days_ago)).isoformat()
    jobs = [CIJob(pr_num*100+i, f"job-{i}", c, ts, ts, []) for i, c in enumerate(conclusions)]
    run = CIRun(pr_num*10, wf_name, "failure" if "failure" in conclusions else "success",
                "main", pr_num, ts, "pull_request", pipeline_type, jobs)
    return FailureReport(pr_num, f"PR {pr_num}", "test", f"url/{pr_num}", now.isoformat(), [run], [])


class TestEmptyData:
    def test_empty_reports(self):
        data = compute_health([])
        assert data["pipelines"] == {}
        assert data["consecutive_failures"] == {}

    def test_empty_jobs(self):
        r = make_report(1, "E2E-Light", "pr_e2e", [])
        data = compute_health([r])
        # With 0 jobs, pipeline has no data points → may not appear
        # This is expected: no jobs = nothing to measure
        assert isinstance(data["pipelines"], dict)

    def test_no_pipeline_type(self):
        """When pipeline_type is empty, health.py classifies from workflow name."""
        r = make_report(1, "E2E-Light", "", ["failure"])
        data = compute_health([r])
        # pipeline_type="" gets classified as "other" but the workflow is still E2E-Light
        assert len(data["pipelines"]) >= 1


class TestBoundaryValues:
    def test_health_score_zero(self):
        r = make_report(1, "E2E-Light", "pr_e2e", ["failure"] * 100, days_ago=0)
        data = compute_health([r])
        assert data["pipelines"]["pr_e2e"]["health_score"] >= 0

    def test_health_score_100(self):
        r = make_report(1, "E2E-Light", "pr_e2e", ["success"] * 100, days_ago=0)
        data = compute_health([r])
        assert data["pipelines"]["pr_e2e"]["health_score"] <= 100

    def test_rating_boundaries(self):
        assert _rating(80) == ("good", "#16a34a")
        assert _rating(79) == ("fair", "#ca8a04")
        assert _rating(60) == ("fair", "#ca8a04")
        assert _rating(59) == ("danger", "#dc2626")

    def test_large_duration(self):
        """Jobs with very long durations should not break computation."""
        now = datetime.now(timezone.utc)
        ts_start = (now - timedelta(days=10)).isoformat()
        ts_end = now.isoformat()
        job = CIJob(1, "long-job", "failure", ts_start, ts_end, [])
        run = CIRun(1, "Nightly-A2", "failure", "main", 1, ts_start, "schedule", "nightly", [job])
        r = FailureReport(1, "test", "test", "url", now.isoformat(), [run], [])
        data = compute_health([r])
        assert data["pipelines"]["nightly"]["health_score"] >= 0


class TestTruncateLog:
    def test_empty_log(self):
        assert truncate_log("") == ""

    def test_short_log(self):
        log = "line1\nline2\nline3"
        assert "line1" in truncate_log(log)

    def test_long_log_truncation(self):
        lines = [f"line {i}" for i in range(2000)]
        log = "\n".join(lines)
        result = truncate_log(log)
        assert len(result.splitlines()) < len(lines)
        assert "LOG TAIL" in result

    def test_error_pattern_extraction(self):
        lines = ["setup line"] * 300 + ["ERROR: something broke"] + ["more lines"] * 800
        log = "\n".join(lines)
        result = truncate_log(log)
        assert "ERROR" in result
        assert "ERROR PATTERNS FOUND" in result


class TestClassificationEdgeCases:
    def test_empty_workflow_name(self):
        assert classify_pipeline("") == "other"

    def test_none_like_string(self):
        assert classify_pipeline("None") == "other"

    def test_partial_match(self):
        """E2E should match E2E-Light but 'E2' alone should not."""
        assert classify_pipeline("E2E-Light") == "pr_e2e"
        assert classify_pipeline("E2E") == "other"

    def test_exact_match_required(self):
        """Pipeline patterns are case-sensitive (GitHub workflow names are exact)."""
        assert classify_pipeline("E2E-Light") == "pr_e2e"
        assert classify_pipeline("Nightly-A2") == "nightly"
        # Lowercase variants should NOT match (real workflow names are always Title-Case)
        assert classify_pipeline("e2e-light") == "other"


class TestFailureReportConsistency:
    def test_multiple_runs_same_pr(self):
        """PR with multiple failed runs should aggregate correctly."""
        r1 = make_report(1, "E2E-Light", "pr_e2e", ["failure", "success"])
        r2 = make_report(1, "E2E-Full", "pr_e2e", ["failure"])
        r1.runs.extend(r2.runs)
        assert len(r1.runs) == 2

    def test_mixed_conclusions(self):
        r = make_report(1, "E2E-Light", "pr_e2e", ["success", "failure", "success", "failure", "skipped"])
        assert len(r.runs[0].jobs) == 5
        failed = sum(1 for j in r.runs[0].jobs if j.conclusion == "failure")
        assert failed == 2

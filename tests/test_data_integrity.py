"""Verify all actual report data is structurally correct and consistent."""

import json
import os
import pytest
from datetime import datetime
from pathlib import Path

from src.storage import read_json, resolve_dashboard_path, source_reports_dir

REPORTS_DIR = source_reports_dir()
REQUIRED_REPORT_FIELDS = ["pr_number", "pr_title", "pr_author", "pr_url", "analyzed_at", "runs"]
REQUIRED_RUN_FIELDS = ["run_id", "workflow_name", "conclusion", "created_at", "jobs"]
REQUIRED_JOB_FIELDS = ["job_id", "job_name", "conclusion"]
REQUIRED_ANALYSIS_FIELDS = ["job_name", "job_id", "severity", "confidence", "root_cause"]


def collect_all_reports():
    """Collect all report JSON paths from disk."""
    paths = []
    for root, dirs, files in os.walk(str(REPORTS_DIR)):
        for f in files:
            if f.startswith("pr-") and f.endswith(".json"):
                paths.append(Path(root) / f)
    return paths


ALL_REPORTS = collect_all_reports()


def test_reports_exist():
    """At least some reports should exist."""
    assert len(ALL_REPORTS) > 0, "No report files found"


@pytest.mark.parametrize("path", ALL_REPORTS)
def test_report_valid_json(path):
    """Every report file must be valid JSON."""
    data = read_json(path, default={})
    assert isinstance(data, dict), f"{path.name}: not a dict"


@pytest.mark.parametrize("path", ALL_REPORTS)
def test_report_required_fields(path):
    """Every report must have all required top-level fields."""
    data = read_json(path, default={})
    for field in REQUIRED_REPORT_FIELDS:
        assert field in data, f"{path.name}: missing field '{field}'"
    assert isinstance(data["runs"], list), f"{path.name}: runs must be list"
    assert len(data["runs"]) > 0, f"{path.name}: must have at least 1 run"


@pytest.mark.parametrize("path", ALL_REPORTS)
def test_report_run_fields(path):
    """Every run must have required fields."""
    data = read_json(path, default={})
    for run in data["runs"]:
        for field in REQUIRED_RUN_FIELDS:
            assert field in run, f"{path.name} run {run.get('run_id','?')}: missing '{field}'"


@pytest.mark.parametrize("path", ALL_REPORTS)
def test_report_job_fields(path):
    """Every job must have required fields + timing."""
    data = read_json(path, default={})
    for run in data["runs"]:
        for job in run["jobs"]:
            for field in REQUIRED_JOB_FIELDS:
                assert field in job, f"{path.name} job {job.get('job_id','?')}: missing '{field}'"
            # Timing must be present and valid (allow 5s clock skew)
            if job.get("started_at") and job.get("completed_at"):
                started = datetime.fromisoformat(job["started_at"].replace("Z", "+00:00"))
                completed = datetime.fromisoformat(job["completed_at"].replace("Z", "+00:00"))
                diff = (completed - started).total_seconds()
                assert diff > -10, f"{path.name} job {job['job_id']}: completed {abs(diff)}s before started (clock skew)"


@pytest.mark.parametrize("path", ALL_REPORTS)
def test_report_analysis_fields(path):
    """Every analysis (confidence>0) must have required fields."""
    data = read_json(path, default={})
    for a in data.get("analyses", []):
        if a.get("confidence", 0) > 0:
            for field in REQUIRED_ANALYSIS_FIELDS:
                assert field in a, f"{path.name}: analysis missing '{field}'"
            assert a["severity"] in ("critical", "high", "medium", "low"), f"{path.name}: invalid severity '{a['severity']}'"
            assert 0 <= a["confidence"] <= 100, f"{path.name}: confidence {a['confidence']} out of range"
            if "effort" in a:
                assert a["effort"] in ("low", "medium", "high"), f"{path.name}: invalid effort '{a['effort']}'"


@pytest.mark.parametrize("path", ALL_REPORTS)
def test_report_job_analysis_consistency(path):
    """Every analysis job_id must match a job in the runs."""
    data = read_json(path, default={})
    job_ids = set()
    for run in data["runs"]:
        for job in run["jobs"]:
            job_ids.add(job["job_id"])

    for a in data.get("analyses", []):
        if a.get("confidence", 0) > 0:
            assert a["job_id"] in job_ids, (
                f"{path.name}: analysis job_id={a['job_id']} not found in runs"
            )


@pytest.mark.parametrize("path", ALL_REPORTS)
def test_report_pr_number_consistent(path):
    """Report filename PR number must match pr_number field."""
    data = read_json(path, default={})
    expected_pr = int(path.stem.split("-")[1])
    assert data["pr_number"] == expected_pr, f"{path.name}: filename says #{expected_pr}, field says #{data['pr_number']}"


def test_no_duplicate_reports():
    """Each PR should have at most one report per date."""
    seen = {}
    for path in ALL_REPORTS:
        date_dir = path.parent.name
        pr = path.stem
        key = f"{date_dir}/{pr}"
        assert key not in seen, f"Duplicate report: {key} (also at {seen[key]})"
        seen[key] = str(path)


def test_all_reports_have_valid_confidence():
    """Confidence values must be valid integers 0-100."""
    for path in ALL_REPORTS:
        data = read_json(path, default={})
        for a in data.get("analyses", []):
            conf = a.get("confidence", 0)
            assert isinstance(conf, (int, float)), f"{path.name}: confidence not a number: {conf}"
            assert 0 <= conf <= 100, f"{path.name}: confidence {conf} out of [0,100]"


def test_report_index_consistent():
    """index.json must match actual report files on disk."""
    index_path = REPORTS_DIR / "index.json"
    if not index_path.exists():
        pytest.skip("No index.json")
    index = read_json(index_path, default={})
    indexed_prs = set()
    for entry in index["reports"]:
        indexed_prs.add(entry["pr_number"])
        json_path = resolve_dashboard_path(entry["json_path"])
        assert json_path.exists(), f"index references missing file: {json_path}"

    # All report files should be in index
    for path in ALL_REPORTS:
        data = read_json(path, default={})
        assert data["pr_number"] in indexed_prs, (
            f"{path.name}: PR #{data['pr_number']} on disk but not in index.json"
        )


def test_health_counts_are_consistent():
    """Dashboard health buckets must add up to total jobs."""
    health_path = REPORTS_DIR / "health.json"
    if not health_path.exists():
        pytest.skip("No health.json")
    data = read_json(health_path, default={})
    overall_bucket_sum = 0
    overall_measured = 0
    for ptype, pdata in data.get("pipelines", {}).items():
        bucket_sum = sum(pdata.get(key, 0) for key in ("success", "failure", "skipped", "cancelled", "pending", "other"))
        assert pdata.get("total", 0) == bucket_sum, f"{ptype}: total does not match conclusion buckets"
        assert pdata.get("measured_total", 0) == pdata.get("success", 0) + pdata.get("failure", 0)
        assert "workflow_runs" in pdata, f"{ptype}: missing workflow-run count"
        overall_bucket_sum += bucket_sum
        overall_measured += pdata.get("measured_total", 0)
    assert data.get("overall", {}).get("total", 0) == overall_bucket_sum
    assert data.get("overall", {}).get("measured_total", 0) == overall_measured

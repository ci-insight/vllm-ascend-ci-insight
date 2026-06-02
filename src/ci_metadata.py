"""Lightweight GitHub Actions metadata collection for CI health metrics."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .collector import REPO, _gh, _parse_json_output, classify_pipeline, get_run_jobs
from .models import CIJob, CIRun, FailureReport
from .storage import DOCS_REPORTS_DIR, LOCAL_REPORTS_DIR, read_json, write_json

LOCAL_CI_RUNS_FILE = LOCAL_REPORTS_DIR / "ci-runs.json"
DOCS_CI_RUNS_FILE = DOCS_REPORTS_DIR / "ci-runs.json"
MEASURED_CONCLUSIONS = {"success", "failure"}
TARGET_PIPELINES = ("pr_e2e", "nightly")


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def list_recent_runs(days: int = 7, limit: int = 200) -> list[dict]:
    """List recent workflow runs without fetching logs."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = _gh(
        "run", "list",
        "--repo", REPO,
        "--limit", str(limit),
        "--json", "databaseId,name,workflowName,conclusion,status,createdAt,updatedAt,headBranch,event,url",
        check=False,
    )
    if result.returncode != 0:
        print(f"Warning: gh run list failed: {result.stderr}", file=sys.stderr)
        return []
    runs = _parse_json_output(result)
    if not isinstance(runs, list):
        return []
    return [
        run for run in runs
        if (created := _parse_time(run.get("createdAt", ""))) is not None and created >= cutoff
    ]


def _count_measured_jobs(records: list[dict]) -> dict[str, int]:
    counts = {pipeline: 0 for pipeline in TARGET_PIPELINES}
    for run in records:
        pipeline = run.get("pipeline_type", "other")
        if pipeline not in counts:
            continue
        counts[pipeline] += sum(
            1 for job in run.get("jobs", [])
            if job.get("conclusion") in MEASURED_CONCLUSIONS
        )
    return counts


def _targets_met(records: list[dict], min_measured_per_pipeline: int) -> bool:
    if min_measured_per_pipeline <= 0:
        return False
    counts = _count_measured_jobs(records)
    return all(counts[pipeline] >= min_measured_per_pipeline for pipeline in TARGET_PIPELINES)


def collect_ci_metadata(days: int = 7, limit: int = 200, min_measured_per_pipeline: int = 0) -> dict:
    """Collect run/job metadata for health metrics.

    This intentionally does not fetch job logs and does not call any LLM.
    When min_measured_per_pipeline is set, collection stops early after each
    core pipeline has enough success/failure jobs or the limit is exhausted.
    """
    runs = list_recent_runs(days=days, limit=limit)
    records: list[dict] = []

    for idx, run in enumerate(runs, 1):
        run_id = run.get("databaseId")
        workflow = run.get("workflowName") or run.get("name") or ""
        print(f"  [{idx}/{len(runs)}] {workflow} run {run_id}")
        jobs_raw = get_run_jobs(run_id)
        jobs = [
            {
                "job_id": job.get("id"),
                "job_name": job.get("name", ""),
                "conclusion": job.get("conclusion") or job.get("status") or "unknown",
                "started_at": job.get("started_at", ""),
                "completed_at": job.get("completed_at", ""),
            }
            for job in jobs_raw
            if job.get("id") is not None
        ]
        records.append({
            "run_id": run_id,
            "workflow_name": workflow,
            "conclusion": run.get("conclusion") or run.get("status") or "unknown",
            "status": run.get("status", ""),
            "branch": run.get("headBranch", ""),
            "created_at": run.get("createdAt", ""),
            "updated_at": run.get("updatedAt", ""),
            "event": run.get("event", ""),
            "url": run.get("url", ""),
            "pipeline_type": classify_pipeline(workflow),
            "jobs": jobs,
        })
        if _targets_met(records, min_measured_per_pipeline):
            counts = _count_measured_jobs(records)
            print(
                "  Measured target reached: "
                + ", ".join(f"{name}={count}" for name, count in counts.items())
            )
            break

    measured_counts = _count_measured_jobs(records)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo": REPO,
        "days": days,
        "limit": limit,
        "min_measured_per_pipeline": min_measured_per_pipeline,
        "measured_jobs_by_pipeline": measured_counts,
        "dataset_kind": "full_ci_run_metadata",
        "runs": records,
    }


def save_ci_metadata(data: dict) -> None:
    write_json(LOCAL_CI_RUNS_FILE, data)
    write_json(DOCS_CI_RUNS_FILE, data)
    print(f"  CI metadata: {DOCS_CI_RUNS_FILE} ({len(data.get('runs', []))} runs)")


def load_ci_metadata() -> dict | None:
    data = read_json(LOCAL_CI_RUNS_FILE, default=None) or read_json(DOCS_CI_RUNS_FILE, default=None)
    return data if isinstance(data, dict) and data.get("runs") else None


def metadata_to_reports(data: dict) -> list[FailureReport]:
    """Adapt metadata JSON into FailureReport objects consumed by health.py."""
    reports: list[FailureReport] = []
    generated_at = data.get("generated_at") or datetime.now(timezone.utc).isoformat()
    for run in data.get("runs", []):
        jobs = [
            CIJob(
                job_id=job["job_id"],
                job_name=job.get("job_name", ""),
                conclusion=job.get("conclusion", "unknown"),
                started_at=job.get("started_at", ""),
                completed_at=job.get("completed_at", ""),
            )
            for job in run.get("jobs", [])
            if job.get("job_id") is not None
        ]
        ci_run = CIRun(
            run_id=run["run_id"],
            workflow_name=run.get("workflow_name", ""),
            conclusion=run.get("conclusion", "unknown"),
            branch=run.get("branch", ""),
            pr_number=None,
            created_at=run.get("created_at", ""),
            event=run.get("event", ""),
            pipeline_type=run.get("pipeline_type") or classify_pipeline(run.get("workflow_name", "")),
            jobs=jobs,
        )
        reports.append(FailureReport(
            pr_number=0,
            pr_title=f"CI metadata run {run.get('run_id')}",
            pr_author="",
            pr_url=run.get("url", ""),
            analyzed_at=generated_at,
            runs=[ci_run],
            analyses=[],
        ))
    return reports

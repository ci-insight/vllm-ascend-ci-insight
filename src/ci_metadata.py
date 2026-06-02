"""Lightweight GitHub Actions metadata collection for CI health metrics."""

from __future__ import annotations

import json
import subprocess
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


def _api_json(*args: str) -> list[dict] | dict:
    cmd = ["gh", "api", *args]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        print(f"Warning: gh api {' '.join(args)} failed: {result.stderr}", file=sys.stderr)
        return []
    try:
        return json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return []


def _to_run_record(run: dict) -> dict:
    workflow = run.get("workflow_name") or run.get("name") or ""
    return {
        "databaseId": run.get("id") or run.get("databaseId"),
        "name": run.get("name") or workflow,
        "workflowName": workflow,
        "conclusion": run.get("conclusion") or "",
        "status": run.get("status") or "",
        "createdAt": run.get("created_at") or run.get("createdAt") or "",
        "updatedAt": run.get("updated_at") or run.get("updatedAt") or "",
        "headBranch": run.get("head_branch") or run.get("headBranch") or "",
        "event": run.get("event") or "",
        "url": run.get("html_url") or run.get("url") or "",
    }


def list_runs_for_date(day: str) -> list[dict]:
    """List all workflow runs for one UTC date without fetching jobs."""
    created = f"{day}T00:00:00Z..{day}T23:59:59Z"
    data = _api_json(
        "--method", "GET",
        "/repos/vllm-project/vllm-ascend/actions/runs",
        "-f", "per_page=100",
        "-f", f"created={created}",
        "--paginate",
        "--slurp",
    )
    if not isinstance(data, list):
        return []
    runs: list[dict] = []
    for page in data:
        if isinstance(page, dict):
            runs.extend(page.get("workflow_runs", []))
    return [_to_run_record(run) for run in runs]


def list_runs_by_date(days: int = 7) -> tuple[list[dict], dict[str, int]]:
    """List run inventory by UTC date, newest date first."""
    today = datetime.now(timezone.utc).date()
    all_runs: list[dict] = []
    counts: dict[str, int] = {}
    seen: set[int] = set()
    for offset in range(days):
        day = (today - timedelta(days=offset)).isoformat()
        runs = list_runs_for_date(day)
        counts[day] = len(runs)
        print(f"  Run inventory {day}: {len(runs)} run(s)")
        for run in runs:
            run_id = run.get("databaseId")
            if run_id in seen:
                continue
            seen.add(run_id)
            all_runs.append(run)
    all_runs.sort(key=lambda run: run.get("createdAt", ""), reverse=True)
    return all_runs, counts


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


def _job_execution_date(job: dict, fallback: str = "") -> str | None:
    value = job.get("completed_at") or job.get("started_at") or fallback
    parsed = _parse_time(value)
    return parsed.date().isoformat() if parsed else None


def _execution_dates(records: list[dict]) -> list[str]:
    dates: set[str] = set()
    for run in records:
        fallback = run.get("created_at", "")
        jobs = run.get("jobs", [])
        if not jobs:
            date = _job_execution_date({}, fallback)
            if date:
                dates.add(date)
            continue
        for job in jobs:
            date = _job_execution_date(job, fallback)
            if date:
                dates.add(date)
    return sorted(dates)


def _run_created_date(run: dict) -> str:
    return (run.get("createdAt") or "")[:10]


def _select_runs_for_job_details(runs: list[dict], limit: int, inventory_by_date: dict[str, int]) -> tuple[list[dict], str]:
    if limit <= 0 or limit >= len(runs):
        return runs, "all"
    if not inventory_by_date:
        return runs[:limit], "newest"

    dates = [day for day in sorted(inventory_by_date.keys(), reverse=True) if inventory_by_date.get(day, 0) > 0]
    if not dates:
        return runs[:limit], "newest"

    groups: dict[str, list[dict]] = {day: [] for day in dates}
    for run in runs:
        day = _run_created_date(run)
        if day in groups:
            groups[day].append(run)

    per_day = max(1, limit // len(dates))
    selected: list[dict] = []
    selected_ids: set[int] = set()
    for day in dates:
        for run in groups[day][:per_day]:
            run_id = run.get("databaseId")
            if run_id in selected_ids:
                continue
            selected.append(run)
            selected_ids.add(run_id)
            if len(selected) >= limit:
                return selected, "balanced_by_date"

    for run in runs:
        run_id = run.get("databaseId")
        if run_id in selected_ids:
            continue
        selected.append(run)
        selected_ids.add(run_id)
        if len(selected) >= limit:
            break
    return selected, "balanced_by_date"


def _targets_met(records: list[dict], min_measured_per_pipeline: int, min_execution_days: int) -> bool:
    if min_measured_per_pipeline <= 0 and min_execution_days <= 0:
        return False
    if min_measured_per_pipeline > 0:
        counts = _count_measured_jobs(records)
        measured_ok = all(counts[pipeline] >= min_measured_per_pipeline for pipeline in TARGET_PIPELINES)
    else:
        measured_ok = True
    dates_ok = min_execution_days <= 0 or len(_execution_dates(records)) >= min_execution_days
    return measured_ok and dates_ok


def collect_ci_metadata(
    days: int = 7,
    limit: int = 200,
    min_measured_per_pipeline: int = 0,
    min_execution_days: int = 0,
    collection_strategy: str = "recent",
    job_detail_limit: int = 0,
) -> dict:
    """Collect run/job metadata for health metrics.

    This intentionally does not fetch job logs and does not call any LLM.
    When sample targets are set, collection stops early only after each core
    pipeline has enough measured jobs and the sample covers enough execution
    dates, or the limit is exhausted.
    """
    if collection_strategy == "date_partition":
        runs, run_inventory_by_date = list_runs_by_date(days=days)
    else:
        runs = list_recent_runs(days=days, limit=limit)
        run_inventory_by_date = {}
    run_inventory_count = len(runs)
    runs_to_fetch, job_detail_selection = _select_runs_for_job_details(
        runs,
        job_detail_limit,
        run_inventory_by_date if collection_strategy == "date_partition" else {},
    )
    records: list[dict] = []

    for idx, run in enumerate(runs_to_fetch, 1):
        run_id = run.get("databaseId")
        workflow = run.get("workflowName") or run.get("name") or ""
        print(f"  [{idx}/{len(runs_to_fetch)}] {workflow} run {run_id}")
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
        if _targets_met(records, min_measured_per_pipeline, min_execution_days):
            counts = _count_measured_jobs(records)
            execution_dates = _execution_dates(records)
            print(
                "  CI metadata sample target reached: "
                + ", ".join(f"{name}={count}" for name, count in counts.items())
                + f", execution_days={len(execution_dates)}"
            )
            break

    measured_counts = _count_measured_jobs(records)
    execution_dates = _execution_dates(records)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo": REPO,
        "days": days,
        "limit": limit,
        "collection_strategy": collection_strategy,
        "run_inventory_count": run_inventory_count,
        "run_inventory_by_date": run_inventory_by_date,
        "job_detail_limit": job_detail_limit,
        "job_detail_selection": job_detail_selection,
        "job_detail_runs_collected": len(records),
        "job_detail_coverage_percent": round(len(records) / run_inventory_count * 100, 2) if run_inventory_count else 0,
        "min_measured_per_pipeline": min_measured_per_pipeline,
        "min_execution_days": min_execution_days,
        "measured_jobs_by_pipeline": measured_counts,
        "execution_dates": execution_dates,
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

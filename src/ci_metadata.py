"""Lightweight GitHub Actions metadata collection for CI health metrics."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import ci_store
from .collector import REPO, _gh, _parse_json_output, classify_pipeline, get_job_log, get_run_jobs
from .models import CIJob, CIRun, FailureReport
from .storage import DOCS_REPORTS_DIR, LOCAL_REPORTS_DIR, read_json, write_json

LOCAL_CI_RUNS_FILE = LOCAL_REPORTS_DIR / "ci-runs.json"
DOCS_CI_RUNS_FILE = DOCS_REPORTS_DIR / "ci-runs.json"
LOCAL_COVERAGE_FILE = LOCAL_REPORTS_DIR / "coverage.json"
DOCS_COVERAGE_FILE = DOCS_REPORTS_DIR / "coverage.json"
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


def _api_json(*args: str):
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


def _format_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def count_runs_for_window(start: datetime, end: datetime) -> int:
    created = f"{_format_z(start)}..{_format_z(end)}"
    data = _api_json(
        "--method", "GET",
        "/repos/vllm-project/vllm-ascend/actions/runs",
        "-f", "per_page=1",
        "-f", f"created={created}",
        "--jq", ".total_count",
    )
    return data if isinstance(data, int) else 0


def list_runs_for_window(start: datetime, end: datetime) -> list[dict]:
    created = f"{_format_z(start)}..{_format_z(end)}"
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


def list_runs_for_window_complete(start: datetime, end: datetime, cap: int = 1000) -> list[dict]:
    """List runs for a window, splitting recursively when GitHub caps results."""
    total = count_runs_for_window(start, end)
    if total <= cap:
        return list_runs_for_window(start, end)
    if (end - start).total_seconds() <= 60:
        print(
            f"Warning: run inventory window {_format_z(start)}..{_format_z(end)} "
            f"has {total} runs; GitHub may cap returned rows",
            file=sys.stderr,
        )
        return list_runs_for_window(start, end)

    midpoint = start + (end - start) / 2
    left = list_runs_for_window_complete(start, midpoint, cap=cap)
    right_start = midpoint + timedelta(seconds=1)
    right = list_runs_for_window_complete(right_start, end, cap=cap)
    seen: set[int] = set()
    merged: list[dict] = []
    for run in [*left, *right]:
        run_id = run.get("databaseId")
        if run_id in seen:
            continue
        seen.add(run_id)
        merged.append(run)
    return merged


def list_runs_for_date(day: str) -> list[dict]:
    """List all workflow runs for one UTC date without fetching jobs."""
    start = datetime.fromisoformat(f"{day}T00:00:00+00:00")
    end = datetime.fromisoformat(f"{day}T23:59:59+00:00")
    return list_runs_for_window_complete(start, end)


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

    db = ci_store.conn()
    runs_needing_jobs = ci_store.runs_needing_jobs(db, runs)
    ci_store.upsert_runs(db, runs)
    db.commit()
    runs_to_fetch, job_detail_selection = _select_runs_for_job_details(
        runs_needing_jobs,
        job_detail_limit,
        run_inventory_by_date if collection_strategy == "date_partition" else {},
    )

    for idx, run in enumerate(runs_to_fetch, 1):
        run_id = run.get("databaseId")
        workflow = run.get("workflowName") or run.get("name") or ""
        print(f"  [{idx}/{len(runs_to_fetch)}] {workflow} run {run_id}")
        jobs_raw = get_run_jobs(run_id)
        if jobs_raw is None:
            continue
        ci_store.replace_run_jobs(db, run, jobs_raw)
        db.commit()

        if collection_strategy != "date_partition" and _targets_met(ci_store.export_runs_with_jobs(db, days), min_measured_per_pipeline, min_execution_days):
            records = ci_store.export_runs_with_jobs(db, days)
            counts = _count_measured_jobs(records)
            execution_dates = _execution_dates(records)
            print(
                "  CI metadata sample target reached: "
                + ", ".join(f"{name}={count}" for name, count in counts.items())
                + f", execution_days={len(execution_dates)}"
            )
            break

    records = ci_store.export_runs_with_jobs(db, days)
    coverage = ci_store.coverage(db, days)
    db.close()
    measured_counts = _count_measured_jobs(records)
    execution_dates = _execution_dates(records)
    run_inventory_by_date = run_inventory_by_date or coverage["run_inventory"]["by_date"]
    run_inventory_count = coverage["run_inventory"]["total"] or run_inventory_count

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
        "job_detail_runs_collected": coverage["job_details"]["collected_runs"],
        "job_detail_coverage_percent": coverage["job_details"]["coverage_percent"],
        "coverage": coverage,
        "min_measured_per_pipeline": min_measured_per_pipeline,
        "min_execution_days": min_execution_days,
        "measured_jobs_by_pipeline": measured_counts,
        "execution_dates": execution_dates,
        "dataset_kind": "full_ci_run_metadata",
        "runs": records,
    }


def collect_run_inventory(
    days: int = 7,
    limit: int = 200,
    collection_strategy: str = "recent",
) -> dict:
    """Collect only lightweight workflow-run inventory into SQLite."""
    if collection_strategy == "date_partition":
        runs, run_inventory_by_date = list_runs_by_date(days=days)
    else:
        runs = list_recent_runs(days=days, limit=limit)
        run_inventory_by_date = {}

    db = ci_store.conn()
    ci_store.upsert_runs(db, runs)
    db.commit()
    coverage = ci_store.coverage(db, days)
    db.close()

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo": REPO,
        "days": days,
        "limit": limit,
        "collection_strategy": collection_strategy,
        "run_inventory_count": coverage["run_inventory"]["total"] or len(runs),
        "run_inventory_by_date": run_inventory_by_date or coverage["run_inventory"]["by_date"],
        "coverage": coverage,
    }


def collect_pending_job_details(days: int = 7, limit: int = 500, force: bool = False) -> dict:
    """Fetch job details for inventoried runs that still need them."""
    db = ci_store.conn()
    runs = ci_store.runs_for_job_collection(db, days=days, limit=limit, force=force)
    for idx, run in enumerate(runs, 1):
        run_id = run.get("databaseId")
        workflow = run.get("workflowName") or run.get("name") or ""
        print(f"  [{idx}/{len(runs)}] {workflow} run {run_id}")
        jobs_raw = get_run_jobs(run_id)
        if jobs_raw is None:
            continue
        ci_store.replace_run_jobs(db, run, jobs_raw)
        db.commit()
    coverage = ci_store.coverage(db, days)
    db.close()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo": REPO,
        "days": days,
        "job_detail_limit": limit,
        "force": force,
        "job_detail_runs_processed": len(runs),
        "coverage": coverage,
    }


def collect_pending_job_logs(days: int = 7, limit: int = 100, force: bool = False) -> dict:
    """Fetch raw logs for failed-like jobs that are already known in SQLite."""
    db = ci_store.conn()
    try:
        jobs = ci_store.jobs_needing_logs(db, days=days, limit=limit, force=force)
        for idx, job in enumerate(jobs, 1):
            print(
                f"  [{idx}/{len(jobs)}] {job['workflow_name']} / "
                f"{job['job_name']} job {job['job_id']}"
            )
            raw_log = get_job_log(job["job_id"])
            ci_store.update_job_log(db, job["job_id"], raw_log)
            db.commit()
        coverage = ci_store.coverage(db, days)
    finally:
        db.close()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo": REPO,
        "days": days,
        "log_limit": limit,
        "force": force,
        "logs_processed": len(jobs),
        "coverage": coverage,
    }


def reports_from_store_failed_logs(days: int = 7, limit: int = 0) -> list[FailureReport]:
    """Build FailureReport objects from SQLite failed jobs with stored logs."""
    db = ci_store.conn()
    try:
        records = ci_store.export_failed_jobs_with_logs(db, days=days, limit=limit)
    finally:
        db.close()

    generated_at = datetime.now(timezone.utc).isoformat()
    reports: list[FailureReport] = []
    for run in records:
        jobs = [
            CIJob(
                job_id=job["job_id"],
                job_name=job.get("job_name", ""),
                conclusion=job.get("conclusion", "unknown"),
                started_at=job.get("started_at", ""),
                completed_at=job.get("completed_at", ""),
                created_at=job.get("created_at", ""),
                raw_log=job.get("raw_log", ""),
            )
            for job in run.get("jobs", [])
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
            pr_number=int(run["run_id"]),
            pr_title=f"Stored CI run {run.get('workflow_name', '')}",
            pr_author="",
            pr_url=run.get("url", ""),
            analyzed_at=generated_at,
            runs=[ci_run],
            analyses=[],
        ))
    return reports


def save_coverage_from_store(days: int, ai_analyzed: int = 0, failed_jobs: int | None = None) -> dict:
    """Persist coverage.json using SQLite counters plus AI analysis counters."""
    db = ci_store.conn()
    try:
        if failed_jobs is None:
            failed_jobs = ci_store.log_coverage(db, days)["failed_jobs"]
        coverage = ci_store.coverage(db, days, ai_analyzed=ai_analyzed, failed_jobs=failed_jobs)
    finally:
        db.close()
    write_json(LOCAL_COVERAGE_FILE, coverage)
    write_json(DOCS_COVERAGE_FILE, coverage)
    return coverage


def build_ci_metadata_from_store(
    days: int = 7,
    limit: int = 0,
    collection_strategy: str = "sqlite",
    job_detail_limit: int = 0,
    job_detail_selection: str = "sqlite_pending",
) -> dict:
    """Build static CI metadata JSON from the local SQLite store."""
    db = ci_store.conn()
    records = ci_store.export_runs_with_jobs(db, days)
    coverage = ci_store.coverage(db, days)
    db.close()
    measured_counts = _count_measured_jobs(records)
    execution_dates = _execution_dates(records)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo": REPO,
        "days": days,
        "limit": limit,
        "collection_strategy": collection_strategy,
        "run_inventory_count": coverage["run_inventory"]["total"],
        "run_inventory_by_date": coverage["run_inventory"]["by_date"],
        "job_detail_limit": job_detail_limit,
        "job_detail_selection": job_detail_selection,
        "job_detail_runs_collected": coverage["job_details"]["collected_runs"],
        "job_detail_coverage_percent": coverage["job_details"]["coverage_percent"],
        "coverage": coverage,
        "min_measured_per_pipeline": 0,
        "min_execution_days": 0,
        "measured_jobs_by_pipeline": measured_counts,
        "execution_dates": execution_dates,
        "dataset_kind": "full_ci_run_metadata",
        "runs": records,
    }


def save_ci_metadata(data: dict) -> None:
    write_json(LOCAL_CI_RUNS_FILE, data)
    write_json(DOCS_CI_RUNS_FILE, data)
    if isinstance(data.get("coverage"), dict):
        write_json(LOCAL_COVERAGE_FILE, data["coverage"])
        write_json(DOCS_COVERAGE_FILE, data["coverage"])
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
                created_at=job.get("created_at", "") or job.get("queued_at", ""),
                raw_log=job.get("raw_log", ""),
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

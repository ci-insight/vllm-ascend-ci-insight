"""Data collector: wraps gh CLI to fetch CI runs, jobs, and logs."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

from .models import CIRun, CIJob, StepResult

REPO = "vllm-project/vllm-ascend"

# Error-indicating patterns to scan in raw logs
ERROR_PATTERNS = [
    r"\berror\b",
    r"\bfail(?:ed|ure)?\b",
    r"\bexception\b",
    r"\btraceback\b",
    r"\bassert\b.*\bfail",
    r"\bkilled\b",
    r"\bpanic\b",
    r"\bfatal\b",
    r"\btimeout\b",
    r"\bcancelled\b",
    r"\baborted\b",
]


def _gh(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a gh command and return the CompletedProcess."""
    cmd = ["gh", *args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def _parse_json_output(result: subprocess.CompletedProcess) -> list[dict] | dict:
    """Parse JSON output from gh commands."""
    text = result.stdout.strip()
    if not text:
        return [] if text == "" else {}
    try:
        parsed = json.loads(text)
        return parsed
    except json.JSONDecodeError:
        return []


def list_failed_prs(limit: int = 20, state: str = "open") -> list[dict]:
    """List PRs with failed CI status."""
    result = _gh(
        "pr", "list",
        "--repo", REPO,
        "--search", "status:failure",
        "--state", state,
        "--limit", str(limit),
        "--json", "number,title,headRefName,author,url,state,createdAt",
        check=False,
    )
    if result.returncode != 0:
        print(f"Warning: gh pr list failed: {result.stderr}", file=sys.stderr)
        return []
    prs = _parse_json_output(result)
    return prs if isinstance(prs, list) else []


def list_runs_for_branch(branch: str, status: str = "failure", limit: int = 10) -> list[dict]:
    """List CI runs for a specific branch."""
    result = _gh(
        "run", "list",
        "--repo", REPO,
        "--branch", branch,
        "--status", status,
        "--limit", str(limit),
        "--json", "databaseId,name,conclusion,createdAt,headBranch,event",
        check=False,
    )
    if result.returncode != 0:
        print(f"Warning: gh run list for branch {branch} failed: {result.stderr}", file=sys.stderr)
        return []
    runs = _parse_json_output(result)
    return runs if isinstance(runs, list) else []


def get_run_jobs(run_id: int) -> list[dict]:
    """Get all jobs for a CI run, including their steps."""
    result = _gh(
        "api", f"repos/{REPO}/actions/runs/{run_id}/jobs",
        "--paginate",
        check=False,
    )
    if result.returncode != 0:
        print(f"Warning: failed to get jobs for run {run_id}: {result.stderr}", file=sys.stderr)
        return []

    data = _parse_json_output(result)
    if isinstance(data, dict):
        return data.get("jobs", [])
    return data if isinstance(data, list) else []


def get_job_log(job_id: int) -> str:
    """Fetch raw log text for a job."""
    result = _gh(
        "api", f"repos/{REPO}/actions/jobs/{job_id}/logs",
        check=False,
    )
    if result.returncode != 0:
        print(f"Warning: failed to get log for job {job_id}: {result.stderr}", file=sys.stderr)
        return ""
    return result.stdout


def get_pr_info(pr_number: int) -> dict:
    """Get PR metadata, including head branch for run lookup."""
    result = _gh(
        "pr", "view", str(pr_number),
        "--repo", REPO,
        "--json", "number,title,author,url,state,createdAt,headRefName,headRepository,labels",
        check=False,
    )
    if result.returncode != 0:
        print(f"Warning: failed to get PR #{pr_number}: {result.stderr}", file=sys.stderr)
        return {}
    data = _parse_json_output(result)
    if isinstance(data, list):
        return data[0] if data else {}
    return data if isinstance(data, dict) else {}


def _build_ci_run(run: dict, jobs: list[CIJob], pr_number: int) -> CIRun:
    return CIRun(
        run_id=run["databaseId"],
        workflow_name=run.get("name", ""),
        conclusion=run.get("conclusion", ""),
        branch=run.get("headBranch", ""),
        pr_number=pr_number,
        created_at=run.get("createdAt", ""),
        event=run.get("event", ""),
        jobs=jobs,
    )


def _build_ci_job(job: dict, fetch_log: bool = True) -> CIJob:
    steps = []
    raw = job.get("steps", [])
    if raw:
        sorted_steps = sorted(raw, key=lambda s: s.get("number", 0))
        steps = [
            StepResult(
                name=s.get("name", ""),
                conclusion=s.get("conclusion", "") or "unknown",
                number=s.get("number", 0),
            )
            for s in sorted_steps
        ]

    log = ""
    if fetch_log:
        conclusion = job.get("conclusion", "")
        if conclusion in ("failure", "cancelled", "timed_out"):
            log = get_job_log(job["id"])

    return CIJob(
        job_id=job["id"],
        job_name=job.get("name", ""),
        conclusion=job.get("conclusion", "") or "unknown",
        started_at=job.get("startedAt", ""),
        completed_at=job.get("completedAt", ""),
        steps=steps,
        raw_log=log,
    )


def find_failed_prs(days: int = 7, limit: int = 30, pr_filter: Optional[int] = None) -> list[FailureReport]:
    """Main entry point: find PRs with failed CI, collect logs, return report objects.

    Starts from PR-level search (status:failure) instead of run-level,
    which gives reliable PR-to-run association.

    Args:
        days: Look back window in days.
        limit: Max number of PRs to check.
        pr_filter: If set, only process this specific PR number.

    Returns a list of FailureReport objects ready for analysis.
    """
    from .models import FailureReport

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # If a specific PR is requested, fetch it directly
    if pr_filter is not None:
        pr_info = get_pr_info(pr_filter)
        if not pr_info:
            print(f"PR #{pr_filter} not found")
            return []
        all_prs = {pr_filter: pr_info}
    else:
        # Collect failed PRs from both open and closed/merged states
        all_prs: dict[int, dict] = {}
        for state in ("open", "merged"):
            prs = list_failed_prs(limit=limit, state=state)
            for pr in prs:
                num = pr["number"]
                if num not in all_prs:
                    all_prs[num] = pr
            if len(all_prs) >= limit:
                break

    if not all_prs:
        print("No PRs with failed CI found.")
        return []

    print(f"Found {len(all_prs)} PR(s) with failed CI status\n")

    reports: list[FailureReport] = []

    for pr_num, pr_info in all_prs.items():
        branch = pr_info.get("headRefName", "")
        if not branch:
            print(f"PR #{pr_num}: no head branch, skipping")
            continue

        print(f"PR #{pr_num}: {pr_info.get('title', '?')} (branch: {branch})")

        # Find failed runs for this PR's branch
        runs = list_runs_for_branch(branch, status="failure", limit=10)

        # Filter by date
        recent_runs = [r for r in runs if r.get("createdAt", "") >= cutoff]
        if not recent_runs:
            print(f"  No recent failed runs (within {days} days)")
            continue

        print(f"  {len(recent_runs)} recent failed run(s)")

        ci_runs: list[CIRun] = []
        for run in recent_runs:
            jobs_raw = get_run_jobs(run["databaseId"])
            failed_jobs = [j for j in jobs_raw if j.get("conclusion") in ("failure", "cancelled", "timed_out")]

            if not failed_jobs:
                continue

            print(f"    Run {run['databaseId']} ({run.get('name', '')}) -> {len(failed_jobs)} failed job(s)")

            jobs: list[CIJob] = []
            for fj in failed_jobs:
                print(f"      Job: {fj.get('name', fj['id'])} ({fj['id']})")
                job = _build_ci_job(fj, fetch_log=True)
                jobs.append(job)

            if jobs:
                ci_runs.append(_build_ci_run(run, jobs, pr_num))

        if ci_runs:
            author_data = pr_info.get("author", {}) or {}
            author_login = author_data.get("login", "unknown") if isinstance(author_data, dict) else str(author_data)

            report = FailureReport(
                pr_number=pr_num,
                pr_title=pr_info.get("title", ""),
                pr_author=author_login,
                pr_url=pr_info.get("url", f"https://github.com/{REPO}/pull/{pr_num}"),
                analyzed_at=datetime.now(timezone.utc).isoformat(),
                runs=ci_runs,
                analyses=[],
            )
            reports.append(report)

    return reports


def truncate_log(raw_log: str, head_lines: int = 200, tail_lines: int = 500) -> str:
    """Truncate a large log to a manageable size, keeping setup context and failure output."""
    if not raw_log:
        return ""

    lines = raw_log.splitlines()
    total = len(lines)

    if total <= head_lines + tail_lines:
        return raw_log

    # Also scan for lines matching error patterns throughout the middle section
    middle_start = head_lines
    middle_end = max(head_lines, total - tail_lines)
    error_lines: list[str] = []
    error_pattern = re.compile("|".join(ERROR_PATTERNS), re.IGNORECASE)

    for i in range(middle_start, middle_end):
        if error_pattern.search(lines[i]):
            # Include surrounding context (2 lines before, 3 after)
            start = max(middle_start, i - 2)
            end = min(middle_end, i + 4)
            error_lines.append(f"... (line {i + 1}) ...")
            error_lines.extend(lines[start:end])
            error_lines.append("")

    parts: list[str] = []
    parts.extend(lines[:head_lines])
    if error_lines:
        parts.append(f"\n{'='*60}")
        parts.append(f"ERROR PATTERNS FOUND (lines {middle_start + 1}-{middle_end}):")
        parts.append(f"{'='*60}\n")
        parts.extend(error_lines)
    parts.append(f"\n{'='*60}")
    parts.append(f"LOG TAIL (last {tail_lines} lines):")
    parts.append(f"{'='*60}\n")
    parts.extend(lines[-tail_lines:])

    return "\n".join(parts)

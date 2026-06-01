"""Multi-PR interference detection.

Detects when failures may be caused by interactions between concurrent PRs
rather than individual PR code changes.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import FailureReport

REPORTS_DIR = Path("reports")
INTERFERENCE_FILE = REPORTS_DIR / "interference.json"


def detect(reports: list[FailureReport], window_hours: int = 2) -> dict:
    """Detect potential interference between PRs.

    Returns dict with interference groups and evidence.
    """
    now = datetime.now(timezone.utc)

    # Collect all failed jobs with their PR and timing
    failures: list[dict] = []
    for report in reports:
        for run in report.runs:
            for job in run.jobs:
                if job.conclusion == "failure":
                    try:
                        ts = datetime.fromisoformat(run.created_at.replace("Z", "+00:00"))
                    except (ValueError, AttributeError):
                        ts = now
                    failures.append({
                        "pr_number": report.pr_number,
                        "run_id": run.run_id,
                        "workflow": run.workflow_name,
                        "job_name": job.job_name,
                        "created_at": ts.isoformat(),
                        "branch": run.branch,
                    })

    if len(failures) < 2:
        return {"generated_at": now.isoformat(), "groups": [], "summary": "Not enough data for interference detection"}

    # Rule 1: Same time window detection
    # Group failures by time window (2-hour buckets)
    time_groups: dict[str, list[dict]] = defaultdict(list)
    for f in failures:
        try:
            ts = datetime.fromisoformat(f["created_at"])
            bucket = ts.replace(minute=0, second=0, microsecond=0).isoformat()
            time_groups[bucket].append(f)
        except ValueError:
            continue

    interference_groups: list[dict] = []

    for bucket, items in sorted(time_groups.items()):
        prs_in_bucket = set(item["pr_number"] for item in items)
        if len(prs_in_bucket) >= 2:
            # Multiple PRs failing in same time window
            interference_groups.append({
                "type": "time_window",
                "severity": "medium",
                "window": bucket,
                "prs": sorted(prs_in_bucket),
                "pr_count": len(prs_in_bucket),
                "failures": len(items),
                "evidence": [
                    {"pr": item["pr_number"], "workflow": item["workflow"], "job": item["job_name"]}
                    for item in items[:10]  # limit
                ],
            })

    # Rule 2: Same test/job failing across different PRs
    job_pr_map: dict[str, set[int]] = defaultdict(set)
    for f in failures:
        job_pr_map[f["job_name"]].add(f["pr_number"])

    cross_pr_jobs = []
    for job_name, prs in job_pr_map.items():
        if len(prs) >= 2:
            cross_pr_jobs.append({
                "job_name": job_name,
                "affected_prs": sorted(prs),
                "count": len(prs),
            })

    if cross_pr_jobs:
        interference_groups.append({
            "type": "shared_failure",
            "severity": "high",
            "description": "Same job/task failing across multiple PRs",
            "shared_jobs": sorted(cross_pr_jobs, key=lambda j: j["count"], reverse=True)[:10],
        })

    # Rule 3: Version matrix inconsistency
    # Check if PRs are using different upstream vLLM versions
    versions: dict[int, str] = {}
    for report in reports:
        for run in report.runs:
            for job in run.jobs:
                if "0d4d334e" in job.job_name or "7e1b45a" in job.job_name:
                    versions[report.pr_number] = job.job_name
    if len(set(versions.values())) >= 2:
        interference_groups.append({
            "type": "version_conflict",
            "severity": "low",
            "description": "Multiple upstream vLLM versions detected across PRs",
            "pr_versions": [{"pr": pr, "version": ver} for pr, ver in versions.items()],
        })

    return {
        "generated_at": now.isoformat(),
        "total_failures": len(failures),
        "total_prs": len(set(f["pr_number"] for f in failures)),
        "groups": interference_groups,
        "summary": f"Found {len(interference_groups)} potential interference group(s) across {len(set(f['pr_number'] for f in failures))} PRs",
    }


def save_interference(data: dict):
    INTERFERENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    INTERFERENCE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    docs_path = Path("docs/reports/interference.json")
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    docs_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"  Interference: {data.get('summary', '')}")

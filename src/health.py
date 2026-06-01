"""Health score calculator for pipeline types.

Computes 0-100 health scores per pipeline type (pr_e2e/nightly/weekly/other)
based on success rate, trend, recency, and consecutive failure penalty.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .models import FailureReport

REPORTS_DIR = Path("reports")
HEALTH_FILE = REPORTS_DIR / "health.json"

RATING_THRESHOLDS = [
    (80, "good", "#16a34a"),
    (60, "fair", "#ca8a04"),
    (0, "danger", "#dc2626"),
]


def _rating(score: float) -> tuple[str, str]:
    for threshold, name, color in RATING_THRESHOLDS:
        if score >= threshold:
            return name, color
    return "danger", "#dc2626"


def compute_health(reports: list[FailureReport]) -> dict:
    """Compute health data from collected reports.

    Returns a dict suitable for JSON serialization and dashboard consumption.
    """
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)
    two_days_ago = now - timedelta(hours=48)
    seven_days_ago = now - timedelta(days=7)

    # Group jobs by pipeline_type
    by_type: dict[str, list[dict]] = defaultdict(list)

    for report in reports:
        for run in report.runs:
            for job in run.jobs:
                ptype = run.pipeline_type or "other"
                try:
                    created = datetime.fromisoformat(run.created_at.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    created = now
                by_type[ptype].append({
                    "workflow": run.workflow_name,
                    "job_name": job.job_name,
                    "conclusion": job.conclusion,
                    "created_at": created.isoformat(),
                    "run_id": run.run_id,
                })

    # Compute scores per pipeline type
    pipelines: dict[str, dict] = {}
    overall_total = 0
    overall_success = 0
    consecutive_map: dict[str, int] = {}

    for ptype, jobs in sorted(by_type.items()):
        total = len(jobs)
        success = sum(1 for j in jobs if j["conclusion"] == "success")
        failure = sum(1 for j in jobs if j["conclusion"] == "failure")
        success_rate = success / total if total > 0 else 0

        # Recent stats
        recent_24h = [j for j in jobs if j["created_at"] >= day_ago.isoformat()]
        recent_48h = [j for j in jobs if j["created_at"] >= two_days_ago.isoformat()]
        recent_7d = [j for j in jobs if j["created_at"] >= seven_days_ago.isoformat()]

        recent_failures_24h = sum(1 for j in recent_24h if j["conclusion"] == "failure")
        recent_failures_48h = sum(1 for j in recent_48h if j["conclusion"] == "failure")

        # Trend: compare recent (last 3 days) vs earlier (days 4-7)
        recent_3d_success = sum(1 for j in recent_24h + recent_48h if j["conclusion"] == "success")
        recent_3d_total = len(recent_24h) + len(recent_48h)
        older_7d = [j for j in recent_7d if j["created_at"] < two_days_ago.isoformat()]
        older_success = sum(1 for j in older_7d if j["conclusion"] == "success")
        older_total = len(older_7d)

        recent_rate = recent_3d_success / recent_3d_total if recent_3d_total > 0 else 0
        older_rate = older_success / older_total if older_total > 0 else recent_rate

        if recent_rate > older_rate + 0.05:
            trend_bonus = 20
            trend_dir = "up"
        elif recent_rate > older_rate - 0.05:
            trend_bonus = 10
            trend_dir = "flat"
        else:
            trend_bonus = 0
            trend_dir = "down"

        # Recency bonus
        if recent_failures_24h == 0 and recent_24h:
            recency_bonus = 20
        elif recent_failures_48h == 0 and recent_48h:
            recency_bonus = 10
        else:
            recency_bonus = 0

        # Consecutive failure penalty (per workflow)
        consecutive_penalty = 0
        consec_details: list[dict] = []
        wf_jobs = defaultdict(list)
        for j in jobs:
            wf_jobs[j["workflow"]].append(j)
        for wf, wjobs in wf_jobs.items():
            sorted_jobs = sorted(wjobs, key=lambda j: j["created_at"], reverse=True)
            streak = 0
            for j in sorted_jobs:
                if j["conclusion"] == "failure":
                    streak += 1
                else:
                    break
            if streak >= 2:
                consecutive_map[wf] = streak
                penalty = min(streak * 15, 30)
                consecutive_penalty += penalty
                consec_details.append({
                    "workflow": wf,
                    "streak": streak,
                    "penalty": penalty,
                })

        # Health score
        health_score = max(0, min(100,
            success_rate * 60 + trend_bonus + recency_bonus - consecutive_penalty
        ))
        rating_name, rating_color = _rating(health_score)
        health_score = round(health_score)

        # Daily aggregates (for trend charts)
        daily: dict[str, dict] = {}
        for j in recent_7d:
            day = j["created_at"][:10]
            if day not in daily:
                daily[day] = {"total": 0, "success": 0, "failure": 0}
            daily[day]["total"] += 1
            if j["conclusion"] == "success":
                daily[day]["success"] += 1
            elif j["conclusion"] == "failure":
                daily[day]["failure"] += 1

        daily_trend = []
        for day in sorted(daily.keys()):
            d = daily[day]
            daily_trend.append({
                "date": day,
                "total": d["total"],
                "success": d["success"],
                "failure": d["failure"],
                "success_rate": round(d["success"] / d["total"] * 100) if d["total"] > 0 else 0,
                "health": round(max(0, min(100,
                    (d["success"] / d["total"] * 60) if d["total"] > 0 else 0 + trend_bonus * 0.3
                ))),
            })

        pipelines[ptype] = {
            "type": ptype,
            "total": total,
            "success": success,
            "failure": failure,
            "success_rate": round(success_rate * 100),
            "health_score": health_score,
            "rating": rating_name,
            "rating_color": rating_color,
            "trend": trend_dir,
            "consecutive_details": consec_details,
            "recent_24h_total": len(recent_24h),
            "recent_24h_failures": recent_failures_24h,
            "daily_trend": daily_trend,
        }

        overall_total += total
        overall_success += success

    return {
        "generated_at": now.isoformat(),
        "overall": {
            "total": overall_total,
            "success": overall_success,
            "success_rate": round(overall_success / overall_total * 100) if overall_total > 0 else 0,
            "health_score": round(sum(p["health_score"] for p in pipelines.values()) / max(1, len(pipelines))),
        },
        "pipelines": pipelines,
        "consecutive_failures": {k: v for k, v in consecutive_map.items() if v >= 2},
    }


def save_health(data: dict):
    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    docs_path = Path("docs/reports/health.json")
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    docs_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"  Health data: {HEALTH_FILE}")

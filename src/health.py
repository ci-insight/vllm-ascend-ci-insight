"""Health score calculator for pipeline types.

Computes 0-100 health scores per pipeline type (pr_e2e/nightly/weekly/other)
based on success rate, trend, recency, and consecutive failure penalty.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .models import FailureReport
from .storage import DOCS_REPORTS_DIR, LOCAL_REPORTS_DIR, load_rules, write_json

REPORTS_DIR = LOCAL_REPORTS_DIR
HEALTH_FILE = REPORTS_DIR / "health.json"
SUCCESS_CONCLUSIONS = {"success"}
FAILURE_CONCLUSIONS = {"failure", "timed_out"}
NEUTRAL_CONCLUSIONS = {"skipped", "cancelled", "neutral"}


def _run_conclusion(run_jobs: list[dict], fallback: str = "") -> str:
    """Collapse a workflow run into one measured conclusion."""
    conclusions = {job["conclusion"] for job in run_jobs}
    if conclusions & FAILURE_CONCLUSIONS:
        return "failure"
    if conclusions & SUCCESS_CONCLUSIONS:
        return "success"
    if fallback in FAILURE_CONCLUSIONS:
        return "failure"
    if fallback in SUCCESS_CONCLUSIONS:
        return "success"
    return "neutral"


def _load_rating_thresholds() -> list[tuple[int, str, str]]:
    data = load_rules()
    if data:
        return [(t["min"], t["rating"], t["color"]) for t in data.get("health_rating_thresholds", [])]
    return [(80, "good", "#16a34a"), (60, "fair", "#ca8a04"), (0, "danger", "#dc2626")]

RATING_THRESHOLDS = _load_rating_thresholds()


def _rating(score: float) -> tuple[str, str]:
    for threshold, name, color in RATING_THRESHOLDS:
        if score >= threshold:
            return name, color
    return "danger", "#dc2626"


def compute_health(reports: list[FailureReport], *, complete_sample: bool = True) -> dict:
    """Compute health data from collected reports.

    Returns a dict suitable for JSON serialization and dashboard consumption.
    Set complete_sample=False when reports come from failed PR/run collection
    only; in that mode success rates are descriptive for the observed failure
    sample and health scores/alerts must not be treated as global CI health.
    """
    now = datetime.now(timezone.utc)
    one_day_ago = now - timedelta(hours=24)
    two_days_ago = now - timedelta(hours=48)
    three_days_ago = now - timedelta(days=3)
    seven_days_ago = now - timedelta(days=7)

    # Group jobs by pipeline_type, and workflow runs by pipeline_type for
    # run-level signals such as consecutive failure streaks.
    by_type: dict[str, list[dict]] = defaultdict(list)
    runs_by_type: dict[str, list[dict]] = defaultdict(list)
    seen_jobs: set[int] = set()
    seen_runs: set[tuple[str, int]] = set()

    for report in reports:
        for run in report.runs:
            ptype = run.pipeline_type or "other"
            try:
                created = datetime.fromisoformat(run.created_at.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                created = now
            run_jobs: list[dict] = []
            for job in run.jobs:
                if job.job_id in seen_jobs:
                    continue
                seen_jobs.add(job.job_id)
                job_record = {
                    "workflow": run.workflow_name,
                    "job_name": job.job_name,
                    "conclusion": job.conclusion,
                    "created_at": created.isoformat(),
                    "run_id": run.run_id,
                }
                by_type[ptype].append(job_record)
                run_jobs.append(job_record)
            run_key = (run.workflow_name, run.run_id)
            if run_jobs and run_key not in seen_runs:
                seen_runs.add(run_key)
                runs_by_type[ptype].append({
                    "workflow": run.workflow_name,
                    "conclusion": _run_conclusion(run_jobs, run.conclusion),
                    "created_at": created.isoformat(),
                    "run_id": run.run_id,
                })

    # Compute scores per pipeline type
    pipelines: dict[str, dict] = {}
    overall_total = 0
    overall_measured_total = 0
    overall_success = 0
    consecutive_map: dict[str, int] = {}

    for ptype, jobs in sorted(by_type.items()):
        total = len(jobs)
        success = sum(1 for j in jobs if j["conclusion"] in SUCCESS_CONCLUSIONS)
        failure = sum(1 for j in jobs if j["conclusion"] in FAILURE_CONCLUSIONS)
        skipped = sum(1 for j in jobs if j["conclusion"] == "skipped")
        cancelled = sum(1 for j in jobs if j["conclusion"] == "cancelled")
        other = total - success - failure - skipped - cancelled
        measured_total = success + failure
        success_rate = success / measured_total if measured_total > 0 else 0

        # Recent stats
        recent_24h = [j for j in jobs if j["created_at"] >= one_day_ago.isoformat()]
        recent_48h = [j for j in jobs if j["created_at"] >= two_days_ago.isoformat()]
        recent_3d = [j for j in jobs if j["created_at"] >= three_days_ago.isoformat()]
        recent_7d = [j for j in jobs if j["created_at"] >= seven_days_ago.isoformat()]

        recent_failures_24h = sum(1 for j in recent_24h if j["conclusion"] in FAILURE_CONCLUSIONS)
        recent_failures_48h = sum(1 for j in recent_48h if j["conclusion"] in FAILURE_CONCLUSIONS)

        # Trend: compare recent (last 3 days) vs earlier (days 4-7)
        recent_3d_success = sum(1 for j in recent_3d if j["conclusion"] in SUCCESS_CONCLUSIONS)
        recent_3d_failure = sum(1 for j in recent_3d if j["conclusion"] in FAILURE_CONCLUSIONS)
        recent_3d_total = recent_3d_success + recent_3d_failure
        older_7d = [j for j in recent_7d if j["created_at"] < three_days_ago.isoformat()]
        older_success = sum(1 for j in older_7d if j["conclusion"] in SUCCESS_CONCLUSIONS)
        older_failure = sum(1 for j in older_7d if j["conclusion"] in FAILURE_CONCLUSIONS)
        older_total = older_success + older_failure

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

        # Consecutive failure penalty (per workflow run). This is only a true
        # streak when the input includes successful runs too.
        consecutive_penalty = 0
        consec_details: list[dict] = []
        if complete_sample:
            wf_runs = defaultdict(list)
            for run_record in runs_by_type.get(ptype, []):
                wf_runs[run_record["workflow"]].append(run_record)
            for wf, wruns in wf_runs.items():
                sorted_runs = sorted(wruns, key=lambda item: (item["created_at"], item["run_id"]), reverse=True)
                streak = 0
                for run_record in sorted_runs:
                    if run_record["conclusion"] in FAILURE_CONCLUSIONS:
                        streak += 1
                    elif run_record["conclusion"] in SUCCESS_CONCLUSIONS:
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
        if measured_total == 0:
            health_score = None
            rating_name, rating_color = "insufficient_data", "#8b949e"
        elif complete_sample:
            health_score = max(0, min(100,
                success_rate * 60 + trend_bonus + recency_bonus - consecutive_penalty
            ))
            rating_name, rating_color = _rating(health_score)
            health_score = round(health_score)
        else:
            rating_name, rating_color = "insufficient_data", "#8b949e"
            health_score = None

        # Daily aggregates (for trend charts)
        daily: dict[str, dict] = {}
        for j in recent_7d:
            day = j["created_at"][:10]
            if day not in daily:
                daily[day] = {"total": 0, "measured_total": 0, "success": 0, "failure": 0, "skipped": 0, "cancelled": 0, "other": 0}
            daily[day]["total"] += 1
            if j["conclusion"] in SUCCESS_CONCLUSIONS:
                daily[day]["success"] += 1
                daily[day]["measured_total"] += 1
            elif j["conclusion"] in FAILURE_CONCLUSIONS:
                daily[day]["failure"] += 1
                daily[day]["measured_total"] += 1
            elif j["conclusion"] == "skipped":
                daily[day]["skipped"] += 1
            elif j["conclusion"] == "cancelled":
                daily[day]["cancelled"] += 1
            else:
                daily[day]["other"] += 1

        daily_trend = []
        for day in sorted(daily.keys()):
            d = daily[day]
            day_rate = d["success"] / d["measured_total"] if d["measured_total"] > 0 else 0
            daily_trend.append({
                "date": day,
                "total": d["total"],
                "measured_total": d["measured_total"],
                "success": d["success"],
                "failure": d["failure"],
                "skipped": d["skipped"],
                "cancelled": d["cancelled"],
                "other": d["other"],
                "success_rate": round(day_rate * 100),
                "health": round(max(0, min(100,
                    day_rate * 60 + trend_bonus * 0.3
                ))),
            })

        pipelines[ptype] = {
            "type": ptype,
            "total": total,
            "measured_total": measured_total,
            "success": success,
            "failure": failure,
            "skipped": skipped,
            "cancelled": cancelled,
            "other": other,
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
        overall_measured_total += measured_total
        overall_success += success

    scored = [p["health_score"] for p in pipelines.values() if p["health_score"] is not None]
    return {
        "generated_at": now.isoformat(),
        "data_quality": {
            "complete_success_sample": complete_sample,
            "sample_kind": "complete_ci_runs" if complete_sample else "failure_reports_only",
            "warning": "" if complete_sample else (
                "This dataset is built from failed PR/run reports only. "
                "Do not interpret success rates, streaks, or health scores as global CI health."
            ),
        },
        "overall": {
            "total": overall_total,
            "measured_total": overall_measured_total,
            "success": overall_success,
            "success_rate": round(overall_success / overall_measured_total * 100) if overall_measured_total > 0 else 0,
            "health_score": round(sum(scored) / len(scored)) if scored else None,
        },
        "pipelines": pipelines,
        "consecutive_failures": {k: v for k, v in consecutive_map.items() if v >= 2},
    }


def save_health(data: dict):
    write_json(HEALTH_FILE, data)
    docs_path = DOCS_REPORTS_DIR / "health.json"
    write_json(docs_path, data)
    print(f"  Health data: {HEALTH_FILE}")

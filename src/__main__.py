"""Main entry point for ascend-ci-insight.

Usage:
    python -m src [--days 7] [--limit 20]
    python -m src --health         # Only health/alert/interference (no re-collect)
    python -m src --no-analyze     # Only collect data, skip analysis
    python -m src --no-notify      # Skip notification sending
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .collector import find_failed_prs
from .analyzer import analyze_report, AnalysisCache, set_analysis_lang
from .reporter import generate_report, update_index
from .health import compute_health, save_health
from .alert import evaluate, save_alerts
from .notify import notify_alerts
from .interference import detect as detect_interference, save_interference


def main():
    parser = argparse.ArgumentParser(
        description="vllm-ascend CI Insight - pipeline failure analysis"
    )
    parser.add_argument("--days", type=int, default=7, help="Look back N days for failed runs")
    parser.add_argument("--limit", type=int, default=30, help="Max failed runs to fetch")
    parser.add_argument("--pr", type=int, help="Analyze a specific PR only")
    parser.add_argument("--analyze-only", action="store_true", help="Re-analyze cached raw data")
    parser.add_argument("--no-analyze", action="store_true", help="Only collect data, skip analysis")
    parser.add_argument("--health", action="store_true", help="Only compute health/alert/interference")
    parser.add_argument("--no-notify", action="store_true", help="Skip notification sending")
    parser.add_argument("--lang", choices=["zh", "en"], default="en", help="Analysis output language (default: en)")
    args = parser.parse_args()

    set_analysis_lang(args.lang)

    print("=" * 60)
    print("  vllm-ascend CI Insight")
    print("=" * 60)

    if args.health:
        # Health-only mode: reload existing reports and compute metrics
        print("  Health-only mode: computing from existing reports")
        reports = _load_existing_reports()
        if not reports:
            print("No existing reports found. Run without --health first.")
            return
    else:
        print(f"  Looking back {args.days} days, max {args.limit} runs, lang={args.lang}")
        print()

        # Phase 1: Collect
        if not args.analyze_only:
            print("[1/4] Collecting CI failure data...")
            reports = find_failed_prs(days=args.days, limit=args.limit, pr_filter=args.pr)
            if not reports:
                print("No failed PRs found. Good news!")
                return
            for report in reports:
                generate_report(report)
        else:
            print("[1/4] Skipping collection (--analyze-only)")
            reports = _load_existing_reports()
            if not reports:
                print("No cached reports to analyze.")
                return

        print(f"\nFound {len(reports)} PR(s) with CI failures\n")

        # Phase 2: Analyze
        if not args.no_analyze:
            print("[2/4] Analyzing with Claude CLI...")
            cache = AnalysisCache()
            for i, report in enumerate(reports):
                print(f"\nAnalyzing PR #{report.pr_number} ({i + 1}/{len(reports)})")
                analyze_report(report, cache=cache)
        else:
            print("[2/4] Skipping analysis (--no-analyze)")

        # Phase 3: Report
        print("\n[3/4] Generating reports...")
        valid_reports = []
        skipped = 0
        for report in reports:
            has_valid = any(a.confidence > 0 for a in report.analyses) or args.no_analyze
            if has_valid:
                generate_report(report)
                valid_reports.append(report)
            else:
                skipped += 1
                print(f"  Skipping PR #{report.pr_number}: all analyses failed (rate limited)")

        if valid_reports:
            update_index(valid_reports)
        else:
            print("  No valid reports to index.")

    # Phase 4: Health + Alerts + Interference + Notify
    print("\n[4/4] Computing health scores, alerts, interference...")

    health_data = compute_health(reports if reports else [])
    save_health(health_data)

    alerts = evaluate(health_data)
    save_alerts(alerts)

    interference_data = detect_interference(reports if reports else [])
    save_interference(interference_data)

    if alerts and not args.no_notify:
        print(f"\n  Sending notifications for {len(alerts)} alert(s)...")
        sent = notify_alerts(alerts)
        print(f"  Sent {sent} notification(s)")

    # Summary
    print()
    print("=" * 60)
    pipelines = health_data.get("pipelines", {})
    for ptype, pdata in sorted(pipelines.items()):
        score = pdata["health_score"]
        rating = pdata["rating"]
        print(f"  {ptype:12s}: score={score:3d} ({rating})  SR={pdata['success_rate']}%  ({pdata['success']}/{pdata['total']})")
    if alerts:
        print(f"  Alerts: {len(alerts)} triggered")
    print(f"  Reports: reports/")
    print(f"  Dashboard: open docs/index.html")
    print("=" * 60)


def _load_existing_reports():
    """Load reports from existing report files."""
    from .models import FailureReport
    from .collector import classify_pipeline
    import json

    reports: list[FailureReport] = []
    reports_dir = Path("reports")
    if not reports_dir.exists():
        return reports

    for date_dir in sorted(reports_dir.iterdir(), reverse=True):
        if not date_dir.is_dir():
            continue
        for f in sorted(date_dir.glob("pr-*.json")):
            if f.name == "index.json":
                continue
            try:
                data = json.loads(f.read_text())
                report = FailureReport(
                    pr_number=data["pr_number"],
                    pr_title=data.get("pr_title", ""),
                    pr_author=data.get("pr_author", ""),
                    pr_url=data.get("pr_url", ""),
                    analyzed_at=data.get("analyzed_at", ""),
                    runs=[],
                    analyses=[],
                )
                # Reconstruct runs
                from .models import CIRun, CIJob, StepResult
                for r in data.get("runs", []):
                    jobs = []
                    for j in r.get("jobs", []):
                        jobs.append(CIJob(
                            job_id=j["job_id"], job_name=j["job_name"],
                            conclusion=j.get("conclusion", ""),
                            started_at=j.get("started_at", ""),
                            completed_at=j.get("completed_at", ""),
                            steps=[], raw_log="",
                        ))
                    wf_name = r.get("workflow_name", "")
                    pt = r.get("pipeline_type") or classify_pipeline(wf_name)
                    report.runs.append(CIRun(
                        run_id=r["run_id"], workflow_name=wf_name,
                        conclusion=r.get("conclusion", ""), branch=r.get("branch", ""),
                        pr_number=r.get("pr_number"), created_at=r.get("created_at", ""),
                        event=r.get("event", ""),
                        pipeline_type=pt,
                        jobs=jobs,
                    ))
                reports.append(report)
            except Exception:
                continue
    return reports


if __name__ == "__main__":
    main()

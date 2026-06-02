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
from .aggregator import save_snapshot
from .storage import load_reports
from .ci_metadata import collect_ci_metadata, save_ci_metadata, load_ci_metadata, metadata_to_reports
from .static_sync import import_static_reports


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
    parser.add_argument("--refresh-ci-metrics", action="store_true", help="Collect full lightweight CI run/job metadata for health metrics")
    parser.add_argument("--metrics-limit", type=int, default=200, help="Max workflow runs to fetch for CI metrics")
    parser.add_argument(
        "--metrics-min-measured-per-pipeline",
        type=int,
        default=0,
        help="Stop CI metadata collection after each core pipeline has at least N success/failure jobs (0 disables)",
    )
    parser.add_argument("--no-notify", action="store_true", help="Skip notification sending")
    parser.add_argument("--lang", choices=["zh", "en"], default="en", help="Analysis output language (default: en)")
    parser.add_argument(
        "--import-static",
        nargs="?",
        const="docs/reports",
        metavar="DIR",
        help="Import static dashboard JSON artifacts into local SQLite and exit (default: docs/reports)",
    )
    args = parser.parse_args()

    set_analysis_lang(args.lang)

    print("=" * 60)
    print("  vllm-ascend CI Insight")
    print("=" * 60)

    if args.import_static:
        print(f"  Importing static reports from {args.import_static}")
        result = import_static_reports(args.import_static)
        print(
            "  Imported: "
            f"{result['daily_snapshots']} daily snapshot row(s), "
            f"{result['job_records']} job record(s)"
        )
        print(f"  SQLite: data/metrics.db")
        return

    if args.health:
        # Health-only mode: reload existing reports and compute metrics
        print("  Health-only mode: computing from existing reports")
        reports = _load_existing_reports()
        if args.refresh_ci_metrics:
            print(
                "  Refreshing full CI metadata: "
                f"days={args.days}, limit={args.metrics_limit}, "
                f"min_measured={args.metrics_min_measured_per_pipeline}"
            )
            ci_metadata = collect_ci_metadata(
                days=args.days,
                limit=args.metrics_limit,
                min_measured_per_pipeline=args.metrics_min_measured_per_pipeline,
            )
            save_ci_metadata(ci_metadata)
        if not reports and not load_ci_metadata():
            print("No existing reports or CI metadata found. Run with --refresh-ci-metrics first.")
            return
    else:
        print(f"  Looking back {args.days} days, max {args.limit} runs, lang={args.lang}")
        print()
        if args.refresh_ci_metrics:
            print("[0/4] Collecting full CI metadata...")
            ci_metadata = collect_ci_metadata(
                days=args.days,
                limit=args.metrics_limit,
                min_measured_per_pipeline=args.metrics_min_measured_per_pipeline,
            )
            save_ci_metadata(ci_metadata)

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

    ci_metadata = load_ci_metadata()
    if ci_metadata:
        health_reports = metadata_to_reports(ci_metadata)
        health_data = compute_health(health_reports, complete_sample=True)
    else:
        health_reports = reports if reports else []
        health_data = compute_health(health_reports, complete_sample=False)
    save_health(health_data)

    alerts = evaluate(health_data)
    save_alerts(alerts)

    interference_data = detect_interference(reports if reports else [])
    save_interference(interference_data)

    # Save to SQLite aggregator + static JSON for long-term trends
    save_snapshot(health_data, health_reports)

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
        measured_total = pdata.get("measured_total", pdata.get("total", 0))
        score_text = "n/a" if score is None else f"{score:3d}"
        sr_text = "no measured success/failure jobs" if measured_total == 0 else f"SR={pdata['success_rate']}% ({pdata['success']}/{measured_total} measured)"
        print(f"  {ptype:12s}: score={score_text} ({rating})  {sr_text}, {pdata['total']} total")
    if alerts:
        print(f"  Alerts: {len(alerts)} active")
    print(f"  Reports: reports/")
    print(f"  Dashboard: open docs/index.html")
    print("=" * 60)


def _load_existing_reports():
    """Load reports from existing report files."""
    return load_reports()


if __name__ == "__main__":
    main()

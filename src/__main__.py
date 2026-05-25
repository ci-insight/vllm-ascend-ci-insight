"""Main entry point for ascend-ci-insight.

Usage:
    python -m src [--days 7] [--limit 20]
    python -m src --analyze-only   # re-analyze cached reports
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .collector import find_failed_prs
from .analyzer import analyze_report, AnalysisCache, set_analysis_lang
from .reporter import generate_report, update_index


def main():
    parser = argparse.ArgumentParser(
        description="vllm-ascend CI Insight - pipeline failure analysis"
    )
    parser.add_argument("--days", type=int, default=7, help="Look back N days for failed runs")
    parser.add_argument("--limit", type=int, default=30, help="Max failed runs to fetch")
    parser.add_argument("--pr", type=int, help="Analyze a specific PR only")
    parser.add_argument("--analyze-only", action="store_true", help="Re-analyze cached raw data")
    parser.add_argument("--no-analyze", action="store_true", help="Only collect data, skip analysis")
    parser.add_argument("--lang", choices=["zh", "en"], default="en", help="Analysis output language (default: en)")
    args = parser.parse_args()

    set_analysis_lang(args.lang)

    print("=" * 60)
    print("  vllm-ascend CI Insight")
    print("=" * 60)
    print(f"  Looking back {args.days} days, max {args.limit} runs, lang={args.lang}")
    print()

    # Phase 1: Collect
    if not args.analyze_only:
        print("[1/3] Collecting CI failure data...")
        reports = find_failed_prs(days=args.days, limit=args.limit, pr_filter=args.pr)
        if not reports:
            print("No failed PRs found. Good news!")
            return

        # Save raw reports before analysis (as interim cache)
        for report in reports:
            generate_report(report)
    else:
        print("[1/3] Skipping collection (--analyze-only)")
        # TODO: load existing reports from reports/ dir
        reports = []
        if not reports:
            print("No cached reports to analyze.")
            return

    print(f"\nFound {len(reports)} PR(s) with CI failures\n")

    # Phase 2: Analyze
    if not args.no_analyze:
        print("[2/3] Analyzing with Claude CLI...")
        cache = AnalysisCache()
        for i, report in enumerate(reports):
            print(f"\nAnalyzing PR #{report.pr_number} ({i + 1}/{len(reports)})")
            analyze_report(report, cache=cache)
    else:
        print("[2/3] Skipping analysis (--no-analyze)")

    # Phase 3: Report (skip reports with all-fallback analyses)
    print("\n[3/3] Generating reports...")
    valid_reports = []
    skipped = 0
    for report in reports:
        has_valid = any(a.confidence > 0 for a in report.analyses)
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

    print()
    print("=" * 60)
    print(f"  Done! {len(valid_reports)} PR(s) analyzed, {skipped} skipped.")
    print(f"  Reports: reports/")
    print(f"  Dashboard: open dashboard/index.html")
    print("=" * 60)


if __name__ == "__main__":
    main()

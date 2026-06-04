from src import analyzer
from src.models import CIJob, CIRun, FailureReport


def test_analyze_report_skips_non_failed_jobs(monkeypatch, tmp_path):
    calls = []

    def fake_claude(text):
        calls.append(text)
        return {
            "error_snippets": ["boom"],
            "root_cause": "failure root cause",
            "related_files": [],
            "fix_suggestions": [],
            "severity": "high",
            "confidence": 90,
        }

    monkeypatch.setattr(analyzer, "_claude_analyze", fake_claude)
    cache = analyzer.AnalysisCache(cache_path=tmp_path / "analysis-cache.json")

    report = FailureReport(
        pr_number=1,
        pr_title="demo",
        pr_author="",
        pr_url="",
        analyzed_at="2026-06-04T00:00:00Z",
        runs=[
            CIRun(
                run_id=1,
                workflow_name="E2E-Light",
                conclusion="failure",
                branch="main",
                pr_number=1,
                created_at="2026-06-04T00:00:00Z",
                event="pull_request",
                jobs=[
                    CIJob(1, "success job", "success", "", "", raw_log="success log"),
                    CIJob(2, "skipped job", "skipped", "", "", raw_log="skipped log"),
                    CIJob(3, "failed job", "failure", "", "", raw_log="failed log"),
                ],
            )
        ],
    )

    analyzer.analyze_report(report, cache=cache)

    assert len(calls) == 1
    assert len(report.analyses) == 1
    assert report.analyses[0].job_id == 3

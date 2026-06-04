from datetime import datetime, timezone

from src import reporter
from src.models import FailureReport


def test_update_index_prints_persist_reminder(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(reporter, "OUTPUT_DIR", tmp_path / "reports")
    monkeypatch.setattr(reporter, "DOCS_DIR", tmp_path / "docs" / "reports")
    monkeypatch.setattr(reporter, "INDEX_FILE", tmp_path / "reports" / "index.json")
    monkeypatch.setattr(reporter, "current_date_str", lambda: "2026-06-04")

    report = FailureReport(
        pr_number=9972,
        pr_title="example",
        pr_author="",
        pr_url="https://example.test/pr/9972",
        analyzed_at=datetime.now(timezone.utc).isoformat(),
    )

    reporter.update_index([report])

    out = capsys.readouterr().out
    assert "AI analysis reports are only durable after committing docs/reports" in out
    assert "git add docs/reports/2026-06-04/" in out
    assert "git commit -m \"Add 2026-06-04 AI analysis reports\"" in out

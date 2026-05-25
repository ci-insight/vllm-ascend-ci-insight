from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class StepResult:
    name: str
    conclusion: str  # success, failure, skipped, cancelled
    number: int


@dataclass
class CIJob:
    job_id: int
    job_name: str
    conclusion: str
    started_at: str
    completed_at: str
    steps: list[StepResult] = field(default_factory=list)
    raw_log: str = ""


@dataclass
class CIRun:
    run_id: int
    workflow_name: str
    conclusion: str
    branch: str
    pr_number: Optional[int]
    created_at: str
    event: str
    jobs: list[CIJob] = field(default_factory=list)


@dataclass
class JobAnalysis:
    job_name: str
    job_id: int
    conclusion: str
    error_snippets: list[str] = field(default_factory=list)
    root_cause: str = ""
    related_files: list[str] = field(default_factory=list)
    fix_suggestions: list[str] = field(default_factory=list)
    severity: str = "unknown"  # critical, high, medium, low, unknown
    confidence: int = 0


@dataclass
class FailureReport:
    pr_number: int
    pr_title: str
    pr_author: str
    pr_url: str
    analyzed_at: str
    runs: list[CIRun] = field(default_factory=list)
    analyses: list[JobAnalysis] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


@dataclass
class ReportIndex:
    """Index of all reports for the dashboard."""
    generated_at: str
    reports: list[ReportEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


@dataclass
class ReportEntry:
    pr_number: int
    pr_title: str
    json_path: str
    md_path: str
    analyzed_at: str
    failed_job_count: int
    top_severity: str

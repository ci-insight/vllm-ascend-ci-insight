"""Shared storage helpers for reports, dashboard data, and JSON files."""

from __future__ import annotations

import json
import re
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import CIJob, CIRun, FailureReport, JobAnalysis, StepResult

ROOT = Path(__file__).resolve().parents[1]
LOCAL_REPORTS_DIR = ROOT / "reports"
DOCS_DIR = ROOT / "docs"
DOCS_REPORTS_DIR = DOCS_DIR / "reports"
CONFIG_DIR = ROOT / "config"
RULES_FILE = CONFIG_DIR / "rules.json"


def read_json(path: Path | str, default: Any = None) -> Any:
    """Read UTF-8 JSON, returning default when the file is missing or invalid."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def write_json(path: Path | str, data: Any) -> Path:
    """Write pretty UTF-8 JSON and return the path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def load_rules() -> dict:
    return read_json(RULES_FILE, default={}) or {}


def classify_pipeline_name(workflow_name: str) -> str:
    for ptype, cfg in load_rules().get("pipeline_types", {}).items():
        for pattern in cfg.get("patterns", []):
            if re.search(pattern, workflow_name):
                return ptype
    return "other"


def _has_report_files(path: Path) -> bool:
    return path.exists() and any(path.rglob("pr-*.json"))


def source_reports_dir() -> Path:
    """Return the best available source for existing report data.

    The dashboard consumes docs/reports. Local reports/ is useful during live
    runs, but a fresh clone often only has docs/reports checked in.
    """
    if _has_report_files(LOCAL_REPORTS_DIR):
        return LOCAL_REPORTS_DIR
    return DOCS_REPORTS_DIR


def iter_report_json_paths(base_dir: Path | None = None) -> list[Path]:
    base = base_dir or source_reports_dir()
    if not base.exists():
        return []
    return sorted(
        (p for p in base.rglob("pr-*.json") if p.is_file()),
        key=lambda p: (p.parent.name, p.name),
        reverse=True,
    )


def dashboard_json_path_for(pr_number: int, date_str: str) -> str:
    return f"reports/{date_str}/pr-{pr_number}.json"


def dashboard_md_path_for(pr_number: int, date_str: str) -> str:
    return f"reports/{date_str}/pr-{pr_number}.md"


def resolve_dashboard_path(path_str: str) -> Path:
    """Resolve a dashboard-relative path to the checked-in docs location."""
    path = Path(path_str)
    if path.is_absolute():
        return path
    if path.parts and path.parts[0] == "reports":
        return DOCS_DIR / path
    return ROOT / path


def current_date_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _known_kwargs(cls, data: dict) -> dict:
    names = {field.name for field in fields(cls)}
    return {key: value for key, value in data.items() if key in names}


def step_from_dict(data: dict) -> StepResult:
    return StepResult(**_known_kwargs(StepResult, data))


def job_from_dict(data: dict) -> CIJob:
    kwargs = _known_kwargs(CIJob, data)
    kwargs["steps"] = [step_from_dict(item) for item in data.get("steps", [])]
    return CIJob(**kwargs)


def run_from_dict(data: dict) -> CIRun:
    kwargs = _known_kwargs(CIRun, data)
    kwargs["jobs"] = [job_from_dict(item) for item in data.get("jobs", [])]
    if not kwargs.get("pipeline_type"):
        kwargs["pipeline_type"] = classify_pipeline_name(kwargs.get("workflow_name", ""))
    return CIRun(**kwargs)


def analysis_from_dict(data: dict) -> JobAnalysis:
    return JobAnalysis(**_known_kwargs(JobAnalysis, data))


def report_from_dict(data: dict) -> FailureReport:
    kwargs = _known_kwargs(FailureReport, data)
    kwargs["runs"] = [run_from_dict(item) for item in data.get("runs", [])]
    kwargs["analyses"] = [analysis_from_dict(item) for item in data.get("analyses", [])]
    return FailureReport(**kwargs)


def load_reports(paths: Iterable[Path] | None = None) -> list[FailureReport]:
    reports: list[FailureReport] = []
    for path in paths or iter_report_json_paths():
        data = read_json(path, default=None)
        if isinstance(data, dict):
            try:
                reports.append(report_from_dict(data))
            except (KeyError, TypeError, ValueError):
                continue
    return reports

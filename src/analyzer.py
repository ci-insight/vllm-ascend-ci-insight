"""Log analyzer: uses Claude CLI to intelligently analyze CI failure logs."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from .collector import truncate_log
from .models import FailureReport, JobAnalysis, CIJob

# Maximum characters to send to claude for analysis (roughly 30K tokens)
MAX_LOG_CHARS = 60000

# Delay between Claude CLI calls to avoid rate limiting (seconds)
CALL_DELAY = 2.0

# Max retries for failed Claude calls
MAX_RETRIES = 3

# Track last call time for rate limiting
_last_call_time: float = 0.0

ANALYSIS_PROMPT = """Analyze this CI failure log from a GitHub Actions run. The project is vllm-ascend, a community-maintained Ascend NPU hardware plugin for vLLM.

Focus on:
1. The actual error messages (not setup/checkout noise)
2. What specific code change likely caused the failure
3. File paths mentioned in errors or stack traces
4. Whether this is a known pattern (lint, test, build, dependency, environment issue)

Return ONLY a JSON object (no markdown, no code fences) with exactly these fields:
{
  "error_snippets": ["array of the 3-5 most important error log lines, keep them short"],
  "root_cause": "concise 1-3 sentence root cause analysis",
  "related_files": ["array of file paths mentioned in the errors or likely involved"],
  "fix_suggestions": ["array of 1-3 actionable fix suggestions"],
  "severity": "one of: critical, high, medium, low",
  "confidence": 0-100
}

Severity guide:
- critical: build broken, merge blocked, or CI infrastructure failure
- high: test failure that indicates a real bug
- medium: lint/formatting issue, minor test flake
- low: deprecation warning, non-blocking issue

Log to analyze:
"""


def _claude_analyze(text: str) -> dict:
    """Send text to claude -p for analysis, return parsed JSON.

    Includes rate limiting delay and retry logic.
    """
    global _last_call_time

    prompt = ANALYSIS_PROMPT + text

    for attempt in range(MAX_RETRIES):
        # Rate limiting: ensure minimum gap between calls
        elapsed = time.time() - _last_call_time
        if elapsed < CALL_DELAY:
            time.sleep(CALL_DELAY - elapsed)

        _last_call_time = time.time()

        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            response = result.stdout.strip()
            parsed = _parse_claude_response(response)
            if parsed.get("confidence", 0) > 0 or parsed.get("root_cause", ""):
                return parsed
            # Empty/unparseable response - retry
            if attempt < MAX_RETRIES - 1:
                retry_delay = (attempt + 1) * 5
                print(f"    Empty response, retrying in {retry_delay}s...", file=sys.stderr)
                time.sleep(retry_delay)
                continue
        else:
            stderr_summary = result.stderr.strip()[:100] if result.stderr else "no stderr"
            print(f"    claude CLI error (attempt {attempt + 1}): {stderr_summary}", file=sys.stderr)
            if attempt < MAX_RETRIES - 1:
                retry_delay = (attempt + 1) * 5
                print(f"    Retrying in {retry_delay}s...", file=sys.stderr)
                time.sleep(retry_delay)
                continue

    return _fallback_analysis(f"claude CLI failed after {MAX_RETRIES} attempts")


def _parse_claude_response(response: str) -> dict:
    """Extract JSON object from claude response, handling various formats."""
    # Try direct JSON parse first
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        pass

    # Try to extract from code fences
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", response, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find a JSON object in the text
    brace_match = re.search(r"\{.*\}", response, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    print(f"  Could not parse claude response as JSON, using raw response", file=sys.stderr)
    return {
        "error_snippets": [],
        "root_cause": response[:500],
        "related_files": [],
        "fix_suggestions": [],
        "severity": "unknown",
        "confidence": 0,
    }


def _fallback_analysis(reason: str) -> dict:
    return {
        "error_snippets": [],
        "root_cause": f"Analysis unavailable: {reason}",
        "related_files": [],
        "fix_suggestions": [],
        "severity": "unknown",
        "confidence": 0,
    }


def _log_hash(log_text: str) -> str:
    return hashlib.sha256(log_text.encode()).hexdigest()[:16]


class AnalysisCache:
    """Simple JSON-file-based cache to avoid re-analyzing identical logs."""

    def __init__(self, cache_path: Path = Path("reports/.analysis_cache.json")):
        self.cache_path = cache_path
        self.entries: dict[str, dict] = {}
        if cache_path.exists():
            try:
                self.entries = json.loads(cache_path.read_text())
            except (json.JSONDecodeError, OSError):
                self.entries = {}

    def get(self, key: str) -> Optional[dict]:
        return self.entries.get(key)

    def set(self, key: str, data: dict):
        self.entries[key] = data
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self.entries, indent=2))


def analyze_report(report: FailureReport, cache: Optional[AnalysisCache] = None) -> FailureReport:
    """Analyze all failed jobs in a report using Claude CLI.

    Modifies the report in-place by populating the analyses field.
    """
    if cache is None:
        cache = AnalysisCache()

    analyses: list[JobAnalysis] = []

    for run in report.runs:
        for job in run.jobs:
            print(f"  Analyzing job: {job.job_name} (id={job.job_id})")

            # Truncate log for analysis
            truncated = truncate_log(job.raw_log)
            if len(truncated) > MAX_LOG_CHARS:
                truncated = truncated[:MAX_LOG_CHARS] + "\n\n[... LOG TRUNCATED ...]"

            if not truncated.strip():
                analysis = JobAnalysis(
                    job_name=job.job_name,
                    job_id=job.job_id,
                    conclusion=job.conclusion,
                    root_cause="No log available for analysis",
                    severity="unknown",
                    confidence=0,
                )
                analyses.append(analysis)
                continue

            # Check cache
            key = _log_hash(truncated)
            cached = cache.get(key)
            if cached:
                print(f"    (cache hit)")
                result = cached
            else:
                print(f"    Analyzing {len(truncated)} chars of log with Claude...")
                start = time.time()
                result = _claude_analyze(truncated)
                elapsed = time.time() - start
                print(f"    Analysis completed in {elapsed:.1f}s")
                cache.set(key, result)

            analysis = JobAnalysis(
                job_name=job.job_name,
                job_id=job.job_id,
                conclusion=job.conclusion,
                error_snippets=result.get("error_snippets", []),
                root_cause=result.get("root_cause", ""),
                related_files=result.get("related_files", []),
                fix_suggestions=result.get("fix_suggestions", []),
                severity=result.get("severity", "unknown"),
                confidence=result.get("confidence", 0),
            )
            analyses.append(analysis)

    report.analyses = analyses
    return report

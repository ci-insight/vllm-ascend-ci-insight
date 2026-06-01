"""Shared fixtures for ascend tests."""

import json
import pytest
from pathlib import Path


@pytest.fixture
def rules_config():
    """Load shared classification rules."""
    config_path = Path("config/rules.json")
    if config_path.exists():
        return json.loads(config_path.read_text())
    return {}


@pytest.fixture
def sample_workflow_names():
    """Workflow names observed in production."""
    return [
        "E2E-Light", "E2E-Full", "Nightly-A2", "Nightly-A3",
        "vLLM Main Schedule Test", "Cache csrc Build Artifacts",
        "Image Build and Push", "Merge Conflict Labeler", "PR Create",
        "ruff", "mypy", "Release Code and Wheel", "Build Wheel Schedule",
        "ascend test / full", "e2e test / a3-test", "shellcheck",
    ]


@pytest.fixture
def sample_failure_report():
    """Minimal FailureReport-like dict for testing."""
    from datetime import datetime, timezone
    return {
        "pr_number": 9999,
        "pr_title": "Test PR",
        "pr_author": "testuser",
        "pr_url": "https://github.com/vllm-project/vllm-ascend/pull/9999",
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "runs": [
            {
                "run_id": 12345,
                "workflow_name": "E2E-Light",
                "conclusion": "failure",
                "branch": "test-branch",
                "pr_number": 9999,
                "created_at": "2026-06-01T00:00:00Z",
                "event": "pull_request",
                "pipeline_type": "pr_e2e",
                "jobs": [
                    {
                        "job_id": 100,
                        "job_name": "lint / pre-commit",
                        "conclusion": "failure",
                        "started_at": "2026-06-01T00:01:00Z",
                        "completed_at": "2026-06-01T00:03:00Z",
                        "steps": [],
                    },
                    {
                        "job_id": 101,
                        "job_name": "e2e-light / singlecard-light",
                        "conclusion": "success",
                        "started_at": "2026-06-01T00:01:30Z",
                        "completed_at": "2026-06-01T00:10:00Z",
                        "steps": [],
                    },
                ],
            }
        ],
        "analyses": [
            {
                "job_name": "lint / pre-commit",
                "job_id": 100,
                "conclusion": "failure",
                "error_snippets": ["ruff check failed", "E501 Line too long"],
                "root_cause": "Pre-commit hooks not run before push",
                "related_files": ["src/test.py"],
                "fix_suggestions": ["Run pre-commit locally"],
                "severity": "medium",
                "confidence": 90,
                "effort": "low",
            }
        ],
    }

"""Test classification rules loaded from config/rules.json."""

import json
import re
from pathlib import Path


def load_classify_pipeline():
    """Load pipeline classification from shared config."""
    config = json.loads(Path("config/rules.json").read_text())
    patterns = {}
    for pt, cfg in config.get("pipeline_types", {}).items():
        pats = cfg.get("patterns", [])
        if pats:
            patterns[pt] = [re.compile(p) for p in pats]
    def classify(wf_name):
        for pt, pats in patterns.items():
            for p in pats:
                if p.search(wf_name):
                    return pt
        return "other"
    return classify


def load_classify_category():
    """Load category classification from shared config."""
    config = json.loads(Path("config/rules.json").read_text())
    rules = []
    for cat in config.get("categories", []):
        combined = "|".join(cat["patterns"])
        rules.append((cat["key"], re.compile(combined, re.IGNORECASE)))
    def classify(text):
        for key, pat in rules:
            if pat.search(text):
                return key
        return "other"
    return classify


classify_pipeline = load_classify_pipeline()
classify_category = load_classify_category()


def test_pipeline_pr_e2e():
    assert classify_pipeline("E2E-Light") == "pr_e2e"
    assert classify_pipeline("E2E-Full") == "pr_e2e"
    assert classify_pipeline("PR Create") == "pr_e2e"
    assert classify_pipeline("Merge Conflict Labeler") == "pr_e2e"
    assert classify_pipeline("Image Build and Push") == "pr_e2e"
    assert classify_pipeline("Docs link check") == "pr_e2e"
    assert classify_pipeline("Cache csrc Build Artifacts") == "pr_e2e"
    assert classify_pipeline("ruff") == "pr_e2e"
    assert classify_pipeline("mypy") == "pr_e2e"
    assert classify_pipeline("yapf") == "pr_e2e"
    assert classify_pipeline("codespell") == "pr_e2e"
    assert classify_pipeline("shellcheck") == "pr_e2e"
    assert classify_pipeline("actionlint") == "pr_e2e"


def test_pipeline_nightly():
    assert classify_pipeline("Nightly-A2") == "nightly"
    assert classify_pipeline("Nightly-A3") == "nightly"
    assert classify_pipeline("vLLM Main Schedule Test") == "nightly"
    assert classify_pipeline("accuracy test") == "nightly"
    assert classify_pipeline("nightly_benchmarks") == "nightly"
    assert classify_pipeline("performance test") == "nightly"
    assert classify_pipeline("ascend test / full") == "nightly"


def test_pipeline_build():
    assert classify_pipeline("Build Wheel Schedule") == "build"
    assert classify_pipeline("build / sdist") == "build"
    assert classify_pipeline("Release Code and Wheel") == "build"


def test_pipeline_other():
    assert classify_pipeline("Unknown Workflow") == "other"


def test_category_lint():
    assert classify_category("ruff check failed in pre-commit hook") == "lint"
    assert classify_category("E501 Line too long at src/foo.py") == "lint"
    assert classify_category("unused import os in module") == "lint"
    assert classify_category("F821 undefined name 'foo'") == "lint"


def test_category_build():
    assert classify_category("cmake>=3.26.1 not found") == "build"
    assert classify_category("pip install failed: package not found") == "build"


def test_category_code():
    assert classify_category("ImportError: No module named 'torch'") == "code"
    assert classify_category("AttributeError: 'NoneType' has no attribute 'foo'") == "code"
    assert classify_category("ModuleNotFoundError: No module named 'vllm_ascend'") == "code"


def test_category_test():
    assert classify_category("accuracy test failed for Qwen3-8B") == "test"
    assert classify_category("assertion fail: expected 42 got 0") == "test"
    assert classify_category("this is a flaky test") == "test"


def test_category_perf():
    assert classify_category("OOM killed process") == "perf"
    assert classify_category("test timed out after 3600s") == "perf"


def test_category_infra():
    assert classify_category("runner disconnected unexpectedly") == "infra"
    assert classify_category("HTTP 404 when fetching resource") == "infra"


def test_category_compat():
    assert classify_category("module renamed to new_path") == "compat"
    assert classify_category("deprecated method removed in v2.0") == "compat"


def test_category_order():
    """Lint should match before code (undefined name is caught by lint first)."""
    result = classify_category("ruff check: F821 undefined name 'foo' at src/bar.py")
    assert result == "lint", f"Expected lint, got {result}"


def test_all_workflows_covered(sample_workflow_names):
    """Every observed workflow should have a non-other classification."""
    for wf in sample_workflow_names:
        pt = classify_pipeline(wf)
        assert pt != "other", f"Workflow '{wf}' classified as 'other' — add to config/rules.json"

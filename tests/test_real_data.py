"""Test classification on ALL real report data for coverage and consistency."""

import json
import re
import os
from collections import defaultdict
import pytest

from src.storage import source_reports_dir, load_rules, read_json

REPORTS_DIR = source_reports_dir()


def load_classification_rules():
    """Load rules from shared config."""
    config = load_rules()

    pipeline_patterns = {}
    for pt, cfg in config.get("pipeline_types", {}).items():
        pats = cfg.get("patterns", [])
        if pats:
            pipeline_patterns[pt] = [re.compile(p) for p in pats]

    category_rules = []
    for cat in config.get("categories", []):
        combined = "|".join(cat["patterns"])
        category_rules.append((cat["key"], re.compile(combined, re.IGNORECASE)))

    return pipeline_patterns, category_rules


PIPELINE_PATTERNS, CATEGORY_RULES = load_classification_rules()


def classify_pipeline(wf_name: str) -> str:
    for pt, pats in PIPELINE_PATTERNS.items():
        for p in pats:
            if p.search(wf_name):
                return pt
    return "other"


def classify_category(text: str) -> str:
    for key, pat in CATEGORY_RULES:
        if pat.search(text):
            return key
    return "other"


def collect_all_analyses():
    """Collect all real analyses with their job context."""
    items = []
    for root, dirs, files in os.walk(str(REPORTS_DIR)):
        for f in files:
            if not f.startswith("pr-") or not f.endswith(".json"):
                continue
            data = read_json(os.path.join(root, f), default={})

            # Build job_id -> workflow_name map from runs
            job_wf = {}
            for run in data.get("runs", []):
                for job in run.get("jobs", []):
                    job_wf[job["job_id"]] = run.get("workflow_name", "")

            for a in data.get("analyses", []):
                if a.get("confidence", 0) > 0:
                    wf = job_wf.get(a["job_id"], "")
                    text = " ".join([
                        a.get("root_cause", ""),
                        " ".join(a.get("error_snippets", [])),
                        a.get("job_name", ""),
                    ])
                    items.append({
                        "pr_number": data["pr_number"],
                        "job_name": a["job_name"],
                        "workflow_name": wf,
                        "text": text,
                    })
    return items


ALL_ANALYSES = collect_all_analyses()


def test_real_data_exists():
    assert len(ALL_ANALYSES) > 0, "No real analyses to test"


def test_all_analyses_classified():
    """Every real analysis must get a valid category (not just 'other')."""
    unclassified = []
    for item in ALL_ANALYSES:
        cat = classify_category(item["text"])
        if cat == "other":
            unclassified.append(item)

    # Allow a small number of "other" (up to 5% of total)
    pct = len(unclassified) / len(ALL_ANALYSES) * 100
    assert pct < 10, (
        f"{len(unclassified)}/{len(ALL_ANALYSES)} ({pct:.1f}%) unclassified analyses.\n"
        + "First 5:\n" + "\n".join(
            f"  PR#{u['pr_number']}: {u['job_name'][:60]}\n    {u['text'][:150]}"
            for u in unclassified[:5]
        )
    )


def test_all_workflows_classified():
    """Every workflow name seen in real data must be classified."""
    wfs = set(item["workflow_name"] for item in ALL_ANALYSES if item["workflow_name"])
    unclassified_wfs = []
    for wf in sorted(wfs):
        pt = classify_pipeline(wf)
        if pt == "other":
            unclassified_wfs.append(wf)

    if unclassified_wfs:
        pytest.fail(
            f"{len(unclassified_wfs)} workflow(s) classified as 'other':\n" +
            "\n".join(f"  - {w}" for w in unclassified_wfs) +
            "\nAdd patterns to config/rules.json"
        )


def test_category_distribution_reasonable():
    """Category distribution should be within expected ranges."""
    cats = defaultdict(int)
    for item in ALL_ANALYSES:
        cats[classify_category(item["text"])] += 1

    total = len(ALL_ANALYSES)
    # No single category should dominate > 80%
    for cat, count in cats.items():
        pct = count / total * 100
        assert pct < 80, f"Category '{cat}' at {pct:.0f}% — patterns may be too broad"


def test_job_analysis_has_workflow():
    """Every analysis with confidence>0 should map to a workflow."""
    missing = []
    for item in ALL_ANALYSES:
        if not item["workflow_name"]:
            missing.append(item)
    assert len(missing) == 0, (
        f"{len(missing)} analyses have no workflow mapping.\n" +
        "\n".join(f"  PR#{a['pr_number']}: {a['job_name'][:60]}" for a in missing[:5])
    )

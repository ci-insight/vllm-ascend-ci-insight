# Pipeline Type Classification

Rules loaded from `config/rules.json` (single source of truth for Python and JS).

## Pipeline Types

### pr_e2e — PR-triggered CI
Covered workflows (30 total from vllm-ascend):
- E2E-Light, E2E-Full, E2E-upstream
- PR Create, Merge Conflict Labeler
- Image Build and Push, Docs link check
- Cache csrc Build Artifacts, model downloader
- ruff, mypy, yapf, codespell, actionlint, shellcheck
- Dependabot Updates

### nightly — Scheduled tests
- Nightly-A2, Nightly-A3
- vLLM Main Schedule Test
- accuracy test (all variants), Benchmarks
- nightly_benchmarks, performance
- ascend test (full, a3, 310p, long-term, pd-disaggregation)

### build — Build and release
- Build Wheel Schedule
- build/sdist, build/wheel
- Release Code, Release Wheel

### other — Fallback
Catch-all for unclassified workflows. Should be empty after proper classification.

## Classification Algorithm

```python
def classify_pipeline(workflow_name: str) -> str:
    for pipeline_type, patterns in PIPELINE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, workflow_name):
                return pipeline_type
    return "other"
```

First match wins. Order: pr_e2e → nightly → build → other.

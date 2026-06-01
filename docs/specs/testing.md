# Testing Strategy

## Test Structure

```
tests/
├── conftest.py              # Shared fixtures: rules_config, sample data
├── test_classifier.py       # 19 tests: pipeline + category classification
├── test_health.py           # 6 tests: health score computation
├── test_alert.py            # 6 tests: alert rule engine + cooldown
├── test_data_integrity.py   # 155 tests: ALL real report data validation
├── test_real_data.py        # 5 tests: real data coverage analysis
└── test_edge_cases.py       # 7 tests: boundaries, empty data, nulls
```

**Total: 198 tests, all passing.**

## Test Categories

### 1. Classification Tests (test_classifier.py)
- Pipeline type classification for all observed workflow names
- Category classification for all 7 categories
- Rule ordering (lint before code)
- Coverage: all 30 workflows from vllm-ascend
- Rules loaded from `config/rules.json` (not hardcoded)

### 2. Health Score Tests (test_health.py)
- All-success → high score
- All-failure → low score
- Consecutive failure penalty
- Multi-pipeline aggregation
- Score bounds [0, 100]
- Rating thresholds (good ≥ 80, fair ≥ 60, danger < 60)

### 3. Alert Tests (test_alert.py)
- R001: Consecutive failure detection
- R002: Low health score alert (< 70)
- R003: Success rate drop (≥ 20%)
- R004: Nightly failure alert
- Cooldown isolation (autouse fixture clears state)
- Non-trigger verification (healthy pipeline doesn't alert)

### 4. Data Integrity Tests (test_data_integrity.py)
Parametrized over ALL report files on disk:
- Valid JSON structure
- Required fields (report, run, job, analysis levels)
- Job timestamp validity (start ≤ end, 10s clock skew tolerance)
- Job-analysis consistency (analysis job_id exists in runs)
- PR number consistency (filename matches field)
- No duplicate reports per date
- Confidence values in [0, 100]
- Index.json matches disk files

### 5. Real Data Tests (test_real_data.py)
- Classification coverage: < 10% unclassified
- All observed workflows classified (not "other")
- Category distribution: no single category > 80%
- Every analysis maps to a workflow

### 6. Edge Case Tests (test_edge_cases.py)
- Empty reports / 0 jobs
- Missing pipeline_type fallback
- Health score boundaries (0 and 100)
- Large duration values (10-day jobs)
- Log truncation: empty, short, long, error extraction
- Null/empty workflow names
- Partial match vs exact match
- Multiple runs per PR

## Running Tests

```bash
# All tests
.venv/bin/python -m pytest tests/ -v

# Specific file
.venv/bin/python -m pytest tests/test_classifier.py -v

# Quick (no real data)
.venv/bin/python -m pytest tests/ --ignore=tests/test_data_integrity.py -q

# Pre-commit verification
./scripts/verify.sh
```

## Adding New Tests

1. Add new workflow to `tests/conftest.py::sample_workflow_names`
2. Add patterns to `config/rules.json`
3. Run `test_all_workflows_covered` and `test_all_analyses_classified`
4. If adding a new category, add test cases to `test_classifier.py`
5. Run full suite before committing

## Test Principles

- **Data-driven**: Tests use real data from `reports/` when possible
- **Config-driven**: Classification tests load from `config/rules.json`
- **Isolated**: Alert tests clear cooldown state; health tests use synthetic data
- **Comprehensive**: Every report file, every analysis, every workflow is checked
- **Fast**: Full suite runs in < 1 second (no network calls)

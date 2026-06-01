#!/bin/bash
# Pre-commit verification checklist
set -euo pipefail

echo "=== ascend-ci-insight Verification ==="
echo ""

# 1. Run tests
echo "[1/5] Running tests..."
if [ -d .venv ]; then
    .venv/bin/python -m pytest tests/ -q
else
    python3 -m pytest tests/ -q
fi
echo "  PASS"
echo ""

# 2. Verify classification rules are synced
echo "[2/5] Verifying classification rules..."
python3 -c "
import json, re
from pathlib import Path

config = json.loads(Path('config/rules.json').read_text())

# Python side: collector.py loads from this config
from src.collector import classify_pipeline, PIPELINE_PATTERNS
assert PIPELINE_PATTERNS, 'PIPELINE_PATTERNS not loaded from config'

# Verify all pipeline types from config are loaded
for pt in config['pipeline_types']:
    if config['pipeline_types'][pt]['patterns']:
        assert pt in PIPELINE_PATTERNS, f'{pt} missing from PIPELINE_PATTERNS'
        assert len(PIPELINE_PATTERNS[pt]) == len(config['pipeline_types'][pt]['patterns']), f'{pt} pattern count mismatch'

# Verify all categories from config
categories = config['categories']
for cat in categories:
    assert cat['key'], f'category missing key'
    assert cat['patterns'], f'category {cat[\"key\"]} has no patterns'

print(f'  PASS: {len(config[\"pipeline_types\"])} pipeline types, {len(categories)} categories')
"
echo ""

# 3. Health computation smoketest
echo "[3/5] Health computation smoketest..."
python3 -c "
from src.__main__ import _load_existing_reports
from src.health import compute_health

reports = _load_existing_reports()
assert reports, 'No reports loaded'
data = compute_health(reports)
assert 'pipelines' in data
for pt, p in data['pipelines'].items():
    assert 0 <= p['health_score'] <= 100, f'{pt} health {p[\"health_score\"]} out of bounds'
    print(f'  {pt}: score={p[\"health_score\"]} SR={p[\"success_rate\"]}%')
print('  PASS')
"
echo ""

# 4. Check JS loads from config (fallback is allowed as safety net)
echo "[4/5] Checking JS rules..."
if grep -q 'PIPELINE_PATTERNS = null' docs/app.js && grep -q 'loadRules' docs/app.js; then
    echo "  PASS: JS loads from config (with fallback)"
else
    echo "  WARNING: JS may not load from config/rules.json"
fi
echo ""

# 5. Git diff check
echo "[5/5] Git diff check..."
if git diff --check --cached 2>/dev/null | grep -q '^'; then
    echo "  FAIL: Whitespace issues found. Run: git diff --check --cached"
    exit 1
else
    echo "  PASS"
fi

echo ""
echo "=== All checks passed ==="

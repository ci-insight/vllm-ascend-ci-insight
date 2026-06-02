# Problem Category Rules

Problem categories are defined in `config/rules.json` under `categories` and
loaded by `docs/app.js`. They are used for dashboard filtering, category
breakdown charts, and badges in report details.

## Classification Input

The browser dashboard classifies a failed analysis/job with:

- AI analysis fields such as root cause, summary, and recommendation,
- job name,
- raw category if present in report data.

The exact matching implementation is in `docs/app.js` `classifyJob(...)`.

## Categories

| Key | Label | Typical signals |
| --- | --- | --- |
| `lint` | Lint/Format | ruff, pre-commit, mypy, flake8, unused import, line too long, undefined name, PR title. |
| `build` | Build/CI Script | cmake, pip install, uv pip, setup.py, requirements, wheel build, package/version lookup errors. |
| `perf` | Performance | OOM, out of memory, killed, timeout. |
| `infra` | Infrastructure | runner failure, disk full, node allocation failure, network errors, rate limit, HTTP 404. |
| `test` | Test Case | accuracy test, regression, assert failure, flaky test, test files. |
| `compat` | Compatibility | deprecated, removed, renamed, unsupported, moved module/import path, incompatible. |
| `code` | Code Bug | ImportError, AttributeError, ModuleNotFoundError, NameError, TypeError, ValueError, KeyError, IndexError. |
| `other` | Other | Fallback when no category pattern matches. |

## Dashboard Metrics Using Categories

| Display | Calculation |
| --- | --- |
| Category filter | Keeps analyses whose computed `_category` equals the selected category. |
| Category Breakdown chart | Count filtered analyses grouped by `_category`. |
| Detail badge | Shows the computed category for each analysis row. |

## Invariants

- Category rules affect problem-analysis grouping only. They do not affect CI
  health score, job success rate, or workflow-run counts.
- Category counts are analysis counts, not job counts, unless a single analysis
  maps one-to-one to a failed job in the input report.
- `config/rules.json` is the source of truth. This document describes the
  current intent and must be updated when category keys or meanings change.

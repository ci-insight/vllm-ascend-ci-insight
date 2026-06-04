# Coverage Metadata

`coverage.json` describes how complete the dashboard data is for the selected
period. It separates workflow-run inventory, job-detail coverage, measured job
coverage, and AI-analysis coverage.

## File

Static deploy path:

```text
docs/reports/coverage.json
```

Local path:

```text
reports/coverage.json
```

## Schema

```json
{
  "generated_at": "2026-06-03T00:00:00Z",
  "period": {
    "days": 7,
    "since": "2026-05-27T00:00:00Z",
    "until": "2026-06-03T00:00:00Z"
  },
  "run_inventory": {
    "total": 9935,
    "complete": true,
    "by_date": {
      "2026-06-03": 800,
      "2026-06-02": 1700
    }
  },
  "job_details": {
    "collected_runs": 9935,
    "total_runs": 9935,
    "coverage_percent": 100,
    "quality": "full"
  },
  "measured_jobs": {
    "measured": 12431,
    "total_jobs": 67200,
    "coverage_percent": 18.5
  },
  "ai_analysis": {
    "analyzed": 42,
    "failed_jobs": 185,
    "coverage_percent": 22.7,
    "log_collection": {
      "collected_logs": 120,
      "failed_jobs": 185,
      "coverage_percent": 64.86,
      "quality": "partial"
    }
  }
}
```

## Semantics

- `run_inventory.complete` means the collector queried every configured date
  partition in the period. It does not mean job details are complete.
- `job_details.quality == "full"` only when every inventoried workflow run has
  job details.
- Health metrics are full-period objective metrics only when job detail quality
  is `full`.
- `measured_jobs` counts only `success` and `failure` jobs as measured
  outcomes.
- `ai_analysis` is independent from base CI health metrics.
- `ai_analysis.log_collection` tracks failed-like jobs whose raw logs are
  already stored in SQLite. It is the prerequisite for `--analyze-from-store`.
- `ai_analysis.analyzed` counts jobs that have passed through the AI analyzer,
  not merely jobs whose logs are available.

## Dashboard Rules

- Always show job detail coverage when CI metadata is available.
- Label health as `partial` when `job_details.quality != "full"`.
- Do not present partial job-detail health as full-period objective health.

## Resumable Collection Workflow

The preferred production workflow is split into resumable stages:

```bash
python -m src --collect-run-inventory --days 7 --metrics-collection-strategy date_partition
python -m src --collect-job-details --days 7 --metrics-job-detail-limit 500
python -m src --collect-logs --days 7 --metrics-job-detail-limit 100
python -m src --analyze-from-store --days 7 --limit 30
python -m src --export-ci-metadata --health --days 7 --no-notify
```

Rules:

- Run inventory is cheap and can be refreshed frequently.
- Job detail collection is budgeted and resumes from runs where
  `jobs_collected_at IS NULL`.
- If an inventoried run changes `updated_at` or moves from non-completed to
  completed, its existing `jobs_collected_at` is cleared so jobs are refreshed.
- `--force-job-details` intentionally re-fetches already collected jobs.
- Log collection is a separate budgeted step. `--collect-logs` only fetches
  raw logs for failed/cancelled/timed_out jobs already present in SQLite.
- `--analyze-from-store` builds `FailureReport` objects from SQLite-stored
  failed-job logs and must not re-fetch workflow-run or job metadata.
- Static export must read from SQLite, not from only the current command's API
  sample.

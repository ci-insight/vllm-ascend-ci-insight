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
    "coverage_percent": 22.7
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

## Dashboard Rules

- Always show job detail coverage when CI metadata is available.
- Label health as `partial` when `job_details.quality != "full"`.
- Do not present partial job-detail health as full-period objective health.

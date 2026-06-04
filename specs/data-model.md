# Data Model

## Core Entities

```
FailureReport
├── pr_number, pr_title, pr_author, pr_url
├── analyzed_at: ISO timestamp (analysis time)
├── runs: list[CIRun]
└── analyses: list[JobAnalysis]

CIRun
├── run_id, workflow_name, conclusion
├── branch, pr_number, created_at
├── event: pull_request | schedule
├── pipeline_type: pr_e2e | nightly | build | other
└── jobs: list[CIJob]

CIJob
├── job_id, job_name, conclusion
├── created_at, started_at, completed_at (ISO timestamps)
├── steps: list[StepResult]
└── raw_log: str (only for failed jobs)

JobAnalysis
├── job_name, job_id, conclusion
├── error_snippets, root_cause
├── related_files, fix_suggestions
├── severity: critical | high | medium | low
├── confidence: 0-100
└── effort: low | medium | high
```

## Derived Data

```
health.json
├── pipelines: {pr_e2e, nightly, build, other}
│   ├── success_rate, health_score, rating
│   ├── consecutive_details
│   └── daily_trend[]
└── consecutive_failures

alerts.json
└── alerts[]: {rule_id, severity, message, triggered_at}

daily-snapshots.json (from SQLite aggregator)
└── pipeline_types: {pt: [{date, success_rate, health_score, ...}]}
```

## Store-backed AI Analysis

Problem Analysis can consume the same CI fact store used by CI Execution and
Health Overview:

1. `workflow_runs` stores run inventory.
2. `ci_jobs` stores job metadata for those runs.
3. `--collect-logs` populates `ci_jobs.raw_log` only for failed-like jobs.
4. `--analyze-from-store` converts logged failed jobs into `FailureReport`
   objects and reuses the existing analyzer/reporter.

This keeps Health Overview as fact statistics and Problem Analysis as AI
inference, while avoiding redundant GitHub API calls for run/job metadata.

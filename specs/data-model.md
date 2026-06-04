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

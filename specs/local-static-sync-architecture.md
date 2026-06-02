# Local DB and Static JSON Sync Architecture

## Purpose

This document defines the target architecture for running `ascend-ci-insight` in two deployment modes:

- Local dynamic deployment backed by SQLite.
- Remote static deployment backed by generated JSON files under `docs/reports/`.

The goal is to keep the dashboard timely, data-rich, and cheap to operate while avoiding unbounded log collection or unnecessary AI calls.

## Core Principle

Use one logical data model with two storage surfaces:

```text
GitHub Actions / gh CLI
        |
        v
Collectors
        |
        v
SQLite local database  --->  Static JSON exporter  --->  docs/reports/*.json
        ^                                                   |
        |                                                   v
        +---------------- Static JSON importer <-------------+
```

SQLite is the primary operational store for local dynamic deployment.

Static JSON is the published read-only snapshot for GitHub Pages or other static hosting.

Bidirectional sync is allowed only as import/export. Do not make SQLite and static JSON independent writable primaries.

## Deployment Modes

### Local Dynamic Deployment

Local deployment should use SQLite as the source of truth for:

- Incremental GitHub Actions metadata.
- Workflow run and job history.
- Health snapshots.
- AI analysis task state.
- AI analysis results.
- Failure clusters.
- Notification and retry state.

The local service can expose APIs over SQLite and can trigger collection or analysis interactively.

### Remote Static Deployment

Remote static deployment should read only generated files:

- `docs/reports/ci-runs.json`
- `docs/reports/health.json`
- `docs/reports/alerts.json`
- `docs/reports/daily-snapshots.json`
- `docs/reports/index.json`
- future `docs/reports/failure-clusters.json`
- future `docs/reports/analysis-results.json`

Static JSON must include enough metadata for users and agents to judge freshness and coverage:

```json
{
  "generated_at": "...",
  "schema_version": 1,
  "source": "sqlite-export",
  "data_age_sec": 120,
  "sample_coverage": {
    "target_measured_per_pipeline": 10,
    "measured_jobs_by_pipeline": {
      "pr_e2e": 42,
      "nightly": 11
    }
  }
}
```

## Synchronization Model

### Local to Static

Export SQLite data into `docs/reports/*.json`.

Recommended command shape:

```bash
python -m src export-static
```

The exporter should:

- Read SQLite tables.
- Generate dashboard JSON atomically.
- Preserve schema versions.
- Write `generated_at` and sample coverage.
- Avoid changing unrelated report files.

### Static to Local

Import JSON snapshots into SQLite for cold start, recovery, or workstation handoff.

Implemented compatibility command:

```bash
python -m src --import-static
python -m src --import-static docs/reports
```

Future subcommand shape:

```bash
python -m src import-static --from docs/reports
```

The importer should:

- Upsert workflow runs and jobs.
- Upsert health snapshots.
- Upsert AI results when present.
- Never import local-only task locks as active work.
- Treat static JSON as a snapshot, not as a live task queue.

### Conflict Rules

Use deterministic upsert rules:

- `workflow_runs`: `run_id` is unique. Newer `updated_at` wins.
- `ci_jobs`: `job_id` is unique. Newer status/completion data wins.
- `analysis_results`: `log_hash` is unique. Newer `analyzed_at` or higher schema version wins.
- `health_snapshots`: `(date, pipeline_type)` is unique. Newer `generated_at` wins.
- `failure_clusters`: `cluster_signature` is unique. Merge occurrence counts and keep latest `last_seen`.

Do not synchronize:

- Active collection locks.
- In-progress AI task locks.
- Notification cooldown runtime state unless explicitly designed.

## Target SQLite Schema

The current database has `daily_snapshots` and `job_records`. The target schema should evolve toward:

```text
workflow_runs
ci_jobs
collection_state
health_snapshots
analysis_tasks
analysis_results
failure_clusters
notification_state
```

### workflow_runs

```text
run_id INTEGER PRIMARY KEY
workflow_name TEXT NOT NULL
pipeline_type TEXT NOT NULL
conclusion TEXT
status TEXT
branch TEXT
event TEXT
pr_number INTEGER
created_at TEXT
updated_at TEXT
url TEXT
raw_json TEXT
ingested_at TEXT NOT NULL
```

### ci_jobs

```text
job_id INTEGER PRIMARY KEY
run_id INTEGER NOT NULL
job_name TEXT NOT NULL
workflow_name TEXT NOT NULL
pipeline_type TEXT NOT NULL
conclusion TEXT
status TEXT
started_at TEXT
completed_at TEXT
duration_sec REAL
queue_sec REAL
url TEXT
raw_json TEXT
ingested_at TEXT NOT NULL
```

### collection_state

```text
source TEXT PRIMARY KEY
last_collected_at TEXT
last_seen_run_id INTEGER
last_seen_updated_at TEXT
cursor TEXT
metadata TEXT
```

### analysis_tasks

```text
task_id TEXT PRIMARY KEY
job_id INTEGER NOT NULL
run_id INTEGER NOT NULL
status TEXT NOT NULL
priority INTEGER DEFAULT 0
reason TEXT
log_hash TEXT
attempt_count INTEGER DEFAULT 0
created_at TEXT NOT NULL
started_at TEXT
completed_at TEXT
error TEXT
```

Allowed task statuses:

```text
pending
running
succeeded
failed
retryable
skipped
```

### analysis_results

```text
result_id TEXT PRIMARY KEY
job_id INTEGER
run_id INTEGER
log_hash TEXT NOT NULL
model TEXT
prompt_version TEXT
severity TEXT
confidence INTEGER
effort TEXT
root_cause TEXT
error_snippets TEXT
related_files TEXT
fix_suggestions TEXT
analyzed_at TEXT NOT NULL
```

### failure_clusters

```text
cluster_id TEXT PRIMARY KEY
cluster_signature TEXT UNIQUE NOT NULL
representative_job_id INTEGER
pipeline_type TEXT
workflow_name TEXT
occurrence_count INTEGER DEFAULT 0
first_seen TEXT
last_seen TEXT
severity TEXT
root_cause TEXT
metadata TEXT
```

## Collection Strategy

### Lightweight Metadata Collection

This is the default frequent path.

It collects:

- Workflow runs via `gh run list`.
- Jobs via `gh api repos/{repo}/actions/runs/{run_id}/jobs --paginate`.

It must not:

- Fetch job logs.
- Invoke Claude or another AI model.

Recommended refresh cadence:

- Local dynamic: every 1-5 minutes.
- Static GitHub Pages: every 5-15 minutes, or triggered by `workflow_run`.

Sampling targets:

```text
pr_e2e measured success/failure jobs >= 20
nightly measured success/failure jobs >= 10
```

The collector should continue paging until:

- all targets are met,
- the configured run limit is exhausted,
- or the date window is exhausted.

### Failure Deep Collection

This is the expensive path.

It should run only for:

- failed jobs,
- cancelled/timed-out jobs when configured,
- repeated failure clusters,
- user-triggered analysis,
- high-priority nightly failures.

It may fetch logs:

```bash
gh api repos/{repo}/actions/jobs/{job_id}/logs
```

Logs should be truncated before analysis using:

- head context,
- error windows,
- tail context.

## AI Analysis Strategy

AI analysis should be asynchronous and deduplicated.

Pipeline:

```text
failed job detected
    |
    v
create analysis_task
    |
    v
fetch/truncate log
    |
    v
compute log_hash and cluster_signature
    |
    v
reuse existing result or call Claude
    |
    v
store analysis_result
    |
    v
update failure_cluster
    |
    v
export static JSON
```

Token controls:

- Use `log_hash` to avoid analyzing identical logs.
- Use failure clusters and analyze only representative logs.
- Cap input size.
- Store prompt version and model.
- Keep retryable task state in SQLite.

## Dashboard Data Products

### Live CI

Source:

- Local: SQLite API.
- Static: `ci-runs.json`.

Shows:

- current runs and jobs,
- queued/in-progress/completed states,
- PR check state,
- workflow and job duration,
- queue time,
- measured sample coverage.

### Health

Source:

- Local: SQLite health query.
- Static: `health.json` and `daily-snapshots.json`.

Rules:

- Health score uses measured success/failure jobs.
- skipped, queued, pending, in-progress jobs must not reduce success rate.
- insufficient samples must display as insufficient, not as zero health.
- Success-rate and failure-count trend charts must use CI execution dates from
  workflow/job timestamps, not dashboard collection dates.
- Snapshot dates may be used only for explicitly labeled snapshot charts, such
  as health score snapshots over time.

Trend data products:

```text
execution_trends
  X axis: CI execution date, derived from job.completed_at or run.created_at
  Use for: success rate trend, failure count trend

pipeline_types / daily_snapshots
  X axis: dashboard snapshot date, derived from collection/export date
  Use for: health score snapshot trend
```

Do not label a snapshot-date chart as a CI execution trend.

Sampling guardrail:

- Lightweight GitHub metadata collection may stop early only after both sample
  quality targets are satisfied: measured success/failure job coverage per core
  pipeline and distinct CI execution-date coverage.
- The static JSON and local database should carry `execution_dates` and
  `min_execution_days` metadata so the dashboard can disclose when a trend is
  based on a narrow execution-date sample.
- Increasing measured job count alone does not make a seven-day trend reliable
  if all sampled jobs executed on the same day.

### Failure Analysis

Source:

- Local: `analysis_results` and `failure_clusters`.
- Static: historical report JSON and future `failure-clusters.json`.

Shows:

- AI root cause,
- representative failed jobs,
- affected PRs/runs,
- related files,
- suggested fixes,
- confidence and effort.

### Data Quality

Source:

- collection state,
- generated JSON metadata.

Shows:

- last collection time,
- data age,
- sample target and actual measured coverage,
- API errors,
- static vs dynamic mode,
- stale warnings.

## Commands

Target command surface:

```bash
# Collect lightweight metadata into SQLite.
python -m src collect-ci --db --days 7 --limit 300 --min-measured-per-pipeline 10

# Compute health from SQLite and store snapshots.
python -m src compute-health --db

# Export SQLite data to static JSON.
python -m src export-static

# Import static JSON into SQLite.
python -m src import-static --from docs/reports

# Queue AI analysis for failures.
python -m src queue-analysis --failures-only

# Run AI analysis worker.
python -m src analyze-queue --limit 20
```

Existing compatibility commands may continue to work while the command surface is migrated.

## GitHub Actions Static Refresh

Recommended workflow triggers:

```yaml
on:
  schedule:
    - cron: "*/15 * * * *"
  workflow_dispatch:
  workflow_run:
    workflows:
      - E2E-Light
      - E2E-Full
      - Nightly-A2
      - Nightly-A3
    types:
      - completed
      - requested
```

Recommended job:

```bash
python -m src --health \
  --refresh-ci-metrics \
  --days 7 \
  --metrics-limit 300 \
  --metrics-min-measured-per-pipeline 10 \
  --no-notify
```

Future version:

```bash
python -m src collect-ci --db --days 7 --limit 300 --min-measured-per-pipeline 10
python -m src compute-health --db
python -m src export-static
```

## Implementation Roadmap

### Phase 1: Spec and Layout

- Move specs from `docs/specs` to root `specs`.
- Keep dashboard deploy assets under `docs/`.
- Add this architecture spec.

### Phase 2: SQLite as Operational Store

- Add `workflow_runs`, `ci_jobs`, and `collection_state`.
- Upsert lightweight metadata into SQLite.
- Keep current JSON generation compatible.

### Phase 3: Static Export and Import

- Implement `export-static`.
- Implement `import-static`.
- Add schema versions and freshness metadata to JSON.

### Phase 4: Dashboard Restructure

- Add Live CI tab.
- Add Data Quality tab or banner.
- Keep Failure Analysis explicitly separate from current CI metadata.

### Phase 5: AI Task Queue

- Add `analysis_tasks`, `analysis_results`, and `failure_clusters`.
- Queue analysis only for failure clusters that need it.
- Export AI results and clusters to static JSON.

### Phase 6: Automation

- Add GitHub Actions static refresh.
- Add local service endpoints for collection, export, and analysis.
- Add stale-data alerts.

## Non-Goals

- Do not make static JSON a transactional database.
- Do not fetch logs during lightweight refresh.
- Do not run AI on every job.
- Do not hide sample insufficiency by converting it into a zero score.
- Do not allow two independent writable primaries without explicit conflict rules.

# Dashboard Metrics and Calculation Rules

This document defines the meaning, source, aggregation level, and calculation
rule for every major dashboard number. It is intended for both human review and
AI-assisted implementation changes.

## Core Counting Levels

The dashboard uses two different CI levels. They must not be added together.

| Level | Definition | Example use |
| --- | --- | --- |
| Workflow run | One GitHub Actions workflow execution, identified by `run_id`. | CI sample size, workflow run table, run coverage. |
| Job | One job inside a workflow run, identified by `job_id`. | Health totals, success rate, duration, queue time. |

If `ci-runs.json` contains 500 workflow runs, expanding those runs can produce
thousands of jobs. Health totals are job counts, not workflow-run counts.

## Data Source Banner

Source: `docs/reports/ci-runs.json`, `docs/reports/index.json`.

| Display | Calculation |
| --- | --- |
| Generated time | `ci_metadata.generated_at`. |
| Sampled runs | `len(ci_metadata.runs) / ci_metadata.limit`. |
| Run inventory | For date-partition collection, `run_inventory_count` and `run_inventory_by_date`; this is workflow-run-level coverage. |
| Job detail coverage | `job_detail_runs_collected / run_inventory_count`; this is the fraction of inventoried runs whose jobs were fetched. `job_detail_selection` describes whether the enriched runs were all runs, newest runs, or balanced across dates. |
| Measured jobs | Number of jobs whose conclusion is `success` or `failure`, divided by all jobs in the sampled CI metadata. |
| Skipped jobs | Number of jobs whose conclusion is `skipped`. |
| Pending jobs | Number of jobs whose conclusion is `queued`, `in_progress`, or `pending`. |
| Target per pipeline | `min_measured_per_pipeline` and `measured_jobs_by_pipeline`. |
| Execution day coverage | `len(execution_dates) / min_execution_days`, with the date range from first to last sampled execution date. |
| Problem analysis report count | `len(index.reports)`. |

The banner must disclose narrow temporal coverage. For example, `1/7 execution
day(s)` means the collector requested seven execution dates but the sampled runs
only covered one date.

For date-partition collection, the banner must distinguish full run inventory
from job detail coverage. A dashboard can have complete seven-day workflow-run
inventory while health metrics are still based on a smaller job-detail subset.

## Problem Analysis Tab

Source: historical AI analysis reports under `docs/reports/**/pr-*.json` and
`docs/reports/index.json`.

### Filtered Analysis Set

Most problem-analysis cards and charts are based on `getFilteredAnalyses()`:

- text search filters PR title and PR number,
- severity filter matches `analysis.severity`,
- category filter matches `analysis.category`,
- pipeline filter matches the report's enriched pipeline types.

### Pipeline Cards

The pipeline cards use historical job records, not current lightweight CI
metadata.

| Display | Calculation |
| --- | --- |
| Pipeline value | Failed job count for the pipeline: `count(job.conclusion == "failure")`. |
| WF | Distinct workflow names in that pipeline. |
| Runs | Distinct `(workflow_name, run_id)` pairs in that pipeline. |
| Jobs | Total historical jobs in that pipeline. |

### Severity Cards

| Display | Calculation |
| --- | --- |
| Critical | Count of filtered analyses where `severity == "critical"`. |
| High | Count of filtered analyses where `severity == "high"`. |
| Medium | Count of filtered analyses where `severity == "medium"`. |
| Low | Count of filtered analyses where severity is anything else or `"low"`. |
| Avg Confidence | `round(sum(analysis.confidence) / count(filtered analyses))`. |

### Problem Analysis Charts

| Chart | Calculation |
| --- | --- |
| Severity Breakdown | Count filtered analyses by severity. |
| Top Failing Workflows | Count filtered analysis/job failures by workflow, then show the top workflows. |
| Category Breakdown | Count filtered analyses by category. |

## CI Execution Tab

Source priority:

1. current lightweight CI metadata from `docs/reports/ci-runs.json`,
2. historical failure reports if current CI metadata is unavailable.

### Job Metrics

Let `jobs` be all jobs after the selected pipeline filter.

| Display | Calculation |
| --- | --- |
| Total Jobs | `len(jobs)`. |
| Measured Jobs | `success + failure`. |
| Avg Duration | Average of positive job durations. |
| Job P50 | 50th percentile of positive job durations. |
| Job P90 | 90th percentile of positive job durations. |
| Job P20 | 20th percentile of positive job durations. |
| Queue Time | 50th percentile of non-negative queue times. |
| Measured Success Rate | `round(success / measured_jobs * 100)`, or `N/A` if no measured jobs exist. |

Job conclusion buckets:

| Bucket | Conclusions |
| --- | --- |
| Success | `success` |
| Failure | `failure` |
| Skipped | `skipped` |
| Pending | `queued`, `in_progress`, `pending` |
| Cancelled | `cancelled` |
| Other | Any other conclusion |

### Workflow Metrics

Jobs are grouped into workflow runs by `(workflow_name, run_id)`.

For each workflow run:

```text
wall_clock = max(job.completed_at) - min(job.started_at)
sum_duration = sum(job.duration)
job_count = len(jobs in the workflow run)
max_concurrency = maximum number of overlapping jobs
parallel_efficiency = sum_duration / wall_clock
```

Dashboard cards:

| Display | Calculation |
| --- | --- |
| Workflow Runs | Number of workflow-run groups. |
| Avg Wall-Clock | Average `wall_clock` across workflow runs with timing. |
| Workflow P50 | 50th percentile of workflow `wall_clock`. |
| Workflow P90 | 90th percentile of workflow `wall_clock`. |
| Avg Jobs | Average `job_count` per workflow run. |
| Efficiency | Average `parallel_efficiency`. Values above 1 mean jobs ran in parallel. |
| Workflow Success | Average per-run `success / total_jobs` percentage. |

### CI Execution Charts

| Chart | Calculation |
| --- | --- |
| Job Duration Distribution | Histogram of positive job durations. |
| Queue Wait Time | Top workflows by average queue time. |
| Success Rate by Workflow | Top ten workflows by measured job count, then failure count; stacked success/failure/skipped/pending counts. |
| Slowest Jobs | Top ten timed jobs by duration. |
| Workflow Runs Detail | Workflow-run groups sorted by descending wall-clock time. |

## Health Overview Tab

Source: `docs/reports/health.json`, `docs/reports/alerts.json`,
`docs/reports/daily-snapshots.json`.

Health is computed per pipeline type from job-level data.

### Per-Pipeline Job Counts

For each pipeline:

```text
total = len(jobs)
success = count(conclusion == "success")
failure = count(conclusion == "failure")
skipped = count(conclusion == "skipped")
cancelled = count(conclusion == "cancelled")
other = total - success - failure - skipped - cancelled
measured_total = success + failure
success_rate = success / measured_total
```

`skipped`, `cancelled`, `queued`, `in_progress`, and `pending` do not reduce
success rate. They are included in `total`, but excluded from `measured_total`.

### Health Score

Health score is only valid when the sample is complete enough to include both
successful and failed CI runs. If `complete_success_sample == false`, the score
must be shown as insufficient or `N/A`.

Formula:

```text
health_score = clamp(
  success_rate * 60
  + trend_bonus
  + recency_bonus
  - consecutive_failure_penalty,
  0,
  100
)
```

The final score is rounded to an integer.

### Health Score Components

| Component | Calculation |
| --- | --- |
| Base success score | `success_rate * 60`. Maximum contribution is 60. |
| Trend bonus | Compare measured success rate from the last three days against measured success rate from days four to seven. |
| Recency bonus | Rewards pipelines with no recent failures. |
| Consecutive failure penalty | Penalizes workflows with consecutive failed workflow runs. |

Trend bonus:

| Condition | Bonus |
| --- | ---: |
| Recent rate is more than 5 percentage points above older rate | 20 |
| Recent rate is within 5 percentage points below older rate | 10 |
| Recent rate is worse by more than 5 percentage points | 0 |

Recency bonus:

| Condition | Bonus |
| --- | ---: |
| There are recent 24h jobs and no failures in the last 24h | 20 |
| Otherwise, there are recent 48h jobs and no failures in the last 48h | 10 |
| Otherwise | 0 |

Consecutive failure penalty:

```text
per_workflow_penalty = min(streak * 15, 30)
consecutive_failure_penalty = sum(per_workflow_penalty for workflows with streak >= 2)
```

A streak is counted per workflow name from newest workflow run backwards. It
increments for failed workflow runs and stops at the first successful workflow
run.

### Health Ratings

Ratings come from `config/rules.json` `health_rating_thresholds`. The current
rating is the first threshold whose `min` is less than or equal to the score.

### Overall Health

The overall section is job-level aggregation across pipeline types:

```text
overall.total = sum(pipeline.total)
overall.measured_total = sum(pipeline.measured_total)
overall.success = sum(pipeline.success)
overall.success_rate = round(overall.success / overall.measured_total * 100)
overall.health_score = round(avg(non-null pipeline.health_score))
```

Overall health score is the average of pipeline health scores, not a weighted
average by job count.

### Health Charts

| Chart | X axis | Calculation |
| --- | --- | --- |
| Success Rate by CI Execution Date | CI execution date from job `completed_at`, `started_at`, or run timestamp | Per pipeline, `round(success / measured_total * 100)` for measured jobs on that execution date. |
| Failure Count by CI Execution Date | CI execution date | Per pipeline, failure job count on that execution date. |
| Health Score Snapshot Trend | Dashboard snapshot date | Per pipeline, stored snapshot `health_score`. |
| Worst Workflows | Workflow name | `success / total_jobs` in health job records, sorted ascending. |

Do not use dashboard snapshot dates for CI execution trend charts.

### Pipeline Detail Modal

| Display | Calculation |
| --- | --- |
| Total Jobs | `pipeline.total`. |
| Measured Jobs | `pipeline.measured_total`. |
| Success Rate | `pipeline.success_rate`. |
| Failures | `pipeline.failure`. |
| Skipped | `pipeline.skipped`. |
| Cancelled | `pipeline.cancelled`. |
| 24h Failures | `pipeline.recent_24h_failures`. |
| Failed Jobs by Workflow | Failed jobs in the selected pipeline grouped by workflow. |

## Static Snapshot Data

`docs/reports/daily-snapshots.json` has two different trend products:

| Field | Axis | Use |
| --- | --- | --- |
| `execution_trends` | CI execution date | Success-rate and failure-count trend charts. |
| `pipeline_types` | dashboard snapshot date | Health score snapshot trend only. |

## Invariants

- Always label whether a number is workflow-run level or job level.
- Success rate must use measured jobs only: `success / (success + failure)`.
- Skipped, cancelled, queued, in-progress, and pending jobs must not be treated
  as failures.
- Health score must be `N/A` or insufficient when the dataset is failure-only.
- Sample coverage must disclose both sampled workflow runs and execution-date
  coverage.

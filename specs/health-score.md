# Health Score Specification

Health score is a 0-100 risk summary per pipeline type. It is computed from
job-level CI metadata and is valid only when the dataset includes complete CI
run metadata, not only failed reports.

## Input

Source: `health.py` consumes `FailureReport` objects. In current dashboard
mode, those reports are usually adapted from `docs/reports/ci-runs.json`.

Required fields:

- pipeline type,
- workflow name,
- workflow run id,
- run conclusion,
- run creation time,
- job conclusion,
- job start and completion time when available.

## Job Buckets

For each pipeline type:

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

Only `success` and `failure` are measured outcomes. `skipped`, `cancelled`,
`queued`, `in_progress`, `pending`, and unknown states are not counted as
failures.

## Formula

When `measured_total == 0`, health score is `null` and rating is
`insufficient_data`.

When the sample is complete:

```text
health_score = round(clamp(
  success_rate * 60
  + trend_bonus
  + recency_bonus
  - consecutive_failure_penalty,
  0,
  100
))
```

When the sample is failure-only or otherwise incomplete:

```text
health_score = null
rating = insufficient_data
```

The dashboard must not convert insufficient data into a zero score.

## Trend Bonus

The trend bonus compares measured success rate from recent jobs against older
jobs in the same seven-day window:

```text
recent_rate = success(last 3 days) / measured_total(last 3 days)
older_rate = success(days 4-7) / measured_total(days 4-7)
```

If there are no older measured jobs, `older_rate` falls back to `recent_rate`.

| Condition | Bonus |
| --- | ---: |
| `recent_rate > older_rate + 0.05` | 20 |
| `recent_rate > older_rate - 0.05` | 10 |
| Otherwise | 0 |

## Recency Bonus

| Condition | Bonus |
| --- | ---: |
| There are jobs in the last 24h and zero measured failures in the last 24h | 20 |
| Otherwise, there are jobs in the last 48h and zero measured failures in the last 48h | 10 |
| Otherwise | 0 |

## Consecutive Failure Penalty

Consecutive failures are computed at workflow-run level, grouped by workflow
name. For each workflow, sort workflow runs newest first:

- increment streak for each failed workflow run,
- stop at the first successful workflow run,
- ignore non-measured conclusions for streak termination.

For each workflow with `streak >= 2`:

```text
penalty = min(streak * 15, 30)
```

The pipeline penalty is the sum of all workflow penalties in that pipeline.

## Rating

Ratings come from `config/rules.json`:

```json
"health_rating_thresholds": [
  {"min": 90, "rating": "good"},
  {"min": 70, "rating": "warning"},
  {"min": 0, "rating": "danger"}
]
```

The first threshold whose `min` is less than or equal to the score determines
the rating and color.

## Daily Trend Values

Pipeline `daily_trend` is grouped by job creation date in `health.py` and
contains:

- `total`,
- `measured_total`,
- `success`,
- `failure`,
- `skipped`,
- `cancelled`,
- `other`,
- `success_rate`,
- `health`.

Dashboard trend charts should prefer `daily-snapshots.json.execution_trends`
for CI execution-date charts because that axis uses job execution timestamps.

## Overall Health

```text
overall.total = sum(pipeline.total)
overall.measured_total = sum(pipeline.measured_total)
overall.success = sum(pipeline.success)
overall.success_rate = round(overall.success / overall.measured_total * 100)
overall.health_score = round(avg(non-null pipeline.health_score))
```

Overall health score is not weighted by job count.

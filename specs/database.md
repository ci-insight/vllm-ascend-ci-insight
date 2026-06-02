# Database Design

## Architecture

Dual-write: SQLite (local long-term) + JSON snapshots (GitHub Pages static).

```
python3 -m src --days 2
    │
    ├──► data/metrics.db (SQLite, local only, gitignored)
    │      ├── daily_snapshots    — 每日每个 pipeline type 一行
    │      └── job_records        — 每个 job 的详细记录
    │
    └──► docs/reports/daily-snapshots.json (committed, GitHub Pages)
           └── 按 pipeline_type 分组的时间序列数组
```

## Schema

### daily_snapshots

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| date | TEXT NOT NULL | Date key (YYYY-MM-DD) |
| pipeline_type | TEXT NOT NULL | pr_e2e, nightly, build, other |
| total_runs | INTEGER | Total job count |
| success_runs | INTEGER | Successful job count |
| failure_runs | INTEGER | Failed job count |
| success_rate | REAL | 0-100 |
| health_score | REAL | 0-100 |
| avg_duration_sec | REAL | Average job duration (computed from job_records) |
| metadata | TEXT | JSON: {rating, trend} |
| created_at | TEXT | ISO timestamp |

**Constraints**: `UNIQUE(date, pipeline_type)` — one row per pipeline type per day.

### job_records

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| run_id | INTEGER | GitHub Actions run ID |
| job_name | TEXT | Full job name |
| workflow_name | TEXT | Workflow name |
| pipeline_type | TEXT | pr_e2e, nightly, build, other |
| conclusion | TEXT | success, failure, skipped, cancelled |
| duration_sec | REAL | completed_at - started_at |
| queue_sec | REAL | started_at - run.created_at |
| started_at | TEXT | ISO timestamp |
| completed_at | TEXT | ISO timestamp |
| created_at | TEXT | Record insertion time |

**Constraints**: `UNIQUE(run_id, job_name)` via INSERT OR IGNORE.

## Queries

```sql
-- Trend: last 30 days success rate per pipeline type
SELECT date, success_rate, health_score
FROM daily_snapshots
WHERE pipeline_type = 'pr_e2e' AND date >= date('now', '-30 days')
ORDER BY date;

-- Slowest jobs this week
SELECT job_name, duration_sec, pipeline_type
FROM job_records
WHERE created_at >= date('now', '-7 days')
ORDER BY duration_sec DESC LIMIT 10;

-- Consecutive failure detection
SELECT workflow_name, conclusion, started_at
FROM job_records
WHERE pipeline_type = 'nightly'
ORDER BY workflow_name, started_at DESC;
```

## JSON Snapshot Format

`docs/reports/daily-snapshots.json`:

```json
{
  "generated_at": "2026-06-01T08:00:00Z",
  "pipeline_types": {
    "pr_e2e": [
      {"date": "2026-06-01", "total": 168, "success": 86, "failure": 82,
       "success_rate": 48.8, "health_score": 14.0, "avg_duration_sec": 149.6,
       "rating": "danger", "trend": "down"}
    ],
    "nightly": [
      {"date": "2026-06-01", "total": 128, "success": 82, "failure": 46,
       "success_rate": 64.1, "health_score": 0.0, "avg_duration_sec": 121.5,
       "rating": "danger", "trend": "down"}
    ]
  }
}
```

Dashboard 的健康概览页签加载此文件渲染趋势折线图。
## Trend Axis Correction

`docs/reports/daily-snapshots.json` must distinguish two axes:

- `execution_trends`: CI execution date, derived from `job.completed_at`,
  `job.started_at`, or run timestamps. Use this for success-rate and
  failure-count trend charts.
- `pipeline_types`: dashboard snapshot date, derived from collection/export
  time. Use this only for explicitly labeled snapshot charts, such as health
  score snapshot trend.

Do not use snapshot dates for charts labeled as CI execution trends.

## CI Metadata Sampling Targets

The lightweight CI metadata collector must not stop only because measured job
counts are high enough. For trend charts, the sample also needs enough distinct
CI execution dates.

Recommended default for a seven-day health dashboard:

- measured target: at least five success/failure jobs per core pipeline
  (`pr_e2e` and `nightly`)
- execution-date target: at least seven distinct CI execution dates when the
  upstream repository has runs across those dates

If the configured run limit is exhausted before the execution-date target is
met, the dashboard must expose the sampled execution-date count so users can see
that the trend has limited temporal coverage.

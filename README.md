# vllm-ascend-ci-insight

## Local Data Bootstrap

The repository commits static dashboard data under `docs/reports/`. Local runtime
state is intentionally ignored:

- `data/`: SQLite database for local dynamic deployment.
- `reports/`: local report/cache output.

After cloning, rebuild the local SQLite database from committed static JSON:

```bash
python -m src --import-static
```

This imports `docs/reports/daily-snapshots.json` and `docs/reports/ci-runs.json`
into `data/metrics.db`.

To refresh current lightweight CI metadata without running AI analysis:

```bash
python -m src --health --refresh-ci-metrics --days 7 --metrics-limit 300 --metrics-min-measured-per-pipeline 10 --no-notify
```

For full-period operation, prefer the resumable split workflow:

```bash
# 1. Refresh lightweight workflow-run inventory.
python -m src --collect-run-inventory --days 7 --metrics-collection-strategy date_partition

# 2. Enrich missing job details within an explicit API budget.
python -m src --collect-job-details --days 7 --metrics-job-detail-limit 500

# 3. Export SQLite-backed data for the static dashboard.
python -m src --export-ci-metadata --health --days 7 --no-notify
```

Repeat step 2 until `coverage.job_details.quality` becomes `full` when a
complete objective period is required.

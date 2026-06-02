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

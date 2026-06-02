# ascend-ci-insight Design Documents

| Document | Description |
|----------|-------------|
| [architecture.md](architecture.md) | System overview, component diagram, data flow |
| [data-model.md](data-model.md) | Core entities: FailureReport, CIRun, CIJob, JobAnalysis |
| [database.md](database.md) | SQLite schema, JSON snapshot format, queries |
| [local-static-sync-architecture.md](local-static-sync-architecture.md) | Target architecture for SQLite local deployment, static JSON deployment, sync, collection, and AI analysis |
| [testing.md](testing.md) | Test strategy, 198-test suite, running guide |
| [pipeline-types.md](pipeline-types.md) | Pipeline classification rules (from config/rules.json) |
| [category-rules.md](category-rules.md) | Problem category classification rules |
| [dashboard-metrics.md](dashboard-metrics.md) | Dashboard metric definitions, aggregation levels, and calculation rules |
| [health-score.md](health-score.md) | Health score formula and rating thresholds |
| [alert-rules.md](alert-rules.md) | Alert rule definitions and cooldown mechanism |

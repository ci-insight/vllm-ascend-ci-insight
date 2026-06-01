# Architecture

## Overview

ascend-ci-insight 是 vllm-ascend 项目的 CI 流水线观测 + 智能诊断系统。

```
GitHub Actions (vllm-ascend)
    │ gh CLI
    ▼
Python Backend (src/)
    ├── collector.py    采集 PR/run/job/log 数据
    ├── analyzer.py     Claude CLI 智能分析
    ├── health.py       健康分计算 + 趋势聚合
    ├── alert.py        告警规则引擎
    ├── aggregator.py   SQLite 长期存储
    ├── interference.py PR 干扰检测
    ├── notify.py       飞书/Webhook 通知
    └── reporter.py     JSON + Markdown 报告生成
    │
    ├── reports/        本地输出
    └── docs/reports/   静态部署 (GitHub Pages)
    │
    ▼
Frontend (docs/)
    ├── index.html      SPA 看板 (3 tabs)
    ├── app.js          问题分析 + CI 执行分析
    ├── health.js       健康概览
    └── i18n.js         中英文切换
```

## Data Flow

```
[1] gh CLI → collector.py
    └── PR list → runs → jobs → logs
    └── ALL jobs stored (with timing), failed jobs get Claude analysis

[2] analyzer.py → Claude CLI
    └── classify + root cause + fix suggestions
    └── output: analysis JSON embedded in report

[3] reporter.py
    └── JSON (structured) + Markdown (human)
    └── reports/YYYY-MM-DD/pr-NNNNN.{json,md}
    └── reports/index.json

[4] health.py + alert.py + interference.py + aggregator.py
    └── health.json + alerts.json + interference.json
    └── SQLite daily snapshots for long-term trends

[5] Dashboard (static)
    └── Loads index.json → async loads all reports → charts
    └── Health tab loads health.json + daily-snapshots.json
```

## Single Source of Truth

`config/rules.json` 是分类规则的唯一来源，Python 和 JS 都从此加载：

- `pipeline_types`: PR CI/Nightly/Build 分类模式
- `categories`: lint/code/build/perf/infra/test/compat 分类模式
- `health_rating_thresholds`: 健康分评级阈值

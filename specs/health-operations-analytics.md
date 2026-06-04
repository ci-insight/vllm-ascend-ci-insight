# Health Operations Analytics

This document defines the product boundary and roadmap for operational CI health
analytics. It is intended for AI-assisted implementation work, so every chart
must identify whether it is based on collected CI facts or AI-derived failure
analysis.

## Product Boundary

The dashboard has two complementary analysis surfaces:

```text
Health Overview
  = operational health analysis over collected CI facts

Problem Analysis
  = AI root-cause analysis over collected failed samples
```

The boundary is important:

- Health Overview must stay fact-first. It should use collected workflow-run and
  job facts from the CI metadata model, plus deterministic aggregation rules.
- Problem Analysis may use AI classification, root-cause summaries, confidence,
  and fix suggestions, because it explains known failures rather than measuring
  the whole CI population.
- Health Overview may link to Problem Analysis for explanation, but it must not
  mix AI-derived categories or inferred root causes into base workflow/job
  counts, success rates, queue time, or duration metrics.

## Health To Problem Analysis Linkage

Health Overview should answer:

```text
What is unhealthy?
How large is the impact?
Which workflow/job should operators inspect first?
```

Problem Analysis should answer:

```text
Why did the known failures happen?
What category/root cause did AI infer?
What fixes are suggested?
```

The two tabs should be connected by explicit drill-down links, not by mixing
their metrics.

### Link Keys

Health-to-Problem links should use stable identifiers that already exist in the
data model:

| Link level | Keys |
| --- | --- |
| Pipeline | `pipeline_type` |
| Workflow | `pipeline_type`, `workflow_name` |
| Workflow run | `run_id`, `workflow_name` |
| Job | `job_id` when available; otherwise `workflow_name`, `job_name`, `run_id` |
| PR | `pr_number` |

Problem Analysis reports should be searchable/filterable by the same keys. When
one exact key is missing, the UI may fall back to a narrower available key, but
it must label the match as approximate.

### Health Overview Additions

Health cards, workflow charts, and job charts may show related AI context as a
secondary annotation:

```text
Related AI analyses: 5 failed-sample reports
Top AI category: Test Case
Top AI severity: High
```

Rules:

- Related AI context must be labeled `AI-derived from failed samples`.
- AI counts must not be added to CI fact counts.
- AI category/severity must not alter success rate, failure count, queue time,
  duration, or health base counts.
- Health charts should remain useful even when no AI reports exist.

### Problem Analysis Additions

Problem Analysis report cards may show related CI fact context:

```text
Workflow success rate in selected CI facts
Job failure count in selected CI facts
Whether the workflow/job appears in Health Top N lists
```

Rules:

- CI fact context must be labeled with the same collection window as
  `ci-runs.json`.
- Problem Analysis must not imply its failed samples are the full CI population.
- If the CI fact snapshot and AI report dates differ, the UI must show both
  timestamps or avoid displaying a single combined number.

Implemented baseline:

- PR detail analysis blocks show current CI fact context for the matching
  workflow/job when available.
- Problem Analysis drill-down modals show the same CI fact context.
- The CI fact context can open the matching Health workflow detail.

### Navigation Behavior

Recommended interactions:

1. Clicking a Health workflow opens either:
   - a Health detail modal with current fact metrics and a `View related AI
     analyses` action, or
   - the Problem Analysis tab with `pipeline_type` and `workflow_name` filters
     preselected.
2. Clicking a Health job opens job detail and offers a Problem Analysis filter
   by `job_id` or `(workflow_name, job_name)`.
3. Clicking a Problem Analysis report may show a small CI fact panel for the
   workflow/job if the current `ci-runs.json` snapshot contains matching facts.

### Empty And Partial States

| State | Behavior |
| --- | --- |
| Health issue has no AI report | Show fact metrics and `No related AI analysis in collected failed samples`. |
| AI report has no current CI fact match | Show AI report normally and label CI fact context as unavailable for the current snapshot. |
| Coverage is partial | Keep links available, but add the standard coverage warning. |
| Multiple approximate matches | Show the grouped result and label the match key used. |

## Source Of Truth

Current implementation:

```text
SQLite workflow_runs / ci_jobs
        |
        v
docs/reports/ci-runs.json
        |
        +--> CI Execution tab
        +--> Health Overview base counts and operational charts
```

`docs/reports/health.json` may add health scores, ratings, and alert state, but
its base facts must remain aligned with `ci-runs.json`:

- `workflow_runs`
- `total`
- `measured_total`
- `success`
- `failure`
- `skipped`
- `cancelled`
- `pending`
- `other`

Recommended future model:

```text
ci-facts snapshot
  facts.runs
  facts.jobs
  aggregates.by_pipeline
  aggregates.by_workflow
  aggregates.by_job
  coverage
  generated_at
  selection_window
```

Both CI Execution and Health Overview should read the same `aggregates` object
for base facts. Health Overview should only add scoring and alert interpretation.

## Current-Scope Charts

The following charts can be computed from already collected CI facts. They do
not require additional GitHub API calls or AI analysis.

### Workflow Health Ranking

Purpose: identify workflows that need operational attention first.

Level: workflow name.

Calculation:

```text
measured_jobs = success + failure
success_rate = success / measured_jobs
failure_count = failure
health_like_score = success_rate adjusted by failure_count and sample size
```

Display rule:

- show only workflows with `measured_jobs >= minMeasuredJobs`,
- sort by success rate ascending, then failure count descending,
- include workflow-run count, total jobs, and measured jobs in tooltip/detail.

### Workflow Failure Contribution Top N

Purpose: show whether failures are concentrated in a small set of workflows.

Calculation:

```text
workflow_failure_share = workflow.failure / total_failures
```

Display rule:

- bar chart sorted by `failure` descending,
- include cumulative share for the top N workflows when possible.

### Workflow Stability Matrix

Purpose: separate low-volume noise from high-impact instability.

Axes:

```text
x = success_rate
y = measured_jobs or workflow_runs
point_size = failure_count
color = pipeline_type or severity bucket
```

Display rule:

- use collected jobs only,
- show coverage/sample warning when job detail coverage is incomplete.

### Workflow Duration And Queue Top N

Purpose: identify slow workflows and runner-capacity pressure.

Metrics:

```text
workflow_wall_clock = max(job.completed_at) - min(job.started_at)
workflow_queue_time = max(job.started_at - job.created_at)
```

Display rule:

- show P50/P90 or average over workflow runs,
- queue chart must label that queue is derived from job-level queued time, not
  `run.created_at`.

### Lowest Job Success Rate Top N

Purpose: find flaky or broken jobs with enough samples to be actionable.

Level: normalized job identity, preferably `(workflow_name, normalized_job_name)`.

Calculation:

```text
measured_jobs = success + failure
success_rate = success / measured_jobs
```

Display rule:

- show only jobs with `measured_jobs >= minMeasuredJobs`,
- sort by success rate ascending, then failure count descending,
- do not include skipped/cancelled/pending in the success-rate denominator.

### Job Failure Contribution Top N

Purpose: identify jobs that contribute the largest absolute number of failures.

Calculation:

```text
job_failure_share = job.failure / total_failures
```

Display rule:

- sorted by failure count descending,
- include measured jobs and success rate to avoid overreacting to tiny samples.

### Neutral Outcome Distribution

Purpose: expose CI coverage and usability issues that success rate hides.

Buckets:

```text
skipped
cancelled
pending
other
```

Display rule:

- show by pipeline and optionally by workflow,
- explicitly state these buckets are excluded from measured success rate.

### Failure Concentration

Purpose: show whether remediation is concentrated or systemic.

Calculation:

```text
top_5_workflow_failure_share = sum(top5.workflow.failure) / total_failures
top_10_job_failure_share = sum(top10.job.failure) / total_failures
```

Interpretation:

- high concentration means focused workflow/job remediation can move the metric,
- low concentration means the CI problem is broadly distributed.

## Roadmap Charts

These should not be lost, but they may require more data retention, richer
aggregation, or AI-linked data.

### Failure Category Trend

Source: Problem Analysis AI reports.

Purpose: trend root-cause classes such as build script, test case, lint/format,
compatibility, and performance.

Boundary:

- keep this in Problem Analysis or label it as AI-derived if shown elsewhere,
- do not use it as a Health base fact.

### Queue P50/P90 Trend

Source: CI facts with job `created_at` and `started_at`.

Purpose: detect runner-capacity or scheduling pressure over time.

Need:

- retain queue-time aggregates by execution date,
- avoid relying on one static snapshot only.

### Long-Tail Duration Trend

Source: CI facts.

Purpose: identify whether CI is getting slower even when average duration looks
stable.

Metrics:

```text
job_duration_p50 / p90 / p99
workflow_wall_clock_p50 / p90 / p99
```

### Job Duration Variability Top N

Source: CI facts.

Purpose: identify unstable jobs whose runtime fluctuates heavily.

Calculation:

```text
variability = p90_duration / max(p50_duration, 1)
```

### Branch / Event / PR Dimension Analysis

Source: CI facts.

Purpose: distinguish pull request, schedule, workflow_dispatch, branch-specific,
and mainline operational behavior.

Need:

- preserve event, branch, and PR association consistently in the CI fact model.

### Runner Resource Bottleneck Analysis

Source: CI facts plus runner labels if collected.

Purpose: identify whether queue time or long duration is tied to runner class,
device type, or scarce hardware.

Need:

- collect and preserve runner labels or enough job metadata to infer runner
  class.

## Implementation Priority

P0:

- Workflow Failure Contribution Top N.
- Lowest Job Success Rate Top N.
- Neutral Outcome Distribution.
- Health-to-Problem links from unhealthy workflows/jobs, labeled as
  `AI-derived from failed samples`.

P1:

- Workflow Health Ranking.
- Job Failure Contribution Top N.
- Failure Concentration.
- Workflow Duration And Queue Top N.
- Problem Analysis cards with current CI fact context when matching facts exist.
- Health workflow detail rows can jump back to related AI failed-sample
  analyses.

P2:

- Workflow Stability Matrix.
- Queue P50/P90 Trend.
- Long-Tail Duration Trend.
- Failure Category Trend with explicit AI-derived labeling.

## Invariants

- Analyze collected data accurately; do not imply uncollected data is known.
- Every chart must disclose whether it is workflow-run level, job level, or
  AI-analysis level.
- Every success rate must use measured jobs only: `success / (success + failure)`.
- Skipped, cancelled, pending, and other neutral states must be visible somewhere
  because they affect CI usefulness even when they do not reduce success rate.
- Health Overview can link to AI explanations, but its base operational metrics
  must remain deterministic and fact-derived.

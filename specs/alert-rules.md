# Alert Rules Specification

Alerts are generated from `health.json` by `src/alert.py`. They are dashboard
alerts first; notification cooldown only suppresses repeated notification
sending, not dashboard visibility.

If `health_data.data_quality.complete_success_sample == false`, alert
evaluation returns no alerts. Failure-only data must not trigger global health
alerts.

## Cooldown Model

Cooldown state is stored in `reports/.alert_cooldown.json`.

For each alert:

```text
notification_suppressed = rule_key exists in active cooldowns
```

If not suppressed, the rule key is written with an expiry time:

```text
expires_at = now + cooldown_hours
```

Expired cooldowns are removed before evaluation.

## R001 Consecutive Failure

| Field | Value |
| --- | --- |
| Rule id | `R001` |
| Rule name | `Consecutive Failure` |
| Severity | `critical` |
| Cooldown | 2 hours |
| Rule key | `R001_{workflow}` |

Trigger:

```text
health_data.consecutive_failures[workflow] >= 2
```

Message:

```text
Workflow '{workflow}' has {streak} consecutive failures
```

Details:

- `workflow`,
- `streak`.

## R002 Low Health Score

| Field | Value |
| --- | --- |
| Rule id | `R002` |
| Rule name | `Low Health Score` |
| Severity | `warning` |
| Cooldown | 6 hours |
| Rule key | `R002_{pipeline_type}` |

Trigger:

```text
pipeline.health_score is not null
and pipeline.health_score < 70
```

Message:

```text
{pipeline_type} pipeline health score is {score}/100 (below 70)
```

Details:

- `pipeline_type`,
- `score`,
- `rating`.

## R003 Success Rate Drop

| Field | Value |
| --- | --- |
| Rule id | `R003` |
| Rule name | `Success Rate Drop` |
| Severity | `warning` |
| Cooldown | 4 hours |
| Rule key | `R003_{pipeline_type}` |

Input: pipeline `daily_trend`.

Trigger:

```text
len(daily_trend) >= 2
previous.success_rate > 0
drop = previous.success_rate - recent.success_rate
drop >= 20
```

`recent` is the last daily trend entry. `previous` is the entry immediately
before it.

Message:

```text
{pipeline_type} success rate dropped from {previous}% to {recent}% ({drop}% drop)
```

Details:

- `pipeline_type`,
- `drop`.

## R004 Nightly Failure

| Field | Value |
| --- | --- |
| Rule id | `R004` |
| Rule name | `Nightly Failure` |
| Severity | `critical` |
| Cooldown | 1 hour |
| Rule key | `R004` |

Trigger:

```text
health_data.pipelines.nightly.failure > 0
```

Message:

```text
Nightly pipeline has {failure} failed measured job(s) out of {measured_total}
```

Details:

- `pipeline_type = nightly`,
- `failures`,
- `measured_total`,
- `total`.

## Dashboard Rendering

`docs/health.js` renders all active alerts from `alerts.json` in the Health
Overview tab. Alert severity controls badge color:

- `critical` uses the critical badge,
- all other severities currently use the medium/warning badge.

## Invariants

- Do not emit alerts from incomplete or failure-only samples.
- Alert counts are counts of active alert objects, not counts of jobs or runs.
- Cooldown does not remove an active alert from the dashboard; it only marks
  `notification_suppressed`.

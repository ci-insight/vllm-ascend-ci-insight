"""Alert rule engine with cooldown mechanism."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .storage import DOCS_REPORTS_DIR, LOCAL_REPORTS_DIR, read_json, write_json

REPORTS_DIR = LOCAL_REPORTS_DIR
ALERTS_FILE = REPORTS_DIR / "alerts.json"
COOLDOWN_FILE = REPORTS_DIR / ".alert_cooldown.json"

ALERT_RULES = [
    {
        "id": "R001",
        "name": "Consecutive Failure",
        "description": "Same workflow failed >=2 times in a row",
        "severity": "critical",
        "cooldown_hours": 2,
    },
    {
        "id": "R002",
        "name": "Low Health Score",
        "description": "Pipeline health score below 70",
        "severity": "warning",
        "cooldown_hours": 6,
    },
    {
        "id": "R003",
        "name": "Success Rate Drop",
        "description": "24h success rate dropped >=20% vs previous 24h",
        "severity": "warning",
        "cooldown_hours": 4,
    },
    {
        "id": "R004",
        "name": "Nightly Failure",
        "description": "Nightly pipeline has failures",
        "severity": "critical",
        "cooldown_hours": 1,
    },
]


def _load_cooldowns() -> dict[str, str]:
    return read_json(COOLDOWN_FILE, default={}) or {}


def _save_cooldowns(cooldowns: dict[str, str]):
    COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
    COOLDOWN_FILE.write_text(json.dumps(cooldowns, indent=2), encoding="utf-8")


def evaluate(health_data: dict) -> list[dict]:
    """Evaluate alert rules against health data. Returns active alerts.

    Cooldown suppresses repeated notifications, but active dashboard alerts are
    still returned with notification_suppressed=true.
    """
    now = datetime.now(timezone.utc)
    cooldowns = _load_cooldowns()
    active_alerts: list[dict] = []

    def add_alert(rule_key: str, cooldown_hours: int, alert: dict):
        suppressed = rule_key in active_cooldowns
        alert["notification_suppressed"] = suppressed
        active_alerts.append(alert)
        if not suppressed:
            active_cooldowns[rule_key] = (now + timedelta(hours=cooldown_hours)).isoformat()

    # Clean expired cooldowns
    active_cooldowns = {}
    for rule_id, until_str in cooldowns.items():
        try:
            until = datetime.fromisoformat(until_str)
            if until > now:
                active_cooldowns[rule_id] = until_str
        except ValueError:
            pass

    pipelines = health_data.get("pipelines", {})
    consecutive = health_data.get("consecutive_failures", {})
    data_quality = health_data.get("data_quality", {})
    if data_quality.get("complete_success_sample") is False:
        _save_cooldowns(active_cooldowns)
        return []

    # R001: Consecutive failures
    if consecutive:
        for wf, streak in consecutive.items():
            rule_id = f"R001_{wf}"
            add_alert(
                rule_id,
                2,
                {
                    "rule_id": "R001",
                    "rule_name": "Consecutive Failure",
                    "severity": "critical",
                    "message": f"Workflow '{wf}' has {streak} consecutive failures",
                    "details": {"workflow": wf, "streak": streak},
                    "triggered_at": now.isoformat(),
                },
            )

    # R002: Low health score per pipeline
    for ptype, pdata in pipelines.items():
        score = pdata.get("health_score", 100)
        if score is None:
            continue
        if score < 70:
            rule_id = f"R002_{ptype}"
            add_alert(
                rule_id,
                6,
                {
                    "rule_id": "R002",
                    "rule_name": "Low Health Score",
                    "severity": "warning",
                    "message": f"{ptype} pipeline health score is {score}/100 (below 70)",
                    "details": {"pipeline_type": ptype, "score": score, "rating": pdata.get("rating")},
                    "triggered_at": now.isoformat(),
                },
            )

    # R003: Success rate drop (check daily trends)
    for ptype, pdata in pipelines.items():
        daily = pdata.get("daily_trend", [])
        if len(daily) >= 2:
            recent = daily[-1]
            previous = daily[-2]
            if previous.get("success_rate", 0) > 0:
                drop = previous["success_rate"] - recent.get("success_rate", 0)
                if drop >= 20:
                    rule_id = f"R003_{ptype}"
                    add_alert(
                        rule_id,
                        4,
                        {
                            "rule_id": "R003",
                            "rule_name": "Success Rate Drop",
                            "severity": "warning",
                            "message": f"{ptype} success rate dropped from {previous['success_rate']}% to {recent['success_rate']}% ({drop}% drop)",
                            "details": {"pipeline_type": ptype, "drop": drop},
                            "triggered_at": now.isoformat(),
                        },
                    )

    # R004: Nightly pipeline failure
    nightly = pipelines.get("nightly", {})
    if nightly.get("failure", 0) > 0:
        rule_id = "R004"
        add_alert(
            rule_id,
            1,
            {
                "rule_id": "R004",
                "rule_name": "Nightly Failure",
                "severity": "critical",
                "message": f"Nightly pipeline has {nightly['failure']} failed measured job(s) out of {nightly.get('measured_total', nightly.get('total', 0))}",
                "details": {
                    "pipeline_type": "nightly",
                    "failures": nightly["failure"],
                    "measured_total": nightly.get("measured_total", nightly.get("total", 0)),
                    "total": nightly.get("total", 0),
                },
                "triggered_at": now.isoformat(),
            },
        )

    _save_cooldowns(active_cooldowns)
    return active_alerts


def save_alerts(alerts: list[dict]):
    ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "alerts": alerts,
    }
    write_json(ALERTS_FILE, data)
    docs_path = DOCS_REPORTS_DIR / "alerts.json"
    write_json(docs_path, data)
    if alerts:
        print(f"  Alerts: {len(alerts)} active -> {ALERTS_FILE}")
    else:
        print(f"  Alerts: none active")

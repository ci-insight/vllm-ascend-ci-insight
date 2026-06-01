"""Alert rule engine with cooldown mechanism."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

REPORTS_DIR = Path("reports")
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
    if COOLDOWN_FILE.exists():
        try:
            return json.loads(COOLDOWN_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_cooldowns(cooldowns: dict[str, str]):
    COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
    COOLDOWN_FILE.write_text(json.dumps(cooldowns, indent=2))


def evaluate(health_data: dict) -> list[dict]:
    """Evaluate alert rules against health data. Returns triggered alerts.

    Respects cooldown: a rule won't re-fire within its cooldown window.
    """
    now = datetime.now(timezone.utc)
    cooldowns = _load_cooldowns()
    triggered: list[dict] = []

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

    # R001: Consecutive failures
    if consecutive:
        for wf, streak in consecutive.items():
            rule_id = f"R001_{wf}"
            if rule_id not in active_cooldowns:
                triggered.append({
                    "rule_id": "R001",
                    "rule_name": "Consecutive Failure",
                    "severity": "critical",
                    "message": f"Workflow '{wf}' has {streak} consecutive failures",
                    "details": {"workflow": wf, "streak": streak},
                    "triggered_at": now.isoformat(),
                })
                active_cooldowns[rule_id] = (now + timedelta(hours=2)).isoformat()

    # R002: Low health score per pipeline
    for ptype, pdata in pipelines.items():
        score = pdata.get("health_score", 100)
        if score < 70:
            rule_id = f"R002_{ptype}"
            if rule_id not in active_cooldowns:
                triggered.append({
                    "rule_id": "R002",
                    "rule_name": "Low Health Score",
                    "severity": "warning",
                    "message": f"{ptype} pipeline health score is {score}/100 (below 70)",
                    "details": {"pipeline_type": ptype, "score": score, "rating": pdata.get("rating")},
                    "triggered_at": now.isoformat(),
                })
                active_cooldowns[rule_id] = (now + timedelta(hours=6)).isoformat()

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
                    if rule_id not in active_cooldowns:
                        triggered.append({
                            "rule_id": "R003",
                            "rule_name": "Success Rate Drop",
                            "severity": "warning",
                            "message": f"{ptype} success rate dropped from {previous['success_rate']}% to {recent['success_rate']}% ({drop}% drop)",
                            "details": {"pipeline_type": ptype, "drop": drop},
                            "triggered_at": now.isoformat(),
                        })
                        active_cooldowns[rule_id] = (now + timedelta(hours=4)).isoformat()

    # R004: Nightly pipeline failure
    nightly = pipelines.get("nightly", {})
    if nightly.get("failure", 0) > 0:
        rule_id = "R004"
        if rule_id not in active_cooldowns:
            triggered.append({
                "rule_id": "R004",
                "rule_name": "Nightly Failure",
                "severity": "critical",
                "message": f"Nightly pipeline has {nightly['failure']} failure(s) out of {nightly.get('total', 0)} runs",
                "details": {"pipeline_type": "nightly", "failures": nightly["failure"], "total": nightly.get("total", 0)},
                "triggered_at": now.isoformat(),
            })
            active_cooldowns[rule_id] = (now + timedelta(hours=1)).isoformat()

    _save_cooldowns(active_cooldowns)
    return triggered


def save_alerts(alerts: list[dict]):
    ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "alerts": alerts,
    }
    ALERTS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    docs_path = Path("docs/reports/alerts.json")
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    docs_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    if alerts:
        print(f"  Alerts: {len(alerts)} triggered -> {ALERTS_FILE}")
    else:
        print(f"  Alerts: none triggered")

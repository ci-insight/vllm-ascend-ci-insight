"""Test alert rule engine."""

import pytest
from pathlib import Path
from src.alert import evaluate, COOLDOWN_FILE


@pytest.fixture(autouse=True)
def clear_cooldown():
    """Clear cooldown file before each test for isolation."""
    if COOLDOWN_FILE.exists():
        COOLDOWN_FILE.unlink()
    yield
    if COOLDOWN_FILE.exists():
        COOLDOWN_FILE.unlink()


def make_health_data(pipelines=None, consecutive=None):
    return {
        "pipelines": pipelines or {},
        "consecutive_failures": consecutive or {},
    }


def test_consecutive_failure_alert():
    health = make_health_data(
        pipelines={"pr_e2e": {"total": 10, "success": 5, "failure": 5, "health_score": 50, "rating": "danger", "daily_trend": []}},
        consecutive={"E2E-Light": 3},
    )
    alerts = evaluate(health)
    assert any(a["rule_id"] == "R001" for a in alerts)


def test_low_health_alert():
    health = make_health_data(
        pipelines={"nightly": {"total": 10, "success": 2, "failure": 8, "health_score": 30, "rating": "danger", "daily_trend": []}},
    )
    alerts = evaluate(health)
    assert any(a["rule_id"] == "R002" for a in alerts)


def test_healthy_no_alert():
    health = make_health_data(
        pipelines={"pr_e2e": {"total": 10, "success": 9, "failure": 1, "health_score": 90, "rating": "good", "daily_trend": []}},
    )
    alerts = evaluate(health)
    assert not any(a["rule_id"] == "R002" for a in alerts)


def test_nightly_failure_alert():
    health = make_health_data(
        pipelines={"nightly": {"total": 5, "success": 4, "failure": 1, "health_score": 80, "rating": "good", "daily_trend": []}},
    )
    alerts = evaluate(health)
    assert any(a["rule_id"] == "R004" for a in alerts)


def test_success_rate_drop_alert():
    health = make_health_data(
        pipelines={"pr_e2e": {
            "total": 10, "success": 5, "failure": 5, "health_score": 50, "rating": "danger",
            "daily_trend": [
                {"date": "2026-06-01", "total": 10, "success": 8, "failure": 2, "success_rate": 80, "health": 50},
                {"date": "2026-06-02", "total": 10, "success": 3, "failure": 7, "success_rate": 30, "health": 20},
            ]
        }},
    )
    alerts = evaluate(health)
    assert any(a["rule_id"] == "R003" for a in alerts)


def test_cooldown_prevents_duplicate():
    """Running evaluate twice should not produce duplicate alerts (cooldown)."""
    health = make_health_data(
        pipelines={"nightly": {"total": 5, "success": 4, "failure": 1, "health_score": 80, "rating": "good", "daily_trend": []}},
    )
    alerts1 = evaluate(health)
    alerts2 = evaluate(health)
    assert len(alerts2) == 0  # cooldown prevents re-fire

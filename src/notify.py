"""Multi-channel notification: Feishu CLI + Webhook."""

from __future__ import annotations

import json
import os
import subprocess
import sys


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def send_feishu(message: str, chat_id: str = "") -> bool:
    """Send notification via Feishu CLI.

    Requires: feishu CLI installed and authenticated.
    Install: https://github.com/long2ice/feishu-cli
    """
    target = chat_id or _env("FEISHU_CHAT_ID")
    if not target:
        print("  Feishu: skipped (no FEISHU_CHAT_ID)", file=sys.stderr)
        return False

    result = subprocess.run(
        ["feishu", "message", "send", "--type", "text", "--content", message, "--chat-id", target],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    if result.returncode == 0:
        print(f"  Feishu: sent to {target}")
        return True
    else:
        print(f"  Feishu: failed - {result.stderr.strip()}", file=sys.stderr)
        return False


def send_webhook(message: str, url: str = "") -> bool:
    """Send notification via generic Webhook URL (DingTalk, WeChat Work, etc.)."""
    target = url or _env("NOTIFY_WEBHOOK_URL")
    if not target:
        print("  Webhook: skipped (no NOTIFY_WEBHOOK_URL)", file=sys.stderr)
        return False

    import urllib.request

    payload = json.dumps({
        "msgtype": "text",
        "text": {"content": message},
    }).encode()

    try:
        req = urllib.request.Request(target, data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
        print(f"  Webhook: sent")
        return True
    except Exception as e:
        print(f"  Webhook: failed - {e}", file=sys.stderr)
        return False


def notify_alerts(alerts: list[dict]) -> int:
    """Send notifications for triggered alerts. Returns count of sent notifications."""
    if not alerts:
        return 0

    sent = 0
    for alert in alerts:
        if alert.get("notification_suppressed"):
            continue
        sev = alert["severity"].upper()
        msg = f"[{sev}] {alert['rule_name']}: {alert['message']}"

        if send_feishu(msg):
            sent += 1
        if send_webhook(msg):
            sent += 1

    return sent

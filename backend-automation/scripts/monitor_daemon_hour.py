#!/usr/bin/env python3
"""One-hour daemon progress monitor. Writes snapshots to ~/.leadway/monitor_report.jsonl"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import django

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "linkedin.django_settings")
django.setup()

from django.utils import timezone as dj_tz

from crm.models import Lead
from linkedin.models import ActionLog, InstagramProfile, Task
from linkedin.services.daemon_control import LOG_FILE, daemon_status

REPORT = Path.home() / ".leadway" / "monitor_report.jsonl"
INTERVAL_SEC = 300
DURATION_SEC = 3600

ACTION_PATTERNS = {
    "connect": re.compile(r"\bCONNECTED\b|\bPENDING\b|▶ connect\b", re.I),
    "follow_up_draft": re.compile(r"follow_up drafted message|▶ follow_up\b", re.I),
    "send_message": re.compile(r"▶ send_message\b|message sent|Send verified", re.I),
    "new_lead": re.compile(r"Created enriched lead for", re.I),
    "skipped_rate": re.compile(r"rate limit|can_execute|skipped.*limit", re.I),
    "outside_hours": re.compile(r"Outside active hours", re.I),
}


def snapshot(label: str, baseline: dict) -> dict:
    now = dj_tz.now()
    profile = InstagramProfile.objects.filter(user__username="nittish", active=True).first()
    log_text = LOG_FILE.read_text(encoding="utf-8", errors="replace") if LOG_FILE.exists() else ""
    counts = {
        "leads_total": Lead.objects.count(),
        "actions_total": ActionLog.objects.count(),
        "pending_tasks": Task.objects.filter(status=Task.Status.PENDING).count(),
        "completed_tasks": Task.objects.filter(status=Task.Status.COMPLETED).count(),
        "failed_tasks": Task.objects.filter(status=Task.Status.FAILED).count(),
        "connect_actions_today": 0,
        "follow_up_actions_today": 0,
    }
    if profile:
        counts["connect_actions_today"] = profile._daily_count("connect")
        counts["follow_up_actions_today"] = profile._daily_count("follow_up")
        counts["follow_daily_limit"] = profile.follow_daily_limit
        counts["follow_up_daily_limit"] = profile.follow_up_daily_limit

    log_hits = {k: len(p.findall(log_text)) for k, p in ACTION_PATTERNS.items()}
    row = {
        "label": label,
        "at": now.isoformat(),
        "daemon": daemon_status().__dict__,
        "counts": counts,
        "delta_since_start": {
            k: counts.get(k, 0) - baseline.get(k, 0)
            for k in ("leads_total", "actions_total", "completed_tasks", "failed_tasks", "connect_actions_today", "follow_up_actions_today")
        },
        "log_hits": log_hits,
        "log_tail": log_text.splitlines()[-25:],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")
    print(f"[{label}] leads+{row['delta_since_start']['leads_total']} actions+{row['delta_since_start']['actions_total']} connect_today={counts.get('connect_actions_today')} follow_up_today={counts.get('follow_up_actions_today')} daemon_running={row['daemon']['running']}", flush=True)
    return row


def main() -> None:
    print(f"Monitoring for {DURATION_SEC // 60} minutes. Log: {LOG_FILE}", flush=True)
    baseline_row = snapshot("start", {})
    baseline = baseline_row["counts"]
    started = time.monotonic()
    tick = 0
    while time.monotonic() - started < DURATION_SEC:
        time.sleep(INTERVAL_SEC)
        tick += 1
        snapshot(f"t+{tick * INTERVAL_SEC // 60}m", baseline)
        if not daemon_status().running:
            print("Daemon stopped early.", flush=True)
            break
    snapshot("end", baseline)
    print(f"Report written to {REPORT}", flush=True)


if __name__ == "__main__":
    main()

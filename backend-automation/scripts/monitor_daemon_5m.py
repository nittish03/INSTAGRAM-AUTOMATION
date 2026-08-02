#!/usr/bin/env python3
"""Poll daemon progress every 5 minutes; append to ~/.leadway/monitor_5m.jsonl"""
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

from chat.models import ChatMessage
from crm.models import Lead
from linkedin.models import ActionLog, LinkedInProfile, Task

LIVE_LOG = Path.home() / ".leadway" / "daemon_live.log"
REPORT = Path.home() / ".leadway" / "monitor_5m.jsonl"
INTERVAL_SEC = 300
HANDLE = "nittish"

ERROR_RE = re.compile(r"\b(ERROR|Traceback|failed|skipped)\b", re.I)
TASK_DONE_RE = re.compile(
    r"Task (\S+) (completed|skipped|failed|\[completed\]|\[skipped\]|\[failed\])",
    re.I,
)
TASK_START_RE = re.compile(r"▶ (\S+)(?: (\S+))?", re.I)
DRAFT_RE = re.compile(r"follow_up drafted message for (\S+)", re.I)
SEND_RE = re.compile(r"Dispatching approved message for (\S+)", re.I)


def _profile():
    return LinkedInProfile.objects.filter(user__username=HANDLE, active=True).first()


def snapshot(since_ts: float, since_dt, log_offset: int, tick: int) -> dict:
    profile = _profile()
    log_text = ""
    new_log = ""
    if LIVE_LOG.exists():
        log_text = LIVE_LOG.read_text(encoding="utf-8", errors="replace")
        new_log = log_text[log_offset:]

    events = {
        "tasks_started": TASK_START_RE.findall(new_log),
        "drafts": DRAFT_RE.findall(new_log),
        "sends_attempted": SEND_RE.findall(new_log),
        "task_outcomes": TASK_DONE_RE.findall(new_log),
    }
    errors = [ln.strip() for ln in new_log.splitlines() if ERROR_RE.search(ln)][-15:]

    db = {
        "pending_tasks": Task.objects.filter(status=Task.Status.PENDING).count(),
        "running_tasks": list(
            Task.objects.filter(status=Task.Status.RUNNING).values_list("task_type", "payload")
        ),
        "completed_since_start": Task.objects.filter(
            status=Task.Status.COMPLETED, ended_at__gte=since_dt
        ).count(),
        "failed_since_start": Task.objects.filter(
            status=Task.Status.FAILED, ended_at__gte=since_dt
        ).count(),
        "skipped_since_start": Task.objects.filter(
            status=Task.Status.SKIPPED, ended_at__gte=since_dt
        ).count(),
        "connects_today": profile._daily_count("connect") if profile else 0,
        "follow_ups_today": profile._daily_count("follow_up") if profile else 0,
        "leads_total": Lead.objects.count(),
        "drafts_awaiting": ChatMessage.objects.filter(
            owner__username=HANDLE, is_draft=True, is_approved=False
        ).count(),
    }

    row = {
        "tick": tick,
        "label": f"t+{tick * INTERVAL_SEC // 60}m",
        "at": dj_tz.now().isoformat(),
        "elapsed_min": tick * INTERVAL_SEC // 60,
        "events_in_interval": events,
        "errors_in_interval": errors,
        "database": db,
        "log_tail": log_text.splitlines()[-12:],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")

    print(
        f"[{row['label']}] started={len(events['tasks_started'])} "
        f"drafts={len(events['drafts'])} sends={len(events['sends_attempted'])} "
        f"outcomes={len(events['task_outcomes'])} errors={len(errors)} "
        f"pending={db['pending_tasks']} running={len(db['running_tasks'])}",
        flush=True,
    )
    return row, len(log_text)


def main() -> None:
    since_dt = dj_tz.now()
    since_ts = time.monotonic()
    log_offset = LIVE_LOG.stat().st_size if LIVE_LOG.exists() else 0
    tick = 0
    print(f"5-min monitor started. Log={LIVE_LOG} report={REPORT}", flush=True)

    while True:
        time.sleep(INTERVAL_SEC)
        tick += 1
        _, log_offset = snapshot(since_ts, since_dt, log_offset, tick)


if __name__ == "__main__":
    main()

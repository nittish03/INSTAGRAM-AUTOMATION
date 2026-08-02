#!/usr/bin/env python3
"""Monitor daemon for 3 hours; write 1-hour and 3-hour summary reports."""
from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
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

STATE_DIR = Path.home() / ".leadway"
LIVE_LOG = STATE_DIR / "daemon_live.log"
REPORT_JSONL = STATE_DIR / "monitor_report.jsonl"
HOUR1_REPORT = STATE_DIR / "hour1_report.json"
FINAL_REPORT = STATE_DIR / "hour3_report.json"

INTERVAL_SEC = 300
DURATION_SEC = 3 * 3600
HOUR1_SEC = 3600
HANDLE = "nittish"

ERROR_PATTERNS = [
    re.compile(r"\bERROR\b"),
    re.compile(r"\bTraceback\b"),
    re.compile(r"Task .+ failed"),
    re.compile(r"authentication failed", re.I),
    re.compile(r"LLM configuration invalid", re.I),
    re.compile(r"API key not valid", re.I),
    re.compile(r"OperationalError"),
]

EVENT_PATTERNS = {
    "follow_up_drafted": re.compile(r"follow_up drafted message for (\S+)", re.I),
    "follow_up_wait": re.compile(r"follow_up agent for (\S+): wait", re.I),
    "connect_started": re.compile(r"▶ connect\b", re.I),
    "connect_pending": re.compile(r"(\S+) PENDING\b"),
    "connect_connected": re.compile(r"(\S+) CONNECTED\b"),
    "send_message": re.compile(r"▶ send_message\b", re.I),
    "new_lead": re.compile(r"Created enriched lead for (\S+)", re.I),
    "task_failed": re.compile(r"Task (\S+) \[failed\]", re.I),
    "task_skipped": re.compile(r"Task (\S+) skipped:", re.I),
}


def _parse_start_from_log() -> datetime:
    if LIVE_LOG.exists():
        for line in LIVE_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
            if "Daemon started" in line:
                break
    return dj_tz.now() - timedelta(seconds=30)


def _profile() -> LinkedInProfile | None:
    return LinkedInProfile.objects.filter(user__username=HANDLE, active=True).first()


def _db_snapshot(since: datetime) -> dict:
    profile = _profile()
    data = {
        "at": dj_tz.now().isoformat(),
        "leads_total": Lead.objects.count(),
        "new_leads_since_start": Lead.objects.filter(creation_date__gte=since).count()
        if hasattr(Lead, "creation_date")
        else Lead.objects.filter(id__gt=0).count(),
        "pending_tasks": Task.objects.filter(status=Task.Status.PENDING).count(),
        "running_tasks": Task.objects.filter(status=Task.Status.RUNNING).count(),
        "completed_tasks_since_start": Task.objects.filter(
            status=Task.Status.COMPLETED, ended_at__gte=since
        ).count(),
        "failed_tasks_since_start": Task.objects.filter(
            status=Task.Status.FAILED, ended_at__gte=since
        ).count(),
        "skipped_tasks_since_start": Task.objects.filter(
            status=Task.Status.SKIPPED, ended_at__gte=since
        ).count(),
        "drafts_created_since_start": ChatMessage.objects.filter(
            is_draft=True, creation_date__gte=since, owner__username=HANDLE
        ).count(),
        "messages_sent_since_start": ActionLog.objects.filter(
            action_type=ActionLog.ActionType.FOLLOW_UP,
            status=ActionLog.Status.SUCCESS,
            created_at__gte=since,
        ).count(),
        "connects_sent_since_start": ActionLog.objects.filter(
            action_type=ActionLog.ActionType.CONNECT,
            status=ActionLog.Status.SUCCESS,
            created_at__gte=since,
        ).count(),
    }
    if profile:
        data["connect_actions_today"] = profile._daily_count("connect")
        data["follow_up_actions_today"] = profile._daily_count("follow_up")
        data["connect_daily_limit"] = profile.connect_daily_limit
        data["follow_up_daily_limit"] = profile.follow_up_daily_limit
    return data


def _parse_log(since_line_count: int = 0) -> dict:
    text = LIVE_LOG.read_text(encoding="utf-8", errors="replace") if LIVE_LOG.exists() else ""
    lines = text.splitlines()
    new_lines = lines[since_line_count:]
    events = Counter()
    details: dict[str, list[str]] = {k: [] for k in EVENT_PATTERNS}
    errors: list[str] = []

    for line in new_lines:
        for pat in ERROR_PATTERNS:
            if pat.search(line):
                errors.append(line.strip())
                break
        for name, pat in EVENT_PATTERNS.items():
            m = pat.search(line)
            if m:
                events[name] += 1
                if m.groups():
                    details[name].append(m.group(1))

    return {
        "total_log_lines": len(lines),
        "new_lines": len(new_lines),
        "events": dict(events),
        "event_details": {k: v for k, v in details.items() if v},
        "errors": errors[-20:],
        "log_tail": lines[-30:],
    }


def _write_report(path: Path, label: str, since: datetime, baseline: dict, log_parsed: dict) -> dict:
    snap = _db_snapshot(since)
    report = {
        "label": label,
        "generated_at": dj_tz.now().isoformat(),
        "monitoring_since": since.isoformat(),
        "elapsed_minutes": round((dj_tz.now() - since).total_seconds() / 60, 1),
        "profile": HANDLE,
        "database": snap,
        "delta": {
            k: snap.get(k, 0) - baseline.get(k, 0)
            for k in (
                "leads_total",
                "pending_tasks",
                "completed_tasks_since_start",
                "failed_tasks_since_start",
                "skipped_tasks_since_start",
                "drafts_created_since_start",
                "messages_sent_since_start",
                "connects_sent_since_start",
                "connect_actions_today",
                "follow_up_actions_today",
            )
        },
        "log_events": log_parsed.get("events", {}),
        "log_event_details": log_parsed.get("event_details", {}),
        "errors_in_log": log_parsed.get("errors", []),
        "issues_found": len(log_parsed.get("errors", [])),
        "log_tail": log_parsed.get("log_tail", []),
    }
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    with REPORT_JSONL.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(report, default=str) + "\n")
    return report


def main() -> None:
    since = _parse_start_from_log()
    baseline = _db_snapshot(since)
    baseline["completed_tasks_since_start"] = 0
    baseline["failed_tasks_since_start"] = 0
    baseline["skipped_tasks_since_start"] = 0
    baseline["drafts_created_since_start"] = 0
    baseline["messages_sent_since_start"] = 0
    baseline["connects_sent_since_start"] = 0

    print(f"Monitoring {HANDLE} for {DURATION_SEC // 3600}h. Live log: {LIVE_LOG}", flush=True)
    started = time.monotonic()
    last_line_count = 0
    hour1_written = HOUR1_REPORT.exists() and HOUR1_REPORT.stat().st_mtime > started - 60

    while time.monotonic() - started < DURATION_SEC:
        parsed = _parse_log(last_line_count)
        last_line_count = parsed["total_log_lines"]
        elapsed = time.monotonic() - started
        label = f"t+{int(elapsed // 60)}m"
        snap = _write_report(REPORT_JSONL.with_name(f"snapshot_{label}.json"), label, since, baseline, parsed)
        err_n = len(parsed["errors"])
        print(
            f"[{label}] drafts+{snap['delta']['drafts_created_since_start']} "
            f"connects+{snap['delta']['connects_sent_since_start']} "
            f"msgs_sent+{snap['delta']['messages_sent_since_start']} "
            f"new_leads+{snap['database'].get('new_leads_since_start', 0)} "
            f"errors+{err_n} pending={snap['database']['pending_tasks']}",
            flush=True,
        )

        if elapsed >= HOUR1_SEC and not hour1_written:
            hour1 = _write_report(HOUR1_REPORT, "hour1", since, baseline, _parse_log(0))
            hour1_written = True
            print(f"=== 1-HOUR REPORT WRITTEN → {HOUR1_REPORT} ===", flush=True)

        if err_n:
            print("  ⚠ errors detected:", parsed["errors"][-3:], flush=True)

        if not LIVE_LOG.exists():
            print("  ⚠ live log missing — daemon may have stopped", flush=True)

        time.sleep(INTERVAL_SEC)

    final = _write_report(FINAL_REPORT, "hour3", since, baseline, _parse_log(0))
    print(f"=== 3-HOUR REPORT WRITTEN → {FINAL_REPORT} ===", flush=True)
    print(json.dumps(final.get("delta", {}), indent=2), flush=True)


if __name__ == "__main__":
    main()

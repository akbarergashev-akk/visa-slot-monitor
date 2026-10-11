"""Best-effort Tashkent-time scheduled Short Stay calendar monitoring.

GitHub cron fires at xx:30, thirty minutes before each desired top-of-hour.
Within one warm runner, checks are aligned to :00, :02, :04.
Missed checks are skipped rather than made up outside the intended window.
If login is required, persist a non-sensitive pause flag and alert once.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tashkent")
HERE = Path(__file__).resolve().parent
STATUS = HERE / "calendar_schedule_status.json"
GRACE_SECONDS = 15


def target_hour_from_event() -> int:
    path = os.getenv("GITHUB_EVENT_PATH")
    if not path:
        raise ValueError("GITHUB_EVENT_PATH_NOT_SET")
    event = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(event, dict):
        raise ValueError("INVALID_EVENT")
    cron = event.get("schedule", "")
    match = re.fullmatch(r"30 (5|6|7|8|9|10|11) \* \* \*", cron)
    if not match:
        raise ValueError("UNRECOGNIZED_CRON_EXPRESSION")
    return int(match.group(1)) + 1


def status_paused() -> bool:
    if not STATUS.exists():
        return False
    data = json.loads(STATUS.read_text(encoding="utf-8"))
    return bool(data.get("auth_paused", False))


def set_paused(value: bool) -> None:
    STATUS.write_text(json.dumps({"auth_paused": value}, indent=2) + "\n", encoding="utf-8")


def run_monitor_once() -> int:
    from calendar_change_watcher import main
    try:
        return int(main())
    except Exception:
        print("RESULT: CHECK_ERROR (details withheld)")
        return 3


def notify_auth_pause() -> None:
    try:
        from calendar_change_watcher import send_telegram
        send_telegram("⚠️ Виза календарини кузатиш тўхтатилди: сайт қайта логин талаб қиляпти. "
                      "GitHub'даги AUTH_STATE_B64 сессиясини янгилаш керак. "
                      "Ҳозир бўш слотлар текширилмаяпти.")
        print("AUTH_PAUSE_NOTICE: Telegram sent")
    except Exception:
        print("AUTH_PAUSE_NOTICE: Telegram delivery failed; see GitHub run")


def try_one_check() -> int:
    result = run_monitor_once()
    if result == 4:
        set_paused(True)
        notify_auth_pause()
        print("RESULT: AUTH_PAUSED; no more checks until session is restored")
    return result


def main() -> int:
    now = datetime.now(TZ)
    event_name = os.getenv("GITHUB_EVENT_NAME", "")

    if event_name == "workflow_dispatch":
        # Only after a new secret was saved: manual reset and one verification.
        event_file = os.getenv("GITHUB_EVENT_PATH", "")
        event = json.loads(Path(event_file).read_text("utf-8")) if event_file else {}
        raw = str((event.get("inputs") or {}).get("reset_after_session_update", "false")).lower()
        if raw != "true":
            print("RESULT: MANUAL_NOT_STARTED; select reset_after_session_update after refreshing session")
            return 0
        set_paused(False)
        print("MANUAL_SESSION_RETEST: one check; scheduled times unchanged")
        result = try_one_check()
        return 0 if result == 0 else 3

    if event_name != "schedule":
        print("RESULT: UNSUPPORTED_EVENT; no checks performed")
        return 3

    hour = target_hour_from_event()
    first = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    report = {
        "date": first.date().isoformat(), "hour": hour,
        "attempted": 0, "succeeded": 0, "missed": 0, "state": "unknown",
    }
    try:
        # GitHub Actions may start late; never run outside requested window.
        if now < first - timedelta(minutes=36) or now > first + timedelta(minutes=4, seconds=GRACE_SECONDS):
            report["state"] = "missed_window"
            report["missed"] = 3
            print("RESULT: MISSED_SCHEDULE_WINDOW; no website requests")
            return 0
        if status_paused():
            report["state"] = "auth_paused"
            print("RESULT: PAUSED_DUE_TO_LOGIN; no website requests")
            return 0
        for minute in (0, 2, 4):
            intended = first + timedelta(minutes=minute)
            current = datetime.now(TZ)
            if current > intended + timedelta(seconds=GRACE_SECONDS):
                report["missed"] += 1
                print(f"SKIP_MISSED_SLOT: {hour:02d}:{minute:02d}")
                continue
            wait = (intended - current).total_seconds()
            if wait > 0:
                time.sleep(wait)
            print(f"CHECK_START: {hour:02d}:{minute:02d} Asia/Tashkent")
            report["attempted"] += 1
            code = try_one_check()
            if code == 0:
                report["succeeded"] += 1
                continue
            if code == 4:
                report["state"] = "auth_paused"
                return 0
            report["state"] = "check_error"
            print("RESULT: STOPPED_ON_UNVERIFIED_PAGE; no further checks this hour")
            return 3
        if report["succeeded"] == 3:
            report["state"] = "complete"
        elif report["succeeded"] > 0:
            report["state"] = "partial"
        else:
            report["state"] = "missed_window"
        print(f"RESULT: WINDOW_COMPLETE successful={report['succeeded']} missed={report['missed']}")
        return 0
    finally:
        # Ephemeral diagnostic, not committed, never stores session details.
        folder = Path(os.environ.get("RUNNER_TEMP") or str(HERE))
        (folder / "visa_hourly_status.json").write_text(
            json.dumps(report, ensure_ascii=False), encoding="utf-8"
        )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print("RESULT: SCHEDULER_ERROR (details withheld)")
        raise SystemExit(3)

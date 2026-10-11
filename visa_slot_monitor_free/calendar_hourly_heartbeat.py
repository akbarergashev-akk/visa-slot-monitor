"""Telegram status once per scheduled Tashkent-hour GitHub job.

Reports verified checks only. Does not access the embassy, print secrets,
or claim success when a scheduled workflow was missed or paused.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
TZ = ZoneInfo("Asia/Tashkent")


def hourly_target() -> tuple[str, int]:
    p = os.getenv("GITHUB_EVENT_PATH")
    if not p:
        raise ValueError("EVENT_NOT_FOUND")
    event = json.loads(Path(p).read_text("utf-8"))
    cron = str(event.get("schedule", ""))
    match = re.fullmatch(r"30 (5|6|7|8|9|10|11) \* \* \*", cron)
    if not match:
        raise ValueError("UNRECOGNIZED_SCHEDULE")
    return datetime.now(TZ).strftime("%Y-%m-%d"), int(match.group(1)) + 1


def wait_until_window_end() -> None:
    # A paused run can finish at xx:55 without opening the website.
    # Send its hourly status only after the last intended xx:04 check.
    if os.getenv("GITHUB_EVENT_NAME") != "schedule":
        return
    _, hour = hourly_target()
    now = datetime.now(TZ)
    target = now.replace(hour=hour, minute=4, second=15, microsecond=0)
    delay = (target - now).total_seconds()
    if 0 < delay <= 2400:
        time.sleep(delay)


def status_message() -> str | None:
    if os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch":
        if os.getenv("HEARTBEAT_TEST", "").lower() == "true":
            return ("🧪 Виза мониторинги: соатлик Telegram хабарномаси ишлаяпти.\n"
                    "Бу ФАҚАТ хабар юбориш синови, сайт текширилмади.")
        return None
    if os.getenv("GITHUB_EVENT_NAME") != "schedule":
        return None

    date, hour = hourly_target()
    heading = f"🕒 Short Stay — {date}, {hour:02d}:00–{hour:02d}:04 (Тошкент)"
    report_path = Path(os.getenv("RUNNER_TEMP") or str(HERE)) / "visa_hourly_status.json"
    if not report_path.is_file():
        try:
            paused = json.loads((HERE / "calendar_schedule_status.json").read_text("utf-8")).get("auth_paused", False)
        except (ValueError, OSError, AttributeError):
            paused = False
        if paused:
            detail = "⏸️ Авторизация тўхтатилган. Бу соатда сайт текширилмади."
        else:
            detail = "⚠️ Бу соатда сайт текширилгани тасдиқланмади (GitHub вазифаси тўлиқ бажарилмади)."
    else:
        report = json.loads(report_path.read_text("utf-8"))
        if report.get("hour") != hour or report.get("date") != date:
            detail = "⚠️ Текширув натижасининг вақти мос эмас; бу соат текширилгани тасдиқланмади."
        else:
            state = str(report.get("state"))
            good = int(report.get("succeeded", 0))
            missing = int(report.get("missed", 0))
            if state == "complete" and good == 3:
                detail = "✅ Календар 3/3 марта текширилди. Слот борлиги тасдиқланмаган."
            elif state == "partial":
                detail = f"⚠️ Календар {good}/3 марта текширилди; {missing} та белгиланган вақт ўтказиб юборилди."
            elif state == "auth_paused":
                detail = f"⏸️ Қайта логин талаб қилинди; муваффақиятли текширувлар: {good}/3. Мониторинг тўхтатилган."
            elif state == "missed_window":
                detail = "⚠️ GitHub кечикди: бу соатда календар текширилмади."
            elif state == "check_error":
                detail = f"⚠️ Календар текширувида хато; муваффақиятли текширувлар: {good}/3."
            else:
                detail = "⚠️ Календар текширувининг натижаси тасдиқланмади."
    repo = os.getenv("GITHUB_REPOSITORY", "akbarergashev-akk/visa-slot-monitor")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    link = f"https://github.com/{repo}/actions/runs/{run_id}" if run_id.isdigit() else ""
    return f"{heading}\n{detail}\n{link}".strip()


def send_message(message: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise ValueError("TELEGRAM_SECRETS_MISSING")
    payload = json.dumps({"chat_id": chat_id, "text": message, "disable_web_page_preview": True}).encode("utf-8")
    conn = http.client.HTTPSConnection("api.telegram.org", timeout=15)
    try:
        conn.request("POST", f"/bot{token}/sendMessage", body=payload,
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = resp.read()
        if resp.status != 200 or not json.loads(data).get("ok"):
            raise RuntimeError("DELIVERY_FAILED")
    finally:
        conn.close()


def main() -> int:
    try:
        wait_until_window_end()
        message = status_message()
        if message is None:
            print("HEARTBEAT: NOT_REQUESTED")
            return 0
        send_message(message)
        print("HEARTBEAT: SENT (no sensitive details logged)")
        return 0
    except Exception:
        print("HEARTBEAT: FAILED (no sensitive details logged)")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

"""Read-only, manual GitHub test of Short Stay calendar changes.

Does not book appointments, bypass CAPTCHA, or classify unmarked cells as open.
The checkpoint contains only calendar-marker identifiers, no account/session data.
"""
from __future__ import annotations
import base64
import binascii
import http.client
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright
from marker_rules import CALENDAR_MARKERS_JS, classify_calendar_marks

ROOT = Path(__file__).resolve().parent
CHECKPOINT = ROOT / "calendar_marker_checkpoint.json"
URL = "https://uzembassyryouji.rsvsys.jp/reservations/calendar"

CATEGORY_JS = r"""() => {
  const grid = document.querySelector('table.sc_cal_month');
  if (!grid) return false;
  const normalize = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const wanted = /visa\\s+application\\s+for\\s+short\\s+stay\\s*\\(\\s*applicant\\s*\\)/i;
  const top = grid.getBoundingClientRect().top;
  return [...document.querySelectorAll('a,button,div,span,p,label,li')].some(el => {
    if (!el.getClientRects().length) return false;
    const text = normalize(el.innerText || el.textContent);
    if (text.length > 150 || !wanted.test(text)) return false;
    const bottom = el.getBoundingClientRect().bottom;
    return bottom <= top + 10 && bottom >= top - 900;
  });
}"""

def send_telegram(message: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        raise ValueError("TELEGRAM_SECRETS_MISSING")
    conn = http.client.HTTPSConnection("api.telegram.org", timeout=15)
    try:
        payload = json.dumps({"chat_id": chat, "text": message,
                              "disable_web_page_preview": True}).encode("utf-8")
        conn.request("POST", "/bot" + token + "/sendMessage",
                     body=payload, headers={"Content-Type":"application/json"})
        response = conn.getresponse()
        body = response.read()
        if response.status >= 400 or not json.loads(body).get("ok"):
            raise RuntimeError("TELEGRAM_DELIVERY_FAILED")
    finally:
        conn.close()

def read_secret_state() -> dict:
    encoded = os.getenv("AUTH_STATE_B64", "").strip()
    if not encoded:
        raise ValueError("AUTH_SECRET_MISSING")
    try:
        state = json.loads(base64.b64decode(encoded, validate=True))
        if not isinstance(state, dict) or not isinstance(state.get("cookies"), list) or not isinstance(state.get("origins"), list):
            raise ValueError()
    except (ValueError, UnicodeError, binascii.Error):
        raise ValueError("AUTH_SECRET_INVALID") from None
    return state

def snapshot(records) -> dict:
    # Day and cell are only public calendar positions, not account information.
    return {str(r.cell): {"day":r.day, "assets":list(r.assets),
                           "status":r.classification} for r in records}

def main() -> int:
    state = read_secret_state()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(storage_state=state, viewport={"width":1280,"height":900},
                                      locale="en-US", timezone_id="Asia/Tashkent",
                                      accept_downloads=False)
            page = ctx.new_page()
            response = page.goto(URL, wait_until="domcontentloaded", timeout=30000)
            if response and response.status in (401,403,429):
                if response.status == 401:
                    print("RESULT: LOGIN_REQUIRED (HTTP 401)")
                    return 4
                print("RESULT: SITE_RESTRICTED (no automatic retry)")
                return 3
            try:
                page.locator("table.sc_cal_month").wait_for(state="visible", timeout=25000)
            except Exception:
                # Categorize failures without printing sensitive page data, URL or cookies.
                from urllib.parse import urlparse
                login_path = urlparse(page.url).path.lower().startswith("/auth/")
                try:
                    password_form = page.locator('input[type="password"]:visible').count() > 0
                    challenge = page.locator(
                        'iframe[src*="recaptcha"]:visible, iframe[src*="hcaptcha"]:visible, '
                        '[class*="h-captcha"]:visible, [class*="g-recaptcha"]:visible'
                    ).count() > 0
                except Exception:
                    password_form, challenge = False, False
                if login_path or password_form:
                    print("RESULT: LOGIN_REQUIRED (saved GitHub session may have expired)")
                    print("NOTE: No Telegram notification and no site retry performed.")
                    return 4
                elif challenge:
                    print("RESULT: CAPTCHA_REQUIRES_MANUAL_ACTION")
                else:
                    print("RESULT: CALENDAR_NOT_VISIBLE (cause uncertain; no automatic retry)")
                print("NOTE: No Telegram notification and no site retry performed.")
                return 3
            if not page.evaluate(CATEGORY_JS):
                print("RESULT: CATEGORY_NOT_VERIFIED (no notification sent)")
                return 3
            records = classify_calendar_marks(page.evaluate(CALENDAR_MARKERS_JS))
        finally:
            browser.close()
    current = snapshot(records)
    prior = None
    if CHECKPOINT.exists():
        old = json.loads(CHECKPOINT.read_text("utf-8"))
        prior = old.get("markers") if isinstance(old, dict) else None
    closed = sum(r.classification == "closed" for r in records)
    unknown = sum(r.classification == "needs_review" for r in records)
    if prior is None:
        message = ("✅ Виза календарини GitHub сервери ўқий олди.\n"
                   f"Ёпиқ белги: {closed}; текшириш керак бўлган белги: {unknown}.\n"
                   "Бу биринчи синов. Бўш слот борлиги тасдиқлангани ЙЎҚ.")
        send_telegram(message)
        print("RESULT: BASELINE_OK; first-run Telegram confirmation sent")
    elif prior != current:
        changes = sorted(k for k in set(prior) | set(current)
                         if prior.get(k) != current.get(k))
        message = ("🔎 Short Stay календарда ўзгариш бор — қўлда текширинг.\n"
                   "Ўзгарган календар катаклари: " + ", ".join(changes[:15]) + "\n"
                   "Бу бўш слот очилганини ТАСДИҚЛАМАЙДИ.\n" + URL)
        send_telegram(message)
        print("RESULT: CHANGED; Telegram review notification sent")
    else:
        print("RESULT: UNCHANGED; no Telegram message needed")
    CHECKPOINT.write_text(json.dumps({"markers":current}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"CONFIRMED_CATEGORY: True; CLOSED_MARKERS: {closed}; UNVERIFIED_MARKERS: {unknown}")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Deliberately no stack trace or secret-dependent exception strings.
        print("RESULT: ERROR (" + type(exc).__name__ + "; secrets withheld)")
        raise SystemExit(3)

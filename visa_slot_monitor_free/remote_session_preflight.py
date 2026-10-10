"""One-off read-only cloud session test. Never prints secret/session content."""
import base64
import binascii
import json
import os
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

URL = "https://uzembassyryouji.rsvsys.jp/reservations/calendar"

def main():
    b64 = os.getenv("AUTH_STATE_B64", "").strip()
    if not b64:
        print("RESULT: MISSING_SECRET (AUTH_STATE_B64)")
        return 2
    try:
        state = json.loads(base64.b64decode(b64, validate=True).decode("utf-8"))
        if not isinstance(state, dict) or not isinstance(state.get("cookies"), list) or not isinstance(state.get("origins"), list):
            raise ValueError("invalid state structure")
    except (ValueError, UnicodeError, binascii.Error):
        print("RESULT: INVALID_SECRET_FORMAT (no secret values printed)")
        return 2
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    storage_state=state, locale="en-US", timezone_id="Asia/Tashkent",
                    viewport={"width": 1280, "height": 900},
                    accept_downloads=False,
                )
                page = context.new_page()
                response = page.goto(URL, wait_until="domcontentloaded", timeout=30000)
                if response is not None and response.status in (401, 403, 429):
                    print("RESULT: SITE_RESTRICTED_OR_AUTH_REQUIRED")
                    return 3
                try:
                    page.locator("table.sc_cal_month").wait_for(state="visible", timeout=25000)
                except PWTimeout:
                    print("RESULT: NOT_CONFIRMED (calendar absent; login/CAPTCHA/site restrictions possible)")
                    return 3
                result = page.evaluate("""() => {
                    const table = document.querySelector('table.sc_cal_month');
                    if (!table) return {ok:false};
                    const cells = [...table.querySelectorAll('td')];
                    return {ok:cells.length >= 28 && cells.length <= 42, cells:cells.length,
                            imageCells:cells.filter(c=>c.querySelector('img')).length};
                }""")
                if not result["ok"]:
                    print("RESULT: NOT_CONFIRMED (unexpected calendar structure)")
                    return 3
                print(f"RESULT: SUCCESS calendar_grid_cells={result['cells']} marker_cells={result['imageCells']}")
                print("NOTE: Calendar visibility was verified, not Short Stay category or bookable slot availability.")
                return 0
            finally:
                browser.close()
    except Exception:
        print("RESULT: ERROR (network/browser/site failure; private details withheld)")
        return 3

if __name__ == "__main__":
    raise SystemExit(main())

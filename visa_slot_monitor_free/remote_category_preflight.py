"""Read-only, one-time cloud category audit. Prints booleans/counts only.
No login details, raw page text, URLs or session state are exported.
"""
import base64, binascii, json, os
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

URL = "https://uzembassyryouji.rsvsys.jp/reservations/calendar"
CHECK_JS = r"""() => {
  const grid = document.querySelector("table.sc_cal_month");
  const visible = el => !!el.getClientRects().length && getComputedStyle(el).visibility !== "hidden";
  const norm = text => (text || "").replace(/\s+/g," ").trim();
  const target = /visa\s+application\s+for\s+short\s+stay\s*\(\s*applicant\s*\)/i;
  const selectors = "a,button,div,span,p,label,li,[role=link],[role=button]";
  const elements = [...document.querySelectorAll(selectors)];
  const matching = elements.filter(el => {
    if (!visible(el)) return false;
    const text = norm(el.innerText || el.textContent);
    return text.length < 150 && target.test(text);
  });
  const rect = grid?.getBoundingClientRect();
  const above = matching.filter(el => {
    if (!rect) return false;
    const b = el.getBoundingClientRect();
    const distance = rect.top - b.bottom;
    return distance >= -10 && distance < 700;
  });
  // A visible category card above the calendar is stronger evidence than
  // incidental category words elsewhere on the page. This still is not
  // equivalent to server-verified booking availability.
  return {
    calendar: !!grid && grid.querySelectorAll("td").length >= 28,
    category_exact_visible: matching.length > 0,
    category_card_above_calendar: above.length > 0,
    visible_category_candidates: Math.min(matching.length, 20)
  };
}"""

def main():
    encoded = os.getenv("AUTH_STATE_B64", "").strip()
    if not encoded:
        print("RESULT: MISSING_SECRET")
        return 2
    try:
        state = json.loads(base64.b64decode(encoded, validate=True))
        if not isinstance(state, dict) or not isinstance(state.get("cookies"), list) or not isinstance(state.get("origins"), list):
            raise ValueError()
    except (ValueError, UnicodeError, binascii.Error):
        print("RESULT: INVALID_SECRET_FORMAT")
        return 2
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                ctx = browser.new_context(storage_state=state, viewport={"width":1280,"height":900},
                    locale="en-US", timezone_id="Asia/Tashkent", accept_downloads=False)
                page = ctx.new_page()
                response = page.goto(URL, wait_until="domcontentloaded", timeout=30000)
                if response and response.status in (401,403,429):
                    print("RESULT: LOGIN_OR_RESTRICTION")
                    return 3
                try:
                    page.locator("table.sc_cal_month").wait_for(state="visible", timeout=25000)
                except PWTimeout:
                    print("RESULT: CALENDAR_NOT_VISIBLE")
                    return 3
                result = page.evaluate(CHECK_JS)
                if not result["calendar"]:
                    print("RESULT: CALENDAR_NOT_CONFIRMED")
                    return 3
                print("RESULT: SUCCESS (calendar visible)")
                print("CATEGORY_EXACT_VISIBLE:", result["category_exact_visible"])
                print("CATEGORY_CARD_ABOVE_CALENDAR:", result["category_card_above_calendar"])
                print("CATEGORY_CANDIDATES:", result["visible_category_candidates"])
                print("NOTE: visible category above the calendar strongly supports the scope, but does not guarantee appointment availability.")
                return 0
            finally:
                browser.close()
    except Exception:
        print("RESULT: ERROR (details withheld)")
        return 3

if __name__ == "__main__":
    raise SystemExit(main())

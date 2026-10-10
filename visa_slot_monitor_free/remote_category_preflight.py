"""Read-only, one-time cloud category audit. Prints booleans/counts only.
No login details, raw page text, URLs or session state are exported.
"""
import base64, binascii, json, os
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

URL = "https://uzembassyryouji.rsvsys.jp/reservations/calendar"
CHECK_JS = r"""() => {
  const grid = document.querySelector("table.sc_cal_month");
  const visible = el => !!el.getClientRects().length;
  const names = /short\s*[- ]?stay/i;
  const applicant = /applicant/i;
  const norm = el => (el.innerText || el.textContent || "").replace(/\s+/g," ").trim().slice(0,250);
  const scoped = [...document.querySelectorAll("h1,h2,h3,h4,[aria-current],[aria-selected],option:checked,select,button,[role=tab],[role=heading],[class*=selected],[class*=active]")];
  const exact = scoped.filter(el => {
    if (!visible(el) && el.tagName !== "OPTION") return false;
    const text = norm(el);
    return text.length < 160 && names.test(text) && applicant.test(text);
  });
  const selected = exact.filter(el => {
    const a=el.getAttribute("aria-selected") === "true" || el.getAttribute("aria-current") ||
      el.matches("option:checked") || /selected|active|current/i.test(String(el.className || ""));
    return !!a;
  });
  const txt = (document.body.innerText || "").slice(0,150000);
  return {calendar: !!grid && grid.querySelectorAll("td").length >= 28,
          page_mentions_short_stay: names.test(txt) && applicant.test(txt),
          heading_or_control_matches: exact.length, selected_control_matches: selected.length};
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
                print("CATEGORY_TEXT_PRESENT:", result["page_mentions_short_stay"])
                print("CATEGORY_HEADING_OR_CONTROL_MATCHES:", result["heading_or_control_matches"])
                print("CATEGORY_SELECTED_CONTROL_MATCHES:", result["selected_control_matches"])
                print("NOTE: category selection needs manual confirmation; these hints are not conclusive.")
                return 0
            finally:
                browser.close()
    except Exception:
        print("RESULT: ERROR (details withheld)")
        return 3

if __name__ == "__main__":
    raise SystemExit(main())

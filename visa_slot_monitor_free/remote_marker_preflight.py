import base64, binascii, json, os
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

URL = "https://uzembassyryouji.rsvsys.jp/reservations/calendar"
JS = """() => {
  const grid = document.querySelector("table.sc_cal_month");
  if (!grid) return null;
  const cells = [...grid.querySelectorAll("td")];
  const markers = [];
  for (const cell of cells) {
    const day = (cell.querySelector(".sc_cal_date")?.textContent || "").trim();
    if (!/^\d{1,2}$/.test(day)) continue;
    for (const img of cell.querySelectorAll("img")) {
      if (!img.getClientRects().length) continue;
      const path = new URL(img.getAttribute("src") || "", location.href).pathname;
      const name = path.split("/").pop() || "";
      markers.push(/^[a-z0-9_.-]{1,65}\.(svg|png|gif|webp|jpe?g)$/i.test(name) ? name.toLowerCase() : "unknown_image");
    }
  }
  return {cells: cells.length, markers};
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
                context = browser.new_context(storage_state=state, viewport={"width": 1280, "height": 900}, locale="en-US", timezone_id="Asia/Tashkent", accept_downloads=False)
                page = context.new_page()
                response = page.goto(URL, wait_until="domcontentloaded", timeout=30000)
                if response and response.status in (401, 403, 429):
                    print("RESULT: RESTRICTED_OR_LOGIN_REQUIRED")
                    return 3
                try:
                    page.locator("table.sc_cal_month").wait_for(state="visible", timeout=25000)
                except PlaywrightTimeout:
                    print("RESULT: NOT_CONFIRMED")
                    return 3
                result = page.evaluate(JS)
                if not result or not 28 <= result["cells"] <= 42:
                    print("RESULT: NOT_CONFIRMED")
                    return 3
                markers = result["markers"]
                print("RESULT: SUCCESS cells=%d marker_images=%d" % (result["cells"], len(markers)))
                for name in sorted(set(markers)):
                    kind = "CLOSED_MARKER" if name == "icon_disabled.svg" else "UNVERIFIED_MARKER"
                    print("%s: %s count=%d" % (kind, name, markers.count(name)))
                print("NOTE: no image does not mean open; Short Stay category and bookability not verified.")
                return 0
            finally:
                browser.close()
    except Exception:
        print("RESULT: ERROR; site/network/browser issue (details withheld)")
        return 3

if __name__ == "__main__":
    raise SystemExit(main())

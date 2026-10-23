"""Keep the Lighthouse awake on Streamlit Community Cloud.

Community Cloud puts an app to sleep after 12 hours without traffic, and
whoever opens it next meets the "Zzzz — this app has gone to sleep" page and
waits a minute or two. Run every few hours by .github/workflows/keep-awake.yml.

WHY A REAL BROWSER AND NOT A PING. A plain HTTP request only fetches the
Community Cloud shell; the app itself starts when that page opens its
websocket, and that is what counts as a visit. So this opens the page in
headless Chromium, clicks "Yes, get this app back up!" if the app is already
asleep, and waits until the Lighthouse itself has drawn.

Exit code 1 when the app never comes up, so GitHub emails the failure — which
doubles as a free uptime alarm.
"""
from __future__ import annotations

import os
import re
import sys
import time

from playwright.sync_api import sync_playwright

APP_URL = os.environ.get(
    "APP_URL",
    "https://atlantic-lighthouse-ciudtjtmum3lt5x3d8lcjj.streamlit.app/?view=overview")
WAKE = re.compile(r"get this app back up", re.I)        # the sleeping page's button
UP_TEXT = os.environ.get("UP_TEXT", "Run Lighthouse")     # something only our app draws
WAIT_UP = float(os.environ.get("WAIT_UP", "300"))         # waking can take minutes


def _app_is_up(page) -> bool:
    """True once the Lighthouse has drawn, in the page or in any frame of it."""
    for frame in page.frames:
        try:
            if frame.get_by_text(UP_TEXT, exact=False).count():
                return True
        except Exception:
            continue                                      # frame navigated away
    return False


def _click_wake(page) -> bool:
    for frame in page.frames:
        try:
            btn = frame.get_by_role("button", name=WAKE)
            if btn.count():
                btn.first.click()
                return True
        except Exception:
            continue
    return False


def main() -> int:
    t0 = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(APP_URL, wait_until="domcontentloaded", timeout=120_000)
        woke = False
        deadline = time.time() + WAIT_UP
        while time.time() < deadline:
            if _app_is_up(page):
                break
            if not woke and _click_wake(page):
                woke = True
                print("App was asleep — clicked the wake button.", flush=True)
            page.wait_for_timeout(3000)       # lets Playwright process frame events
        up = _app_is_up(page)
        if up:
            # Stay a moment so the session registers as real traffic.
            page.wait_for_timeout(15_000)
        browser.close()
    took = int(time.time() - t0)
    if up:
        print(f"Lighthouse is up ({'woken' if woke else 'was already awake'}) · {took}s · {APP_URL}")
        return 0
    print(f"Lighthouse did NOT come up within {int(WAIT_UP)}s · {APP_URL}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

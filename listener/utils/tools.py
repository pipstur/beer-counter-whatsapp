from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from typing import Optional, Tuple, Set

from playwright.sync_api import sync_playwright, BrowserContext, Page, Locator
from data.utils.data_utils import (
    extract_user_timestamp,
    parse_time_12h,
    get_beer_count,
    convert_to_24h,
    determine_day_rollover,
)
from data.utils.db_utils import save_message


CHECK_INTERVAL = 60  # seconds between checks
SCROLL_UP_STEP = 5  # scroll attempts when catching new messages

from data.utils import DB_PATH


def launch_browser(user_data_dir: str) -> Tuple[BrowserContext, Page]:
    """
    Launch a persistent Chromium browser context for WhatsApp Web.

    Each user_data_dir represents a separate WhatsApp session.
    """
    playwright = sync_playwright().start()
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=user_data_dir,
        headless=False,
        args=["--start-fullscreen"],
        viewport={"width": 1920, "height": 1080},
    )
    page = context.new_page()
    return context, page


def process_message(
    msg: Locator,
    seen_ids: Set[str],
    last_hour: Optional[int],
    last_minute: Optional[int],
    current_date: datetime.date,
    conn: sqlite3.Connection,
) -> Tuple[Optional[int], Optional[int], datetime.date]:
    msg_id = msg.get_attribute("data-id")
    if not msg_id or msg_id in seen_ids:
        return last_hour, last_minute, current_date

    seen_ids.add(msg_id)

    timestamp, nickname, _ = extract_user_timestamp(msg)
    beer_count = get_beer_count(msg)
    if beer_count is None or timestamp == "unknown":
        return last_hour, last_minute, current_date

    hour, minute, ampm = parse_time_12h(timestamp)
    hour_24 = convert_to_24h(hour, ampm)

    current_date = determine_day_rollover(last_hour, last_minute, hour_24, minute, current_date)
    last_hour, last_minute = hour_24, minute

    dt = datetime(
        year=current_date.year,
        month=current_date.month,
        day=current_date.day,
        hour=hour_24,
        minute=minute,
        tzinfo=timezone.utc,
    )
    full_timestamp = dt.isoformat().replace("+00:00", "Z")

    print(f"{nickname} @ {full_timestamp} → {beer_count} beer(s)")
    save_message(conn, msg_id, nickname, full_timestamp, beer_count)

    return last_hour, last_minute, current_date


def live_checker(page, chat_panel):
    seen_ids = set()  # optionally prefill from DB

    print("Running initial scan...")
    scroll_attempts = 0
    last_hour, last_minute = None, None
    current_date = datetime.now().date()

    while scroll_attempts < 5:
        messages = chat_panel.locator("div[data-id]")
        new_found = 0
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            for i in range(messages.count() - 1, -1, -1):  # newest → oldest
                last_hour, last_minute, current_date = process_message(
                    msg=messages.nth(i),
                    seen_ids=seen_ids,
                    last_hour=last_hour,
                    last_minute=last_minute,
                    current_date=current_date,
                    conn=conn,
                )
                new_found += 1

            page.keyboard.press("PageUp")
            time.sleep(3)

            if new_found == 0:
                scroll_attempts += 1
            else:
                scroll_attempts = 0

    print("Initial scan complete. Entering live check loop...")

    # Live check loop
    while True:
        messages = chat_panel.locator("div[data-id]")
        new_found = 0

        last_hour, last_minute = None, None
        current_date = datetime.now().date()
        for i in range(messages.count() - 1, -1, -1):
            last_hour, last_minute, current_date = process_message(
                msg=messages.nth(i),
                seen_ids=seen_ids,
                last_hour=last_hour,
                last_minute=last_minute,
                current_date=current_date,
                conn=conn,
            )
            new_found += 1

        if new_found > 0:
            for _ in range(SCROLL_UP_STEP):
                page.keyboard.press("PageUp")
                time.sleep(0.5)
            last_hour, last_minute = None, None
            current_date = datetime.now().date()
            for i in range(messages.count() - 1, -1, -1):
                last_hour, last_minute, current_date = process_message(
                    msg=messages.nth(i),
                    seen_ids=seen_ids,
                    last_hour=last_hour,
                    last_minute=last_minute,
                    current_date=current_date,
                    conn=conn,
                )
        for _ in range(50):
            page.keyboard.press("PageDown")
            time.sleep(0.5)

        time.sleep(CHECK_INTERVAL)

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from typing import Optional, Tuple, Set, List, Dict

from playwright.sync_api import (
    sync_playwright,
    BrowserContext,
    Page,
    Locator,
    JSHandle,
    TimeoutError as PlaywrightTimeoutError,
)
from data.utils.data_utils import (
    extract_user_timestamp,
    parse_time_12h,
    get_beer_count,
    convert_to_24h,
    determine_day_rollover,
)
from data.utils.db_utils import save_message


CHECK_INTERVAL = 60  # seconds between checks
SCROLL_UP_STEP = 1  # keypresses per "load more history" nudge
MAX_HISTORY_PASSES = 10
OLDER_MESSAGES_TEXT = "older messages from your phone"

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


def get_visible_snapshot(chat_panel: Locator) -> List[Dict[str, str]]:
    """One round-trip: id + render-state for every row currently mounted in the DOM."""
    return chat_panel.locator("div[data-id]").evaluate_all(
        """
        els => els.map(el => ({
            id: el.getAttribute('data-id'),
            // the virtualization flag lives on a nested wrapper, not the row itself
            virtualized: el.querySelector('[data-virtualized]')?.getAttribute('data-virtualized') ?? 'false',
        }))
        """
    )


def locator_for_id(chat_panel: Locator, msg_id: str) -> Locator:
    return chat_panel.locator(f'div[data-id="{msg_id}"]')


def is_rendered(msg: Locator, settle_timeout_ms: int = 800) -> bool:
    """
    True once the row has real content attached, not just past the
    virtualization flag flip. `data-virtualized="false"` fires as soon as
    WhatsApp *starts* mounting the row — the image blob/text can still take
    a beat to actually populate, especially right after a scroll. This waits
    briefly for that, but does NOT scroll (that's the caller's job, and doing
    it here is what was causing the index drift/jumping-back behaviour).
    """
    virtualized = msg.evaluate(
        "el => el.querySelector('[data-virtualized]')?.getAttribute('data-virtualized')"
    )
    if virtualized not in (None, "false"):
        return False

    try:
        msg.locator(
            '[data-testid="msg-container"], [data-testid="msg-notification-container"]'
        ).first.wait_for(timeout=settle_timeout_ms, state="attached")
        return True
    except PlaywrightTimeoutError:
        return False


def process_message(
    msg: Locator,
    msg_id: str,
    seen_ids: Set[str],
    last_hour: Optional[int],
    last_minute: Optional[int],
    current_date: datetime.date,
    conn: sqlite3.Connection,
) -> Tuple[Optional[int], Optional[int], datetime.date]:
    try:
        if not is_rendered(msg):
            return last_hour, last_minute, current_date

        timestamp, nickname, _ = extract_user_timestamp(msg)
        beer_count = get_beer_count(msg)

        if beer_count is None or timestamp == "unknown":
            seen_ids.add(msg_id)
            return last_hour, last_minute, current_date

        seen_ids.add(msg_id)

        hour, minute, ampm = parse_time_12h(timestamp)
        hour_24 = convert_to_24h(hour, ampm)

        current_date = determine_day_rollover(
            last_hour, last_minute, hour_24, minute, current_date
        )
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
    except Exception:
        return last_hour, last_minute, current_date


def process_pass(
    chat_panel: Locator,
    seen_ids: Set[str],
    conn: sqlite3.Connection,
    last_hour: Optional[int],
    last_minute: Optional[int],
    current_date: datetime.date,
) -> Tuple[int, Optional[int], Optional[int], datetime.date]:
    """
    One full pass: snapshot the currently mounted rows, process every rendered
    row we haven't seen yet, newest-to-oldest (matches original behaviour and
    is what determine_day_rollover expects). Date/time state is passed in and
    returned — it must be threaded across passes by the caller, NOT reset
    here, or day-rollover breaks the moment you scroll to a new chunk.
    """
    snapshot = get_visible_snapshot(chat_panel)

    todo = [
        row
        for row in snapshot
        if row["id"] and row["id"] not in seen_ids and row["virtualized"] == "false"
    ]

    if not todo:
        return 0, last_hour, last_minute, current_date

    processed = 0
    for row in reversed(todo):
        msg = locator_for_id(chat_panel, row["id"])
        last_hour, last_minute, current_date = process_message(
            msg=msg,
            msg_id=row["id"],
            seen_ids=seen_ids,
            last_hour=last_hour,
            last_minute=last_minute,
            current_date=current_date,
            conn=conn,
        )
        processed += 1

    return processed, last_hour, last_minute, current_date


def scroll_up(
    page: Page, steps: int = SCROLL_UP_STEP, pause: float = 0.3, settle: float = 0.5
) -> None:
    for _ in range(steps):
        page.keyboard.press("PageUp")
        time.sleep(pause)
    # let newly-loaded rows finish mounting before the next snapshot reads them
    time.sleep(settle)


def get_scroller(chat_panel: Locator) -> JSHandle:
    """Nearest ancestor-or-self of the chat panel that actually scrolls."""
    return chat_panel.evaluate_handle(
        """
        el => {
            for (let n = el; n; n = n.parentElement) {
                const s = getComputedStyle(n);
                if ((s.overflowY === 'auto' || s.overflowY === 'scroll')
                    && n.scrollHeight > n.clientHeight) return n;
            }
            return el;
        }
        """
    )


def oldest_loaded_id(chat_panel: Locator) -> Optional[str]:
    return chat_panel.evaluate(
        "el => el.querySelector('div[data-id]')?.getAttribute('data-id') ?? null"
    )


def at_history_wall(page: Page) -> bool:
    """WhatsApp stops lazy-loading at 'Click here to get older messages from your phone.'"""
    return page.locator("#main button", has_text=OLDER_MESSAGES_TEXT).count() > 0


def bounce_at_wall(page: Page, chat_panel: Locator, settle: float = 2.0) -> None:
    """
    Scroll down a bit and back to the top. At the history wall this makes
    WhatsApp load the next chunk of older messages without clicking the
    'get older messages from your phone' button.
    """
    scroller = get_scroller(chat_panel)
    page.evaluate("s => { s.scrollTop = 1500; }", scroller)
    time.sleep(0.8)
    page.evaluate("s => { s.scrollTop = 0; }", scroller)
    time.sleep(settle)


def scroll_to_bottom(page: Page, chat_panel: Locator) -> None:
    """
    Jump straight to the latest message instead of spamming PageDown.
    Falls back to a small number of keypresses if the direct scroll doesn't
    stick (e.g. selector for the scroll container is slightly off).
    """
    try:
        chat_panel.evaluate("el => { el.scrollTop = el.scrollHeight; }")
        time.sleep(0.5)
    except Exception:
        pass

    page.keyboard.press("End")
    time.sleep(0.3)
    for _ in range(5):
        page.keyboard.press("PageDown")
        time.sleep(0.2)


def live_checker(page: Page, chat_panel: Locator, live_mode: bool = False) -> None:
    seen_ids: Set[str] = set()  # optionally prefill from DB

    if not live_mode:
        print("Running initial scan...")
        stalled_passes = 0
        last_hour, last_minute = None, None
        current_date = datetime.now().date()
        prev_oldest_id = None

        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            while stalled_passes < MAX_HISTORY_PASSES:
                seen_before = len(seen_ids)
                _, last_hour, last_minute, current_date = process_pass(
                    chat_panel, seen_ids, conn, last_hour, last_minute, current_date
                )

                oldest_id = oldest_loaded_id(chat_panel)
                if oldest_id != prev_oldest_id or len(seen_ids) > seen_before:
                    stalled_passes = 0
                else:
                    stalled_passes += 1
                prev_oldest_id = oldest_id

                # Load older history
                if at_history_wall(page):
                    bounce_at_wall(page, chat_panel)
                else:
                    scroll_up(page)

        print("Initial scan complete.")

    print("Entering live check mode...")
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        while True:
            last_hour, last_minute = None, None
            current_date = datetime.now().date()

            _, last_hour, last_minute, current_date = process_pass(
                chat_panel, seen_ids, conn, last_hour, last_minute, current_date
            )

            scroll_up(page, steps=SCROLL_UP_STEP)
            _, last_hour, last_minute, current_date = process_pass(
                chat_panel, seen_ids, conn, last_hour, last_minute, current_date
            )

            scroll_to_bottom(page, chat_panel)

            time.sleep(CHECK_INTERVAL)

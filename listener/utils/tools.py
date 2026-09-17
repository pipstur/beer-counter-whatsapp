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
SCROLL_UP_STEP = 5  # keypresses per "load more history" nudge
MAX_HISTORY_PASSES = 5  # consecutive empty passes before giving up on initial scan

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


# ---------------------------------------------------------------------------
# Snapshotting
# ---------------------------------------------------------------------------
#
# We never iterate by positional index (`.nth(i)`) against a live, virtualized
# list. WhatsApp Web prepends/removes DOM nodes as you scroll, so any index
# captured before a scroll can point at a totally different message after it.
# Instead we snapshot {id, virtualized} for every currently-mounted row in a
# single JS round-trip, filter down to what we actually need to touch, and
# then re-locate each message by its stable `data-id` when we need to read it.


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


# ---------------------------------------------------------------------------
# Per-message processing
# ---------------------------------------------------------------------------


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
        # The snapshot only told us the row *started* mounting. Give it a
        # short, bounded moment to actually finish (image swap-in, text
        # nodes attaching) — no scrolling involved, so this can't trigger
        # the history-splicing that caused messages to drift under us.
        # If it never settles in time, skip for now; NOT marking it seen
        # means a later pass will retry it once it's fully rendered.
        if not is_rendered(msg):
            return last_hour, last_minute, current_date

        timestamp, nickname, _ = extract_user_timestamp(msg)
        beer_count = get_beer_count(msg)

        if beer_count is None or timestamp == "unknown":
            # Fully rendered but genuinely not a beer message (text, system
            # message, reaction-only bubble, etc.) — nothing will change if we
            # look again, so it's safe to mark seen.
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
    # snapshot is in DOM order (oldest → newest); walk it newest → oldest,
    # same direction the original nth-based loop used.
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

    # Cheap safety net: a handful of End/PageDown presses in case the
    # scrollable ancestor isn't chat_panel itself.
    page.keyboard.press("End")
    time.sleep(0.3)
    for _ in range(5):
        page.keyboard.press("PageDown")
        time.sleep(0.2)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def live_checker(page: Page, chat_panel: Locator, live_mode: bool = False) -> None:
    seen_ids: Set[str] = set()  # optionally prefill from DB

    if not live_mode:
        print("Running initial scan...")
        empty_passes = 0
        last_hour, last_minute = None, None
        current_date = datetime.now().date()

        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            while empty_passes < MAX_HISTORY_PASSES:
                processed, last_hour, last_minute, current_date = process_pass(
                    chat_panel, seen_ids, conn, last_hour, last_minute, current_date
                )

                if processed == 0:
                    empty_passes += 1
                else:
                    empty_passes = 0

                # Load older history. This is the ONLY place we scroll during
                # the historical pass — no per-message scrolling fighting it.
                scroll_up(page)

        print("Initial scan complete.")

    print("Entering live check mode...")
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        while True:
            # Live mode always looks at "now" — fresh date/time state each
            # poll cycle, but shared between the two sub-passes below so a
            # midnight-crossing scroll-up within one cycle doesn't reset twice.
            last_hour, last_minute = None, None
            current_date = datetime.now().date()

            _, last_hour, last_minute, current_date = process_pass(
                chat_panel, seen_ids, conn, last_hour, last_minute, current_date
            )

            # Nudge up briefly in case messages arrived while we were scrolled
            # to the bottom and got virtualized away before we could read them.
            scroll_up(page, steps=SCROLL_UP_STEP)
            _, last_hour, last_minute, current_date = process_pass(
                chat_panel, seen_ids, conn, last_hour, last_minute, current_date
            )

            scroll_to_bottom(page, chat_panel)

            time.sleep(CHECK_INTERVAL)

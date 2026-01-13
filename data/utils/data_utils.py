from typing import Optional, Tuple
from playwright.sync_api import Locator
from listener import TIME_REGEX
from datetime import datetime, timedelta


def extract_user_timestamp(msg: Locator) -> Tuple[str, str, Optional[str]]:
    nickname_loc = msg.locator("span[aria-label]")
    nickname = (
        nickname_loc.nth(0).get_attribute("aria-label") if nickname_loc.count() > 0 else None
    )
    nickname = nickname.replace("Maybe ", "") if nickname else "unknown"

    timestamp: Optional[str] = None
    ampm: Optional[str] = None

    span_locs = msg.locator("span")
    for i in range(span_locs.count()):
        text = span_locs.nth(i).inner_text()
        match = TIME_REGEX.search(text)
        if match:
            timestamp = match.group(0)
            upper = timestamp.upper()
            if "AM" in upper:
                ampm = "AM"
            elif "PM" in upper:
                ampm = "PM"
            break

    return timestamp or "unknown", nickname, ampm


def parse_time_12h(timestamp: str) -> tuple[int, int, str]:
    """
    Parses a 12-hour format timestamp (e.g., '10:51 AM') and returns hour, minute, AM/PM.
    """
    parts = timestamp.strip().split()
    if len(parts) != 2:
        raise ValueError(f"Invalid timestamp format: {timestamp}")
    time_part, ampm = parts
    hour_str, minute_str = time_part.split(":")
    hour, minute = int(hour_str), int(minute_str)
    return hour, minute, ampm.upper()


def resolve_message_date(
    timestamp_ampm: Optional[str],
    last_seen_ampm: Optional[str],
    current_date: datetime.date,
) -> datetime.date:
    if last_seen_ampm is None and timestamp_ampm == "AM":
        if datetime.now().hour >= 12:
            return current_date - timedelta(days=1)

    if last_seen_ampm == "PM" and timestamp_ampm == "AM":
        return current_date - timedelta(days=1)

    return current_date


def convert_to_24h(hour: int, ampm: str) -> int:
    if ampm == "AM" and hour == 12:
        return 0
    elif ampm == "PM" and hour != 12:
        return hour + 12
    return hour


def determine_day_rollover(
    last_hour: Optional[int],
    last_minute: Optional[int],
    current_hour: int,
    current_minute: int,
    current_date: datetime.date,
) -> datetime.date:
    if last_hour is not None and last_minute is not None:
        last_total_min = last_hour * 60 + last_minute
        current_total_min = current_hour * 60 + current_minute
        if current_total_min > last_total_min:
            return current_date - timedelta(days=1)
    return current_date


def get_beer_count(msg: Locator) -> Optional[int]:
    image_count = msg.locator('div[role="button"][aria-label="Open picture"]').count()
    gif_count = msg.locator('div[role="button"][aria-label="Play GIF"]').count()

    text = msg.inner_text().lower()
    is_view_once = "view once message" in text

    if image_count > 0:
        return image_count
    if gif_count > 0:
        return gif_count
    if is_view_once:
        return 1

    return None

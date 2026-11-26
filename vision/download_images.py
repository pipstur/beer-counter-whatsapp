"""
Download beer photos from the WhatsApp group for training/evaluating the counter.

    venv/bin/python vision/download_images.py [--max-passes N] [--max-age-days 30]

Walks back through the chat like the scanner's initial scan, and when loading
stalls at the "older messages from your phone" wall it clicks that button (the
phone must be online), then saves every photo of a beer
message to data/beer_images/{captioned,uncaptioned}/<msg_id>_<i>.<ext>, with
data/beer_images/index.csv describing each one. Captioned photos carry their
"+N" as ground truth. Resumable: photos already in index.csv are skipped and
the index is rewritten as it goes. Read-only towards the beer database.

Runs with the main project venv (it needs Playwright and the scanner code),
not vision/.venv.
"""

from __future__ import annotations

import argparse
import base64
import csv
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import rootutils

rootutils.setup_root(__file__, indicator="README.md", pythonpath=True)

from data.utils.data_utils import extract_message_text, extract_user_timestamp, get_beer_count
from listener import GROUP_PREFIX, PLUS_BEER_REGEX, USER_DATA_DIR
from listener.utils.tools import (
    MAX_HISTORY_PASSES,
    load_older,
    get_visible_snapshot,
    is_rendered,
    launch_browser,
    locator_for_id,
    oldest_loaded_id,
    scroll_to_bottom,
)
from listener.whatsapp import dismiss_dialogs, get_chat_panel, open_group, open_whatsapp

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "beer_images"
FIELDS = [
    "msg_id", "file", "user", "time", "pre_plain_text", "caption_plus",
    "scanner_count", "images_in_msg", "w", "h",
]
EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
SIZE_LABEL = re.compile(r"\d+(?:[.,]\d+)?\s*[kKmM]B")  # "215 kB" on a not-yet-downloaded photo
OLDER_MESSAGES = re.compile("older messages", re.I)
PRE_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})\]")  # "[11:50 PM, 10/25/2026] ..."
UNAVAILABLE = "unavailable"  # the phone answered "Photo unavailable": it no longer has the photo

# full-resolution image is a blob: URL next to a tiny data: URI placeholder
FETCH_BLOB_JS = """async button => {
  const imgs = [...button.querySelectorAll('img')].filter(i => i.src.startsWith('blob:'));
  if (!imgs.length) return null;
  const img = imgs.sort((x, y) => y.naturalWidth - x.naturalWidth)[0];
  const blob = await (await fetch(img.src)).blob();
  const buf = new Uint8Array(await blob.arrayBuffer());
  let s = '';
  for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode(...buf.subarray(i, i + 0x8000));
  return {b64: btoa(s), type: blob.type, w: img.naturalWidth, h: img.naturalHeight};
}"""


def load_index() -> list[dict]:
    path = OUT / "index.csv"
    return list(csv.DictReader(open(path))) if path.exists() else []


def save_index(rows: list[dict]) -> None:
    tmp = OUT / "index.csv.tmp"
    with open(tmp, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(OUT / "index.csv")


def close_unavailable(page) -> bool:
    """Close the phone's "Photo unavailable" answer, if it's showing; it blocks every click."""
    dialog = page.locator("div[role='dialog']", has_text="Photo unavailable")
    if dialog.count() == 0:
        return False
    dialog.get_by_role("button", name="OK").click(timeout=5_000)
    dismiss_dialogs(page)
    return True


def poll_blob(button, seconds: float) -> dict | str | None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        data = button.evaluate(FETCH_BLOB_JS, timeout=5_000)
        if data:
            return data
        if close_unavailable(button.page):
            return UNAVAILABLE
        time.sleep(0.5)
    return None


def fetch_image(button) -> dict | str | None:
    """
    Get the full-res photo behind an "Open picture" button:
    1. cached in the browser: the blob is already there;
    2. on disk but not rendered: it loads once scrolled into view;
    3. never downloaded (older photos show "215 kB" instead): click to download,
       then close the media viewer that may open. Past ~30 days the phone has to
       send it, and answers "Photo unavailable" when it no longer has it.
    """
    close_unavailable(button.page)  # a late answer about an earlier photo
    data = button.evaluate(FETCH_BLOB_JS, timeout=5_000)
    if data:
        return data
    # in-page scroll/click: Playwright's waits for the element to stop moving, and
    # around old photos the list keeps shifting while thumbnails above it load
    button.evaluate("b => b.scrollIntoView({block: 'center'})", timeout=5_000)
    data = poll_blob(button, 3)
    if data or not SIZE_LABEL.search(button.inner_text(timeout=5_000)):
        return data
    # the first click asks for the photo (spinner); clicking the spinner'd photo again
    # opens it, which is when WhatsApp says whether the phone still has it
    for wait in (8, 20):
        button.evaluate("b => b.click()", timeout=5_000)
        data = poll_blob(button, wait)
        if data:
            break
    page = button.page
    if page.evaluate("() => [...document.querySelectorAll('img[src^=\"blob:\"]')].some(i => !i.closest('#main'))"):
        page.keyboard.press("Escape")  # the click opened the media viewer
        time.sleep(0.5)
    return data


def save_message_images(msg, msg_id: str) -> list[dict]:
    """Index rows for the message's photos; "file" is empty where a photo couldn't be fetched."""
    count = get_beer_count(msg)
    buttons = msg.locator('div[role="button"][aria-label="Open picture"]')
    if count is None or buttons.count() == 0:
        return []
    timestamp, nickname, _ = extract_user_timestamp(msg)
    match = PLUS_BEER_REGEX.search(extract_message_text(msg).lower())
    caption = match.group(1) if match else ""
    pre = msg.evaluate(
        "el => el.querySelector('[data-pre-plain-text]')?.getAttribute('data-pre-plain-text') ?? ''"
    )
    rows = []
    for i in range(buttons.count()):
        data = fetch_image(buttons.nth(i))
        fname = UNAVAILABLE if data == UNAVAILABLE else ""
        data = data if isinstance(data, dict) else None
        if data:
            folder = "captioned" if caption else "uncaptioned"
            fname = f"{folder}/{msg_id}_{i}.{EXTENSIONS.get(data['type'], 'jpg')}"
            (OUT / folder).mkdir(parents=True, exist_ok=True)
            (OUT / fname).write_bytes(base64.b64decode(data["b64"]))
        rows.append({
            "msg_id": msg_id, "file": fname, "user": nickname, "time": timestamp,
            "pre_plain_text": pre, "caption_plus": caption, "scanner_count": count,
            "images_in_msg": buttons.count(),
            "w": data["w"] if data else "", "h": data["h"] if data else "",
        })
    return rows


COVERED_JS = """() => {
  const main = document.querySelector('#main');
  if (!main) return false;
  const r = main.getBoundingClientRect();
  return !main.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2));
}"""


def reset_screen(page) -> None:
    """
    Close whatever a failed photo left open (media viewer, dialogs) so later
    clicks land. Escape only while something covers the chat: with nothing
    open it would close the chat itself.
    """
    try:
        close_unavailable(page)
        for _ in range(3):
            if not page.evaluate(COVERED_JS):
                break
            page.keyboard.press("Escape")
            time.sleep(0.5)
        dismiss_dialogs(page)
    except Exception as e:
        print(f"could not reset the screen: {type(e).__name__}: {str(e).splitlines()[0]}", flush=True)


def loaded_before(panel, cutoff: datetime) -> bool:
    """True once every mounted dated message is older than the cutoff."""
    pres = panel.locator("[data-pre-plain-text]").evaluate_all(
        "els => els.map(e => e.getAttribute('data-pre-plain-text'))"
    )
    dates = [datetime(int(m[3]), int(m[1]), int(m[2])) for p in pres if (m := PRE_DATE.search(p))]
    return bool(dates) and max(dates) < cutoff


def click_older_messages(page) -> bool:
    """Ask the phone for the next chunk of history, if WhatsApp offers it."""
    button = page.locator("#main button", has_text=OLDER_MESSAGES)
    if button.count() == 0:
        return False
    dismiss_dialogs(page)
    button.first.click(timeout=10_000)
    time.sleep(5)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--max-passes", type=int, default=100_000, help="stop after this many scroll passes")
    parser.add_argument(
        "--max-age-days", type=int,
        help="stop once the chat is scrolled past this age (WhatsApp keeps photos ~30 days)",
    )
    parser.add_argument("--debug-dir", type=Path, help="save a screenshot of the first few failures here")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    index = load_index()
    done = {r["msg_id"] for r in index if r["file"]}  # includes photos the phone no longer has
    seen: set[str] = set()
    failures: dict[str, int] = {}
    print(f"resuming with {len(index)} indexed images", flush=True)

    context, page = launch_browser(user_data_dir=str(ROOT / USER_DATA_DIR))
    try:
        open_whatsapp(page)
        open_group(page, GROUP_PREFIX)
        panel = get_chat_panel(page)
        scroll_to_bottom(page, panel)

        stalled, prev_oldest, new = 0, None, 0
        for p in range(args.max_passes):
            seen_before = len(seen)
            for row in reversed(get_visible_snapshot(panel)):
                msg_id = row["id"]
                if not msg_id or msg_id in seen or row["virtualized"] != "false":
                    continue
                msg = locator_for_id(panel, msg_id)
                # scrolling a photo into view can unmount rows from the same snapshot
                if msg.count() == 0 or not is_rendered(msg):
                    continue
                seen.add(msg_id)
                if msg_id in done:
                    continue
                try:
                    rows = save_message_images(msg, msg_id)
                except Exception as e:
                    print(f"failed {msg_id}: {type(e).__name__}: {str(e).splitlines()[0]}", flush=True)
                    rows = None
                    if args.debug_dir and len(failures) < 5:
                        args.debug_dir.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=args.debug_dir / f"failed_{msg_id}.png")
                        (args.debug_dir / f"failed_{msg_id}.txt").write_text(str(e))
                    reset_screen(page)
                if rows:
                    # replace entries left without a file by an earlier run
                    index = [r for r in index if r["msg_id"] != msg_id] + rows
                    new += sum(bool(r["file"]) and r["file"] != UNAVAILABLE for r in rows)
                if rows is None or not all(r["file"] for r in rows):
                    # retry in a later pass, when the row is mounted and on screen again
                    failures[msg_id] = failures.get(msg_id, 0) + 1
                    if failures[msg_id] < 3:
                        seen.discard(msg_id)
                    continue
                done.add(msg_id)

            if args.max_age_days and loaded_before(panel, datetime.now() - timedelta(days=args.max_age_days)):
                print(f"reached messages older than {args.max_age_days} days", flush=True)
                break

            oldest = oldest_loaded_id(panel)
            stalled = 0 if oldest != prev_oldest or len(seen) > seen_before else stalled + 1
            prev_oldest = oldest
            if p % 20 == 0:
                save_index(index)
                oldest_date = next((r["pre_plain_text"] for r in reversed(index) if r["pre_plain_text"]), "")
                missing = sum(not r["file"] for r in index)
                unavailable = sum(r["file"] == UNAVAILABLE for r in index)
                print(
                    f"pass {p}: {new} new images, {len(index)} indexed ({missing} pending, "
                    f"{unavailable} no longer on the phone), "
                    f"oldest so far {oldest_date[:24]}",
                    flush=True,
                )
            if stalled >= MAX_HISTORY_PASSES:
                if click_older_messages(page):
                    stalled = 0
                    continue
                print("reached the start of the chat history", flush=True)
                break
            load_older(page, panel)
    finally:
        save_index(index)
        context.close()
        print(f"done: {new} new images, {len(index)} indexed", flush=True)


if __name__ == "__main__":
    main()

import rootutils


rootutils.setup_root(__file__, indicator="README.md", pythonpath=True)

import time
import sqlite3

from playwright.sync_api import Locator, Page
from listener.utils.tools import launch_browser
from listener.whatsapp import get_chat_panel, open_group, open_whatsapp
from data.utils.db_utils import DB_PATH
from listener import GROUP_PREFIX

INITIAL_BEER_COUNT = 73
BOT_NAME = "@PivoBot"
answered_message_ids: set[str] = set()


def get_total_beers(conn: sqlite3.Connection) -> int:
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(beer_count) FROM messages")
    result = cursor.fetchone()
    return int(result[0] or 0)


def extract_message_text(msg: Locator) -> str:
    spans = msg.locator('span[data-testid="selectable-text"] span')
    print(f"Found {spans.count()} spans in message.")
    for i in range(spans.count()):
        text = spans.nth(i).inner_text().strip()
        if text:
            return text
    return ""


def is_pivo_query(text: str) -> bool:
    text_lower = text.lower()
    return BOT_NAME.lower() in text_lower and "koliko piva" in text_lower


def send_message(page: Page, text: str) -> None:
    """Send a message in the WhatsApp chat."""
    input_field = page.locator('//*[@id="main"]/footer/div[1]/div/span/div/div/div/div[3]/div[1]')
    input_field.click()
    input_field.fill(text)
    input_field.press("Enter")


def respond_to_pivo_queries(conn: sqlite3.Connection, page: Page, chat_panel: Locator) -> None:
    """
    Pregledava nove poruke i odgovara na '@PivoBot koliko piva'.
    Odgovara samo jednom po batch-u i pamti poruke na koje je već odgovorio.
    """
    answered_in_batch = False

    messages = chat_panel.locator("div[data-id]")
    for i in range(messages.count() - 1, -1, -1):
        msg = messages.nth(i)
        msg_id = msg.get_attribute("data-id")
        if not msg_id or msg_id in answered_message_ids:
            continue

        text = extract_message_text(msg)
        if "@PivoBot" in text and "koliko piva" in text.lower():
            if not answered_in_batch:
                cursor = conn.cursor()
                cursor.execute("SELECT SUM(beer_count) FROM messages")
                result = cursor.fetchone()
                total_beers = (
                    INITIAL_BEER_COUNT + result[0] if result and result[0] is not None else 0
                )

                input_box = page.locator(
                    '//*[@id="main"]/footer/div[1]/div/span/div/div/div/div[3]/div[1]'
                )
                input_box.click()
                input_box.fill(f"Piva popijenih do sad: {total_beers}")
                input_box.press("Enter")

                answered_in_batch = True
                print(f"PivoBot je odgovorio: {total_beers} piva")

            # dodajemo u globalni set da znamo da smo odgovorili na ovu poruku
            answered_message_ids.add(msg_id)


def main() -> None:
    context, page = launch_browser(user_data_dir="chat_listener_data")
    open_whatsapp(page)
    open_group(page, GROUP_PREFIX)
    chat_panel = get_chat_panel(page)

    try:
        print("PivoBot is running...")
        while True:
            with sqlite3.connect(DB_PATH) as conn:
                respond_to_pivo_queries(conn, page, chat_panel)
                time.sleep(10)
    finally:
        try:
            context.close()
        except Exception as e:
            print(f"Warning: error while closing browser/context: {e}")


if __name__ == "__main__":
    main()

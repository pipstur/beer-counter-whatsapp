from __future__ import annotations

import time
from playwright.sync_api import Page, Locator


def open_whatsapp(page: Page) -> None:
    page.goto("https://web.whatsapp.com")
    page.wait_for_selector("div[role='grid']", timeout=60_000)
    page.evaluate("document.body.style.zoom='50%'")
    time.sleep(1)


def dismiss_dialogs(page: Page, attempts: int = 3) -> None:
    dialogs = page.locator("div[role='dialog'][aria-modal='true']")
    for _ in range(attempts):
        if dialogs.count() == 0:
            return
        print(f"Dismissing WhatsApp dialog: {dialogs.first.inner_text()[:200]!r}")
        page.keyboard.press("Escape")
        time.sleep(1)
    if dialogs.count() > 0:
        raise RuntimeError(
            f"WhatsApp dialog could not be dismissed: {dialogs.first.inner_text()[:200]!r}"
        )


def open_group(page: Page, group_prefix: str) -> None:
    dismiss_dialogs(page)
    chats = page.locator("span[title]")
    for i in range(chats.count()):
        title = chats.nth(i).get_attribute("title")
        if title and title.lower().startswith(group_prefix):
            chats.nth(i).click()
            time.sleep(2)
            return
    raise RuntimeError(f"Group starting with '{group_prefix}' not found")


def get_chat_panel(page: Page) -> Locator:
    panel = page.locator('//*[@id="main"]/div[2]/div/div/div[2]/div[3]')
    if not panel.element_handle(timeout=10_000):
        raise RuntimeError("Chat panel not found")
    return panel

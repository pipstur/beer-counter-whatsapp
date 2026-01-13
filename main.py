import rootutils

rootutils.setup_root(__file__, indicator="README.md", pythonpath=True)

from listener.utils.tools import launch_browser, live_checker
from listener.whatsapp import open_whatsapp, open_group, get_chat_panel
from listener import GROUP_PREFIX
from data.utils.db_utils import init_db
from data.utils import DB_PATH


def main() -> None:
    init_db(DB_PATH)
    context, page = launch_browser()

    try:
        open_whatsapp(page)
        open_group(page, GROUP_PREFIX)
        chat_panel = get_chat_panel(page)
        print("Scanning messages")
        live_checker(page, chat_panel)
    finally:
        context.close()


if __name__ == "__main__":
    main()

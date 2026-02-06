from typing import Any
import rootutils

rootutils.setup_root(__file__, indicator="README.md", pythonpath=True)

from listener.utils.tools import launch_browser, live_checker
from listener.whatsapp import open_whatsapp, open_group, get_chat_panel
from listener import GROUP_PREFIX, USER_DATA_DIR
from data.utils.db_utils import init_db
from data.utils import DB_PATH

from argparse import ArgumentParser

def cli() -> Any:
    parser = ArgumentParser(description="Beer Counter WhatsApp Listener")
    parser.add_argument("--live", action="store_true", help="Enable live mode")
    return parser.parse_args()

def main() -> None:
    init_db(DB_PATH)
    context, page = launch_browser(user_data_dir=USER_DATA_DIR)
    args = cli()
    try:
        open_whatsapp(page)
        open_group(page, GROUP_PREFIX)
        chat_panel = get_chat_panel(page)
        print("Scanning messages")
        live_checker(page, chat_panel, args.live)
    finally:
        context.close()


if __name__ == "__main__":
    main()

import rootutils

rootutils.setup_root(__file__, indicator="README.md", pythonpath=True)

import sqlite3
import time
from data.utils import DB_PATH

from data.utils.db_utils import get_unsynced_messages, mark_messages_synced, push_to_supabase


def live_sync_loop(local_db_path: str, interval_sec: int = 300) -> None:
    """Main loop: checks local DB every interval and pushes new messages."""
    print("Live sync checker started...")

    while True:
        with sqlite3.connect(local_db_path, timeout=30) as conn:
            unsynced = get_unsynced_messages(conn)
            if unsynced:
                print(f"Found {len(unsynced)} unsynced messages. Pushing...")
                success = push_to_supabase(unsynced)
                if success:
                    mark_messages_synced(conn, [msg["id"] for msg in unsynced])
                    print("Messages synced successfully.")
            else:
                print("No new messages to sync.")
        time.sleep(interval_sec)


if __name__ == "__main__":
    live_sync_loop(DB_PATH, interval_sec=300)  # check every 5 min

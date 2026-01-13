import sqlite3
from data.utils import DB_PATH
from typing import List, Tuple, Dict
from dotenv import load_dotenv
import os
import requests

Row = Tuple[str, str, str, int]
load_dotenv(dotenv_path=".env")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_API_KEY = os.getenv("SUPABASE_API_KEY")

HEADERS = {
    "apikey": SUPABASE_API_KEY,
    "Authorization": f"Bearer {SUPABASE_API_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates",
}

HEADERS_GET = {"apikey": SUPABASE_API_KEY, "Authorization": f"Bearer {SUPABASE_API_KEY}"}


def init_db(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        user TEXT NOT NULL,
        timestamp TEXT NOT NULL,        -- ISO-8601 string
        beer_count INTEGER NOT NULL,
        synced INTEGER NOT NULL DEFAULT 0
    );
            """
        )
        conn.commit()


def connect_db() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def save_message(
    conn: sqlite3.Connection,
    msg_id: str,
    user: str,
    timestamp: str,
    beer_count: int,
) -> None:
    try:
        conn.execute(
            "INSERT INTO messages (id, user, timestamp, beer_count) VALUES (?, ?, ?, ?)",
            (msg_id, user, timestamp, beer_count),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass


def fetch_all_messages(conn: sqlite3.Connection) -> List[Row]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, user, timestamp, beer_count
        FROM messages
        ORDER BY timestamp
        """
    )
    return cur.fetchall()


def rank_users_by_beer(conn: sqlite3.Connection) -> List[Tuple[str, int]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT user, SUM(beer_count) AS total_beers
        FROM messages
        GROUP BY user
        ORDER BY total_beers DESC
        """
    )
    return cur.fetchall()


def beers_per_day(conn: sqlite3.Connection) -> List[Tuple[str, int]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT substr(timestamp, 1, 10) AS day, SUM(beer_count) AS total_beers
        FROM messages
        WHERE timestamp != 'unknown'
        GROUP BY day
        ORDER BY total_beers DESC
        """
    )
    return cur.fetchall()


def beers_per_user_per_day(conn: sqlite3.Connection) -> List[Tuple[str, str, int]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            user,
            substr(timestamp, 1, 10) AS day,
            SUM(beer_count) AS total_beers
        FROM messages
        WHERE timestamp != 'unknown'
        GROUP BY user, day
        ORDER BY total_beers DESC
        """
    )
    return cur.fetchall()


def user_drinking_days(conn: sqlite3.Connection, user: str) -> List[Tuple[str, int]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            substr(timestamp, 1, 10) AS day,
            SUM(beer_count) AS total_beers
        FROM messages
        WHERE user = ?
          AND timestamp != 'unknown'
        GROUP BY day
        ORDER BY total_beers DESC
        """,
        (user,),
    )
    return cur.fetchall()


def get_unsynced_messages(conn: sqlite3.Connection) -> List[Dict]:
    """Fetch messages that haven't been synced yet."""
    cursor = conn.cursor()
    cursor.execute("SELECT id, user, timestamp, beer_count FROM messages WHERE synced = 0")
    rows = cursor.fetchall()
    messages = [
        {"id": r[0], "user_name": r[1], "timestamp": r[2], "beer_count": r[3]} for r in rows
    ]
    return messages


def mark_messages_synced(conn: sqlite3.Connection, ids: List[str]) -> None:
    """Mark messages as synced in local DB."""
    cursor = conn.cursor()
    cursor.executemany(
        "UPDATE messages SET synced = 1 WHERE id = ?", [(msg_id,) for msg_id in ids]
    )
    conn.commit()


def push_to_supabase(messages: List[Dict]) -> bool:
    """Push a batch of messages to Supabase."""
    if not messages:
        return True
    try:
        response = requests.post(SUPABASE_URL, json=messages, headers=HEADERS)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"Failed to push to Supabase: {e}")
        return False


def get_messages():
    url = f"{SUPABASE_URL}/rest/v1/messages"
    response = requests.get(url, headers=HEADERS_GET)
    response.raise_for_status()
    return response.json()

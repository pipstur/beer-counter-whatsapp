import sqlite3
from .db_utils import (
    fetch_all_messages,
    rank_users_by_beer,
    beers_per_day,
    beers_per_user_per_day,
    user_drinking_days,
)


def print_total_beers(conn: sqlite3.Connection) -> None:
    rows = fetch_all_messages(conn)
    print(rows)
    print(f"Total items: {len(rows)}\n")


def print_user_ranking(conn: sqlite3.Connection) -> None:
    rows = rank_users_by_beer(conn)
    for i, (user, total) in enumerate(rows, start=1):
        print(f"{i}. {user}: {total}")


def print_beers_per_day(conn: sqlite3.Connection) -> None:
    rows = beers_per_day(conn)
    for day, total in rows:
        print(f"{day}: {total}")


def print_beers_per_user_per_day(conn: sqlite3.Connection) -> None:
    rows = beers_per_user_per_day(conn)
    for user, day, total in rows:
        print(f"{user} | {day}: {total}")


def print_user_stats(conn: sqlite3.Connection) -> None:
    user = input("User name: ").strip()
    rows = user_drinking_days(conn, user)
    if not rows:
        print("No data.")
        return
    for day, total in rows:
        print(f"{day}: {total}")

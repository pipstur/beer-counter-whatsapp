import rootutils

rootutils.setup_root(__file__, indicator="README.md", pythonpath=True)

from data.utils.dashboard_utils import (
    print_total_beers,
    print_user_ranking,
    print_beers_per_day,
    print_beers_per_user_per_day,
    print_user_stats,
)
from data.utils.db_utils import connect_db


def main() -> None:
    conn = connect_db()
    exit = 0
    while not exit:
        try:
            print(
                "\n".join(
                    [
                        "0 - Exit",
                        "1 - Total number of beers",
                        "2 - Rank users by total beers",
                        "3 - Beers per day",
                        "4 - Beers per user per day",
                        "5 - Stats for a single user",
                    ]
                )
            )
            choice = input("Select: ").strip()
            if choice == "0":
                exit = 1
                conn.close()
            elif choice == "1":
                print_total_beers(conn)
            elif choice == "2":
                print_user_ranking(conn)
            elif choice == "3":
                print_beers_per_day(conn)
            elif choice == "4":
                print_beers_per_user_per_day(conn)
            elif choice == "5":
                print_user_stats(conn)
            else:
                print("Invalid choice.")
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    main()

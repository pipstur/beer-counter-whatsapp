import sqlite3

import pytest

from data.utils import INITIAL_BEER_COUNT
from listener.chat_listener import get_total_beers, is_pivo_query


@pytest.fixture
def conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE messages (id TEXT, beer_count INTEGER)")
    yield conn
    conn.close()


def test_total_beers_empty_db_is_initial_count(conn):
    assert get_total_beers(conn) == INITIAL_BEER_COUNT


def test_total_beers_adds_initial_count(conn):
    conn.executemany("INSERT INTO messages VALUES (?, ?)", [("a", 2), ("b", 3)])
    assert get_total_beers(conn) == INITIAL_BEER_COUNT + 5


@pytest.mark.parametrize(
    "text, expected",
    [
        ("@PivoBot koliko piva?", True),
        ("@pivobot Koliko piva", True),
        ("koliko piva", False),
        ("@PivoBot zdravo", False),
    ],
)
def test_is_pivo_query(text, expected):
    assert is_pivo_query(text) == expected

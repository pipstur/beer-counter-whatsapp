from datetime import date

import pytest

from data.utils.data_utils import convert_to_24h, determine_day_rollover, parse_time_12h
from listener import PLUS_BEER_REGEX, TIME_REGEX


@pytest.mark.parametrize(
    "timestamp, expected",
    [
        ("10:51 AM", (10, 51, "AM")),
        ("10:51AM", (10, 51, "AM")),
        ("9:05 pm", (9, 5, "PM")),
        ("14:30", (14, 30, "")),
    ],
)
def test_parse_time_12h(timestamp, expected):
    assert parse_time_12h(timestamp) == expected


def test_parse_time_12h_rejects_garbage():
    with pytest.raises(ValueError):
        parse_time_12h("yesterday")


@pytest.mark.parametrize("text", ["10:51 AM", "10:51AM", "14:30"])
def test_time_regex_matches_are_parseable(text):
    assert parse_time_12h(TIME_REGEX.search(text).group(0))


@pytest.mark.parametrize(
    "hour, ampm, expected",
    [(12, "AM", 0), (1, "AM", 1), (12, "PM", 12), (11, "PM", 23), (14, "", 14)],
)
def test_convert_to_24h(hour, ampm, expected):
    assert convert_to_24h(hour, ampm) == expected


def test_rollover_first_message_keeps_date():
    assert determine_day_rollover(None, None, 22, 0, date(2026, 11, 6)) == date(2026, 11, 6)


def test_rollover_earlier_time_same_day():
    # scanning newest -> oldest: 21:00 seen after 22:00 is the same evening
    assert determine_day_rollover(22, 0, 21, 0, date(2026, 11, 6)) == date(2026, 11, 6)


def test_rollover_later_time_is_previous_day():
    # 23:30 seen after 01:00 must be the night before
    assert determine_day_rollover(1, 0, 23, 30, date(2026, 11, 6)) == date(2026, 11, 5)


@pytest.mark.xfail(reason="dates are inferred from time order only; multi-day gaps collapse")
def test_rollover_multi_day_gap():
    # Wed 19:00 newest, previous beer message was Mon 20:00
    assert determine_day_rollover(19, 0, 20, 0, date(2026, 10, 21)) == date(2026, 10, 19)


@pytest.mark.parametrize("text, expected", [("+1", "1"), ("evo +12 ", "12"), ("+300", "300")])
def test_plus_beer_regex(text, expected):
    assert PLUS_BEER_REGEX.search(text).group(1) == expected

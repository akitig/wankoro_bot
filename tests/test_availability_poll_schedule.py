from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from config import parse_time_windows
from services.availability_poll_service import next_scheduled_at, parse_windows

JST = ZoneInfo("Asia/Tokyo")
WEEKDAY = parse_windows(("20:00-21:00",))
HOLIDAY = parse_windows(("13:00-14:00", "20:00-21:00"))


def choose_min(start: int, _end: int) -> int:
    return start


def choose_max(_start: int, end: int) -> int:
    return end - 1


def schedule(now: datetime, *, random=choose_min, holidays=frozenset()):
    return next_scheduled_at(
        now=now,
        timezone_info=JST,
        weekday_windows=WEEKDAY,
        holiday_windows=HOLIDAY,
        holiday_checker=lambda day: day in holidays,
        randrange=random,
    )


def test_weekday_and_exact_window_start() -> None:
    assert schedule(datetime(2026, 8, 3, 12, 0, tzinfo=JST)) == datetime(
        2026, 8, 3, 20, 0, tzinfo=JST
    )
    assert schedule(datetime(2026, 8, 3, 20, 0, tzinfo=JST)) == datetime(
        2026, 8, 3, 20, 0, tzinfo=JST
    )


@pytest.mark.parametrize("day", [1, 2])
def test_weekend_has_afternoon_and_evening_windows(day: int) -> None:
    assert schedule(datetime(2026, 8, day, 10, 0, tzinfo=JST)).hour == 13
    assert schedule(datetime(2026, 8, day, 14, 0, tzinfo=JST)).hour == 20


def test_japanese_holiday_uses_holiday_windows() -> None:
    holiday = date(2026, 8, 3)
    assert schedule(
        datetime(2026, 8, 3, 10, 0, tzinfo=JST), holidays={holiday}
    ).hour == 13


def test_end_is_exclusive_and_maximum_is_last_second() -> None:
    result = schedule(datetime(2026, 8, 3, 19, 0, tzinfo=JST), random=choose_max)
    assert result == datetime(2026, 8, 3, 20, 59, 59, tzinfo=JST)
    after = schedule(datetime(2026, 8, 3, 21, 0, tzinfo=JST))
    assert after.date() == date(2026, 8, 4)


def test_date_week_and_year_boundaries() -> None:
    friday = schedule(datetime(2026, 7, 31, 21, 1, tzinfo=JST))
    assert friday == datetime(2026, 8, 1, 13, 0, tzinfo=JST)
    sunday = schedule(datetime(2026, 8, 2, 21, 1, tzinfo=JST))
    assert sunday == datetime(2026, 8, 3, 20, 0, tzinfo=JST)
    year = schedule(datetime(2026, 12, 31, 21, 1, tzinfo=JST))
    assert year.year == 2027


def test_custom_multiple_windows() -> None:
    result = next_scheduled_at(
        now=datetime(2026, 8, 3, 20, 30, tzinfo=JST),
        timezone_info=JST,
        weekday_windows=parse_windows(("19:30-20:15", "22:00-23:00")),
        holiday_windows=HOLIDAY,
        holiday_checker=lambda _day: False,
        randrange=choose_min,
    )
    assert result == datetime(2026, 8, 3, 22, 0, tzinfo=JST)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("20:00-21:00", ("20:00-21:00",)),
        (
            " 22:00-23:00 , 19:30-20:15 ",
            ("19:30-20:15", "22:00-23:00"),
        ),
        ("20:00-21:00,20:00-21:00", ("20:00-21:00",)),
    ],
)
def test_config_window_normalization(raw: str, expected: tuple[str, ...]) -> None:
    assert parse_time_windows(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "20:00-21:00,",
        "20-21:00",
        "24:00-25:00",
        "20:60-21:00",
        "21:00-20:00",
        "20:00-20:00",
        "20:00-21:00,20:30-22:00",
    ],
)
def test_config_rejects_invalid_windows(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_time_windows(raw)

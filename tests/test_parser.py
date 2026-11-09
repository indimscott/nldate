from datetime import date

from nldate import parse


def test_today():
    assert parse("today", today=date(2025, 12, 1)) == date(2025, 12, 1)


def test_tomorrow():
    assert parse("tomorrow", today=date(2025, 12, 1)) == date(2025, 12, 2)


def test_yesterday():
    assert parse("yesterday", today=date(2025, 12, 1)) == date(2025, 11, 30)


def test_in_three_days():
    assert parse("in 3 days", today=date(2025, 12, 1)) == date(2025, 12, 4)


def test_next_week():
    assert parse("next week", today=date(2025, 12, 1)) == date(2025, 12, 8)


def test_three_days_ago():
    assert parse("3 days ago", today=date(2025, 12, 1)) == date(2025, 11, 28)


def test_in_one_year():
    assert parse("in one year", today=date(2025, 12, 1)) == date(2026, 12, 1)


def test_in_one_month():
    assert parse("in one month", today=date(2025, 12, 1)) == date(2026, 1, 1)


def test_next_Tuesday():
    assert parse("next Tuesday", today=date(2025, 12, 1)) == date(2025, 12, 2)


def test_next_tues_tdy_tues():
    assert parse("next Tuesday", today=date(2025, 12, 2)) == date(2025, 12, 9)


def test_absolute_date():
    assert parse("December 1, 2025") == date(2025, 12, 1)


def test_days_before_date():
    assert parse("5 days before December 1st, 2025") == date(2025, 11, 26)


def test_multiple_units():
    assert parse(
        "1 year and 2 months after yesterday", today=date(2025, 12, 1)
    ) == date(2027, 1, 30)


def test_weeks_from_tomorrow():
    assert parse("two weeks from tomorrow", today=date(2025, 12, 1)) == date(
        2025, 12, 16
    )


def test_slash_date():
    assert parse("2025/12/04") == date(2025, 12, 4)

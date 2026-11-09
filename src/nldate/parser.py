"""Natural-language date parsing.

The grammar is recursive: an expression is either a simple date (a keyword,
an absolute date, "next Tuesday", "in 3 days", ...) or

    <duration> (before | after | from) <expression>

so offsets can be stacked on top of any other date expression.
"""

import calendar
import re
from datetime import date, timedelta

# --- Vocabulary -------------------------------------------------------------

# Single words relative to the reference date.
_RELATIVE_DAYS = {
    "today": 0,
    "now": 0,
    "tomorrow": 1,
    "yesterday": -1,
}

_ONES = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}

_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}

# Every accepted spelling of a weekday, mapped to date.weekday() (Monday == 0).
_WEEKDAYS = {
    name: index
    for index, names in enumerate(
        [
            ("monday", "mon"),
            ("tuesday", "tue", "tues"),
            ("wednesday", "wed"),
            ("thursday", "thu", "thur", "thurs"),
            ("friday", "fri"),
            ("saturday", "sat"),
            ("sunday", "sun"),
        ]
    )
    for name in names
}

# Every accepted spelling of a month, mapped to its number (January == 1).
_MONTHS = {
    name: index
    for index, names in enumerate(
        [
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ],
        start=1,
    )
    for name in names
}

# A duration is stored as (months, days). Years are 12 months and weeks are
# 7 days, so these two numbers are enough to represent any combination.
Duration = tuple[int, int]

_UNIT_SIZES: dict[str, Duration] = {
    "day": (0, 1),
    "week": (0, 7),
    "month": (1, 0),
    "year": (12, 0),
}

# --- Regex rules ------------------------------------------------------------

# One "<n> <unit>" piece of a duration, e.g. "3 days" or "twenty-one weeks".
_DURATION_PART = re.compile(
    r"(?P<num>\d+|[a-z]+(?:[- ][a-z]+)?) (?P<unit>day|week|month|year)s?"
)
# Separators between duration pieces: "1 year and 2 months", "1 year, 2 days".
_DURATION_SEPARATOR = re.compile(r",? and |, ")

# "<duration> before/after/from <expression>". The duration is non-greedy, so
# the split happens at the FIRST keyword and the rest is parsed recursively.
_OFFSET_PATTERN = re.compile(r"(?P<dur>.+?) (?P<op>before|after|from) (?P<ref>.+)")
_IN_PATTERN = re.compile(r"in (?P<dur>.+)")  # "in 3 days"
_AGO_PATTERN = re.compile(r"(?P<dur>.+) ago")  # "3 days ago"
_NEXT_LAST_PATTERN = re.compile(r"(?P<dir>next|last) (?P<word>[a-z]+)")

# A day of the month with an optional ordinal suffix: "1", "1st", "22nd".
_DAY = r"(?P<day>\d{1,2})(?P<suffix>st|nd|rd|th)?"
_YEAR = r"(?P<year>\d{4})"
_ABSOLUTE_PATTERNS = [
    # "December 1, 2025", "Dec 1st 2025", "December 1st" (year optional)
    re.compile(rf"(?P<month>[a-z]+)\.? {_DAY}(?:,? {_YEAR})?"),
    # "1 December 2025", "1st of December, 2025"
    re.compile(rf"{_DAY} (?:of )?(?P<month>[a-z]+)\.?(?:,? {_YEAR})?"),
    # Numeric year-month-day: "2025-12-01" or "2025/12/01". (?P=sep) makes the
    # second separator match the first, so mixed forms like "2025-12/01" fail.
    re.compile(
        r"(?P<year>\d{4})(?P<sep>[-/])(?P<month>\d{1,2})(?P=sep)(?P<day>\d{1,2})"
    ),
]


# --- Helpers ----------------------------------------------------------------


def _parse_number(text: str) -> int:
    """Convert "3", "three", "twenty-one", or "a" to an int."""
    if text.isdigit():
        return int(text)
    if text in ("a", "an"):
        return 1
    if text in _ONES:
        return _ONES[text]
    if text in _TENS:
        return _TENS[text]

    # Compound like "twenty-one" or "twenty one".
    parts = re.split(r"[- ]", text)
    if len(parts) == 2 and parts[0] in _TENS and parts[1] in _ONES:
        ones = _ONES[parts[1]]
        if 1 <= ones <= 9:
            return _TENS[parts[0]] + ones

    raise ValueError(f"Unrecognized number: {text!r}")


def _parse_duration(text: str) -> Duration:
    """Convert "1 year and 2 months" or "two weeks" to (months, days)."""
    months = days = 0
    for piece in _DURATION_SEPARATOR.split(text):
        match = _DURATION_PART.fullmatch(piece)
        if not match:
            raise ValueError(f"Unrecognized duration: {text!r}")
        amount = _parse_number(match["num"])
        unit_months, unit_days = _UNIT_SIZES[match["unit"]]
        months += amount * unit_months
        days += amount * unit_days
    return months, days


def _add_months(start: date, months: int) -> date:
    """Add calendar months, clamping the day to the end of a shorter month."""
    # Count months from year 0 so negative values and year changes just work.
    total = start.year * 12 + (start.month - 1) + months
    year, month_index = divmod(total, 12)
    month = month_index + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(start.day, last_day))


def _apply(start: date, duration: Duration, sign: int = 1) -> date:
    """Move from `start` by `duration`, forward (sign=1) or backward (-1).

    Months (and years) are applied before days, the usual convention, so
    "1 month and 1 day after January 31" lands on March 1, not March 2.
    """
    months, days = duration
    return _add_months(start, sign * months) + timedelta(days=sign * days)


def _weekday_after(start: date, weekday: int, direction: int) -> date:
    """Nearest `weekday` strictly after (direction=1) or before (-1) `start`."""
    if direction > 0:
        days = (weekday - start.weekday()) % 7 or 7
    else:
        days = -((start.weekday() - weekday) % 7 or 7)
    return start + timedelta(days=days)


def _check_ordinal(day: int, suffix: str | None) -> None:
    """Reject mismatched ordinals like "1th" or "2st"."""
    if suffix is None:
        return
    if day % 100 in (11, 12, 13):
        expected = "th"
    else:
        expected = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    if suffix != expected:
        raise ValueError(f"Invalid ordinal: {day}{suffix}")


def _parse_absolute(text: str, today: date) -> date | None:
    """Parse an absolute calendar date, or return None if it isn't one."""
    for pattern in _ABSOLUTE_PATTERNS:
        match = pattern.fullmatch(text)
        if not match:
            continue
        month_text = match["month"]
        if month_text.isdigit():
            month = int(month_text)
        elif month_text in _MONTHS:
            month = _MONTHS[month_text]
        else:
            continue  # Shape fits but the word isn't a month; try the others.
        day = int(match["day"])
        _check_ordinal(day, match.groupdict().get("suffix"))
        year = int(match["year"]) if match["year"] else today.year
        # date() itself raises ValueError for impossible dates like Feb 30.
        return date(year, month, day)
    return None


def _parse_expression(text: str, today: date) -> date:
    """Parse a normalized (lowercase, single-spaced) expression."""
    if text in _RELATIVE_DAYS:
        return today + timedelta(days=_RELATIVE_DAYS[text])

    # Compound offsets first, so "3 days before 2 days ago" splits at
    # "before" instead of being misread as "<duration> ago".
    if match := _OFFSET_PATTERN.fullmatch(text):
        duration = _parse_duration(match["dur"])
        reference = _parse_expression(match["ref"], today)
        sign = -1 if match["op"] == "before" else 1
        return _apply(reference, duration, sign)

    if match := _IN_PATTERN.fullmatch(text):
        return _apply(today, _parse_duration(match["dur"]))

    if match := _AGO_PATTERN.fullmatch(text):
        return _apply(today, _parse_duration(match["dur"]), sign=-1)

    if match := _NEXT_LAST_PATTERN.fullmatch(text):
        direction = 1 if match["dir"] == "next" else -1
        word = match["word"]
        if word in _WEEKDAYS:
            return _weekday_after(today, _WEEKDAYS[word], direction)
        unit = word.removesuffix("s")
        if unit in _UNIT_SIZES:
            return _apply(today, _UNIT_SIZES[unit], direction)

    if (absolute := _parse_absolute(text, today)) is not None:
        return absolute

    raise ValueError(f"Unrecognized date expression: {text!r}")


# --- Public API -------------------------------------------------------------


def parse(s: str, today: date | None = None) -> date:
    """Parse a natural-language date string into a date.

    Supported forms (case-insensitive):
      - "today", "tomorrow", "yesterday"
      - absolute dates: "December 1, 2025", "Dec 1st 2025",
        "1st of December 2025", "2025-12-01" (year defaults to today's)
      - "in <duration>"       e.g. "in 3 days", "in one month"
      - "<duration> ago"      e.g. "3 days ago", "1 year and 2 months ago"
      - "next/last <unit>"    e.g. "next week", "last year"
      - "next/last <weekday>" e.g. "next Tuesday" (never today itself)
      - "<duration> before/after/from <expression>"
        e.g. "two weeks from tomorrow", "5 days before December 1st, 2025"

    A <duration> is one or more "<n> <unit>" pieces joined by "and" or
    commas; <n> may be digits or words; <unit> is day, week, month, or year.

    `today` is the reference date; if None, the current date is used.
    Raises ValueError if the string is empty or not recognized.
    """
    if today is None:
        today = date.today()

    # Normalize: lowercase and collapse runs of whitespace to single spaces.
    text = " ".join(s.lower().split())
    if not text:
        raise ValueError("Empty date string")

    try:
        return _parse_expression(text, today)
    except ValueError as error:
        # Report the user's original string, keeping the specific reason.
        raise ValueError(f"Could not parse {s!r}: {error}") from error

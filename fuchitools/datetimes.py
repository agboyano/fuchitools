"""Date and time conversion for data that arrives in whatever shape the source
felt like: a Spanish ``30/12/2024``, an ISO string, a ``pd.Timestamp``, an
``int`` like ``20261202``, a ``numpy.datetime64`` out of a DataFrame.

The two entry points are :func:`to_date` and :func:`to_datetime`; everything
else is either a building block they use or a small convenience (``today``,
``prev_day_not_weekend``, day boundaries).

Conventions that apply throughout:

- Ambiguous ``D/M/Y`` strings are read **day first** unless ``usaformat=True``.
- Two-digit years are taken to be in the 2000s (``25`` -> 2025, ``99`` -> 2099).
- Missing values (``None``, ``NaN``, ``NaT``, ``pd.NA``) are **not** converted;
  they raise ``ValueError`` like any other unconvertible input.
- Timezone-aware input is passed through as-is; nothing here converts zones.
"""

from __future__ import annotations

import datetime
import numbers
from typing import Optional, Union

import numpy as np
import pandas as pd

__all__ = [
    "timestamp",
    "now",
    "today",
    "prev_day_not_weekend",
    "del_microseconds",
    "end_of_day",
    "start_of_day",
    "time_from_str",
    "date_to_datetime",
    "datetime_from_str",
    "date_from_int",
    "datetime_from_int",
    "to_datetime",
    "to_date",
]

DateLike = Union[datetime.datetime, datetime.date, pd.Timestamp, np.datetime64, str, int]


def _is_missing(x) -> bool:
    """True for None, NaN, NaT and pd.NA (scalars only)."""
    if x is None or x is pd.NaT or x is pd.NA:
        return True
    return isinstance(x, float) and x != x


# --------------------------------------------------------------------------
# Now and today
# --------------------------------------------------------------------------

def timestamp() -> str:
    """Current local time as an ISO 8601 string, e.g. ``'2026-08-26T13:04:22.918233'``.

    Meant for file names and log lines.
    """
    return datetime.datetime.now().isoformat()


def now() -> datetime.datetime:
    """Current local ``datetime`` (``datetime.datetime.now()``)."""
    return datetime.datetime.now()


def today() -> datetime.date:
    """Today's local date as a ``datetime.date``."""
    return datetime.date.today()


def prev_day_not_weekend(
    date: Optional[Union[datetime.date, datetime.datetime]] = None,
) -> Union[datetime.date, datetime.datetime]:
    """The previous day that is not a Saturday or a Sunday.

    Steps back one day and keeps stepping while it lands on a weekend. It
    knows nothing about holidays: the Friday it returns may well be one.

    Parameters
    ----------
    date : datetime.date | datetime.datetime, optional
        Starting point. Defaults to :func:`today`.

    Returns
    -------
    datetime.date | datetime.datetime
        Same type as the input (a ``datetime`` keeps its time of day).

    Examples
    --------
    >>> prev_day_not_weekend(datetime.date(2026, 8, 24))   # a Monday
    datetime.date(2026, 8, 21)
    """
    if date is None:
        date = today()
    prev_day = date - datetime.timedelta(days=1)
    # weekday(): Monday=0 ... Friday=4, Saturday=5, Sunday=6
    while prev_day.weekday() >= 5:
        prev_day -= datetime.timedelta(days=1)
    return prev_day


# --------------------------------------------------------------------------
# Day boundaries
# --------------------------------------------------------------------------

def del_microseconds(x: datetime.datetime) -> datetime.datetime:
    """Return ``x`` with its microseconds set to zero."""
    return x.replace(microsecond=0)


def end_of_day(x: Union[datetime.date, datetime.datetime], microseconds: bool = True) -> datetime.datetime:
    """The last moment of the day ``x`` falls on.

    Parameters
    ----------
    x : datetime.date | datetime.datetime
    microseconds : bool, default True
        With True the result is ``23:59:59.999999``; with False ``23:59:59``,
        for comparisons against stores that cannot hold microseconds (SQLite
        text timestamps, some Excel exports).
    """
    if isinstance(x, datetime.datetime):
        x = x.date()
    dt = datetime.datetime.combine(x, datetime.datetime.max.time())
    if not microseconds:
        dt = del_microseconds(dt)
    return dt


def start_of_day(x: Union[datetime.date, datetime.datetime], microseconds: bool = True) -> datetime.datetime:
    """The first moment (``00:00:00``) of the day ``x`` falls on.

    ``microseconds`` is accepted for symmetry with :func:`end_of_day`; the
    result is the same either way.
    """
    if isinstance(x, datetime.datetime):
        x = x.date()
    dt = datetime.datetime.combine(x, datetime.datetime.min.time())
    if not microseconds:
        dt = del_microseconds(dt)
    return dt


def date_to_datetime(
    x: Union[datetime.date, datetime.datetime],
    endofday: bool = False,
    microseconds: bool = True,
) -> datetime.datetime:
    """Turn a date into the datetime at the start (default) or end of that day.

    Same choice as :func:`start_of_day` / :func:`end_of_day`, expressed as one
    call for when the flag comes from a variable.
    """
    if endofday:
        return end_of_day(x, microseconds=microseconds)
    return start_of_day(x, microseconds=microseconds)


# --------------------------------------------------------------------------
# Parsers
# --------------------------------------------------------------------------

def time_from_str(x: str) -> datetime.time:
    """Parse ``HH:MM`` or ``HH:MM:SS[.ffffff]`` into a ``datetime.time``.

    Raises
    ------
    ValueError
        If the shape is not one of those two, or a component is out of range.

    Examples
    --------
    >>> time_from_str("14:30:45.123456")
    datetime.time(14, 30, 45, 123456)
    """
    t = x.strip().split(":")
    h: int
    m: int
    s: int = 0
    u: int = 0

    if len(t) == 3:
        h_str, m_str, s_str = t
        h, m = int(h_str), int(m_str)
        if "." in s_str:
            s_float = float(s_str)
            s = int(s_float)
            u = int(round((s_float - s) * 1_000_000))
        else:
            s = int(s_str)
    elif len(t) == 2:
        h_str, m_str = t
        h, m = int(h_str), int(m_str)
    else:
        raise ValueError(f"invalid time string: {x!r}")

    return datetime.time(h, m, s, u)


def date_from_int(x: int) -> datetime.date:
    """Parse an ``int`` in ``YYYYMMDD`` form into a ``datetime.date``.

    Raises
    ------
    ValueError
        If ``x`` does not have exactly eight digits or is not a real date.

    Examples
    --------
    >>> date_from_int(20240115)
    datetime.date(2024, 1, 15)
    """
    text = str(int(x))
    if len(text) != 8:
        raise ValueError(f"expected an int in YYYYMMDD form, got {x!r}")
    try:
        return datetime.datetime.strptime(text, "%Y%m%d").date()
    except ValueError as exc:
        raise ValueError(f"{x!r} is not a valid YYYYMMDD date: {exc}") from None


def datetime_from_int(x: int, endofday: bool = False) -> datetime.datetime:
    """Parse ``YYYYMMDD`` into the datetime at the start (or end) of that day."""
    return date_to_datetime(date_from_int(x), endofday=endofday)


def datetime_from_str(
    x: str,
    usaformat: bool = False,
    endofday: bool = False,
) -> datetime.datetime:
    """Parse a date or date-time string.

    Supported shapes:

    - ISO 8601 (``"2024-01-15T14:30:00"``, ``"2024-01-15 14:30:00.123456"``);
      tz-aware strings come back aware, nothing else does.
    - ``YYYYMMDD`` with an optional time (``"20240115 14:30"``).
    - ``D/M/Y`` or ``D-M-Y`` with an optional time, **day first** by default;
      ``M/D/Y`` with ``usaformat=True``. Two-digit years are in the 2000s.

    The time part, when present, is anything :func:`time_from_str` accepts.

    Parameters
    ----------
    x : str
    usaformat : bool, default False
        Read ``12/30/24`` as month/day/year instead of day/month/year.
    endofday : bool, default False
        When no time is given, return ``23:59:59.999999`` instead of ``00:00:00``.

    Raises
    ------
    ValueError
        For an empty string, an unrecognised shape, or a date that does not
        exist (``"30/2/23"``).
    """
    x = x.strip()
    if not x:
        raise ValueError("empty date string")

    try:
        return datetime.datetime.fromisoformat(x)
    except ValueError:
        pass

    dts = x.split()
    hora: Optional[str] = None

    if len(dts) > 2:
        raise ValueError(f"invalid date/time string: {x!r}")
    elif len(dts) == 2:
        hora = dts[1].strip()

    fecha = dts[0].strip()

    if fecha.isdigit() and len(fecha) == 8:
        # YYYYMMDD; explicit so it does not depend on fromisoformat accepting
        # the basic format, which only Python >= 3.11 does.
        dt_date = date_from_int(int(fecha))
    else:
        fs = fecha.split("/")
        if len(fs) == 1:
            fs = fecha.split("-")

        if len(fs) == 1:
            dt_date = datetime.datetime.fromisoformat(fecha).date()
        elif len(fs) != 3:
            raise ValueError(f"invalid date/time string: {x!r}")
        else:
            if usaformat:
                m_str, d_str, y_str = fs
            else:
                d_str, m_str, y_str = fs
            d, m, y = int(d_str), int(m_str), int(y_str)
            if y < 100:
                y += 2000
            dt_date = datetime.date(y, m, d)

    if hora is None:
        return date_to_datetime(dt_date, endofday=endofday)
    return datetime.datetime.combine(dt_date, time_from_str(hora))


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------

def to_datetime(
    x: DateLike,
    usaformat: bool = False,
    endofday: bool = False,
) -> datetime.datetime:
    """Convert anything date-shaped to a plain ``datetime.datetime``.

    Parameters
    ----------
    x : datetime | date | pandas.Timestamp | numpy.datetime64 | str | int
        A ``datetime`` is returned unchanged (a ``pd.Timestamp`` becomes a
        plain ``datetime``); a ``date`` becomes the start (or end) of that
        day; a ``str`` goes through :func:`datetime_from_str`; an integer
        (Python or numpy) is ``YYYYMMDD``.
    usaformat : bool, default False
        Only for strings: read ambiguous dates as month/day/year.
    endofday : bool, default False
        For dates and strings without a time: return the end of the day.

    Raises
    ------
    ValueError
        For missing values (``None``, ``NaN``, ``NaT``), booleans, floats and
        any other type or shape that cannot be converted.

    Examples
    --------
    >>> to_datetime("2026-02-04 23:00:37.651355")
    datetime.datetime(2026, 2, 4, 23, 0, 37, 651355)
    >>> to_datetime(20261202, endofday=True)
    datetime.datetime(2026, 12, 2, 23, 59, 59, 999999)
    """
    if _is_missing(x):
        raise ValueError(f"cannot convert missing value {x!r} to datetime")
    if isinstance(x, bool):
        raise ValueError("cannot convert a bool to datetime")
    if isinstance(x, datetime.datetime):
        if isinstance(x, pd.Timestamp):  # pd.Timestamp is a datetime subclass
            return x.to_pydatetime()
        return x
    if isinstance(x, datetime.date):
        return date_to_datetime(x, endofday=endofday)
    if isinstance(x, np.datetime64):
        ts = pd.Timestamp(x)
        if ts is pd.NaT:
            raise ValueError("cannot convert NaT to datetime")
        return ts.to_pydatetime()
    if isinstance(x, str):
        return datetime_from_str(x, usaformat=usaformat, endofday=endofday)
    if isinstance(x, numbers.Integral):
        return datetime_from_int(int(x), endofday=endofday)
    raise ValueError(f"cannot convert a value of type {type(x).__name__} to datetime")


def to_date(
    x: DateLike,
    usaformat: bool = False,
) -> datetime.date:
    """Convert anything date-shaped to a plain ``datetime.date``.

    Parameters
    ----------
    x : datetime | date | pandas.Timestamp | numpy.datetime64 | str | int
        Same inputs as :func:`to_datetime`; the time of day, if any, is dropped.
    usaformat : bool, default False
        Only for strings: read ambiguous dates as month/day/year.

    Raises
    ------
    ValueError
        For missing values, booleans, floats and anything else unconvertible.

    Examples
    --------
    >>> to_date(20261202)
    datetime.date(2026, 12, 2)
    >>> to_date("3/2/25")
    datetime.date(2025, 2, 3)
    >>> to_date("12/30/24", usaformat=True)
    datetime.date(2024, 12, 30)
    """
    if _is_missing(x):
        raise ValueError(f"cannot convert missing value {x!r} to date")
    if isinstance(x, bool):
        raise ValueError("cannot convert a bool to date")
    if isinstance(x, datetime.datetime):  # includes pd.Timestamp
        return x.date()
    if isinstance(x, datetime.date):
        return x
    if isinstance(x, np.datetime64):
        return to_datetime(x).date()
    if isinstance(x, str):
        return to_datetime(x, usaformat=usaformat).date()
    if isinstance(x, numbers.Integral):
        return date_from_int(int(x))
    raise ValueError(f"cannot convert a value of type {type(x).__name__} to date")

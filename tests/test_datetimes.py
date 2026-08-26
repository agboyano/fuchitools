from __future__ import annotations

import datetime
from typing import Optional, Union

import numpy as np
import pandas as pd
import pytest

from fuchitools.datetimes import *


@pytest.mark.parametrize(
    "input_value, expected",
    [
        (20261202, datetime.date(2026, 12, 2)),
        (20263012, ValueError),
        (pd.Timestamp('2026-02-04 00:00:00'), datetime.date(2026, 2, 4)),
        (pd.Timestamp('2026-02-04 23:00:37.651355'), datetime.date(2026, 2, 4)),
        ('2026-02-04 00:00:00', datetime.date(2026, 2, 4)),
        ('2026-02-04 23:00:37.651355', datetime.date(2026, 2, 4)),
        ('20260301', datetime.date(2026, 3, 1)),
        ('20263001', ValueError),
        ('3/2/25', datetime.date(2025, 2, 3)),
        ('30/12/2024', datetime.date(2024, 12, 30)),
        ('32/12/2024', ValueError),
        ('30/13/2024', ValueError),
        ('30/2/23', ValueError),
        ('12/30/24', ValueError),
        ('12/30/2026', ValueError),

        ('20260301 12:35:45', datetime.date(2026, 3, 1)),
        ('20263001 12:35:45', ValueError),
        ('3/2/25 12:35:45', datetime.date(2025, 2, 3)),
        ('30/12/2024 12:35:45', datetime.date(2024, 12, 30)),

        ('20260301 12:35:45.234', datetime.date(2026, 3, 1)),
        ('20263001 12:35:45.234', ValueError),

        ('20260301 12:35', datetime.date(2026, 3, 1)),
        ('20263001 12:35', ValueError),

        ('20260301 25:35', ValueError),
        ('3/2/25 25:35', ValueError),
    ]
)
def test_to_date(input_value, expected):
    """
    Test unitario de to_date.
    Si falla, pytest mostrará exactamente qué input provocó el error.
    """
    if expected is ValueError:
        with pytest.raises(ValueError):
            to_date(input_value, usaformat=False)
    else:
        result = to_date(input_value, usaformat=False)
        assert result == expected, (
            f"Error con input={input_value!r}. "
            f"Esperado={expected}, obtenido={result}"
        )

@pytest.mark.parametrize(
    "input_value, expected",
    [
        (20261202, datetime.date(2026, 12, 2)),
        (20263012, ValueError),
        (pd.Timestamp('2026-02-04 00:00:00'), datetime.date(2026, 2, 4)),
        (pd.Timestamp('2026-02-04 23:00:37.651355'), datetime.date(2026, 2, 4)),
        ('2026-02-04 00:00:00', datetime.date(2026, 2, 4)),
        ('2026-02-04 23:00:37.651355', datetime.date(2026, 2, 4)),        
        ('20260301', datetime.date(2026, 3, 1)),
        ('20263001', ValueError),
        ('3/2/25', datetime.date(2025, 3, 2)),
        ('30/12/2024', ValueError),
        ('32/12/2024', ValueError),
        ('30/13/2024', ValueError),
        ('30/2/23', ValueError),
        ('12/30/24',datetime.date(2024, 12, 30)),
        ('12/30/2026', datetime.date(2026, 12, 30)),

        ('20260301 12:35:45', datetime.date(2026, 3, 1)),
        ('20263001 12:35:45', ValueError),
        ('3/2/25 12:35:45', datetime.date(2025, 3, 2)),
        ('30/12/2024 12:35:45', ValueError),

        ('20260301 12:35:45.234', datetime.date(2026, 3, 1)),
        ('20263001 12:35:45.234', ValueError),

        ('20260301 12:35', datetime.date(2026, 3, 1)),
        ('20263001 12:35', ValueError),

        ('20260301 25:35', ValueError),
        ('3/2/25 25:35', ValueError),
    ]
)


def test_to_date_usaformat(input_value, expected):
    """
    Test unitario de to_date.
    Si falla, pytest mostrará exactamente qué input provocó el error.
    """
    if expected is ValueError:
        with pytest.raises(ValueError):
            to_date(input_value, usaformat=True)
    else:
        result = to_date(input_value, usaformat=True)
        assert result == expected, (
            f"Error con input={input_value!r}. "
            f"Esperado={expected}, obtenido={result}"
        )

@pytest.mark.parametrize(
    "input_value, expected",
    [
        (20261202, datetime.datetime(2026, 12, 2, 0, 0, 0)),
        (20263012, ValueError),
        (pd.Timestamp('2026-02-04 00:00:00'), datetime.datetime(2026, 2, 4, 0, 0, 0)),
        (pd.Timestamp('2026-02-04 23:00:37.651355'), datetime.datetime(2026, 2, 4, 23, 0, 37, 651355)),
        ('2026-02-04 00:00:00', datetime.datetime(2026, 2, 4, 0, 0, 0)),
        ('2026-02-04 23:00:37.651355', datetime.datetime(2026, 2, 4, 23, 0, 37, 651355)),
        ('20260301', datetime.datetime(2026, 3, 1, 0, 0, 0)),
        ('20263001', ValueError),
        ('3/2/25', datetime.datetime(2025, 2, 3, 0, 0, 0)),
        ('30/12/2024', datetime.datetime(2024, 12, 30, 0, 0, 0)),
        ('32/12/2024', ValueError),
        ('30/13/2024', ValueError),
        ('30/2/23', ValueError),
        ('12/30/24', ValueError),
        ('12/30/2026', ValueError),

        ('20260301 12:35:45', datetime.datetime(2026, 3, 1, 12, 35, 45)),
        ('20263001 12:35:45', ValueError),
        ('3/2/25 12:35:45', datetime.datetime(2025, 2, 3, 12, 35, 45)),
        ('30/12/2024 12:35:45', datetime.datetime(2024, 12, 30, 12, 35, 45)),

        ('20260301 12:35:45.234', datetime.datetime(2026, 3, 1, 12, 35, 45, 234000)),
        ('20263001 12:35:45.234', ValueError),

        ('20260301 12:35', datetime.datetime(2026, 3, 1, 12, 35)),
        ('20263001 12:35', ValueError),

        ('20260301 25:35', ValueError),
        ('3/2/25 25:35', ValueError),
    ]
)

def test_to_datetime(input_value, expected):
    """
    Test unitario de to_date.
    Si falla, pytest mostrará exactamente qué input provocó el error.
    """
    if expected is ValueError:
        with pytest.raises(ValueError):
            to_datetime(input_value, usaformat=False)
    else:
        result = to_datetime(input_value, usaformat=False)
        assert result == expected, (
            f"Error con input={input_value!r}. "
            f"Esperado={expected}, obtenido={result}"
        )


@pytest.mark.parametrize(
    "input_value, expected",
    [
        (20261202, datetime.datetime(2026, 12, 2, 0, 0, 0)),
        (20263012, ValueError),
        (pd.Timestamp('2026-02-04 00:00:00'), datetime.datetime(2026, 2, 4, 0, 0, 0)),
        (pd.Timestamp('2026-02-04 23:00:37.651355'), datetime.datetime(2026, 2, 4, 23, 0, 37, 651355)),
        ('2026-02-04 00:00:00', datetime.datetime(2026, 2, 4, 0, 0, 0)),
        ('2026-02-04 23:00:37.651355', datetime.datetime(2026, 2, 4, 23, 0, 37, 651355)),
        ('20260301', datetime.datetime(2026, 3, 1, 0, 0, 0)),
        ('20263001', ValueError),
        ('3/2/25', datetime.datetime(2025, 3, 2, 0, 0, 0)),
        ('30/12/2024', ValueError),
        ('32/12/2024', ValueError),
        ('30/13/2024', ValueError),
        ('30/2/23', ValueError),
        ('12/30/24', datetime.datetime(2024, 12, 30, 0, 0, 0)),
        ('12/30/2026', datetime.datetime(2026, 12, 30, 0, 0, 0)),

        ('20260301 12:35:45', datetime.datetime(2026, 3, 1, 12, 35, 45)),
        ('20263001 12:35:45', ValueError),
        ('3/2/25 12:35:45', datetime.datetime(2025, 3, 2, 12, 35, 45)),
        ('30/12/2024 12:35:45', ValueError),

        ('20260301 12:35:45.234', datetime.datetime(2026, 3, 1, 12, 35, 45, 234000)),
        ('20263001 12:35:45.234', ValueError),

        ('20260301 12:35', datetime.datetime(2026, 3, 1, 12, 35)),
        ('20263001 12:35', ValueError),

        ('20260301 25:35', ValueError),
        ('3/2/25 25:35', ValueError),
    ]
)

def test_to_datetime_usaformat(input_value, expected):
    """
    Test unitario de to_date.
    Si falla, pytest mostrará exactamente qué input provocó el error.
    """
    if expected is ValueError:
        with pytest.raises(ValueError):
            to_datetime(input_value, usaformat=True)
    else:
        result = to_datetime(input_value, usaformat=True)
        assert result == expected, (
            f"Error con input={input_value!r}. "
            f"Esperado={expected}, obtenido={result}"
        )


# --- missing values and odd types -----------------------------------------

@pytest.mark.parametrize("value", [None, float("nan"), pd.NaT, pd.NA, np.datetime64("NaT")])
def test_missing_values_raise(value):
    with pytest.raises(ValueError):
        to_datetime(value)
    with pytest.raises(ValueError):
        to_date(value)


@pytest.mark.parametrize("value", [True, False, 20261202.0, [20261202], object()])
def test_unconvertible_types_raise(value):
    with pytest.raises(ValueError):
        to_datetime(value)
    with pytest.raises(ValueError):
        to_date(value)


def test_numpy_inputs_accepted():
    assert to_date(np.int64(20261202)) == datetime.date(2026, 12, 2)
    assert to_datetime(np.int64(20261202)) == datetime.datetime(2026, 12, 2)
    assert to_date(np.datetime64("2026-12-02")) == datetime.date(2026, 12, 2)
    assert to_datetime(np.datetime64("2026-12-02T10:30")) == datetime.datetime(2026, 12, 2, 10, 30)
    # what df[col].max() returns on a datetime column
    series_max = pd.Series(pd.to_datetime(["2026-01-01", "2026-12-02"])).max()
    assert to_date(series_max) == datetime.date(2026, 12, 2)


def test_datetime_passthrough_and_timestamp_conversion():
    dt = datetime.datetime(2026, 12, 2, 10, 30, 15, 123)
    assert to_datetime(dt) is dt
    out = to_datetime(pd.Timestamp(dt))
    assert out == dt and type(out) is datetime.datetime


@pytest.mark.parametrize("value", ["", "   ", "a b c", "2026", "1/2", "x/y/z"])
def test_bad_strings_raise_valueerror(value):
    with pytest.raises(ValueError):
        to_datetime(value)


def test_two_digit_years_are_2000s():
    assert to_date("31/12/99") == datetime.date(2099, 12, 31)
    assert to_date("1/1/00") == datetime.date(2000, 1, 1)


def test_dash_separated_day_first_and_time():
    assert to_datetime("3-2-25 9:05") == datetime.datetime(2025, 2, 3, 9, 5)
    assert to_datetime("20260301 12:35:45.5") == datetime.datetime(2026, 3, 1, 12, 35, 45, 500000)


def test_tz_aware_iso_string_stays_aware():
    out = to_datetime("2024-01-15T10:00:00+02:00")
    assert out.utcoffset() == datetime.timedelta(hours=2)


# --- endofday / microseconds -----------------------------------------------

def test_endofday_paths():
    assert to_datetime(20261202, endofday=True) == datetime.datetime(2026, 12, 2, 23, 59, 59, 999999)
    assert to_datetime("2/12/2026", endofday=True) == datetime.datetime(2026, 12, 2, 23, 59, 59, 999999)
    assert to_datetime(datetime.date(2026, 12, 2), endofday=True) == datetime.datetime(2026, 12, 2, 23, 59, 59, 999999)
    # a time in the string wins over endofday
    assert to_datetime("2/12/2026 10:00", endofday=True) == datetime.datetime(2026, 12, 2, 10, 0)


def test_day_boundaries():
    d = datetime.date(2026, 3, 1)
    dt = datetime.datetime(2026, 3, 1, 12, 0, 0, 123456)
    assert start_of_day(d) == datetime.datetime(2026, 3, 1)
    assert start_of_day(dt) == datetime.datetime(2026, 3, 1)
    assert end_of_day(d) == datetime.datetime(2026, 3, 1, 23, 59, 59, 999999)
    assert end_of_day(dt, microseconds=False) == datetime.datetime(2026, 3, 1, 23, 59, 59)
    assert del_microseconds(dt) == datetime.datetime(2026, 3, 1, 12, 0)
    assert date_to_datetime(d) == start_of_day(d)
    assert date_to_datetime(d, endofday=True, microseconds=False) == end_of_day(d, microseconds=False)


# --- the parsers underneath ------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("14:30", datetime.time(14, 30)),
    ("14:30:45", datetime.time(14, 30, 45)),
    ("14:30:45.123456", datetime.time(14, 30, 45, 123456)),
    (" 9:05 ", datetime.time(9, 5)),
])
def test_time_from_str(value, expected):
    assert time_from_str(value) == expected


@pytest.mark.parametrize("value", ["14", "14:30:45:00", "25:00", "14:60", "ab:cd"])
def test_time_from_str_invalid(value):
    with pytest.raises(ValueError):
        time_from_str(value)


@pytest.mark.parametrize("value", [2026120, 202612020, 20261302, 20260230, 0, -20261202])
def test_date_from_int_invalid(value):
    with pytest.raises(ValueError):
        date_from_int(value)


def test_date_from_int_valid():
    assert date_from_int(20240229) == datetime.date(2024, 2, 29)
    assert datetime_from_int(20240229, endofday=True) == datetime.datetime(2024, 2, 29, 23, 59, 59, 999999)


# --- today / prev_day_not_weekend -----------------------------------------

def test_today_and_now_types():
    assert type(today()) is datetime.date
    assert type(now()) is datetime.datetime
    assert isinstance(timestamp(), str) and "T" in timestamp()


@pytest.mark.parametrize("start, expected", [
    (datetime.date(2026, 8, 24), datetime.date(2026, 8, 21)),   # Monday -> Friday
    (datetime.date(2026, 8, 23), datetime.date(2026, 8, 21)),   # Sunday -> Friday
    (datetime.date(2026, 8, 22), datetime.date(2026, 8, 21)),   # Saturday -> Friday
    (datetime.date(2026, 8, 26), datetime.date(2026, 8, 25)),   # Wednesday -> Tuesday
])
def test_prev_day_not_weekend(start, expected):
    assert prev_day_not_weekend(start) == expected


def test_prev_day_not_weekend_keeps_datetime_and_defaults_to_today():
    out = prev_day_not_weekend(datetime.datetime(2026, 8, 24, 10, 0))
    assert out == datetime.datetime(2026, 8, 21, 10, 0)
    default = prev_day_not_weekend()
    assert isinstance(default, datetime.date) and default < today() and default.weekday() < 5

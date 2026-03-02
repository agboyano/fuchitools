from __future__ import annotations

import datetime
from typing import Optional, Union

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

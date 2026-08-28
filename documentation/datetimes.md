# `fuchitools.datetimes`

Date and time conversion, built around the idea that data arrives in whatever
shape the source felt like: a Spanish `30/12/2024`, an ISO string, a
`pd.Timestamp`, an `int` like `20261202`, a `numpy.datetime64` out of a
DataFrame. The two entry points take any of those and give back a plain
`datetime.date` or `datetime.datetime`.

Depends on pandas (and numpy, which pandas brings), only to recognise their
scalar types.

## The two functions you actually call

| Function | Returns |
|---|---|
| `to_date(x, usaformat=False)` | `datetime.date` |
| `to_datetime(x, usaformat=False, endofday=False)` | `datetime.datetime` |

`x` may be a `datetime`, a `date`, a `pd.Timestamp`, a `numpy.datetime64`, an
integer in `YYYYMMDD` form (Python `int` or numpy integer — what
`df["fecha"].max()` gives you), or a string. Anything else raises
`ValueError`: unparseable strings, dates that look fine but do not exist
(`30/2/23`), floats, booleans, and **missing values** — `None`, `NaN`, `NaT`,
`pd.NA` are refused rather than passed through, so a `NaT` from a DataFrame
cannot slip into a query as if it were a date.

```python
from fuchitools.datetimes import to_date, to_datetime

to_date(20261202)                      # datetime.date(2026, 12, 2)
to_date("30/12/2024")                  # datetime.date(2024, 12, 30)
to_date("3/2/25")                      # datetime.date(2025, 2, 3)   <- 3 February
to_date("2026-02-04 23:00:37.651355")  # datetime.date(2026, 2, 4)
to_date(df["fecha"].max())    # a pd.Timestamp -> date
to_date("30/2/23")                     # ValueError
to_date(pd.NaT)                        # ValueError

to_datetime("2026-02-04 23:00:37.651355")
# datetime.datetime(2026, 2, 4, 23, 0, 37, 651355)

to_datetime(20261202, endofday=True)
# datetime.datetime(2026, 12, 2, 23, 59, 59, 999999)
```

**`usaformat` decides who wins an ambiguous date.** By default `DD/MM/YYYY` —
European order. With `usaformat=True`, `MM/DD/YYYY`. `-` works as a separator
too (`3-2-25`).

```python
to_date("12/30/24")                    # ValueError: there is no month 30
to_date("12/30/24", usaformat=True)    # datetime.date(2024, 12, 30)
```

**Two-digit years are assumed to be 2000s**: `25` becomes `2025` — and `99`
becomes `2099`, not 1999. Data older than 2000 needs four-digit years.

**`endofday` is what you want for closed intervals.** A date turned into a
datetime lands at `00:00:00` by default, which silently excludes everything
that happened that day. `endofday=True` moves it to `23:59:59.999999`. A time
present in the input always wins over the flag.

**Timezones are passed through, never converted.** An ISO string with an
offset (`2024-01-15T10:00:00+02:00`) comes back as an aware `datetime`;
everything else is naive. Mixing the two in a comparison is Python's
`TypeError`, not this module's.

## Day boundaries

```python
import datetime
from fuchitools.datetimes import start_of_day, end_of_day, del_microseconds

start_of_day(datetime.date(2026, 3, 1))
# datetime.datetime(2026, 3, 1, 0, 0)

end_of_day(datetime.date(2026, 3, 1))
# datetime.datetime(2026, 3, 1, 23, 59, 59, 999999)

end_of_day(datetime.date(2026, 3, 1), microseconds=False)
# datetime.datetime(2026, 3, 1, 23, 59, 59)

del_microseconds(datetime.datetime(2026, 3, 1, 12, 0, 0, 123456))
# datetime.datetime(2026, 3, 1, 12, 0)
```

`microseconds=False` matters when the other side of the comparison cannot hold
them — SQLite text timestamps, some Excel exports.

`date_to_datetime(x, endofday=False, microseconds=True)` is the same choice
expressed as one call, for when the flag comes from a variable rather than
from the code.

## Now, today, and the previous working day

```python
from fuchitools.datetimes import now, today, timestamp, prev_day_not_weekend

now()          # datetime.datetime(2026, 8, 26, 13, 4, 22, 918233)
today()        # datetime.date(2026, 8, 26)
timestamp()    # '2026-08-26T13:04:22.918233'  -- ISO string, for file names and logs

prev_day_not_weekend(datetime.date(2026, 8, 24))   # Monday
# datetime.date(2026, 8, 21)                       -- the Friday before
```

`prev_day_not_weekend` steps back one day and keeps stepping while it lands on
a Saturday or Sunday. Called with no argument it starts from today. Given a
`datetime` it returns a `datetime` with the same time of day. **It knows
nothing about holidays**: the Friday it returns may well be one.

## The parsers underneath

Rarely called directly, but useful when the input type is already known and
you want the error to be precise:

| Function | Input |
|---|---|
| `date_from_int(x)` | `20260301` (exactly eight digits) |
| `datetime_from_int(x, endofday=False)` | `20260301` |
| `datetime_from_str(x, usaformat=False, endofday=False)` | any supported string |
| `time_from_str(x)` | `"14:30"`, `"14:30:45"`, `"14:30:45.123456"` |

```python
from fuchitools.datetimes import time_from_str, date_from_int

time_from_str("14:30")            # datetime.time(14, 30)
time_from_str("14:30:45.123456")  # datetime.time(14, 30, 45, 123456)
date_from_int(20260301)           # datetime.date(2026, 3, 1)
date_from_int(2026030)            # ValueError: seven digits
```

`datetime_from_str` tries `datetime.fromisoformat` first, then an explicit
`YYYYMMDD[ time]` shape, and only then splits on `/` or `-`, so well formed
ISO input never goes near the ambiguous-order logic. The `YYYYMMDD` branch is
explicit on purpose: `fromisoformat` only accepts the basic format on Python
3.11+, and the package supports 3.9.

## Tests

`tests/test_datetimes.py` drives `to_date` and `to_datetime` through long
parametrised tables of inputs, including the ones that must raise, plus the
missing-value and numpy cases, `endofday`/`microseconds`, the parsers and
`prev_day_not_weekend`. It is the fastest way to check whether a given string
shape is supported before using it.

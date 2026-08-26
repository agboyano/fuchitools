# `fuchitools.sqlite`

Thin conveniences over `sqlite3` and pandas: run SQL without the connection
boilerplate, move DataFrames in and out, write dates in one text shape, and
keep a small key/value table for job state.

Errors are not swallowed anywhere in this module: SQLite errors propagate,
and the helpers that used to return `None`/`False` on failure now only do so
in the documented cases below.

## The connection convention

Every function whose first parameter is `conn` takes a **path or an open
connection**.

- Given a path (`str` or `os.PathLike`) it opens the database, runs, and then
  **commits if the function returned, rolls back if it raised**, and closes
  the connection in both cases. The exception propagates.
- Given a connection it uses it and leaves commit, rollback and close to the
  caller. Nothing is committed on your behalf.

```python
from fuchitools.sqlite import exe, df_from_sqlite

# one-off: opened, committed, closed
exe("g:/control_iics/iics.db", "CREATE TABLE t (a, b);")

# a session you control
import sqlite3
with sqlite3.connect("g:/control_iics/iics.db") as con:
    exe(con, "INSERT INTO t VALUES (1, 2);")
    df = df_from_sqlite(con, "SELECT * FROM t;")
```

That behaviour comes from the `conn_or_db` decorator, which is also usable on
your own functions (`carga_iics.py` decorates ~40 of them). `connection(x)` is
the helper underneath, returning `(connection, was_already_a_connection)`;
`is_conn(x)` is the predicate. Anything that is neither a connection nor a
path raises `TypeError`.

`SqliteConnection` is a `sqlite3.Connection` subclass that remembers the
`path` it was opened from; it is what `conn_or_db` creates from a path, and
you can use it directly (`with SqliteConnection(path) as conn:`) when you want
`conn.path` available. Remember that `with` on an sqlite3 connection
commits/rolls back but does not close.

Because a path-opened connection is closed before the decorated function
returns, a cursor returned from such a call is dead. Return data, not cursors.

## Running SQL

```python
exe(conn_or_path, *sql)
```

Each argument is either a string or a `(sql, params)` tuple. The cursor of
the last statement is returned (handy for `rowcount`). No statements at all
is a `ValueError`.

```python
exe(db, "DELETE FROM prices WHERE date < '2020-01-01';")

exe(db, ("INSERT INTO prices (ticker, close) VALUES (?, ?);", ("san sm equity", 4.21)))

exe(db,
    "CREATE TABLE IF NOT EXISTS prices (ticker, date, close);",
    ("INSERT INTO prices VALUES (?, ?, ?);", ("bbva sm equity", "2026-08-26", 11.3)))
```

**Two or more statements run atomically.** They are wrapped in
`SAVEPOINT fuchitools_exe … RELEASE`; if one fails, the ones already executed
are undone and the error propagates. A savepoint nests inside a transaction
you may already have open without touching your earlier, uncommitted work.
Two things to know about it:

- `RELEASE` of an *outermost* savepoint is a commit. A multi-statement `exe`
  on a connection with no open transaction is therefore committed on return,
  while a single-statement `exe` is not (it follows sqlite3's implicit
  transaction rules).
- Do not use the name `fuchitools_exe` for your own savepoints.

```python
table_exists(conn_or_path, table) -> bool
```

Tables only, not views. SQLite errors (closed connection, unreadable file)
propagate instead of being reported as `False`.

## DataFrames in and out

```python
df_to_sql(conn_or_path, df, table, index=False, if_exists='fail', **kwargs)
df_from_sqlite(conn_or_path, sql, params=None, parse_dates=None, **kwargs)
```

```python
from fuchitools.sqlite import df_to_sql, df_from_sqlite

df_to_sql("iics.db", positions, "positions", if_exists="replace")

df = df_from_sqlite(
    "iics.db",
    "SELECT * FROM positions WHERE cartera = ? AND date >= ?;",
    params=(93702, "2026-01-01 00:00:00"),
    parse_dates=["date"],
)
```

`if_exists` is pandas' own: `'fail'`, `'replace'` or `'append'`. Extra
keyword arguments go straight to `DataFrame.to_sql` (`dtype`, `chunksize`)
and `pandas.read_sql` (`index_col`, `dtype`). `df_to_sql` returns whatever
`to_sql` returns.

Prefer `params=` to formatting dates into the SQL string; `sqlite_iics.py`
still does the latter with `to_sqlite_dt`, which is why that helper exists.

## Dates into SQLite

SQLite has no date type, so dates go in as text. These write the
`YYYY-MM-DD 00:00:00` shape, **truncating the time of day**:

```python
datetime_to_sqlite(x)          # datetime-like -> text; None for None/NaN/NaT or no strftime
to_sqlite_dt(x)                # anything to_datetime accepts -> text; None for None/NaN/NaT
df_datetimes_to_sqlite(df, dt_columns)   # in place over a list of columns; returns df
```

```python
from fuchitools.sqlite import to_sqlite_dt, df_datetimes_to_sqlite

to_sqlite_dt("30/12/2024")     # '2024-12-30 00:00:00'
to_sqlite_dt(20261202)         # '2026-12-02 00:00:00'

df_datetimes_to_sqlite(df, ["fecha_valor", "fecha_liquidacion"])
```

Things to keep in mind:

- `datetime_to_sqlite` returns `None` for missing values and for anything
  without a `strftime` (a string, an int); it never raises.
- `to_sqlite_dt` returns `None` only for `None`/`NaN`/`NaT`. Anything else
  that `to_datetime` cannot convert **raises `ValueError`** — deliberately,
  because callers interpolate the result into SQL and a silent `None` would
  become the literal text `None` in the query.
- `df_datetimes_to_sqlite` replaces each listed column with a text column
  (missing values become nulls) and returns the same DataFrame, so both the
  in-place and the `df = ...` styles work. A column that is not in the frame
  raises `KeyError`. This replaces the previous `.loc` assignment, which under
  pandas 3 silently kept the datetime dtype and did nothing.

Note that pandas itself writes `datetime64` columns as `YYYY-MM-DD HH:MM:SS`
and `date` objects as `YYYY-MM-DD`; this helper is what makes both land in
the single `YYYY-MM-DD 00:00:00` shape the queries expect.

## The variables table

A key/value store for the bits of state a job needs between runs — a last
processed date, a cursor, a flag. The table is created on first write
(`CREATE TABLE IF NOT EXISTS`, `variable` text primary key, untyped `value`)
and writes use `INSERT OR REPLACE`, so writing the same name twice
overwrites. Databases created by the previous version (with an
`ON CONFLICT REPLACE` constraint) keep working.

```python
set_variable(conn_or_path, variable, value, table="variables")   -> True
get_variable(conn_or_path, variable, table="variables", default=<raise>)
```

```python
from fuchitools.sqlite import set_variable, get_variable

set_variable("iics.db", "ultima_carga", "2026-08-26")
get_variable("iics.db", "ultima_carga")            # '2026-08-26'
get_variable("iics.db", "no_existe", default=0)    # 0
get_variable("iics.db", "no_existe")               # KeyError
```

`get_variable` raises `KeyError` for a name that is not stored **or when the
table itself does not exist yet** (first run), unless `default=` is given.
Reading never creates the table. The table name is quoted, so unusual names
are fine.

`delete_variable` / `delete_all_variables` were removed (nothing used them);
`exe(db, ("DELETE FROM variables WHERE variable=?;", (name,)))` does the job.

## Excel

The `load_excel` and `sheet_to_sqlite` helpers that used to live here are
gone. `load_excel` is in [`fuchitools.pandas`](pandas.md) (the copy that was
actually used). For a sheet into a table:

```python
import pandas as pd
from fuchitools.sqlite import df_to_sql

df_to_sql("iics.db", pd.read_excel("posiciones.xlsx", sheet_name="uno"), "posiciones")
```

## Tests

`tests/test_sqlite.py` — temporary files and in-memory databases only.

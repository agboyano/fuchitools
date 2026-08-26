"""Thin conveniences over ``sqlite3`` and pandas.

Run SQL without connection boilerplate, move DataFrames in and out of SQLite,
write dates in one text shape, and keep a small key/value table for job state.

Every function whose first parameter is ``conn`` accepts either an open
``sqlite3.Connection`` or a database path (``str`` or ``os.PathLike``):

- given a **path**, the function opens the database, runs, commits on success,
  rolls back on error, and closes the connection in every case;
- given a **connection**, it uses it as-is and leaves commit, rollback and
  close to the caller.

That behaviour comes from the :func:`conn_or_db` decorator.
"""

from __future__ import annotations

import functools
import os
import sqlite3
from typing import Any, Callable, Iterable, Optional, Sequence, Tuple, Union

import pandas as pd

from fuchitools.datetimes import to_datetime

__all__ = [
    "SqliteConnection",
    "is_conn",
    "connection",
    "conn_or_db",
    "datetime_to_sqlite",
    "to_sqlite_dt",
    "df_datetimes_to_sqlite",
    "exe",
    "table_exists",
    "df_to_sql",
    "df_from_sqlite",
    "set_variable",
    "get_variable",
]

PathLike = Union[str, bytes, "os.PathLike[str]"]
ConnOrPath = Union[sqlite3.Connection, PathLike]
SqlItem = Union[str, Tuple[str, Sequence[Any]]]

_MISSING = object()
_SAVEPOINT = "fuchitools_exe"
_SQLITE_DATE_FORMAT = "%Y-%m-%d 00:00:00"


def _quote(name) -> str:
    """Quote an SQL identifier."""
    return '"' + str(name).replace('"', '""') + '"'


def _is_missing(x) -> bool:
    """True for None, NaN and NaT scalars; False for everything else."""
    try:
        return bool(pd.isna(x))
    except (TypeError, ValueError):
        # pd.isna of a list/array is an array -> bool() fails; not a scalar.
        return False


# --------------------------------------------------------------------------
# Connections
# --------------------------------------------------------------------------

class SqliteConnection(sqlite3.Connection):
    """``sqlite3.Connection`` that remembers the path it was opened from.

    This is what :func:`conn_or_db` creates when it is given a path. The only
    thing it adds is the ``path`` attribute. It can also be used directly, for
    instance when the rest of the code wants to print where it is writing::

        with SqliteConnection("iics.db") as conn:
            ...

    Note that ``with`` on an sqlite3 connection commits/rolls back but does
    not close it.
    """

    def __init__(self, database, *args, **kwargs):
        super().__init__(database, *args, **kwargs)
        self.path = os.fspath(database)


def is_conn(x) -> bool:
    """Return True if ``x`` is an ``sqlite3.Connection`` (or a subclass)."""
    return isinstance(x, sqlite3.Connection)


def connection(conn_or_path: ConnOrPath) -> Tuple[sqlite3.Connection, bool]:
    """Resolve a connection-or-path into ``(connection, was_already_open)``.

    Parameters
    ----------
    conn_or_path : sqlite3.Connection | str | os.PathLike
        An open connection, or the path of the database to open.

    Returns
    -------
    (sqlite3.Connection, bool)
        The connection itself and ``True`` when given a connection; a new
        :class:`SqliteConnection` and ``False`` when given a path. The flag
        tells the caller whether it owns (and must close) the connection.

    Raises
    ------
    TypeError
        If ``conn_or_path`` is neither a connection nor a path.
    """
    if is_conn(conn_or_path):
        return conn_or_path, True
    if isinstance(conn_or_path, (str, bytes, os.PathLike)):
        return sqlite3.connect(conn_or_path, factory=SqliteConnection), False
    raise TypeError(
        "expected an sqlite3.Connection or a database path (str / os.PathLike), "
        f"got {type(conn_or_path).__name__}"
    )


def conn_or_db(func: Callable) -> Callable:
    """Decorator: let the first argument of ``func`` be a connection or a path.

    ``func`` must take an open ``sqlite3.Connection`` as its first positional
    argument. The decorated function additionally accepts a database path
    there:

    - **path**: the database is opened, ``func`` runs, the transaction is
      committed if ``func`` returns and rolled back if it raises, and the
      connection is closed in both cases. The exception, if any, propagates.
    - **connection**: ``func`` runs on it and nothing else happens; commit,
      rollback and close remain the caller's responsibility.

    Because a path-opened connection is closed before returning, a cursor
    returned by ``func`` is no longer usable in that case; return data, not
    cursors, from functions meant to be called with a path.
    """

    @functools.wraps(func)
    def wrapper(conn_or_path, *args, **kwargs):
        conn, was_open = connection(conn_or_path)
        if was_open:
            return func(conn, *args, **kwargs)
        try:
            result = func(conn, *args, **kwargs)
        except BaseException:
            conn.rollback()
            raise
        else:
            conn.commit()
            return result
        finally:
            conn.close()

    return wrapper


# --------------------------------------------------------------------------
# Dates as text
# --------------------------------------------------------------------------

def datetime_to_sqlite(x) -> Optional[str]:
    """Format a datetime-like value as ``'YYYY-MM-DD 00:00:00'`` text.

    SQLite has no date type, so dates are stored as text in this one shape.
    **The time of day is truncated**: ``2024-01-02 10:30`` becomes
    ``'2024-01-02 00:00:00'``.

    Parameters
    ----------
    x : datetime.date | datetime.datetime | pandas.Timestamp | None
        Anything with a ``strftime`` method.

    Returns
    -------
    str | None
        The formatted text, or ``None`` for ``None``/``NaN``/``NaT`` and for
        values that cannot be formatted (no ``strftime``).
    """
    if _is_missing(x):
        return None
    try:
        return x.strftime(_SQLITE_DATE_FORMAT)
    except (AttributeError, TypeError, ValueError):
        return None


def to_sqlite_dt(x) -> Optional[str]:
    """Convert anything :func:`fuchitools.datetimes.to_datetime` accepts to
    ``'YYYY-MM-DD 00:00:00'`` text.

    Parameters
    ----------
    x : datetime | date | pandas.Timestamp | str | int | None
        ``str`` follows the European day-first parsing of ``to_datetime``
        (``"30/12/2024"``); ``int`` is ``YYYYMMDD`` (``20261202``).

    Returns
    -------
    str | None
        ``None`` for ``None``/``NaN``/``NaT``; otherwise the formatted text
        with the time truncated to ``00:00:00``.

    Raises
    ------
    ValueError
        If ``x`` cannot be converted to a datetime. This propagates on
        purpose: callers interpolate the result into SQL, and a silent
        ``None`` would end up as the literal text ``None`` in the query.

    Examples
    --------
    >>> to_sqlite_dt("30/12/2024")
    '2024-12-30 00:00:00'
    >>> to_sqlite_dt(20261202)
    '2026-12-02 00:00:00'
    """
    if _is_missing(x):
        return None
    return datetime_to_sqlite(to_datetime(x))


def df_datetimes_to_sqlite(df: pd.DataFrame, dt_columns: Iterable[str]) -> pd.DataFrame:
    """Rewrite the given columns of ``df`` as ``'YYYY-MM-DD 00:00:00'`` text.

    The DataFrame is modified **in place** (each listed column is replaced by
    a text column) and also returned, so both ``df_datetimes_to_sqlite(df,
    cols)`` and ``df = df_datetimes_to_sqlite(df, cols)`` work. Missing values
    (``NaT``/``None``) become nulls. Time of day is truncated, and
    ``datetime.date`` and ``datetime64`` columns end up in the same shape.

    Parameters
    ----------
    df : pandas.DataFrame
    dt_columns : iterable of str
        Column names to convert. All must exist in ``df``.

    Returns
    -------
    pandas.DataFrame
        The same object that was passed in.

    Raises
    ------
    KeyError
        If any of ``dt_columns`` is not a column of ``df``.
    """
    dt_columns = list(dt_columns)
    missing = [c for c in dt_columns if c not in df.columns]
    if missing:
        raise KeyError(f"columns not in DataFrame: {missing}")
    for col in dt_columns:
        # Whole-column assignment: replacing the values through .loc keeps the
        # datetime64 dtype and coerces the strings back to timestamps.
        df[col] = df[col].map(datetime_to_sqlite)
    return df


# --------------------------------------------------------------------------
# Running SQL
# --------------------------------------------------------------------------

def _exe_one(conn: sqlite3.Connection, item: SqlItem) -> sqlite3.Cursor:
    if isinstance(item, str):
        return conn.execute(item)
    sql, params = item
    return conn.execute(sql, params)


@conn_or_db
def exe(conn: ConnOrPath, *sql: SqlItem) -> sqlite3.Cursor:
    """Execute one or more SQL statements and return the last cursor.

    Parameters
    ----------
    conn : sqlite3.Connection | str | os.PathLike
        Connection or database path (see :func:`conn_or_db`).
    *sql : str | (str, params)
        Each item is either a SQL string or a ``(sql, params)`` tuple, where
        ``params`` is a sequence (or mapping) of bound parameters.

    Returns
    -------
    sqlite3.Cursor
        The cursor of the last statement (useful for ``rowcount``). For
        query results prefer :func:`df_from_sqlite`.

    Raises
    ------
    ValueError
        If no statement is given.
    sqlite3.Error
        Any SQLite error propagates.

    Notes
    -----
    When two or more statements are given they run inside a
    ``SAVEPOINT``/``RELEASE`` pair, so the batch is atomic: if one fails, the
    ones already executed are undone and the error propagates. A savepoint
    nests inside a transaction the caller may already have open without
    touching the caller's earlier work; on its own it behaves like a
    transaction. Note that ``RELEASE`` of an outermost savepoint commits, so
    a multi-statement ``exe`` on a connection with no open transaction is
    committed on return.

    Examples
    --------
    >>> exe(db, "DELETE FROM prices WHERE date < '2020-01-01';")
    >>> exe(db, ("INSERT INTO prices VALUES (?, ?);", ("san sm equity", 4.21)))
    >>> exe(db,
    ...     "CREATE TABLE IF NOT EXISTS prices (ticker, date, close);",
    ...     ("INSERT INTO prices VALUES (?, ?, ?);", ("bbva", "2026-08-26", 11.3)))
    """
    if not sql:
        raise ValueError("exe() needs at least one SQL statement")
    if len(sql) == 1:
        return _exe_one(conn, sql[0])

    conn.execute(f"SAVEPOINT {_SAVEPOINT}")
    try:
        for item in sql:
            cursor = _exe_one(conn, item)
    except BaseException:
        conn.execute(f"ROLLBACK TO {_SAVEPOINT}")
        conn.execute(f"RELEASE {_SAVEPOINT}")
        raise
    conn.execute(f"RELEASE {_SAVEPOINT}")
    return cursor


@conn_or_db
def table_exists(conn: ConnOrPath, table: str) -> bool:
    """Return True if a table named ``table`` exists.

    Only tables are considered, not views. SQLite errors (closed connection,
    unreadable file, ...) propagate rather than being reported as False.
    """
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;", (table,)
    ).fetchone()
    return row is not None


# --------------------------------------------------------------------------
# DataFrames in and out
# --------------------------------------------------------------------------

@conn_or_db
def df_to_sql(conn: ConnOrPath, df: pd.DataFrame, table: str, index: bool = False,
              if_exists: str = "fail", **kwargs):
    """Write ``df`` to ``table`` with ``DataFrame.to_sql``.

    Parameters
    ----------
    conn : sqlite3.Connection | str | os.PathLike
    df : pandas.DataFrame
    table : str
    index : bool, default False
        Whether to write the DataFrame index as a column.
    if_exists : {'fail', 'replace', 'append'}, default 'fail'
        pandas' own semantics.
    **kwargs
        Passed through to ``DataFrame.to_sql`` (``dtype``, ``chunksize``, ...).

    Returns
    -------
    int | None
        Whatever ``DataFrame.to_sql`` returns (number of rows affected, or
        None when the driver does not report it).
    """
    return df.to_sql(table, conn, index=index, if_exists=if_exists, **kwargs)


@conn_or_db
def df_from_sqlite(conn: ConnOrPath, sql: str, params=None, parse_dates=None,
                   **kwargs) -> pd.DataFrame:
    """Run ``sql`` and return the result as a DataFrame (``pandas.read_sql``).

    Parameters
    ----------
    conn : sqlite3.Connection | str | os.PathLike
    sql : str
    params : sequence | mapping, optional
        Bound parameters for ``?`` / ``:name`` placeholders. Prefer this over
        interpolating values (dates via :func:`to_sqlite_dt`) into ``sql``.
    parse_dates : list | dict, optional
        Columns to parse as datetimes, as in ``pandas.read_sql``.
    **kwargs
        Passed through to ``pandas.read_sql`` (``index_col``, ``dtype``, ...).

    Examples
    --------
    >>> df_from_sqlite("iics.db",
    ...     "SELECT * FROM positions WHERE cartera = ? AND date >= ?;",
    ...     params=(93702, "2026-01-01 00:00:00"), parse_dates=["date"])
    """
    return pd.read_sql(sql, conn, params=params, parse_dates=parse_dates, **kwargs)


# --------------------------------------------------------------------------
# Variables: a key/value table for job state
# --------------------------------------------------------------------------

@conn_or_db
def set_variable(conn: ConnOrPath, variable: str, value, table: str = "variables") -> bool:
    """Store ``value`` under ``variable`` in the key/value table.

    The table is created on first use (``variable`` text primary key,
    ``value`` untyped). Writing an existing name overwrites its value.

    Returns
    -------
    bool
        Always True.
    """
    qtable = _quote(table)
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {qtable} "
        "(variable CHAR PRIMARY KEY NOT NULL, value) WITHOUT ROWID;"
    )
    conn.execute(
        f"INSERT OR REPLACE INTO {qtable} (variable, value) VALUES (?, ?);",
        (variable, value),
    )
    return True


@conn_or_db
def get_variable(conn: ConnOrPath, variable: str, table: str = "variables",
                 default=_MISSING):
    """Read the value stored under ``variable`` in the key/value table.

    Parameters
    ----------
    conn : sqlite3.Connection | str | os.PathLike
    variable : str
    table : str, default "variables"
    default : optional
        Returned when the variable (or the whole table) does not exist. If
        not given, ``KeyError`` is raised instead.

    Raises
    ------
    KeyError
        If ``variable`` is not stored and no ``default`` was given. A missing
        table counts as a missing variable.
    """
    row = None
    if table_exists(conn, table):
        row = conn.execute(
            f"SELECT value FROM {_quote(table)} WHERE variable=?;", (variable,)
        ).fetchone()
    if row is None:
        if default is _MISSING:
            raise KeyError(f"variable {variable!r} not found in table {table!r}")
        return default
    return row[0]

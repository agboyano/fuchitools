"""Tests for fuchitools.sqlite.

Everything runs against temporary files (tmp_path) or in-memory databases;
nothing touches a real database.
"""

import datetime as dt
import pathlib
import sqlite3

import pandas as pd
import pytest

from fuchitools.sqlite import (
    SqliteConnection,
    conn_or_db,
    connection,
    datetime_to_sqlite,
    df_datetimes_to_sqlite,
    df_from_sqlite,
    df_to_sql,
    exe,
    get_variable,
    is_conn,
    set_variable,
    table_exists,
    to_sqlite_dt,
)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "t.db"


@pytest.fixture
def con():
    c = sqlite3.connect(":memory:")
    yield c
    c.close()


def rows(conn_or_path, sql):
    if is_conn(conn_or_path):
        return conn_or_path.execute(sql).fetchall()
    c = sqlite3.connect(conn_or_path)
    try:
        return c.execute(sql).fetchall()
    finally:
        c.close()


# --- connection / conn_or_db --------------------------------------------

def test_connection_returns_open_connection_unchanged(con):
    c, was_open = connection(con)
    assert c is con and was_open is True


def test_connection_opens_sqliteconnection_from_str_and_path(db_path):
    for arg in (str(db_path), db_path):
        c, was_open = connection(arg)
        try:
            assert isinstance(c, SqliteConnection)
            assert isinstance(c, sqlite3.Connection)
            assert c.path == str(db_path)
            assert was_open is False
        finally:
            c.close()


def test_connection_rejects_other_types():
    with pytest.raises(TypeError):
        connection(42)


def test_conn_or_db_path_commits_and_closes(db_path):
    seen = []

    @conn_or_db
    def create_and_insert(conn):
        seen.append(conn)
        conn.execute("CREATE TABLE t (a);")
        conn.execute("INSERT INTO t VALUES (1);")
        return "done"

    assert create_and_insert(db_path) == "done"
    assert rows(db_path, "SELECT * FROM t") == [(1,)]        # committed
    with pytest.raises(sqlite3.ProgrammingError):           # closed
        seen[0].execute("SELECT 1")


def test_conn_or_db_path_rolls_back_closes_and_reraises(db_path):
    exe(db_path, "CREATE TABLE t (a);")
    seen = []

    @conn_or_db
    def insert_then_fail(conn):
        seen.append(conn)
        conn.execute("INSERT INTO t VALUES (1);")
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        insert_then_fail(str(db_path))
    assert rows(db_path, "SELECT * FROM t") == []            # rolled back
    with pytest.raises(sqlite3.ProgrammingError):
        seen[0].execute("SELECT 1")


def test_conn_or_db_connection_is_left_to_the_caller(con):
    @conn_or_db
    def insert(conn):
        conn.execute("CREATE TABLE t (a);")
        conn.execute("INSERT INTO t VALUES (1);")

    insert(con)
    assert con.in_transaction                               # not committed
    con.execute("SELECT 1")                                 # not closed


def test_conn_or_db_preserves_metadata():
    assert exe.__name__ == "exe"
    assert "SAVEPOINT" in exe.__doc__


def test_conn_or_db_without_argument_is_a_typeerror():
    with pytest.raises(TypeError):
        exe()


# --- exe ----------------------------------------------------------------

def test_exe_single_string_returns_cursor(con):
    cur = exe(con, "CREATE TABLE t (a);")
    assert isinstance(cur, sqlite3.Cursor)
    assert table_exists(con, "t")


def test_exe_tuple_with_params(con):
    exe(con, "CREATE TABLE t (a, b);")
    cur = exe(con, ("INSERT INTO t VALUES (?, ?);", (1, "x")))
    assert cur.rowcount == 1
    assert rows(con, "SELECT * FROM t") == [(1, "x")]


def test_exe_multi_returns_last_cursor(con):
    cur = exe(con,
              "CREATE TABLE t (a);",
              "INSERT INTO t VALUES (1);",
              ("INSERT INTO t VALUES (?);", (2,)),
              "DELETE FROM t WHERE a = 1;")
    assert cur.rowcount == 1
    assert rows(con, "SELECT * FROM t") == [(2,)]


def test_exe_multi_is_atomic_and_reraises(con):
    con.execute("CREATE TABLE t (a INTEGER PRIMARY KEY);")
    con.execute("INSERT INTO t VALUES (1);")                # caller's own work
    assert con.in_transaction
    with pytest.raises(sqlite3.IntegrityError):
        exe(con,
            "INSERT INTO t VALUES (2);",
            "INSERT INTO t VALUES (1);")                    # PK violation
    assert rows(con, "SELECT a FROM t") == [(1,)]           # batch undone, caller's row kept
    assert con.in_transaction                               # caller's transaction untouched


def test_exe_multi_ddl_only_failure_is_undone(con):
    with pytest.raises(sqlite3.OperationalError):
        exe(con, "CREATE TABLE v (x);", "CREATE TABLE v (x);")
    assert not table_exists(con, "v")
    assert not con.in_transaction


def test_exe_multi_on_path_is_committed(db_path):
    exe(db_path, "CREATE TABLE t (a);", "INSERT INTO t VALUES (1);")
    assert rows(db_path, "SELECT * FROM t") == [(1,)]


def test_exe_without_sql_raises(con):
    with pytest.raises(ValueError):
        exe(con)


def test_exe_does_not_swallow_errors(con):
    with pytest.raises(sqlite3.OperationalError):
        exe(con, "SELECT * FROM no_such_table;")


# --- table_exists -------------------------------------------------------

def test_table_exists(con, db_path):
    assert table_exists(con, "t") is False
    con.execute("CREATE TABLE t (a);")
    assert table_exists(con, "t") is True
    assert table_exists(db_path, "t") is False               # a different, empty db


def test_table_exists_propagates_errors():
    c = sqlite3.connect(":memory:")
    c.close()
    with pytest.raises(sqlite3.ProgrammingError):
        table_exists(c, "t")


# --- DataFrames ---------------------------------------------------------

def test_df_round_trip_with_path(db_path):
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    df_to_sql(db_path, df, "t")
    out = df_from_sqlite(db_path, "SELECT * FROM t ORDER BY a;")
    assert out["a"].tolist() == [1, 2]
    assert out["b"].tolist() == ["x", "y"]


def test_df_round_trip_with_connection_and_params(con):
    df = pd.DataFrame({"a": [1, 2, 3], "v": [1.5, 2.5, 3.5]})
    df_to_sql(con, df, "t")
    out = df_from_sqlite(con, "SELECT * FROM t WHERE v > ?;", params=(2.0,))
    assert out["a"].tolist() == [2, 3]


def test_df_to_sql_if_exists_and_kwargs(con):
    df = pd.DataFrame({"a": [1]})
    df_to_sql(con, df, "t")
    with pytest.raises(ValueError):
        df_to_sql(con, df, "t")                              # if_exists='fail'
    df_to_sql(con, df, "t", if_exists="append", chunksize=1)  # kwarg passthrough
    df_to_sql(con, pd.DataFrame({"a": [9]}), "t", if_exists="replace")
    assert rows(con, "SELECT * FROM t") == [(9,)]


def test_df_from_sqlite_parse_dates_and_kwargs(con):
    exe(con,
        "CREATE TABLE t (k, d, v);",
        "INSERT INTO t VALUES ('a', '2024-01-02 00:00:00', 1);",
        "INSERT INTO t VALUES ('b', '2024-03-04 00:00:00', 2);")
    out = df_from_sqlite(con, "SELECT * FROM t;", parse_dates=["d"], index_col="k")
    assert out.index.tolist() == ["a", "b"]
    assert str(out["d"].dtype).startswith("datetime64")
    assert out.loc["b", "d"] == pd.Timestamp("2024-03-04")


# --- dates as text ------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    (dt.datetime(2024, 1, 2, 10, 30, 15), "2024-01-02 00:00:00"),   # time truncated
    (dt.date(2024, 1, 2), "2024-01-02 00:00:00"),
    (pd.Timestamp("2024-01-02 23:59"), "2024-01-02 00:00:00"),
    (None, None),
    (pd.NaT, None),
    (float("nan"), None),
    ("2024-01-02", None),                                          # str has no strftime
    (12345, None),
])
def test_datetime_to_sqlite(value, expected):
    assert datetime_to_sqlite(value) == expected


@pytest.mark.parametrize("value, expected", [
    (dt.datetime(2024, 1, 2, 10, 30), "2024-01-02 00:00:00"),
    (dt.date(2024, 1, 2), "2024-01-02 00:00:00"),
    (pd.Timestamp("2024-01-02 23:59"), "2024-01-02 00:00:00"),
    ("30/12/2024", "2024-12-30 00:00:00"),
    (20261202, "2026-12-02 00:00:00"),
    (None, None),
    (pd.NaT, None),
    (float("nan"), None),
])
def test_to_sqlite_dt(value, expected):
    assert to_sqlite_dt(value) == expected


@pytest.mark.parametrize("value", [[1, 2], object(), "not a date"])
def test_to_sqlite_dt_raises_on_unconvertible(value):
    with pytest.raises(ValueError):
        to_sqlite_dt(value)


def test_df_datetimes_to_sqlite_converts_in_place_and_returns_df():
    df = pd.DataFrame({
        "f": pd.to_datetime(["2024-01-02 10:30:00", "2024-03-04 00:00:00", None]),
        "d": [dt.date(2024, 1, 2), dt.date(2024, 3, 4), None],
        "v": [1, 2, 3],
    })
    assert str(df["f"].dtype).startswith("datetime64")       # the pandas 3 no-op scenario
    out = df_datetimes_to_sqlite(df, ["f", "d"])
    assert out is df
    assert df["f"].tolist()[:2] == ["2024-01-02 00:00:00", "2024-03-04 00:00:00"]
    assert df["d"].tolist()[:2] == ["2024-01-02 00:00:00", "2024-03-04 00:00:00"]
    assert pd.isna(df["f"].iloc[2]) and pd.isna(df["d"].iloc[2])
    assert not str(df["f"].dtype).startswith("datetime64")
    assert df["v"].tolist() == [1, 2, 3]                     # untouched


def test_df_datetimes_to_sqlite_writes_text_to_sqlite(con):
    df = pd.DataFrame({"f": pd.to_datetime(["2024-01-02 10:30:00"])})
    df_to_sql(con, df_datetimes_to_sqlite(df, ["f"]), "t")
    assert rows(con, "SELECT f, typeof(f) FROM t") == [("2024-01-02 00:00:00", "text")]


def test_df_datetimes_to_sqlite_missing_column():
    df = pd.DataFrame({"a": [1]})
    with pytest.raises(KeyError, match="nope"):
        df_datetimes_to_sqlite(df, ["a", "nope"])


# --- variables ----------------------------------------------------------

def test_set_and_get_variable(db_path):
    assert set_variable(db_path, "ultima_carga", "2026-08-26") is True
    assert get_variable(db_path, "ultima_carga") == "2026-08-26"
    set_variable(db_path, "ultima_carga", 1.5)                # overwrite
    assert get_variable(db_path, "ultima_carga") == 1.5
    assert rows(db_path, "SELECT count(*) FROM variables") == [(1,)]


def test_get_variable_missing_key_and_default(con):
    set_variable(con, "a", 1)
    with pytest.raises(KeyError):
        get_variable(con, "b")
    assert get_variable(con, "b", default=0) == 0
    assert get_variable(con, "b", default=None) is None
    assert get_variable(con, "a", default=0) == 1


def test_get_variable_missing_table(con):
    with pytest.raises(KeyError):
        get_variable(con, "a")
    assert get_variable(con, "a", default="x") == "x"
    assert not table_exists(con, "variables")                 # get did not create it


def test_variables_custom_table_name_is_quoted(con):
    table = 'odd "name"'
    set_variable(con, "k", "v", table=table)
    assert get_variable(con, "k", table=table) == "v"
    assert table_exists(con, table)


def test_variables_work_with_legacy_table_layout(con):
    # Layout created by the previous version of set_variable.
    con.execute("""CREATE TABLE variables (variable CHAR PRIMARY KEY
                   CONSTRAINT variable_unica UNIQUE ON CONFLICT REPLACE
                   NOT NULL, value) WITHOUT ROWID;""")
    set_variable(con, "k", 1)
    set_variable(con, "k", 2)
    assert get_variable(con, "k") == 2
    assert rows(con, "SELECT count(*) FROM variables") == [(1,)]

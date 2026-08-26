"""Unit tests for duckdb_update_table."""

import duckdb
import pandas as pd
import pytest

from fuchitools.duckdb import duckdb_update_table


@pytest.fixture
def con():
    """Fresh in-memory DuckDB connection per test."""
    connection = duckdb.connect()
    yield connection
    connection.close()


def table_pk(con, table):
    """Return the table's PRIMARY KEY columns, or None if it has none."""
    row = con.execute(
        "SELECT constraint_column_names FROM duckdb_constraints() "
        "WHERE table_name = ? AND constraint_type = 'PRIMARY KEY'",
        [table],
    ).fetchone()
    return list(row[0]) if row else None


def table_columns(con, table):
    return [r[0] for r in con.execute(f'DESCRIBE "{table}"').fetchall()]


def rows(con, sql):
    return con.execute(sql).fetchall()


# --- Creation and return value ---------------------------------------------

def test_create_table_with_keys_sets_primary_key(con):
    df = pd.DataFrame({"id": [1, 2], "v": ["a", "b"]})
    assert duckdb_update_table(con, "t", df, keys=["id"]) == 2
    assert table_pk(con, "t") == ["id"]
    assert rows(con, "SELECT id, v FROM t ORDER BY id") == [(1, "a"), (2, "b")]


def test_keys_as_single_string_is_one_column(con):
    df = pd.DataFrame({"security": ["a", "b"], "v": [1, 2]})
    assert duckdb_update_table(con, "t", df, keys="security") == 2
    assert table_pk(con, "t") == ["security"]
    # upsert through the same spelling
    assert duckdb_update_table(con, "t", pd.DataFrame({"security": ["b", "c"], "v": [20, 30]}), "security") == 1
    assert rows(con, "SELECT security, v FROM t ORDER BY security") == [("a", 1), ("b", 20), ("c", 30)]


def test_create_table_without_keys(con):
    df = pd.DataFrame({"id": [1, 2], "v": ["a", "b"]})
    assert duckdb_update_table(con, "t", df) == 2
    assert table_pk(con, "t") is None
    assert rows(con, "SELECT id, v FROM t ORDER BY id") == [(1, "a"), (2, "b")]


def test_none_or_empty_dataframe_returns_zero_without_creating_table(con):
    assert duckdb_update_table(con, "t", None) == 0
    assert duckdb_update_table(con, "t", pd.DataFrame({"a": []})) == 0
    n_tables = con.execute(
        "SELECT count(*) FROM duckdb_tables() WHERE table_name = 't'"
    ).fetchone()[0]
    assert n_tables == 0


def test_return_value_counts_only_inserted_rows(con):
    df = pd.DataFrame({"id": [1, 2], "v": ["a", "b"]})
    assert duckdb_update_table(con, "t", df, keys=["id"]) == 2
    # Rewriting the same data inserts nothing (rows only get updated).
    assert duckdb_update_table(con, "t", df, keys=["id"]) == 0
    assert rows(con, "SELECT id, v FROM t ORDER BY id") == [(1, "a"), (2, "b")]


# --- Upsert -----------------------------------------------------------------

def test_upsert_updates_existing_and_inserts_new_rows(con):
    duckdb_update_table(
        con, "t", pd.DataFrame({"id": [1, 2], "v": ["a", "b"]}), keys=["id"])
    n = duckdb_update_table(
        con, "t", pd.DataFrame({"id": [2, 3], "v": ["B", "c"]}), keys=["id"])
    assert n == 1
    assert rows(con, "SELECT id, v FROM t ORDER BY id") == [
        (1, "a"), (2, "B"), (3, "c")]


def test_upsert_uses_table_primary_key_when_keys_is_none(con):
    duckdb_update_table(
        con, "t", pd.DataFrame({"id": [1], "v": ["a"]}), keys=["id"])
    n = duckdb_update_table(
        con, "t", pd.DataFrame({"id": [1, 2], "v": ["A", "b"]}))
    assert n == 1
    assert rows(con, "SELECT id, v FROM t ORDER BY id") == [(1, "A"), (2, "b")]


def test_keys_missing_from_dataframe_raise(con):
    df = pd.DataFrame({"id": [1], "v": ["a"]})
    with pytest.raises(ValueError, match=r"missing from DataFrame.*'nope'"):
        duckdb_update_table(con, "t", df, keys=["nope"])


def test_null_in_dataframe_key_column_raises(con):
    duckdb_update_table(
        con, "t", pd.DataFrame({"id": [1], "v": ["a"]}), keys=["id"])
    df = pd.DataFrame({"id": pd.array([2, None], dtype="Int64"),
                       "v": ["b", "c"]})
    with pytest.raises(ValueError, match=r"1 DataFrame rows have NULL"):
        duckdb_update_table(con, "t", df, keys=["id"])
    assert rows(con, "SELECT id, v FROM t") == [(1, "a")]


def test_deduplication_by_key_keeps_last_occurrence(con):
    duckdb_update_table(
        con, "t", pd.DataFrame({"id": [1], "v": ["a"]}), keys=["id"])
    df = pd.DataFrame({"id": [1, 1, 2, 2], "v": ["p", "q", "x", "y"]})
    assert duckdb_update_table(con, "t", df, keys=["id"]) == 1
    assert rows(con, "SELECT id, v FROM t ORDER BY id") == [(1, "q"), (2, "y")]


def test_upsert_where_all_common_columns_are_key_does_nothing(con):
    duckdb_update_table(con, "t", pd.DataFrame({"id": [1, 2]}), keys=["id"])
    n = duckdb_update_table(con, "t", pd.DataFrame({"id": [2, 3]}),
                            keys=["id"])
    assert n == 1
    assert rows(con, "SELECT id FROM t ORDER BY id") == [(1,), (2,), (3,)]


# --- PRIMARY KEY and protect_pk ---------------------------------------------

def test_change_pk_requires_protect_pk_false(con):
    df = pd.DataFrame({"id": [1, 2], "code": ["x", "y"], "v": [10, 20]})
    duckdb_update_table(con, "t", df, keys=["id"])
    df2 = pd.DataFrame({"id": [3], "code": ["z"], "v": [30]})
    with pytest.raises(ValueError, match="protect_pk=False"):
        duckdb_update_table(con, "t", df2, keys=["code"])
    assert table_pk(con, "t") == ["id"]

    assert duckdb_update_table(con, "t", df2, keys=["code"],
                               protect_pk=False) == 1
    assert table_pk(con, "t") == ["code"]
    assert rows(con, "SELECT id, code, v FROM t ORDER BY id") == [
        (1, "x", 10), (2, "y", 20), (3, "z", 30)]


def test_same_key_with_different_column_order_is_not_a_change(con):
    df = pd.DataFrame({"a": [1], "b": [2], "v": ["x"]})
    duckdb_update_table(con, "t", df, keys=["a", "b"])
    # protect_pk stays at its default True and no error is raised.
    assert duckdb_update_table(con, "t", df, keys=["b", "a"]) == 0
    assert sorted(table_pk(con, "t")) == ["a", "b"]


def test_empty_keys_drops_primary_key(con):
    df = pd.DataFrame({"id": [1, 2], "v": ["a", "b"]})
    duckdb_update_table(con, "t", df, keys=["id"])
    with pytest.raises(ValueError, match="protect_pk=False"):
        duckdb_update_table(con, "t", df, keys=[])
    assert table_pk(con, "t") == ["id"]

    assert duckdb_update_table(con, "t", df, keys=[], protect_pk=False) == 0
    assert table_pk(con, "t") is None
    # From here on the keyless path works: only new rows are inserted.
    df2 = pd.DataFrame({"id": [2, 3], "v": ["b", "c"]})
    assert duckdb_update_table(con, "t", df2) == 1
    assert rows(con, "SELECT id, v FROM t ORDER BY id") == [
        (1, "a"), (2, "b"), (3, "c")]


def test_adding_pk_to_table_without_pk_ignores_protect_pk(con):
    duckdb_update_table(con, "t", pd.DataFrame({"id": [1], "v": ["a"]}))
    assert table_pk(con, "t") is None
    n = duckdb_update_table(con, "t", pd.DataFrame({"id": [2], "v": ["b"]}),
                            keys=["id"], protect_pk=True)
    assert n == 1
    assert table_pk(con, "t") == ["id"]


def test_rebuild_rejected_when_existing_keys_are_duplicated(con):
    duckdb_update_table(
        con, "t", pd.DataFrame({"code": ["x", "x", "y"], "v": [1, 2, 3]}))
    df = pd.DataFrame({"code": ["z"], "v": [9]})
    with pytest.raises(ValueError, match="1 duplicated key values"):
        duckdb_update_table(con, "t", df, keys=["code"])
    assert table_pk(con, "t") is None
    assert rows(con, "SELECT count(*) FROM t") == [(3,)]


def test_rebuild_rejected_when_existing_keys_have_nulls(con):
    duckdb_update_table(
        con, "t", pd.DataFrame({"code": ["x", None], "v": [1, 2]}))
    df = pd.DataFrame({"code": ["z"], "v": [9]})
    with pytest.raises(ValueError, match="1 existing rows have NULL"):
        duckdb_update_table(con, "t", df, keys=["code"])
    assert table_pk(con, "t") is None
    assert rows(con, "SELECT count(*) FROM t") == [(2,)]


# --- Keyless path ------------------------------------------------------------

def test_keyless_inserts_only_new_rows_including_nulls(con):
    df = pd.DataFrame({"a": pd.array([1, None], dtype="Int64"),
                       "b": ["x", None]})
    assert duckdb_update_table(con, "t", df) == 2
    # Rewriting the same data inserts nothing, NULL rows included.
    assert duckdb_update_table(con, "t", df) == 0
    assert rows(con, "SELECT count(*) FROM t") == [(2,)]
    df2 = pd.DataFrame({"a": pd.array([1, 3], dtype="Int64"),
                        "b": ["x", "y"]})
    assert duckdb_update_table(con, "t", df2) == 1
    assert rows(con, "SELECT a, b FROM t ORDER BY a NULLS LAST") == [
        (1, "x"), (3, "y"), (None, None)]


def test_keyless_identical_duplicate_rows_inserted_once(con):
    duckdb_update_table(con, "t", pd.DataFrame({"a": [1], "b": ["x"]}))
    df = pd.DataFrame({"a": [2, 2], "b": ["y", "y"]})
    assert duckdb_update_table(con, "t", df) == 1
    assert rows(con, "SELECT a, b FROM t ORDER BY a") == [(1, "x"), (2, "y")]


# --- Columns -----------------------------------------------------------------

def test_check_columns_reports_differences_in_both_directions(con):
    duckdb_update_table(con, "t", pd.DataFrame({"a": [1], "b": [2]}))
    df = pd.DataFrame({"a": [3], "c": [4]})
    with pytest.raises(
            ValueError,
            match=r"missing in table: \['c'\].*missing in DataFrame: \['b'\]"):
        duckdb_update_table(con, "t", df)


def test_check_columns_false_ignores_extra_dataframe_columns(con):
    duckdb_update_table(
        con, "t", pd.DataFrame({"id": [1], "v": ["a"]}), keys=["id"])
    df = pd.DataFrame({"id": [2], "v": ["b"], "extra": [99]})
    assert duckdb_update_table(con, "t", df, check_columns=False) == 1
    assert table_columns(con, "t") == ["id", "v"]
    assert rows(con, "SELECT id, v FROM t ORDER BY id") == [(1, "a"), (2, "b")]


def test_add_columns_adds_new_column_with_null_for_old_rows(con):
    duckdb_update_table(
        con, "t", pd.DataFrame({"id": [1], "v": ["a"]}), keys=["id"])
    df = pd.DataFrame({"id": [2], "v": ["b"], "w": [10]})
    assert duckdb_update_table(con, "t", df, add_columns=True) == 1
    assert table_columns(con, "t") == ["id", "v", "w"]
    assert rows(con, "SELECT id, v, w FROM t ORDER BY id") == [
        (1, "a", None), (2, "b", 10)]


def test_no_common_columns_raises(con):
    duckdb_update_table(con, "t", pd.DataFrame({"a": [1]}))
    df = pd.DataFrame({"z": [1]})
    with pytest.raises(ValueError, match="no columns in common"):
        duckdb_update_table(con, "t", df, check_columns=False)


def test_dataframe_column_order_is_irrelevant(con):
    duckdb_update_table(
        con, "t", pd.DataFrame({"id": [1], "v": ["a"]}), keys=["id"])
    df = pd.DataFrame({"v": ["B", "c"], "id": [1, 2]})  # Reversed order.
    assert duckdb_update_table(con, "t", df, keys=["id"]) == 1
    assert rows(con, "SELECT id, v FROM t ORDER BY id") == [(1, "B"), (2, "c")]


# --- Case sensitivity --------------------------------------------------------

def test_case_insensitive_matching_preserves_table_spelling(con):
    con.execute('CREATE TABLE t ("Id" INTEGER PRIMARY KEY, "Val" VARCHAR)')
    con.execute("INSERT INTO t VALUES (1, 'a')")
    df = pd.DataFrame({"ID": [1, 2], "VAL": ["A", "b"]})
    # keys=["id"] matches the table's "Id" and the DataFrame's "ID".
    assert duckdb_update_table(con, "t", df, keys=["id"]) == 1
    assert table_columns(con, "t") == ["Id", "Val"]
    assert rows(con, 'SELECT "Id", "Val" FROM t ORDER BY "Id"') == [
        (1, "A"), (2, "b")]


def test_case_sensitive_rejects_different_capitalization(con):
    con.execute('CREATE TABLE t ("Id" INTEGER PRIMARY KEY, "Val" VARCHAR)')
    df = pd.DataFrame({"ID": [1], "VAL": ["a"]})
    with pytest.raises(ValueError, match="columns differ"):
        duckdb_update_table(con, "t", df, case_sensitive=True)


def test_ambiguous_dataframe_columns_in_insensitive_mode_raise(con):
    df = pd.DataFrame([[1, 2]], columns=["a", "A"])
    with pytest.raises(ValueError, match="differ only in case"):
        duckdb_update_table(con, "t", df)


# --- Transaction / atomicity -------------------------------------------------

def test_failed_check_columns_does_not_leave_added_column(con):
    duckdb_update_table(con, "t", pd.DataFrame({"a": [1], "b": [2]}))
    df = pd.DataFrame({"a": [3], "c": [4]})  # Adds c, but b is missing.
    with pytest.raises(ValueError, match="missing in DataFrame"):
        duckdb_update_table(con, "t", df, add_columns=True)
    assert table_columns(con, "t") == ["a", "b"]


def test_failed_write_leaves_table_exactly_as_it_was(con):
    con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v VARCHAR)")
    con.execute("INSERT INTO t VALUES (1, 'a')")
    # 'boom' cannot be cast to INTEGER, so the insert fails after the
    # ALTER TABLE ADD COLUMN has already run inside the transaction.
    df = pd.DataFrame({"id": ["boom"], "v": ["x"], "w": [10]})
    with pytest.raises(duckdb.Error):
        duckdb_update_table(con, "t", df, add_columns=True)
    assert table_columns(con, "t") == ["id", "v"]
    assert rows(con, "SELECT id, v FROM t") == [(1, "a")]
    # The connection is still usable (the transaction was rolled back).
    assert con.execute("SELECT 42").fetchone()[0] == 42
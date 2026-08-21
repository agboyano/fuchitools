"""Write a pandas DataFrame into a DuckDB table, creating or updating it."""

import duckdb
import pandas as pd


def _quote(name):
    """Quote an SQL identifier."""
    return '"' + str(name).replace('"', '""') + '"'


def _table_exists(con, table):
    count = con.execute(
        "SELECT count(*) FROM duckdb_tables() WHERE table_name = ?", [table]
    ).fetchone()[0]
    return count > 0


def _primary_key(con, table):
    """Return the primary key columns of a table, or an empty list if it has none."""
    row = con.execute(
        """
        SELECT constraint_column_names
        FROM duckdb_constraints()
        WHERE table_name = ? AND constraint_type = 'PRIMARY KEY'
        """,
        [table],
    ).fetchone()
    return list(row[0]) if row else []


def _table_columns(con, table):
    return [row[0] for row in con.execute(f"DESCRIBE {_quote(table)}").fetchall()]


def _column_definitions(con, describe_target):
    """Return "name type" pairs from a DESCRIBE result (a table or a query)."""
    rows = con.execute(f"DESCRIBE {describe_target}").fetchall()
    return ", ".join(f"{_quote(row[0])} {row[1]}" for row in rows)


def _create_table(con, table, source, keys):
    if not keys:
        con.execute(f"CREATE TABLE {_quote(table)} AS SELECT * FROM {_quote(source)}")
        return
    # With a key the table needs explicit types, so take them from the DataFrame.
    columns = _column_definitions(con, f"SELECT * FROM {_quote(source)}")
    key_list = ", ".join(_quote(k) for k in keys)
    con.execute(f"CREATE TABLE {_quote(table)} ({columns}, PRIMARY KEY ({key_list}))")


def _ensure_primary_key(con, table, keys, protect_pk):
    """Make sure the primary key of an existing table is exactly `keys`."""
    current = _primary_key(con, table)
    if set(current) == set(keys):  # the order of the key columns is irrelevant
        return
    if current and protect_pk:
        raise ValueError(
            f"table '{table}' already has primary key {current}; changing it to {keys} "
            "requires rebuilding the table. Call with protect_pk=False to allow it."
        )

    columns = _table_columns(con, table)
    missing = [k for k in keys if k not in columns]
    if missing:
        raise ValueError(f"table '{table}' has no column(s) {missing} to use as key")

    key_list = ", ".join(_quote(k) for k in keys)
    duplicates = con.execute(
        f"SELECT count(*) FROM (SELECT 1 FROM {_quote(table)} "
        f"GROUP BY {key_list} HAVING count(*) > 1)"
    ).fetchone()[0]
    if duplicates:
        raise ValueError(
            f"cannot use {keys} as primary key of '{table}': "
            f"{duplicates} duplicated key(s) in the current data"
        )

    # DuckDB cannot add constraints with ALTER TABLE, so the table is rebuilt:
    # a temporary copy carries the primary key and then takes the original name.
    rebuilt = f"{table}__pk_rebuild"
    definitions = _column_definitions(con, _quote(table))
    con.execute(f"CREATE TABLE {_quote(rebuilt)} ({definitions}, PRIMARY KEY ({key_list}))")
    con.execute(f"INSERT INTO {_quote(rebuilt)} SELECT * FROM {_quote(table)}")
    con.execute(f"DROP TABLE {_quote(table)}")
    con.execute(f"ALTER TABLE {_quote(rebuilt)} RENAME TO {_quote(table)}")


def _upsert(con, table, source, columns, keys):
    key_list = ", ".join(_quote(k) for k in keys)
    column_list = ", ".join(_quote(c) for c in columns)
    updatable = [c for c in columns if c not in keys]
    if updatable:
        assignments = ", ".join(f"{_quote(c)} = excluded.{_quote(c)}" for c in updatable)
        action = f"DO UPDATE SET {assignments}"
    else:
        action = "DO NOTHING"
    # DuckDB refuses to update the same row twice in a single INSERT, so the source
    # is reduced to one row per key first.
    con.execute(
        f"INSERT INTO {_quote(table)} ({column_list}) "
        f"SELECT {column_list} FROM {_quote(source)} "
        f"QUALIFY row_number() OVER (PARTITION BY {key_list}) = 1 "
        f"ON CONFLICT ({key_list}) {action}"
    )


def _insert_new_rows(con, table, source, columns):
    column_list = ", ".join(_quote(c) for c in columns)
    source_list = ", ".join(f"s.{_quote(c)}" for c in columns)
    # IS NOT DISTINCT FROM so that NULLs on both sides count as equal.
    condition = " AND ".join(
        f"t.{_quote(c)} IS NOT DISTINCT FROM s.{_quote(c)}" for c in columns
    )
    con.execute(
        f"INSERT INTO {_quote(table)} ({column_list}) "
        f"SELECT DISTINCT {source_list} FROM {_quote(source)} AS s "
        f"WHERE NOT EXISTS (SELECT 1 FROM {_quote(table)} AS t WHERE {condition})"
    )


def duckdb_update_generic_table(con, table, new_df, keys=None, protect_pk=True):
    """Store `new_df` in the DuckDB table `table`, creating or updating it.

    con         open DuckDB connection
    table       table name
    new_df      pandas DataFrame with the data to store
    keys        optional list of columns forming the key; if omitted and the table
                already has a primary key, that primary key is used
    protect_pk  if True, refuse to replace an existing primary key with a different
                one (it never prevents adding a key to a table that has none)

    Returns the number of inserted rows, measured as the difference in count(*)
    before and after; updated rows are therefore not counted.
    """
    if new_df is None or len(new_df) == 0:
        return 0

    keys = list(keys) if keys else []
    missing = [k for k in keys if k not in new_df.columns]
    if missing:
        raise ValueError(f"key column(s) {missing} are not in the DataFrame")

    source = f"new_df_source_{id(new_df):x}"
    con.register(source, new_df)
    try:
        exists = _table_exists(con, table)

        if exists and not keys:
            primary_key = _primary_key(con, table)
            missing = [c for c in primary_key if c not in new_df.columns]
            if missing:
                raise ValueError(
                    f"table '{table}' has primary key {primary_key} but the DataFrame "
                    f"is missing column(s) {missing}"
                )
            keys = primary_key

        rows_before = 0
        if exists:
            rows_before = con.execute(
                f"SELECT count(*) FROM {_quote(table)}"
            ).fetchone()[0]

        con.execute("BEGIN TRANSACTION")
        try:
            if not exists:
                _create_table(con, table, source, keys)
            elif keys:
                _ensure_primary_key(con, table, keys, protect_pk)

            # Extra columns in the DataFrame are ignored.
            columns = [c for c in _table_columns(con, table) if c in new_df.columns]
            if not columns:
                raise ValueError(
                    f"table '{table}' and the DataFrame have no columns in common"
                )

            if keys:
                _upsert(con, table, source, columns, keys)
            else:
                _insert_new_rows(con, table, source, columns)

            rows_after = con.execute(
                f"SELECT count(*) FROM {_quote(table)}"
            ).fetchone()[0]
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise

        return rows_after - rows_before
    finally:
        con.unregister(source)


if __name__ == "__main__":
    con = duckdb.connect()

    # Create with a key.
    df = pd.DataFrame({"id": [1, 2], "name": ["a", "b"], "value": [10, 20]})
    assert duckdb_update_generic_table(con, "sales", df, keys=["id"]) == 2
    assert _primary_key(con, "sales") == ["id"]

    # Upsert using the primary key of the table: updates id=2 and inserts id=3.
    df = pd.DataFrame({"id": [2, 3], "name": ["B", "c"], "value": [99, 30]})
    assert duckdb_update_generic_table(con, "sales", df) == 1
    assert con.execute("SELECT id, name, value FROM sales ORDER BY id").fetchall() == [
        (1, "a", 10),
        (2, "B", 99),
        (3, "c", 30),
    ]

    # Changing the key with protect_pk=True must fail.
    try:
        duckdb_update_generic_table(con, "sales", df, keys=["name"])
    except ValueError as error:
        print("expected error:", error)
    else:
        raise AssertionError("changing the primary key should have been refused")

    # ... and must succeed with protect_pk=False.
    assert duckdb_update_generic_table(con, "sales", df, keys=["name"], protect_pk=False) == 0
    assert _primary_key(con, "sales") == ["name"]

    # Without a key only rows that are not already there are inserted (NULL included).
    df = pd.DataFrame({"city": ["Madrid", "Barcelona", None]})
    assert duckdb_update_generic_table(con, "cities", df) == 3
    df = pd.DataFrame({"city": ["Madrid", None, "Valencia"]})
    assert duckdb_update_generic_table(con, "cities", df) == 1

    print("ok")
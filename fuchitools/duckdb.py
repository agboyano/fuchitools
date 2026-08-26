"""Write a pandas DataFrame into a DuckDB table, creating or updating it."""

import uuid

__all__ = ["duckdb_update_table"]


def _quote(name):
    """Quote an SQL identifier."""
    return '"' + name.replace('"', '""') + '"'


def _spelling_map(names, case_sensitive, side):
    """Map normalized name -> real spelling, rejecting case-ambiguous pairs."""
    spelling = {}
    for name in names:
        norm = name if case_sensitive else name.lower()
        if norm in spelling:
            raise ValueError(
                f"{side} columns {spelling[norm]!r} and {name!r} differ only "
                "in case, which is ambiguous with case_sensitive=False"
            )
        spelling[norm] = name
    return spelling


def duckdb_update_table(con, table, new_df, keys=None, protect_pk=True,
                        add_columns=False, check_columns=True,
                        case_sensitive=False):
    """Write a pandas DataFrame into a DuckDB table, creating the table if it
    does not exist and inserting/upserting into it if it does.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open DuckDB connection. The function runs everything inside its own
        explicit transaction, so the connection must NOT have a transaction
        already open when it is called.
    table : str
        Table name. It must be a simple, unqualified name in the current
        schema ("sales", not "main.sales").
    new_df : pandas.DataFrame
        Data to write. If it is None or empty, nothing is done (the table is
        not created either) and 0 is returned.
    keys : None | list of str, default None
        - None: if the table exists and has a PRIMARY KEY, that key is used
          for the upsert (its columns must all be present in the DataFrame);
          otherwise the keyless path is used. The existing key is never
          modified in this mode.
        - Non-empty list: upsert on these columns, making sure the table's
          PRIMARY KEY is exactly this set of columns (creating or replacing
          it if needed; replacing an existing, different key requires
          protect_pk=False and rebuilds the table).
        - Empty list: forces the keyless path. If the table has a PRIMARY
          KEY it is dropped, which requires protect_pk=False and rebuilds
          the table.
    protect_pk : bool, default True
        Protects PRIMARY KEYs that already exist: changing or dropping one
        raises ValueError unless protect_pk=False. Adding a key to a table
        that has none is allowed even with protect_pk=True.
    add_columns : bool, default False
        If True, columns present in the DataFrame but not in the table are
        added to the table (existing rows get NULL in them).
    check_columns : bool, default True
        If True, the table and the DataFrame must have exactly the same
        columns (checked after add_columns has been applied).
    case_sensitive : bool, default False
        If False (default), every column-name comparison (DataFrame vs
        table, keys vs both, PRIMARY KEY vs keys) is case-insensitive; SQL
        is still built with the real spelling of each side. If either side
        has two columns whose names differ only in case, ValueError is
        raised. If True, comparisons are exact.

    Returns
    -------
    int
        Number of rows inserted, computed as the difference of the table's
        count(*) before and after the write. Consequently, updated rows are
        not counted, and duplicate or already-present rows add nothing.

    Warnings
    --------
    - The function manages its own transaction (BEGIN/COMMIT, ROLLBACK on
      error); the connection must not have an open transaction.
    - ``table`` must be a simple name in the current schema, without a
      schema qualifier.
    - Changing or dropping a PRIMARY KEY rebuilds the table, and the
      rebuild only preserves columns, types and data: any other
      constraints, defaults and indexes are lost.
    - On keyed writes the DataFrame is deduplicated by key keeping the
      LAST occurrence (DataFrame row order), because DuckDB cannot update
      the same row twice in a single INSERT.
    - On the keyless path the insert uses SELECT DISTINCT, so identical
      repeated rows in the DataFrame are inserted only once, and only rows
      not already in the table are inserted (NULLs compare as equal).

    Examples
    --------
    # First load of a reference table: create it with a key.
    >>> duckdb_update_table(con, "products", df, keys=["product_id"])

    # Daily maintenance upsert against a table that already has a PRIMARY
    # KEY: call without keys and the existing key is used as-is.
    >>> duckdb_update_table(con, "products", daily_df)

    # Incremental load of a log-style table without a key: only rows not
    # already present are inserted.
    >>> duckdb_update_table(con, "events", new_events_df)

    # The business key changed: replace the PRIMARY KEY (rebuilds the
    # table, so it needs protect_pk=False).
    >>> duckdb_update_table(con, "products", df, keys=["sku"],
    ...                     protect_pk=False)

    # Drop the PRIMARY KEY entirely and switch to the keyless path.
    >>> duckdb_update_table(con, "products", df, keys=[], protect_pk=False)

    # Schema evolution: the source now brings a new column; add it to the
    # table (old rows get NULL in it).
    >>> duckdb_update_table(con, "products", wider_df, add_columns=True)

    # Loading from a raw DataFrame that has extra columns the table does
    # not need: ignore them instead of failing.
    >>> duckdb_update_table(con, "products", raw_df, check_columns=False)
    """
    if new_df is None or new_df.empty:
        return 0

    if isinstance(keys, str):
        # A lone column name; iterating it as a list would split it into
        # characters and produce a baffling "missing columns" error.
        keys = [keys]

    def norm(name):
        return name if case_sensitive else name.lower()

    df_cols = list(new_df.columns)
    if any(not isinstance(col, str) for col in df_cols):
        raise ValueError("DataFrame column names must all be strings")
    if len(set(df_cols)) != len(df_cols):
        raise ValueError("DataFrame has duplicate column names")
    df_map = _spelling_map(df_cols, case_sensitive, "DataFrame")

    if keys is not None:
        if any(not isinstance(key, str) for key in keys):
            raise ValueError("keys must be a list of column names (strings)")
        if len({norm(key) for key in keys}) != len(keys):
            raise ValueError("keys contains repeated columns")
        missing = [key for key in keys if norm(key) not in df_map]
        if missing:
            raise ValueError(f"key columns missing from DataFrame: {missing}")

    # Simple name in the current schema; keep the table's real spelling.
    row = con.execute(
        "SELECT table_name FROM duckdb_tables() "
        "WHERE schema_name = current_schema() AND lower(table_name) = lower(?)",
        [table],
    ).fetchone()
    exists = row is not None
    qtable = _quote(row[0] if exists else table)

    cols_to_add = []
    rebuild_pk = None  # None: leave the PK alone; []: drop it; list: new PK.
    if exists:
        tbl_cols = [r[0] for r in con.execute(
            "SELECT column_name FROM duckdb_columns() "
            "WHERE schema_name = current_schema() AND table_name = ? "
            "ORDER BY column_index",
            [row[0]],
        ).fetchall()]
        tbl_map = _spelling_map(tbl_cols, case_sensitive, "Table")
        pk_row = con.execute(
            "SELECT constraint_column_names FROM duckdb_constraints() "
            "WHERE schema_name = current_schema() AND table_name = ? "
            "AND constraint_type = 'PRIMARY KEY'",
            [row[0]],
        ).fetchone()
        pk_cols = list(pk_row[0]) if pk_row else []

        # Column adjustment goes before PK management so a new key can rely
        # on a column added right here.
        if add_columns:
            cols_to_add = [col for col in df_cols if norm(col) not in tbl_map]
        eff_cols = tbl_cols + cols_to_add
        eff_map = dict(tbl_map)
        eff_map.update({norm(col): col for col in cols_to_add})

        if check_columns:
            missing_in_table = [c for c in df_cols if norm(c) not in eff_map]
            missing_in_df = [c for c in eff_cols if norm(c) not in df_map]
            if missing_in_table or missing_in_df:
                raise ValueError(
                    "table and DataFrame columns differ: "
                    f"missing in table: {missing_in_table}; "
                    f"missing in DataFrame: {missing_in_df}"
                )

        # PRIMARY KEY management.
        if keys is None:
            missing = [c for c in pk_cols if norm(c) not in df_map]
            if missing:
                raise ValueError(
                    f"table PRIMARY KEY columns missing from DataFrame: "
                    f"{missing}"
                )
            upsert_keys = list(pk_cols)
        elif {norm(c) for c in pk_cols} == {norm(k) for k in keys}:
            upsert_keys = list(pk_cols)  # Same key (order does not matter).
        else:
            if pk_cols and protect_pk:
                raise ValueError(
                    "changing or dropping the existing PRIMARY KEY requires "
                    "rebuilding the table, which only preserves columns, "
                    "types and data (other constraints, defaults and indexes "
                    "are lost); call again with protect_pk=False to proceed"
                )
            missing = [k for k in keys if norm(k) not in eff_map]
            if missing:
                raise ValueError(f"key columns missing from table: {missing}")
            rebuild_pk = [eff_map[norm(k)] for k in keys]
            upsert_keys = list(rebuild_pk)

        # A rebuild that sets a PK needs the current data to satisfy it.
        if rebuild_pk:
            n_rows = con.execute(f"SELECT count(*) FROM {qtable}").fetchone()[0]
            if n_rows:
                just_added = [c for c in rebuild_pk if c in cols_to_add]
                if just_added:
                    raise ValueError(
                        f"cannot set PRIMARY KEY: {n_rows} existing rows "
                        f"have NULL in key columns {just_added} (columns "
                        "just added by add_columns)"
                    )
                null_cond = " OR ".join(
                    f"{_quote(c)} IS NULL" for c in rebuild_pk)
                nulls = con.execute(
                    f"SELECT count(*) FROM {qtable} WHERE {null_cond}"
                ).fetchone()[0]
                if nulls:
                    raise ValueError(
                        f"cannot set PRIMARY KEY: {nulls} existing rows have "
                        "NULL in the key columns"
                    )
                group = ", ".join(_quote(c) for c in rebuild_pk)
                dups = con.execute(
                    f"SELECT count(*) FROM (SELECT 1 FROM {qtable} "
                    f"GROUP BY {group} HAVING count(*) > 1)"
                ).fetchone()[0]
                if dups:
                    raise ValueError(
                        f"cannot set PRIMARY KEY: {dups} duplicated key "
                        "values in existing data"
                    )

        # From here on, work only with the common columns; the pairing is
        # by name, so DataFrame column order is irrelevant.
        commons = [(c, df_map[norm(c)]) for c in eff_cols if norm(c) in df_map]
        if not commons:
            raise ValueError("table and DataFrame have no columns in common")
    else:
        commons = [(col, col) for col in df_cols]
        upsert_keys = list(keys) if keys else []

    df_key_cols = [df_map[norm(k)] for k in upsert_keys]
    if exists and upsert_keys:
        # DuckDB cannot update the same row twice in one INSERT, so keep
        # only the last occurrence of each key (DataFrame row order).
        new_df = new_df.drop_duplicates(subset=df_key_cols, keep="last")

    view = "duckdb_update_df_" + uuid.uuid4().hex
    qview = _quote(view)
    con.register(view, new_df)
    try:
        df_types = {name: col_type for name, col_type, *_ in con.execute(
            f"DESCRIBE SELECT * FROM {qview}").fetchall()}

        def df_type(col):
            col_type = df_types.get(col)
            # An all-NULL column can come out with type NULL, unusable in
            # DDL; fall back to VARCHAR.
            if not col_type or col_type.upper() in ("NULL", '"NULL"'):
                return "VARCHAR"
            return col_type

        if df_key_cols:
            null_cond = " OR ".join(
                f"{_quote(c)} IS NULL" for c in df_key_cols)
            nulls = con.execute(
                f"SELECT count(*) FROM {qview} WHERE {null_cond}"
            ).fetchone()[0]
            if nulls:
                raise ValueError(
                    f"{nulls} DataFrame rows have NULL in the key columns")

        if not exists and upsert_keys:
            group = ", ".join(_quote(c) for c in df_key_cols)
            dups = con.execute(
                f"SELECT count(*) FROM (SELECT 1 FROM {qview} "
                f"GROUP BY {group} HAVING count(*) > 1)"
            ).fetchone()[0]
            if dups:
                raise ValueError(
                    f"{dups} duplicated key values in the DataFrame")

        # Every mutation happens inside one transaction so no error can
        # leave the table half-updated.
        con.execute("BEGIN TRANSACTION")
        try:
            if exists:
                before = con.execute(
                    f"SELECT count(*) FROM {qtable}").fetchone()[0]
                for col in cols_to_add:
                    con.execute(
                        f"ALTER TABLE {qtable} ADD COLUMN "
                        f"{_quote(col)} {df_type(col)}"
                    )
                if rebuild_pk is not None:
                    # DuckDB cannot add or drop constraints with ALTER
                    # TABLE, so rebuild: temp copy, drop original, rename.
                    qtmp = _quote("rebuild_" + uuid.uuid4().hex)
                    if rebuild_pk:
                        defs = ", ".join(
                            f"{_quote(name)} {col_type}"
                            for name, col_type, *_ in con.execute(
                                f"DESCRIBE {qtable}").fetchall()
                        )
                        pk_def = ", ".join(_quote(c) for c in rebuild_pk)
                        con.execute(f"CREATE TABLE {qtmp} ({defs}, "
                                    f"PRIMARY KEY ({pk_def}))")
                        con.execute(
                            f"INSERT INTO {qtmp} SELECT * FROM {qtable}")
                    else:
                        con.execute(
                            f"CREATE TABLE {qtmp} AS SELECT * FROM {qtable}")
                    con.execute(f"DROP TABLE {qtable}")
                    con.execute(f"ALTER TABLE {qtmp} RENAME TO {qtable}")

                target_cols = ", ".join(_quote(t) for t, _ in commons)
                source_cols = ", ".join(_quote(d) for _, d in commons)
                if upsert_keys:
                    key_norms = {norm(k) for k in upsert_keys}
                    non_key = [t for t, _ in commons
                               if norm(t) not in key_norms]
                    if non_key:
                        sets = ", ".join(
                            f"{_quote(c)} = EXCLUDED.{_quote(c)}"
                            for c in non_key)
                        action = f"DO UPDATE SET {sets}"
                    else:
                        action = "DO NOTHING"
                    conflict = ", ".join(_quote(k) for k in upsert_keys)
                    con.execute(
                        f"INSERT INTO {qtable} ({target_cols}) "
                        f"SELECT {source_cols} FROM {qview} "
                        f"ON CONFLICT ({conflict}) {action}"
                    )
                else:
                    # Insert only rows not already present; IS NOT DISTINCT
                    # FROM makes NULLs compare as equal. On big tables
                    # without an index this check can be expensive.
                    match = " AND ".join(
                        f"t.{_quote(t)} IS NOT DISTINCT FROM s.{_quote(d)}"
                        for t, d in commons)
                    aliased = ", ".join(f"s.{_quote(d)}" for _, d in commons)
                    con.execute(
                        f"INSERT INTO {qtable} ({target_cols}) "
                        f"SELECT DISTINCT {aliased} FROM {qview} AS s "
                        f"WHERE NOT EXISTS "
                        f"(SELECT 1 FROM {qtable} AS t WHERE {match})"
                    )
            else:
                before = 0
                if upsert_keys:
                    defs = ", ".join(
                        f"{_quote(c)} {df_type(c)}" for c in df_cols)
                    pk_def = ", ".join(_quote(c) for c in df_key_cols)
                    con.execute(f"CREATE TABLE {qtable} ({defs}, "
                                f"PRIMARY KEY ({pk_def}))")
                    cols = ", ".join(_quote(c) for c in df_cols)
                    con.execute(f"INSERT INTO {qtable} ({cols}) "
                                f"SELECT {cols} FROM {qview}")
                else:
                    con.execute(
                        f"CREATE TABLE {qtable} AS SELECT * FROM {qview}")

            after = con.execute(f"SELECT count(*) FROM {qtable}").fetchone()[0]
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
        return after - before
    finally:
        con.unregister(view)
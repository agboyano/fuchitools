# `fuchitools.duckdb`

One function: write a pandas DataFrame into a DuckDB table, creating the table
if it does not exist and upserting into it if it does.

The module does **not** import duckdb — the caller passes an open connection —
so it costs nothing to import and works with whatever duckdb version the
caller has.

```python
duckdb_update_table(con, table, new_df, keys=None, protect_pk=True,
                    add_columns=False, check_columns=True,
                    case_sensitive=False) -> int
```

Returns the number of rows inserted, measured as `count(*)` before against
after. Updated rows therefore count as zero, which is the point: it tells you
how much is new, not how much was touched.

The function docstring in the source is the full reference. What follows is
the shape of it.

## The four ways to call it

```python
import duckdb
from fuchitools.duckdb import duckdb_update_table

con = duckdb.connect("prices.db")

# 1. First load of a reference table: create it with a primary key
duckdb_update_table(con, "products", df, keys=["product_id"])

# 2. Daily upsert against a table that already has a key: say nothing and
#    the existing key is used as-is
duckdb_update_table(con, "products", daily_df)

# 3. Incremental load with no key: only rows not already present go in
duckdb_update_table(con, "events", new_events_df)

# 4. The business key changed: replacing it rebuilds the table
duckdb_update_table(con, "products", df, keys=["sku"], protect_pk=False)
```

`keys=None` means *use whatever the table already has*, and never touches the
key. An explicit list means *make the primary key exactly this*. An empty list
means *no key at all*, dropping one if present.

## The guard rails

**`protect_pk=True` (default)** — changing or dropping an existing primary key
raises `ValueError`. Adding one to a table that has none is allowed, because
that cannot lose anything. Passing `protect_pk=False` is the deliberate act of
saying yes: the change rebuilds the table, and **the rebuild preserves columns,
types and data only** — other constraints, defaults and indexes are lost.

**`check_columns=True` (default)** — the DataFrame and the table must have
exactly the same columns. Turn it off to load from a wider source and let the
extra columns be ignored:

```python
duckdb_update_table(con, "products", raw_df, check_columns=False)
```

**`add_columns=False` (default)** — a column in the DataFrame that the table
lacks is an error. With `add_columns=True` it is added instead, and existing
rows get NULL in it. Checked before `check_columns`, so the two combine the way
you would expect for schema evolution:

```python
duckdb_update_table(con, "products", wider_df, add_columns=True)
```

**`case_sensitive=False` (default)** — every column name comparison is
case-insensitive, while the SQL is still built with each side's real spelling.
If either side has two columns differing only in case, it raises rather than
guess.

## Things that will bite you if you do not know them

- **The function owns its transaction.** It runs `BEGIN`/`COMMIT` and rolls
  back on error, so the connection must not already be inside one.
- **`table` must be a bare name** in the current schema: `"sales"`, never
  `"main.sales"`.
- **Keyed writes deduplicate the DataFrame by key, keeping the last
  occurrence** in row order. DuckDB cannot update the same row twice in one
  `INSERT`, so the alternative would be an error. Sort your DataFrame if
  "last" needs to mean something specific.
- **The keyless path inserts `SELECT DISTINCT`**, and only rows not already in
  the table. Identical repeated rows in the DataFrame land once. NULLs compare
  as equal for this purpose, which is not normal SQL behaviour and is usually
  what you want here.
- **An empty or None DataFrame does nothing at all** — not even create the
  table — and returns 0.

## Tests

`tests/test_duckdb_update_table.py`, 28 tests against in-memory DuckDB
connections. They cover the key transitions (none to one, replace, drop), the
column checks, and the deduplication rules. Worth reading before changing any
of the flag behaviour.

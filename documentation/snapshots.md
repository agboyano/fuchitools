# `fuchitools.snapshots`

Snapshot tests -- "the function still returns what it returned" -- generated
from a **matrix of calls**. You write the matrix, one row per call:
`(group, name, func, args, kwargs)`. The module turns it into one pytest test
per row, records what every call returns into a named **snapshot** (a folder of
CSV and YAML files), and later runs the same matrix again -- in another
environment, against another database -- and reports what changed. Two
recorded snapshots can also be compared with each other without running
anything.

The serialisation and the comparison are done by
[`pytest-regressions`](https://pytest-regressions.readthedocs.io/); this module
adds the matrix, the command-line options and the Python wrappers. It is
**not** imported by `fuchitools/__init__.py` and needs the `snapshots` extra:

```
pip install "fuchitools[snapshots]"        # pytest, pytest-regressions, pyyaml
```

## Quick start: one matrix, two databases, two environments

Suppose `pricing.load(db)` and friends must behave the same after a schema
migration (`db2.db`) as before it (`db1.db`), possibly under a different Python
environment.

1. Write the matrix as a **function of what varies**, in the tests folder of
   the library under test:

   ```python
   # tests/pricing_matrix.py
   import pricing

   def matrix(db, day="2026-06-30"):
       positions = lambda: pricing.load(db, day)            # a dependency: evaluated at test time
       return [
           # group      name            func                 args              kwargs
           ("load",     "positions",    pricing.load,        [db, day]),
           ("load",     "empty_day",    pricing.load,        [db, "1999-01-01"]),
           ("calc",     "pnl",          pricing.pnl,         [positions],      {"currency": "EUR"}),
           ("calc",     "pnl_no_ccy",   pricing.pnl,         [positions],      {"currency": None}),   # raises -> recorded as an error
           ("misc",     "version",      pricing.version),
       ]
   ```

2. Two one-line test modules, one per database:

   ```python
   # tests/record_pricing_before.py      (not test_*.py: pytest only sees it when given the file)
   from fuchitools.snapshots import snapshot_test
   from pricing_matrix import matrix
   test_snapshot = snapshot_test(matrix("db1.db"), subdir="pricing")

   # tests/test_pricing.py               (what `pytest tests` runs)
   from fuchitools.snapshots import snapshot_test
   from pricing_matrix import matrix
   test_snapshot = snapshot_test(matrix("db2.db"), subdir="pricing")
   ```

   Both pass the same `subdir` on purpose: it is the folder the two modules
   share (see [Where the files go](#where-the-files-go)).

3. In the *old* environment, record the reference:

   ```python
   from fuchitools.snapshots import generate
   generate("tests/record_pricing_before.py", "before")
   ```
   ```
   tests/snapshots/pricing/before/
     load__positions.csv  load__empty_day.csv  calc__pnl.csv  calc__pnl_no_ccy.yml  misc__version.yml
   ```
   Commit the folder (or copy it): the other environment needs it.

4. In the *new* environment, run the matrix against `db2.db` and compare:

   ```python
   from fuchitools.snapshots import compare
   compare("tests/test_pricing.py", "before")        # True when every row matches
   ```
   or, on the command line, `python -m pytest tests -p fuchitools.snapshots --snapshot1 before`.
   A different environment can be driven from the current one:
   `compare("tests/test_pricing.py", "before", python=r"c:\venvs\new\Scripts\python.exe")`.

5. Optionally record the new side too and compare the two recordings anywhere,
   without a database or the library:

   ```python
   generate("tests/test_pricing.py", "after")
   compare("tests/test_pricing.py", "before", "after")    # reads files only, runs nothing
   ```

A failing row prints `pytest-regressions`' report: for a CSV, a table per
differing column --

```
E   AssertionError: Values are not sufficiently close.
    pnl:
       obtained_pnl  expected_pnl   diff
    3     1023.4500     1023.4400   0.01
```

-- for a YAML, a text diff.

## The matrix

A row is `(group, name, func, args, kwargs)`; `args` (list or tuple) and
`kwargs` (dict) may be omitted.

| Item | Role |
|---|---|
| `group` | a label: `-k group` selects the rows, the file name starts with it |
| `name` | unique within its group; `group__name` is the test id and the file stem (both sanitised to `[A-Za-z0-9_-]`) |
| `func` | any callable |
| `args`, `kwargs` | the call's arguments. **Any callable among the values is called with no arguments at test time and replaced by its result** -- that is how a row consumes the output of another function (`lambda: load(db)`). To pass a function *as* an argument, wrap it: `lambda: int`. |

`snapshot_test(matrix, tolerance=None, subdir=None)` returns the parametrized
test; assign it to a `test_*` name. `tolerance = {"rtol": ..., "atol": ...}`
applies to every numeric column of every frame in the matrix (default
`DEFAULT_TOLERANCE = {"rtol": 1e-9, "atol": 1e-12}`). Duplicated ids or
malformed rows raise `ValueError` at import, i.e. a collection error.

Several matrices may live in one module (`test_a = snapshot_test(A)`,
`test_b = snapshot_test(B, subdir="b")`); each gets its own folder.

### Sharing an object between rows

A value in `args` / `kwargs` that is **not** callable is passed as is, and the
*same* object goes to every row that lists it. So one `sqlite3.Connection` --
or any client, engine, file handle -- can serve the whole matrix: in the quick
start, `matrix(db)` works the same whether `db` is a path or an open
connection; the matrix does not care.

Declare it in the **test module**, not in the notebook that launches the run:
`generate` and `compare` start pytest in a subprocess (see
[Python API](#python-api)), and an object opened in the notebook does not
travel there. Two forms:

```python
# tests/test_pricing.py

# eager: opened at collection time -- also with --snapshot2, where nothing runs
import sqlite3
conn = sqlite3.connect("db2.db")
test_snapshot = snapshot_test(matrix(conn), subdir="pricing")

# lazy and shared: a cached callable -- opened by the first row, the same object after
from functools import lru_cache
get_conn = lru_cache(maxsize=None)(lambda: sqlite3.connect("db2.db"))
test_snapshot = snapshot_test(matrix(get_conn), subdir="pricing")
```

The lazy form is just the callable rule of the table above at work: every row
calls `get_conn()` at test time and `lru_cache` returns the connection opened
by the first one. Either form requires the functions in the matrix to accept a
connection; a function that does `sqlite3.connect(db)` itself must keep
receiving the path.

Things to know:

* rows run in order, in one process and one thread (no `check_same_thread`
  trouble unless `pytest-xdist` is used -- then each worker imports the module
  and opens its own connection). A row that writes, or leaves a transaction
  open, is seen by the rows after it; read-only queries are unaffected;
* nothing closes it: it dies with the pytest process
  (`atexit.register(conn.close)` if that matters);
* a failing `connect` is a **collection error** in the eager form -- no test
  runs -- and a recorded error per row in the lazy form (`error: OperationalError`
  in every YAML), which `--regen-all` writes without complaint.

## How the result is compared

Decided from the object the function returns -- nothing to declare in the row:

| Returned | Written as | Compared |
|---|---|---|
| `DataFrame`, `Series`, `ndarray` | `name.csv` (after `normalize_frame`) | numbers with the tolerance, text and dates exactly, same shape required |
| tuple / list of frames | `name.0.csv`, `name.1.csv`, ... | each part as above |
| `int`, `float`, numpy number | one-cell `name.csv` (column `value`) | with the tolerance |
| a flat list of numbers | `name.csv` with columns `i` (position) and `value` | with the tolerance, order kept |
| anything else: `str`, `bool`, `list`, `dict`, `datetime`, `None` ... | `name.yml` | as text; dates as ISO strings, numpy scalars as Python scalars, sets as sorted lists, NaN as `null` |
| an **exception** raised by the call (or by an argument lambda) | `name.yml` with `error: <type>` and `message: <str>` | as text -- the suite never aborts because a row raised |

### `normalize_frame`

What is written is the canonical form of the frame, so that two runs that
differ only in things that do not matter still match:

* an unnamed `RangeIndex` is dropped; any other index (named, dates,
  MultiIndex) becomes leading columns;
* column labels become `str`, `1001.0` -> `"1001"`, MultiIndex labels are
  joined with `|` (trailing empty levels dropped), duplicated labels get
  `__2`, `__3`, ...;
* non-numeric columns are converted with `to_numeric` when every value allows
  it, otherwise to the `string` dtype with **missing values as `""`** -- the
  CSV cannot tell `None` from `""` anyway, and `dataframe_regression` accepts a
  text column only when its first value is a `str`; `object` never reaches
  the CSV writer, which rejects it;
* **rows are sorted by all columns**, NaN last, and the index reset.

The same function is applied to a CSV read back from a snapshot, so comparing
two recordings is symmetric.

## Where the files go

```
<root>/<subdir>/<snapshot>/<group>__<name>[.N].csv|.yml
```

* `root`: `--snapshots-dir`, or `<folder of the test module>/snapshots`;
* `subdir`: the `subdir` argument of `snapshot_test`, or
  `<module stem>/<name the test was assigned to>` (`test_pricing/test_snapshot`).
  Deterministic, and two matrices never share a folder unless told to;
* `snapshot`: `--snapshot1` (`generate(..., name)`).

The "obtained" files of a comparison are written to pytest's temporary
directory (`pytest-datadir`), never into the snapshot folder.

## Command line

The module is a pytest plugin. Enable it with `-p fuchitools.snapshots` on the
command line, or once for a project in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
addopts = "-p fuchitools.snapshots --snapshot1 before"   # plain `pytest` then compares with "before"
```

| Option | Effect |
|---|---|
| `--snapshot1 NAME` | snapshot to compare with (or to write). **Without it every snapshot test is skipped.** |
| `--snapshot2 NAME` | compare the recording `snapshot1` with the recording `NAME`; nothing is executed. A row missing on either side fails. Cannot be combined with `--regen-all`. |
| `--snapshots-dir DIR` | root folder instead of `<module dir>/snapshots` |
| `--snapshot-clean` | with `--regen-all`: empty each snapshot folder before the first file is written into it, so files of rows that left the matrix disappear. Do not combine with `-k`. |
| `--regen-all`, `--force-regen` | `pytest-regressions`: write the expected files (`--regen-all` passes, `--force-regen` fails after writing) |

### Examples

From the project root, with the modules of the quick start:

```
# record snapshot "before" from one module  ->  tests/snapshots/pricing/before/
python -m pytest tests/record_pricing_before.py -p fuchitools.snapshots --snapshot1 before --regen-all --snapshot-clean

# run every matrix under tests/ and compare with "before"
python -m pytest tests -p fuchitools.snapshots --snapshot1 before

# record the new side, then compare the two recordings (nothing is executed)
python -m pytest tests/test_pricing.py -p fuchitools.snapshots --snapshot1 after --regen-all --snapshot-clean
python -m pytest tests/test_pricing.py -p fuchitools.snapshots --snapshot1 before --snapshot2 after

# only the "calc" rows, stop at the first failure (never --snapshot-clean together with -k)
python -m pytest tests -p fuchitools.snapshots --snapshot1 before -k calc -x

# snapshots outside the tests folder, e.g. a shared drive
python -m pytest tests -p fuchitools.snapshots --snapshot1 before --snapshots-dir \\server\share\snapshots

# with addopts = "-p fuchitools.snapshots --snapshot1 before" in pyproject.toml, plain pytest compares
python -m pytest tests
```

The Python wrappers build exactly these commands (and add `-p fuchitools.snapshots`
themselves): `generate("tests/record_pricing_before.py", "before")` is the
first one, `compare("tests", "before")` the second,
`compare("tests/test_pricing.py", "before", "after")` the fourth,
`compare("tests", "before", extra=["-k", "calc", "-x"])` the fifth and
`compare("tests", "before", snapshots_dir=r"\\server\share\snapshots")` the sixth.

The behaviour inherited from `pytest-regressions` that surprises people:
**without `--regen-all`, a missing expected file is created and the test fails**
with `File not found in data directory, created: ...`. The next run compares.
So running a comparison against a snapshot that does not exist yet records it
-- in red.

## Python API

```python
generate(test_module, name, snapshots_dir=None, env=None, python=None, extra=(), clean=True) -> bool
compare(test_module, snapshot1, snapshot2=None, snapshots_dir=None, env=None, python=None, extra=()) -> bool
remove(test_module, snapshot=None, subdir=None, snapshots_dir=None) -> list[Path]
```

`generate` and `compare` run `python -m pytest -p fuchitools.snapshots <test_module> ...`
in a **subprocess** and stream its output (notebooks see it too). `test_module`
is a file or a directory of `test_*.py`. `python` selects the interpreter (another
venv -- it needs `fuchitools[snapshots]` installed); `env` adds environment
variables for that run only; `extra` appends pytest options (`["-k", "calc"]`,
`["-x"]`). They return `True` when pytest exited with 0.

Why a subprocess: pytest caches imported test modules, so calling `pytest.main`
twice in one process with a different environment would not re-read the matrix.

`remove` deletes recorded folders and returns them: with `subdir`, below
`<root>/<subdir>`; for a test file, below `<root>/<module stem>` (the default
folders of its matrices); for a directory, everything below `<root>`. With
`snapshot`, only the folders of that name. **Tests are not files**: pytest
builds them from the matrix at collection time, so deleting a module (or its
`snapshot_test` line) is how tests are removed.

## Things to know before trusting a green run

* The **order of rows** is never checked (frames are sorted before writing).
  In exchange, queries without `ORDER BY` do not flake between databases.
* The CSV keeps **values, not dtypes**: `to_csv(float_format="%.17g")` writes
  `1.0` and `1` both as `1`, `read_csv` reads both back as `int64`, and the
  plugin accepts any pair of numeric dtypes. A float column that became an
  int column with the same values passes; `1.1` against `1` fails. A text
  column that became numeric fails only if it was not entirely numeric text
  (`to_numeric` is tried on text first). Likewise a text `NULL` that becomes
  `""` (or the reverse) is invisible.
* Numbers in YAML are compared as text; that is why a bare number, or a flat
  list of numbers, is written to CSV instead.
* Argument lambdas are evaluated **every time they are used**, once per row;
  cache them in the matrix (`functools.lru_cache`) if that is too slow.
* A shared connection or handle (see
  [Sharing an object between rows](#sharing-an-object-between-rows)) is the
  opposite case: the **same object in every row**, so state left by one row --
  an open transaction, a temporary table -- reaches the next.
* Renaming the test or the module changes the default `subdir`: the old folder
  stays behind (`remove` with the old name, or fix `subdir`).
* Plain `pytest --regen-all` does not delete files of rows that left the
  matrix; `generate()` does (`clean=True` -> `--snapshot-clean`).
* Rows whose function reaches a database or a file that is missing do not
  crash: they record an error and **fail the comparison** against a snapshot
  that has data.

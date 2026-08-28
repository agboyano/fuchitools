# fuchitools

General purpose Python utilities: dates, DataFrames in and out of databases,
browser scraping, Jupyter kernels, snapshot tests generated from a matrix of
calls. Written for day-to-day data work, so the defaults lean towards European
date order, Spanish web forms and DuckDB.

## Modules

| Module | What it is for | Reference |
|---|---|---|
| `datetimes` | Turn anything date-shaped into `date` / `datetime` | [documentation/datetimes.md](documentation/datetimes.md) |
| `duckdb` | Write a DataFrame into a DuckDB table, creating or upserting | [documentation/duckdb.md](documentation/duckdb.md) |
| `sqlite` | SQL and DataFrames over sqlite3, plus a key/value table | [documentation/sqlite.md](documentation/sqlite.md) |
| `pandas` | Read an Excel sheet, outer-join a list of DataFrames | [documentation/pandas.md](documentation/pandas.md) |
| `selenium` | Configured Firefox/Chrome drivers and form helpers | [documentation/selenium.md](documentation/selenium.md) |
| `jupyter` | Find, inspect, drive and stop local Jupyter kernels | [documentation/jupyter.md](documentation/jupyter.md) |
| `snapshots` | Record what a matrix of calls returns, then check it again elsewhere (pytest plugin over `pytest-regressions`) | [documentation/snapshots.md](documentation/snapshots.md) |
| `misc` | A console logger in one line | [documentation/misc.md](documentation/misc.md) |

Each page in [documentation/](documentation/) is the how-to for one module.
The design record for `jupyter` — why the obvious approaches do not work, what
was measured and what had to be worked around, none of it recoverable from the
code — lives separately in [memory/jupyter.md](memory/jupyter.md).

## Importing

`__init__.py` imports only `datetimes`, `sqlite` and `pandas`. The rest are
imported explicitly, on purpose: `duckdb`, `selenium`, `jupyter` and
`snapshots` either carry heavy dependencies or are only wanted occasionally.

```python
from fuchitools.datetimes import to_date        # always available
from fuchitools import jupyter                  # explicit
from fuchitools.snapshots import snapshot_test  # explicit; also a pytest plugin: -p fuchitools.snapshots
```

`fuchitools.pandas` and `fuchitools.duckdb` shadow the names of the libraries
they relate to. Inside the package the imports are absolute, so `import
duckdb` still reaches the real one, but import them qualified from outside to
avoid confusing yourself.

## Installation and dependencies

Declared in [pyproject.toml](pyproject.toml), with lower bounds set below the
installed versions so installing does not force upgrades. The base install
needs only `pandas`; the heavier modules are extras:

| Extra | Brings | Needed by |
|---|---|---|
| `excel` | `openpyxl` | `fuchitools.pandas.load_excel` |
| `selenium` | `selenium`, `undetected-chromedriver` | `fuchitools.selenium` |
| `jupyter` | `psutil`, `jupyter-client`, `jupyter-core` | `fuchitools.jupyter` |
| `snapshots` | `pytest`, `pytest-regressions`, `pyyaml` | `fuchitools.snapshots` |
| `all` | the four above | |
| `test` | `pytest`, `duckdb`, plus `all` | running the test suite |

```
pip install -e ".[all,test]"
```

Importing `fuchitools.selenium`, `fuchitools.jupyter` or `fuchitools.snapshots`
without their extra raises an `ImportError` naming the extra to install.
`fuchitools.duckdb` takes the connection as an argument and never imports
duckdb itself, which is why duckdb is only a test dependency.

The package is installed editable, via a PEP 660 import hook. Static analysers
cannot follow that: Pylance reports the imports as unresolved even though they
work at runtime. The workspace works around it with
`python.analysis.extraPaths` in `workspace.code-workspace`.

## Tests

```
python -m pytest tests -q
```

361 tests, in [tests/](tests/), one file per module. Nothing external is
touched: `test_sqlite.py` and `test_duckdb_update_table.py` use temporary or
in-memory databases, `test_pandas.py` builds its workbooks in memory,
`test_selenium.py` starts no browser, `test_jupyter.py` is entirely
synthetic — no kernel is started, pinged, stopped or inspected — and
`test_snapshots.py` runs its matrices of dummy functions through `pytester`
in temporary directories (the `generate`/`compare` tests start a pytest
subprocess with the current interpreter, which is where most of its ~35 s go),
so the suite is safe to run with live notebooks open.

## A note on these documents

They describe what the code does, including the parts that will surprise you:
arguments that are accepted and ignored, exceptions swallowed, a helper that
silently picks the last sheet. Those notes are the reason to read a page
before using a module, so please keep them when editing.

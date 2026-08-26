# fuchitools

General purpose Python utilities: dates, DataFrames in and out of databases,
browser scraping, Jupyter kernels. Written for the fund architecture work, so
the defaults lean towards European date order, Spanish web forms and DuckDB.

## Modules

| Module | What it is for | Reference |
|---|---|---|
| `datetimes` | Turn anything date-shaped into `date` / `datetime` | [datetimes.md](datetimes.md) |
| `duckdb` | Write a DataFrame into a DuckDB table, creating or upserting | [duckdb.md](duckdb.md) |
| `sqlite` | SQL and DataFrames over sqlite3, plus a key/value table | [sqlite.md](sqlite.md) |
| `pandas` | Read an Excel sheet, outer-join a list of DataFrames | [pandas.md](pandas.md) |
| `selenium` | Configured Firefox/Chrome drivers and form helpers | [selenium.md](selenium.md) |
| `jupyter` | Find, inspect, drive and stop local Jupyter kernels | [jupyter.md](jupyter.md) |
| `misc` | A console logger in one line | [misc.md](misc.md) |

`jupyter.md` is longer than the others: as well as the API it records why the
obvious approaches do not work and what had to be worked around, because none
of that is recoverable from the code.

## Importing

`__init__.py` imports only `datetimes`, `sqlite` and `pandas`. The rest are
imported explicitly, on purpose: `duckdb`, `selenium` and `jupyter` either
carry heavy dependencies or are only wanted occasionally.

```python
from fuchitools.datetimes import to_date        # always available
from fuchitools import jupyter                  # explicit
```

`fuchitools.pandas` and `fuchitools.duckdb` shadow the names of the libraries
they relate to. Inside the package the imports are absolute, so `import
duckdb` still reaches the real one, but import them qualified from outside to
avoid confusing yourself.

## Installation and dependencies

Declared in `pyproject.toml`, with lower bounds set below the installed
versions so installing does not force upgrades:

`pandas`, `selenium`, `undetected-chromedriver`, `psutil`, `jupyter-client`,
`jupyter-core`. The `test` extra adds `pytest` and `duckdb` — `fuchitools.duckdb`
takes the connection as an argument and never imports duckdb itself.

The package is installed editable, via a PEP 660 import hook. Static analysers
cannot follow that: Pylance reports the imports as unresolved even though they
work at runtime. The workspace works around it with
`python.analysis.extraPaths` in `desarrollo-workspace.code-workspace`.

## Tests

```
python -m pytest tests -q
```

261 tests. `test_sqlite.py` uses only temporary and in-memory databases.
`test_jupyter.py` is entirely synthetic — no kernel is started,
pinged, stopped or inspected — so it is safe to run with live notebooks open.

## A note on these documents

They describe what the code does, including the parts that will surprise you:
arguments that are accepted and ignored, exceptions swallowed, a helper that
silently picks the last sheet. Those notes are the reason to read a page
before using a module, so please keep them when editing.

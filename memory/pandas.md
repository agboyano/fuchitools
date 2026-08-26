# `fuchitools.pandas`

Two small helpers. Note the module shadows the name `pandas` inside the
package, so import it qualified — `from fuchitools import pandas as fpd` — or
import the functions directly.

## `load_excel(excel_filename, sheet_name=None)`

Reads a sheet and drops the trailing rubbish: every row whose **first column**
is NaN is discarded. That is aimed at the usual export, where the data ends but
the sheet carries on with blank rows, a total, or a note.

```python
from fuchitools.pandas import load_excel

df = load_excel("posiciones.xlsx", sheet_name="cartera")
```

Two things worth knowing before relying on it:

- **With `sheet_name=None` it does not read "the sheet", it reads the last
  one.** pandas returns a dict of every sheet, and the code takes
  `popitem()`, which in Python 3.7+ pops the last inserted item. On a
  single-sheet workbook that is the right answer; on a multi-sheet workbook it
  silently picks one. Name the sheet.
- **The filter is positional, not by name.** If the first column happens to be
  optional in your data, valid rows disappear.

## `join_dataframes(lis, on=None)`

Outer-joins a list of DataFrames left to right, dropping columns that would
otherwise collide.

```python
from fuchitools.pandas import join_dataframes

merged = join_dataframes([prices, statics, weights])          # on the index
merged = join_dataframes([prices, statics], on="ticker")      # on a column
```

It reduces with `DataFrame.join(..., how="outer", on=on)` and after each step
keeps only the first occurrence of each column name. That last part is the
behaviour to be careful with: **when two frames bring the same column, the
left one wins silently** — no suffixes, no warning. If both sides carry a
`nombre` and they disagree, you will not be told.

For anything where the collision matters, use `pd.merge` with explicit
`suffixes` instead.

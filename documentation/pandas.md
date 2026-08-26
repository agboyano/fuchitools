# `fuchitools.pandas`

Two small helpers. Note the module shadows the name `pandas` inside the
package, so import it qualified — `from fuchitools import pandas as fpd` — or
import the functions directly.

`load_excel` needs an Excel engine: `pip install fuchitools[excel]` (openpyxl).

## `load_excel(excel_filename, sheet_name=0, drop_na_first_col=True, **kwargs)`

Reads **one** sheet and drops the trailing rubbish: every row whose **first
column** is NaN is discarded. That is aimed at the usual export, where the data
ends but the sheet carries on with blank rows, a total, or a note.

```python
from fuchitools.pandas import load_excel

df = load_excel("posiciones.xlsx")                       # first sheet
df = load_excel("posiciones.xlsx", sheet_name="cartera") # by name
raw = load_excel("posiciones.xlsx", header=None, drop_na_first_col=False)
```

Things worth knowing before relying on it:

- **The default is the first sheet.** `sheet_name=None` is treated the same
  way. (Before, `None` read every sheet and silently returned the *last* one;
  on a single-sheet workbook the two agree, which is the case for every
  current caller.) A list of sheets is refused with `ValueError` — one sheet
  per call.
- **The filter is positional, not by name.** If the first column happens to
  be optional in your data, valid rows disappear. Pass
  `drop_na_first_col=False` to keep everything.
- The original row labels are kept, not reset, so `df.index` tells you the
  Excel row a value came from (offset by the header).
- Extra keyword arguments go straight to `pandas.read_excel` (`header`,
  `dtype`, `usecols`, ...).

## `join_dataframes(lis, on=None, overlap="raise")`

Outer-joins a list of DataFrames left to right.

```python
from fuchitools.pandas import join_dataframes

merged = join_dataframes([prices, statics, weights])          # on the index
merged = join_dataframes([prices, statics], on="ticker")      # on a column
merged = join_dataframes([prices, statics], overlap="left")   # prices' columns win
```

It reduces with `DataFrame.join(..., how="outer", on=on)`. When two frames
carry a column with the same name, `overlap` decides:

- `"raise"` (default): `ValueError` naming the columns. This is also what
  happened before, only with pandas' own `columns overlap but no suffix
  specified` message — the old documentation's claim that "the left one wins
  silently" was wrong; that code path never ran.
- `"left"`: keep the left frame's version, drop it from the right frame.
- `"right"`: the converse (the `on` column, if any, stays on the left side).

There is deliberately no silent default: if both sides carry a `nombre` and
they disagree, you have to say which one wins. For anything more elaborate
(suffixes, inner joins) use `pd.merge` directly.

An empty list raises `ValueError`; a single frame is returned as a copy.

## Tests

`tests/test_pandas.py`, against workbooks built in memory with openpyxl.

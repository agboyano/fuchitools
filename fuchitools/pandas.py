"""Two small pandas helpers: read one Excel sheet and drop the trailing
rubbish, and outer-join a list of DataFrames.

The module shadows the name ``pandas`` inside the package; import it qualified
(``from fuchitools import pandas as fpd``) or import the functions directly.
"""

from functools import reduce

import pandas as pd

__all__ = ["load_excel", "join_dataframes"]

_OVERLAP_MODES = ("raise", "left", "right")


def load_excel(excel_filename, sheet_name=0, drop_na_first_col=True, **kwargs) -> pd.DataFrame:
    """Read one sheet of a workbook and drop the rows whose first column is empty.

    The filter is aimed at the usual export, where the data ends but the sheet
    carries on with blank rows, a total or a note. It is **positional** — the
    first column, whatever it is called — so if that column is optional in
    your data, disable it.

    Parameters
    ----------
    excel_filename : str | path | file-like
        Anything ``pandas.read_excel`` accepts.
    sheet_name : int | str, default 0
        Sheet index or name. ``None`` is treated as ``0`` (the first sheet);
        this used to mean "the last sheet", which only coincided on
        single-sheet workbooks.
    drop_na_first_col : bool, default True
        Drop rows whose first column is NaN.
    **kwargs
        Passed through to ``pandas.read_excel`` (``header``, ``dtype``,
        ``usecols``, ...).

    Returns
    -------
    pandas.DataFrame
        A new frame; the original row labels are kept (not reset).

    Raises
    ------
    ValueError
        If ``sheet_name`` selects several sheets, or the sheet has no columns.

    Examples
    --------
    >>> df = load_excel("ventas.xlsx", sheet_name="datos")
    >>> raw = load_excel("ventas.xlsx", drop_na_first_col=False, header=None)
    """
    if sheet_name is None:
        sheet_name = 0
    df = pd.read_excel(excel_filename, sheet_name=sheet_name, **kwargs)
    if isinstance(df, dict):
        raise ValueError("load_excel reads one sheet at a time; pass a single sheet name or index")
    if df.shape[1] == 0:
        raise ValueError(f"{excel_filename!r}: sheet {sheet_name!r} has no columns")
    if drop_na_first_col:
        df = df.loc[df.iloc[:, 0].notna()]
    return df.copy()


def join_dataframes(lis, on=None, overlap="raise") -> pd.DataFrame:
    """Outer-join a list of DataFrames left to right.

    Parameters
    ----------
    lis : sequence of pandas.DataFrame
    on : str | list of str, optional
        As in ``DataFrame.join``: join each left frame's column(s) against the
        next frame's index. ``None`` joins index to index.
    overlap : {'raise', 'left', 'right'}, default 'raise'
        What to do when two frames carry a column with the same name.
        ``'raise'`` stops with a ``ValueError`` naming the columns; ``'left'``
        keeps the left frame's version and drops the right one's; ``'right'``
        the converse. There is no silent default: if both sides carry a
        ``nombre`` and they disagree, you must say which one wins.

    Returns
    -------
    pandas.DataFrame

    Raises
    ------
    ValueError
        Empty ``lis``, unknown ``overlap``, or overlapping columns with
        ``overlap='raise'``.

    Examples
    --------
    >>> merged = join_dataframes([prices, statics, weights])          # on the index
    >>> merged = join_dataframes([prices, statics], on="ticker")      # on a column
    >>> merged = join_dataframes([a, b], overlap="left")              # a's columns win
    """
    lis = list(lis)
    if not lis:
        raise ValueError("join_dataframes needs at least one DataFrame")
    if overlap not in _OVERLAP_MODES:
        raise ValueError(f"overlap must be one of {_OVERLAP_MODES}, got {overlap!r}")
    if len(lis) == 1:
        return lis[0].copy()

    on_cols = set() if on is None else set([on] if isinstance(on, str) else on)

    def join_two(x, y):
        common = [c for c in y.columns if c in x.columns]
        if common:
            if overlap == "raise":
                raise ValueError(
                    f"columns present in both frames: {common}; pass "
                    "overlap='left' or overlap='right' to choose, or rename them"
                )
            if overlap == "left":
                y = y.drop(columns=common)
            else:
                # the join column(s) must stay on the left side
                x = x.drop(columns=[c for c in common if c not in on_cols])
                y = y.drop(columns=[c for c in common if c in on_cols])
        return x.join(y, how="outer", on=on)

    return reduce(join_two, lis)

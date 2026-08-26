"""Tests for fuchitools.pandas. Workbooks are built in memory (openpyxl)."""

import io

import pandas as pd
import pytest

from fuchitools.pandas import join_dataframes, load_excel

pytest.importorskip("openpyxl")


@pytest.fixture
def workbook():
    """Two sheets: 'first' (with a NaN in the first column) and 'second'."""
    def make():
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            pd.DataFrame({"a": [1, None, 3], "b": ["x", "y", "z"]}).to_excel(
                writer, sheet_name="first", index=False)
            pd.DataFrame({"c": [9]}).to_excel(writer, sheet_name="second", index=False)
        buf.seek(0)
        return buf
    return make


# --- load_excel ---------------------------------------------------------

def test_load_excel_default_is_first_sheet(workbook):
    df = load_excel(workbook())
    assert list(df.columns) == ["a", "b"]


def test_load_excel_none_means_first_sheet(workbook):
    assert list(load_excel(workbook(), sheet_name=None).columns) == ["a", "b"]


def test_load_excel_by_name_and_index(workbook):
    assert list(load_excel(workbook(), sheet_name="second").columns) == ["c"]
    assert list(load_excel(workbook(), sheet_name=1).columns) == ["c"]


def test_load_excel_drops_rows_with_empty_first_column(workbook):
    df = load_excel(workbook())
    assert df["a"].tolist() == [1, 3]
    assert df["b"].tolist() == ["x", "z"]
    assert df.index.tolist() == [0, 2]                      # labels kept, not reset


def test_load_excel_filter_can_be_disabled(workbook):
    df = load_excel(workbook(), drop_na_first_col=False)
    assert len(df) == 3 and pd.isna(df["a"].iloc[1])


def test_load_excel_kwargs_passthrough(workbook):
    df = load_excel(workbook(), usecols=["b"], drop_na_first_col=False)
    assert list(df.columns) == ["b"]
    raw = load_excel(workbook(), header=None, drop_na_first_col=False)
    assert raw.iloc[0].tolist() == ["a", "b"]                # header row is data now


def test_load_excel_rejects_multiple_sheets(workbook):
    with pytest.raises(ValueError):
        load_excel(workbook(), sheet_name=["first", "second"])


def test_load_excel_returns_a_copy(workbook):
    df = load_excel(workbook())
    df["a"] = 0                                             # must not warn or fail
    assert df["a"].tolist() == [0, 0]


# --- join_dataframes ----------------------------------------------------

@pytest.fixture
def frames():
    a = pd.DataFrame({"k": [1, 2], "v": [10, 20]}).set_index("k")
    b = pd.DataFrame({"k": [2, 3], "w": [200, 300]}).set_index("k")
    c = pd.DataFrame({"k": [1, 3], "v": [-1, -3]}).set_index("k")   # 'v' overlaps with a
    return a, b, c


def test_join_disjoint_columns_outer(frames):
    a, b, _ = frames
    out = join_dataframes([a, b])
    assert out.index.tolist() == [1, 2, 3]
    assert out["v"].tolist()[:2] == [10, 20] and pd.isna(out["v"].iloc[2])
    assert out["w"].tolist()[1:] == [200, 300] and pd.isna(out["w"].iloc[0])


def test_join_on_column(frames):
    left = pd.DataFrame({"k": [1, 2], "v": [10, 20]})
    right = pd.DataFrame({"z": [5, 6]}, index=[1, 2])
    out = join_dataframes([left, right], on="k")
    assert out["z"].tolist() == [5, 6]


def test_join_overlap_raises_with_column_names(frames):
    a, _, c = frames
    with pytest.raises(ValueError, match=r"\['v'\]"):
        join_dataframes([a, c])


def test_join_overlap_left_and_right(frames):
    a, _, c = frames
    left = join_dataframes([a, c], overlap="left")
    assert left.loc[1, "v"] == 10 and left.loc[2, "v"] == 20 and pd.isna(left.loc[3, "v"])
    right = join_dataframes([a, c], overlap="right")
    assert right.loc[1, "v"] == -1 and pd.isna(right.loc[2, "v"]) and right.loc[3, "v"] == -3


def test_join_overlap_right_keeps_on_column():
    left = pd.DataFrame({"k": [1, 2], "v": [10, 20]})
    right = pd.DataFrame({"k": [1, 2], "v": [-1, -2]}, index=[1, 2])
    out = join_dataframes([left, right], on="k", overlap="right")
    assert out["k"].tolist() == [1, 2] and out["v"].tolist() == [-1, -2]


def test_join_three_frames_reduces_left_to_right(frames):
    a, b, c = frames
    out = join_dataframes([a, b, c], overlap="left")
    assert list(out.columns) == ["v", "w"]
    assert out.index.tolist() == [1, 2, 3]


def test_join_edge_cases(frames):
    a, *_ = frames
    with pytest.raises(ValueError):
        join_dataframes([])
    with pytest.raises(ValueError):
        join_dataframes([a, a], overlap="middle")
    only = join_dataframes([a])
    assert only.equals(a) and only is not a

"""Tests for fuchitools.snapshots.

Hermetic: the matrices call dummy functions defined in a temporary test module
that `pytester` writes and runs in a fresh pytest process; every snapshot goes
to that temporary directory. `generate`/`compare` start a real subprocess with
the current interpreter (a few seconds each), nothing outside `tmp_path` is
touched. Skipped as a whole when pytest-regressions is not installed.
"""

import datetime
import sys
import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pytest_regressions")

from fuchitools import snapshots  # noqa: E402
from fuchitools.snapshots import (  # noqa: E402
    CallError,
    normalize_frame,
    read_parts,
    row_id,
    run_row,
    snapshot_test,
    to_parts,
    to_yaml_safe,
)

pytest_plugins = "pytester"

PLUGIN_ARGS = ["-p", "fuchitools.snapshots", "-p", "no:cacheprovider", "-q"]

# a test module with a matrix of dummy functions; CALLS counts executions in a
# side file so a test can prove that --snapshot2 runs nothing
MODULE = textwrap.dedent(
    """
    import datetime, os
    from pathlib import Path
    import numpy as np
    import pandas as pd
    from fuchitools.snapshots import snapshot_test

    COUNTER = Path(__file__).with_name("calls.txt")
    DB = os.environ.get("SNAP_DB", "db1")

    def count():
        COUNTER.write_text(str(int(COUNTER.read_text()) + 1) if COUNTER.exists() else "1")

    def frame(n):
        count()
        return pd.DataFrame({"b": [3.0, 1.0, 2.0][:n], "a": ["z", "x", "y"][:n]}).set_index("a")

    def pair(df):
        return df, df.assign(c=1)

    def boom(x):
        raise KeyError("no such key")

    def dates():
        return [datetime.date(2026, 6, 30), pd.Timestamp("2026-06-29")]

    def which_db():
        return DB

    MATRIX = [
        ("frames", "three", frame, [3]),
        ("frames", "pair", pair, [lambda: frame(2)]),
        ("scalars", "pi", lambda: 3.14159),
        ("scalars", "dates", dates),
        ("scalars", "db", which_db),
        ("errors", "boom", boom, [lambda: 1]),
    ]
    test_snapshot = snapshot_test(MATRIX)
    """
)


@pytest.fixture
def module(pytester):
    """Writes the dummy test module and returns its path."""
    return pytester.makepyfile(test_dummy=MODULE)


def snapshot_dir(module: Path, name: str) -> Path:
    return module.parent / "snapshots" / "test_dummy" / "test_snapshot" / name


def calls(module: Path) -> int:
    counter = module.with_name("calls.txt")
    return int(counter.read_text()) if counter.exists() else 0


# ----------------------------------------------------------------------------- pure functions


def test_row_id_sanitises_both_parts():
    assert row_id("group", "name") == "group__name"
    assert row_id("a b", "x.y/z") == "a_b__x_y_z"


def test_run_row_evaluates_callables_and_captures_exceptions():
    assert run_row(lambda a, b=0: a + b, [lambda: 2], {"b": lambda: 3}) == 5
    assert run_row(lambda f: f(2), [lambda: (lambda x: x * 10)]) == 20   # a function passed as argument, wrapped
    err = run_row(lambda: 1 / 0)
    assert isinstance(err, CallError) and err == {"error": "ZeroDivisionError", "message": "division by zero"}
    err = run_row(lambda x: x, [lambda: [][1]])                          # a failing dependency is a result too
    assert err["error"] == "IndexError"


def test_normalize_frame_index_labels_duplicates_and_sorting():
    df = pd.DataFrame([[2, "b", 1.5], [1, "a", 2.5]], columns=pd.MultiIndex.from_tuples([("x", 1001.0), ("x", 1002.0), ("y", "")]))
    df.index = pd.Index([10, 20], name="k")
    out = normalize_frame(df)
    assert list(out.columns) == ["k", "x|1001", "x|1002", "y"]   # trailing empty levels are dropped
    assert out["k"].tolist() == [10, 20] and out["x|1001"].tolist() == [2, 1]   # sorted by k first

    dup = pd.DataFrame([[1, 2, 3]], columns=["c", "c", "d"])
    assert list(normalize_frame(dup).columns) == ["c", "c__2", "d"]

    unsorted = pd.DataFrame({"a": [2, 1, 2], "b": [1, 9, 0]})
    assert normalize_frame(unsorted).values.tolist() == [[1, 9], [2, 0], [2, 1]]
    assert isinstance(normalize_frame(unsorted).index, pd.RangeIndex)


def test_normalize_frame_object_columns():
    df = pd.DataFrame({"code": ["1001", "1002"], "mixed": ["  ", 2.5], "text": [None, "a"], "lists": [[1], [2]]})
    out = normalize_frame(df)
    assert out["code"].dtype.kind == "i"                    # numeric text becomes numeric
    assert isinstance(out["mixed"].dtype, pd.StringDtype)  # anything else becomes string
    assert isinstance(out["text"].dtype, pd.StringDtype) and out["text"].tolist() == ["", "a"]   # missing -> ""
    assert isinstance(out["lists"].dtype, pd.StringDtype) and out["lists"].tolist() == ["[1]", "[2]"]
    assert not any(d == object for d in out.dtypes)         # nothing is left as plain object
    assert all(type(out[c].iloc[0]) is str for c in ["mixed", "text", "lists"])   # what dataframe_regression checks

    empty = normalize_frame(pd.DataFrame({"t": pd.Series([], dtype=object), "n": pd.Series([], dtype=float)}))
    assert len(empty) == 0 and empty["t"].dtype.kind in "iuf"   # numeric, whatever to_numeric/astype picked


def test_normalize_frame_is_idempotent_through_csv(tmp_path):
    df = pd.DataFrame({"n": [2.5, 1.0, np.nan], "s": ["x", None, "y"], "d": pd.to_datetime(["2026-06-30", "2026-06-29", "2026-06-28"])})
    first = normalize_frame(df)
    path = tmp_path / "f.csv"
    first.to_csv(path, float_format="%.17g")
    again = normalize_frame(pd.read_csv(path, index_col=0).reset_index(drop=True))
    assert list(again.columns) == list(first.columns)
    assert again["n"].tolist()[:2] == first["n"].tolist()[:2]
    assert again["s"].tolist() == first["s"].tolist()
    assert normalize_frame(first).equals(first)


def test_to_parts_by_result_type():
    df = pd.DataFrame({"a": [1]})
    assert [s for s, _ in to_parts(df)] == [""] and isinstance(to_parts(df)[0][1], pd.DataFrame)
    assert to_parts(pd.Series([1, 2], name="v"))[0][1].columns.tolist() == ["v"]
    assert to_parts(np.array([1, 2]))[0][1].shape == (2, 1)
    assert [s for s, _ in to_parts((df, df, df))] == [".0", ".1", ".2"]
    assert to_parts(2.5)[0][1]["value"].tolist() == [2.5]                    # numbers go to CSV (tolerance)
    numbers = to_parts([3, 1, 2.5])[0][1]
    assert numbers.columns.tolist() == ["i", "value"] and numbers["value"].tolist() == [3, 1, 2.5]   # order kept
    assert to_parts(np.float64(1.5))[0][1]["value"].tolist() == [1.5]
    assert to_parts("x") == [("", {"value": "x"})]
    assert to_parts(None) == [("", {"value": None})]
    assert to_parts(True) == [("", {"value": True})]                         # bool is not a number here
    assert to_parts(CallError(KeyError("k"))) == [("", {"error": "KeyError", "message": "'k'"})]


def test_to_yaml_safe_conversions():
    out = to_yaml_safe({
        "d": datetime.date(2026, 6, 30), "ts": pd.Timestamp("2026-06-30 12:00"), "np": np.int64(3),
        "nan": float("nan"), "set": {3, 1, 2}, "arr": np.array([1.5]), (1, 2): "tuple key",
        "series": pd.Series([1], index=["a"]), "dt64": np.datetime64("2026-06-30"),
    })
    assert out == {
        "d": "2026-06-30", "ts": "2026-06-30T12:00:00", "np": 3, "nan": None, "set": [1, 2, 3],
        "arr": [1.5], "(1, 2)": "tuple key", "series": {"a": 1}, "dt64": "2026-06-30T00:00:00",
    }


def test_snapshot_test_validates_rows():
    with pytest.raises(ValueError, match="duplicated"):
        snapshot_test([("g", "n", len, [[]]), ("g", "n", len, [[1]])])
    with pytest.raises(ValueError, match="not callable"):
        snapshot_test([("g", "n", 3)])
    with pytest.raises(ValueError, match="args must be"):
        snapshot_test([("g", "n", len, "abc")])
    with pytest.raises(ValueError, match="3 <= len|got 2 items"):
        snapshot_test([("g", "n")])
    test = snapshot_test([("g", "n", len)], subdir="x")
    assert test.snapshot_subdir == "x"


# ----------------------------------------------------------------------------- the plugin, end to end


def test_record_then_compare(pytester, module):
    result = pytester.runpytest(*PLUGIN_ARGS, "--snapshot1", "s1", "--regen-all")
    result.assert_outcomes(passed=6)
    folder = snapshot_dir(module, "s1")
    names = sorted(p.name for p in folder.iterdir())
    assert names == [
        "errors__boom.yml", "frames__pair.0.csv", "frames__pair.1.csv", "frames__three.csv",
        "scalars__dates.yml", "scalars__db.yml", "scalars__pi.csv",
    ]
    assert (folder / "errors__boom.yml").read_text() == "error: KeyError\nmessage: '''no such key'''\n"
    assert (folder / "scalars__dates.yml").read_text() == "value:\n- '2026-06-30'\n- '2026-06-29T00:00:00'\n"
    assert (folder / "frames__three.csv").read_text().splitlines() == [",a,b", "0,x,1", "1,y,2", "2,z,3"]

    result = pytester.runpytest(*PLUGIN_ARGS, "--snapshot1", "s1")
    result.assert_outcomes(passed=6)
    assert not list(folder.glob("*.obtained.*"))           # obtained files never land in the snapshot


def test_difference_is_reported_by_the_plugin(pytester, module):
    pytester.runpytest(*PLUGIN_ARGS, "--snapshot1", "s1", "--regen-all").assert_outcomes(passed=6)
    csv = snapshot_dir(module, "s1") / "frames__three.csv"
    csv.write_text(csv.read_text().replace("0,x,1\n", "0,x,1.5\n"))
    result = pytester.runpytest(*PLUGIN_ARGS, "--snapshot1", "s1")
    result.assert_outcomes(passed=5, failed=1)
    result.stdout.fnmatch_lines(["*test_snapshot?frames__three?*", "*obtained_b*expected_b*diff*"])


def test_missing_expected_file_is_created_and_fails(pytester, module):
    result = pytester.runpytest(*PLUGIN_ARGS, "--snapshot1", "new")
    result.assert_outcomes(failed=6)
    result.stdout.fnmatch_lines(["*File not found in data directory, created*"])
    assert (snapshot_dir(module, "new") / "frames__three.csv").is_file()
    assert (snapshot_dir(module, "new") / "frames__pair.1.csv").is_file()   # every part is created in one go
    pytester.runpytest(*PLUGIN_ARGS, "--snapshot1", "new").assert_outcomes(passed=6)


def test_skipped_without_snapshot1(pytester, module):
    pytester.runpytest(*PLUGIN_ARGS).assert_outcomes(skipped=6)
    assert not (module.parent / "snapshots").exists()


def test_snapshot2_compares_recordings_without_running(pytester, module, monkeypatch):
    pytester.runpytest(*PLUGIN_ARGS, "--snapshot1", "s1", "--regen-all").assert_outcomes(passed=6)
    monkeypatch.setenv("SNAP_DB", "db2")
    pytester.runpytest(*PLUGIN_ARGS, "--snapshot1", "s2", "--regen-all").assert_outcomes(passed=6)
    before = calls(module)
    assert before == 4                                       # frame() twice per recording

    result = pytester.runpytest(*PLUGIN_ARGS, "--snapshot1", "s1", "--snapshot2", "s2")
    result.assert_outcomes(passed=5, failed=1)               # only scalars__db differs: db1 vs db2
    result.stdout.fnmatch_lines(["*scalars__db*"])
    assert calls(module) == before                           # nothing was executed

    result = pytester.runpytest(*PLUGIN_ARGS, "--snapshot1", "s1", "--snapshot2", "s2", "--regen-all")
    result.assert_outcomes(failed=6)
    result.stdout.fnmatch_lines(["*cannot be combined*"])

    (snapshot_dir(module, "s2") / "scalars__pi.csv").unlink()
    (snapshot_dir(module, "s1") / "frames__three.csv").unlink()
    result = pytester.runpytest(*PLUGIN_ARGS, "--snapshot1", "s1", "--snapshot2", "s2", "-k", "pi or three")
    result.assert_outcomes(failed=2)
    result.stdout.fnmatch_lines(["*not recorded in snapshot 's1'*", "*nothing recorded in snapshot 's2'*"])
    assert not (snapshot_dir(module, "s1") / "frames__three.csv").exists()   # snapshot2 mode never writes


def test_two_matrices_get_their_own_folders(pytester):
    pytester.makepyfile(test_two=textwrap.dedent(
        """
        from fuchitools.snapshots import snapshot_test
        M = [("g", "n", lambda: 1)]
        test_a = snapshot_test(M)
        test_b = snapshot_test(M)
        test_c = snapshot_test(M, subdir="fixed")
        """
    ))
    pytester.runpytest(*PLUGIN_ARGS, "--snapshot1", "s", "--regen-all").assert_outcomes(passed=3)
    root = pytester.path / "snapshots"
    assert (root / "test_two" / "test_a" / "s" / "g__n.csv").is_file()
    assert (root / "test_two" / "test_b" / "s" / "g__n.csv").is_file()
    assert (root / "fixed" / "s" / "g__n.csv").is_file()


def test_snapshots_dir_option(pytester, module, tmp_path):
    pytester.runpytest(*PLUGIN_ARGS, "--snapshot1", "s1", "--regen-all", "--snapshots-dir", str(tmp_path / "elsewhere")).assert_outcomes(passed=6)
    assert (tmp_path / "elsewhere" / "test_dummy" / "test_snapshot" / "s1" / "scalars__pi.csv").is_file()
    assert not (module.parent / "snapshots").exists()


def test_duplicated_ids_are_a_collection_error(pytester):
    pytester.makepyfile(test_dup=textwrap.dedent(
        """
        from fuchitools.snapshots import snapshot_test
        test_x = snapshot_test([("g", "n", lambda: 1), ("g", "n", lambda: 2)])
        """
    ))
    result = pytester.runpytest(*PLUGIN_ARGS, "--snapshot1", "s")
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*duplicated matrix ids*g__n*"])


def test_snapshot_clean_drops_files_of_removed_rows(pytester, module):
    pytester.runpytest(*PLUGIN_ARGS, "--snapshot1", "s1", "--regen-all").assert_outcomes(passed=6)
    folder = snapshot_dir(module, "s1")
    assert (folder / "scalars__pi.csv").is_file()
    module.write_text(module.read_text().replace('("scalars", "pi", lambda: 3.14159),\n', ""))
    pytester.runpytest(*PLUGIN_ARGS, "--snapshot1", "s1", "--regen-all").assert_outcomes(passed=5)
    assert (folder / "scalars__pi.csv").is_file()            # plain --regen-all leaves it
    pytester.runpytest(*PLUGIN_ARGS, "--snapshot1", "s1", "--regen-all", "--snapshot-clean").assert_outcomes(passed=5)
    assert not (folder / "scalars__pi.csv").exists()
    assert (folder / "frames__three.csv").is_file()


# ----------------------------------------------------------------------------- python api (subprocess)


def test_generate_compare_remove(pytester, module, capsys):
    assert snapshots.generate(module, "s1") is True
    assert snapshots.compare(module, "s1") is True
    assert snapshots.generate(module, "s2", env={"SNAP_DB": "db2"}, python=sys.executable) is True
    assert snapshots.compare(module, "s1", "s2") is False    # scalars__db differs
    out = capsys.readouterr().out
    assert "scalars__db" in out and "passed" in out           # pytest output is streamed to the caller
    assert (snapshot_dir(module, "s2") / "scalars__db.yml").read_text() == "value: db2\n"
    assert (snapshot_dir(module, "s1") / "scalars__db.yml").read_text() == "value: db1\n"

    assert snapshots.compare(module, "s1", extra=["-k", "frames"]) is True

    removed = snapshots.remove(module, "s2")
    assert removed == [snapshot_dir(module, "s2")] and not snapshot_dir(module, "s2").exists()
    assert snapshot_dir(module, "s1").is_dir()
    assert snapshots.remove(module, "s2") == []
    assert snapshots.remove(module) == [module.parent / "snapshots" / "test_dummy"]
    assert not (module.parent / "snapshots" / "test_dummy").exists()


def test_remove_by_subdir_and_directory(tmp_path):
    root = tmp_path / "snapshots"
    for sub in ["fixed/s1", "fixed/s2", "test_m/test_x/s1", "other/s1"]:
        (root / sub).mkdir(parents=True)
        (root / sub / "g__n.csv").write_text("x")
    assert snapshots.remove(tmp_path / "test_m.py", "s1", subdir="fixed") == [root / "fixed" / "s1"]
    assert (root / "fixed" / "s2").is_dir()
    assert snapshots.remove(tmp_path / "test_m.py", "s1") == [root / "test_m" / "test_x" / "s1"]
    assert snapshots.remove(tmp_path, "s1") == [root / "other" / "s1"]      # a directory: everything below root
    assert snapshots.remove(tmp_path) == [root] and not root.exists()
    assert snapshots.remove(tmp_path) == []


def test_generate_clean_false_keeps_stale_files(pytester, module):
    assert snapshots.generate(module, "s1") is True
    module.write_text(module.read_text().replace('("scalars", "pi", lambda: 3.14159),\n', ""))
    assert snapshots.generate(module, "s1", clean=False) is True
    assert (snapshot_dir(module, "s1") / "scalars__pi.csv").is_file()
    assert snapshots.generate(module, "s1") is True
    assert not (snapshot_dir(module, "s1") / "scalars__pi.csv").exists()

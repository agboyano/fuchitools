"""Snapshot ("expected output") tests generated from a matrix of calls.

A *matrix* is a list of rows ``(group, name, func, args, kwargs)``. Each row is
one call: ``func(*args, **kwargs)``. ``snapshot_test(matrix)`` turns the matrix
into a single parametrized pytest test -- one test per row, id ``group__name``
-- and the test module that holds the matrix *is* the test file::

    # tests/test_pricing.py
    from fuchitools.snapshots import snapshot_test
    from pricing import matrix          # def matrix(db): return [(group, name, func, args, kwargs), ...]
    test_snapshot = snapshot_test(matrix("db1.db"))

Each test calls the function, serialises the result and hands it to
`pytest-regressions`, which either records it (``--regen-all``) or compares it
with the recorded file and prints the differences::

    pytest tests -p fuchitools.snapshots --snapshot1 v1 --regen-all   # record snapshot "v1"
    pytest tests -p fuchitools.snapshots --snapshot1 v1               # run again, compare with "v1"
    pytest tests -p fuchitools.snapshots --snapshot1 v1 --snapshot2 v2   # compare two recordings, run nothing

``generate``, ``compare`` and ``remove`` wrap those commands for use from
Python or a notebook; they run pytest in a subprocess (optionally with another
interpreter and extra environment variables).

How the result is compared -- decided from the object the function returns:

* ``DataFrame`` / ``Series`` / ``ndarray`` -> CSV via ``dataframe_regression``,
  numbers compared with a tolerance (``DEFAULT_TOLERANCE``), text exactly
  (a missing text value and ``""`` are the same thing in the CSV).
  A tuple or list of frames is written as one CSV per element (``name.0.csv``,
  ``name.1.csv`` ...). Frames are normalised first: see ``normalize_frame``.
* a number -> a one-cell CSV; a flat list of numbers -> a CSV with columns
  ``i`` (position, so the order is kept) and ``value``. Both so the tolerance applies.
* anything else (``str``, ``list``, ``dict``, ``datetime``, ``None`` ...) -> YAML
  via ``data_regression``, compared as text; dates become ISO strings, numpy
  scalars Python scalars, sets sorted lists, NaN ``null``.
* an exception raised by the call is a result too: ``{error: <type>,
  message: <str>}`` in YAML. The suite never aborts because a row fails.

Where the files go: ``<root>/<subdir>/<snapshot>/<group>__<name>[.N].csv|.yml``
with ``root`` = ``--snapshots-dir`` or ``<test module dir>/snapshots`` and
``subdir`` = the ``subdir`` argument of ``snapshot_test`` or, by default,
``<module stem>/<name the test was assigned to>``. Two matrices never share a
folder unless told to.

Rows: ``args`` and ``kwargs`` may be omitted. Any *callable* among the argument
values is called with no arguments at test time and its return value is passed
instead -- that is how a row depends on the output of another function
(``lambda: load(db)``); to pass a function itself as an argument, wrap it
(``lambda: int``). ``name`` must be unique within its ``group``; both are
sanitised to ``[A-Za-z0-9_-]`` for the file name.

Things to know before trusting a green run:

* rows are sorted by every column before writing, so the *order* of a frame is
  never checked; in exchange, queries without ORDER BY do not flake;
* the CSV keeps values, not dtypes: ``1.0`` and ``1`` are both written ``1``
  and read back as ``int64``, so a float column that becomes an int column
  with the same values passes; a text column that becomes numeric fails only
  if it was not entirely numeric text (``to_numeric`` is tried on text first);
* without ``--regen-all`` a missing expected file is *created* and the test
  fails with "File not found ..., created" (pytest-regressions behaviour);
* without ``--snapshot1`` the tests are skipped; with ``--snapshot2`` nothing
  is executed and a row missing on either side fails.

Needs the ``snapshots`` extra (pytest, pytest-regressions, pyyaml). This module
is also the pytest plugin that adds the options: enable it with
``-p fuchitools.snapshots`` (command line or ``addopts``). PYTEST_DONT_REWRITE
(it is imported by test modules and as a plugin; assertion rewriting is not
wanted for it).
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

if importlib.util.find_spec("pytest") is None or importlib.util.find_spec("pytest_regressions") is None:
    raise ImportError(
        "fuchitools.snapshots needs the 'snapshots' extra: pip install fuchitools[snapshots]"
    )

import pytest
import yaml

__all__ = [
    "snapshot_test",
    "generate",
    "compare",
    "remove",
    "run_row",
    "to_parts",
    "normalize_frame",
    "read_parts",
    "row_id",
    "CallError",
    "DEFAULT_TOLERANCE",
]

DEFAULT_TOLERANCE = {"rtol": 1e-9, "atol": 1e-12}

PLUGIN = "fuchitools.snapshots"

Row = Tuple[str, str, Callable[..., Any], tuple, dict]
Part = Tuple[str, Union[pd.DataFrame, dict]]

_PART_RE = r"^{stem}(?:\.(\d+))?\.(csv|yml)$"
_CLEANED = pytest.StashKey[set]()


# --------------------------------------------------------------------------- rows


class CallError(dict):
    """The result of a row whose call raised: ``{"error": type name, "message": str(exc)}``."""

    def __init__(self, exc: BaseException):
        super().__init__(error=type(exc).__name__, message=str(exc))


def row_id(group: Any, name: Any) -> str:
    """``group__name`` with both parts reduced to ``[A-Za-z0-9_-]``: the test id and the file stem."""
    safe = lambda x: re.sub(r"[^A-Za-z0-9_-]+", "_", str(x))
    return f"{safe(group)}__{safe(name)}"


def _normalize_row(row: Sequence[Any]) -> Row:
    row = tuple(row)
    if not 3 <= len(row) <= 5:
        raise ValueError(f"a matrix row is (group, name, func[, args[, kwargs]]), got {len(row)} items: {row!r}")
    group, name, func = row[:3]
    args = row[3] if len(row) > 3 else ()
    kwargs = row[4] if len(row) > 4 else {}
    if not callable(func):
        raise ValueError(f"row {row_id(group, name)}: func is not callable: {func!r}")
    if isinstance(args, (str, bytes)) or not isinstance(args, Iterable):
        raise ValueError(f"row {row_id(group, name)}: args must be a list or tuple, got {args!r}")
    return (str(group), str(name), func, tuple(args), dict(kwargs or {}))


def run_row(func: Callable[..., Any], args: Sequence[Any] = (), kwargs: Optional[dict] = None) -> Any:
    """Call ``func`` with the row's arguments; callables among them are called first.

    An exception -- in the call or while evaluating an argument -- is returned as
    a ``CallError`` instead of raised.
    """
    try:
        a = [v() if callable(v) else v for v in args]
        k = {n: (v() if callable(v) else v) for n, v in (kwargs or {}).items()}
        return func(*a, **k)
    except Exception as exc:  # noqa: BLE001 - a failing row is a result, not a crash
        return CallError(exc)


# --------------------------------------------------------------------------- serialisation


def _label(c: Any) -> str:
    if isinstance(c, tuple):
        parts = [_label(x) for x in c]
        while parts and parts[-1] == "":  # ("k", "") -- what reset_index gives an index under MultiIndex columns
            parts.pop()
        return "|".join(parts)
    if isinstance(c, float) and math.isfinite(c) and c.is_integer():
        return str(int(c))
    return str(c)


def normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    """The canonical form of a frame, the one that is written and compared.

    * an unnamed ``RangeIndex`` is dropped, any other index becomes columns;
    * column labels become ``str`` (``93707.0`` -> ``"93707"``), MultiIndex
      labels are joined with ``|``, duplicates get ``__2``, ``__3`` ...;
    * non-numeric columns are converted with ``to_numeric`` when every value
      allows it, otherwise to the ``string`` dtype with missing values as ``""``
      (the CSV cannot tell them apart, and ``dataframe_regression`` wants a
      ``str`` in the first row); ``object`` never reaches the CSV writer;
    * rows are sorted by all columns, NaN last, and the index reset.

    Idempotent: applying it to a frame read back from its own CSV changes nothing.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"normalize_frame expects a DataFrame, got {type(df).__name__}")
    if isinstance(df.index, pd.RangeIndex) and df.index.name is None:
        df = df.reset_index(drop=True)
    else:
        df = df.reset_index()
    labels, seen = [], {}
    for c in df.columns:
        label = _label(c)
        seen[label] = seen.get(label, 0) + 1
        labels.append(label if seen[label] == 1 else f"{label}__{seen[label]}")
    df = df.copy()
    df.columns = labels
    for c in df.columns:
        s = df[c]
        if s.dtype.kind in "biufM":
            continue
        try:
            df[c] = pd.to_numeric(s)
        except (ValueError, TypeError):
            # text. Missing values become "" -- the CSV cannot tell them apart anyway, and
            # dataframe_regression accepts a text column only when its first value is a str
            df[c] = s.astype("string").fillna("")
    if len(df) == 0:
        # no first value to inspect: give the text columns a dtype the plugin accepts
        df = df.astype({c: "float64" for c in df.columns if df[c].dtype.kind == "O"})
    if len(df.columns):
        df = df.sort_values(list(df.columns), na_position="last")
    return df.reset_index(drop=True)


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float, np.integer, np.floating)) and not isinstance(x, (bool, np.bool_))


def to_yaml_safe(obj: Any) -> Any:
    """Reduce ``obj`` to what ``yaml.safe_dump`` accepts, deterministically."""
    if obj is None or isinstance(obj, (bool, int, str)):
        return obj
    if isinstance(obj, float):
        return None if math.isnan(obj) else obj
    if isinstance(obj, np.datetime64):
        return pd.Timestamp(obj).isoformat()
    if isinstance(obj, np.generic):
        return to_yaml_safe(obj.item())
    if isinstance(obj, (_dt.datetime, _dt.date, _dt.time)):
        return obj.isoformat()
    if isinstance(obj, _dt.timedelta):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): to_yaml_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_yaml_safe(x) for x in obj]
    if isinstance(obj, (set, frozenset)):
        return sorted((to_yaml_safe(x) for x in obj), key=repr)
    if isinstance(obj, np.ndarray):
        return to_yaml_safe(obj.tolist())
    if isinstance(obj, pd.Series):
        return to_yaml_safe(obj.to_dict())
    if isinstance(obj, pd.DataFrame):
        return to_yaml_safe(obj.to_dict(orient="list"))
    return repr(obj)


def to_parts(obj: Any) -> List[Part]:
    """Split a result into the parts that are written: ``[(suffix, DataFrame | dict), ...]``.

    A DataFrame part goes to CSV, a dict part to YAML. Most results are one
    part with suffix ``""``; a tuple/list of frames gives ``".0"``, ``".1"`` ...
    """
    if isinstance(obj, CallError):
        return [("", dict(obj))]
    if isinstance(obj, pd.DataFrame):
        return [("", normalize_frame(obj))]
    if isinstance(obj, pd.Series):
        return [("", normalize_frame(obj.to_frame()))]
    if isinstance(obj, np.ndarray):
        if obj.ndim == 0:
            return to_parts(obj.item())
        return [("", normalize_frame(pd.DataFrame(obj if obj.ndim > 1 else obj.reshape(-1, 1))))]
    if isinstance(obj, (tuple, list)) and obj and all(isinstance(x, (pd.DataFrame, pd.Series)) for x in obj):
        return [(f".{i}", to_parts(x)[0][1]) for i, x in enumerate(obj)]
    if _is_number(obj):
        return [("", normalize_frame(pd.DataFrame({"value": [obj]})))]
    if isinstance(obj, (tuple, list)) and obj and all(_is_number(x) for x in obj):
        # the position column keeps the list order through normalize_frame's row sort
        return [("", normalize_frame(pd.DataFrame({"i": range(len(obj)), "value": list(obj)})))]
    return [("", {"value": to_yaml_safe(obj)})]


def read_parts(folder: Union[str, os.PathLike], stem: str) -> List[Part]:
    """The parts recorded for ``stem`` in a snapshot folder, in the order ``to_parts`` produced them."""
    rx = re.compile(_PART_RE.format(stem=re.escape(stem)))
    found = []
    for p in Path(folder).glob(f"{stem}*"):
        m = rx.match(p.name)
        if not m:
            continue
        index = int(m.group(1)) if m.group(1) is not None else -1
        suffix = f".{m.group(1)}" if m.group(1) is not None else ""
        if m.group(2) == "csv":
            # the recorded index is always 0..n-1 (normalize_frame resets it); drop it, do not turn it into a column
            value: Union[pd.DataFrame, dict] = normalize_frame(pd.read_csv(p, index_col=0).reset_index(drop=True))
        else:
            value = yaml.safe_load(p.read_text(encoding="utf-8"))
        found.append((index, suffix, value))
    return [(s, v) for _, s, v in sorted(found, key=lambda t: t[0])]


# --------------------------------------------------------------------------- pytest plugin


def pytest_addoption(parser):
    group = parser.getgroup("snapshots", "fuchitools.snapshots")
    group.addoption("--snapshot1", default=None, metavar="NAME",
                    help="recorded snapshot to compare with (or to write, with --regen-all); without it the snapshot tests are skipped")
    group.addoption("--snapshot2", default=None, metavar="NAME",
                    help="compare snapshot1 with this recorded snapshot instead of running the matrix")
    group.addoption("--snapshots-dir", default=None, metavar="DIR",
                    help="root folder of the snapshots (default: <test module dir>/snapshots)")
    group.addoption("--snapshot-clean", action="store_true", default=False,
                    help="with --regen-all: empty each snapshot folder before the first file is written into it, "
                         "so files of rows no longer in the matrix disappear")


class Snapshot:
    """What the ``snapshot`` fixture returns; ``check(row)`` does the whole job for one matrix row."""

    def __init__(self, request, dataframe_regression, data_regression):
        self.request = request
        self.df_check = dataframe_regression
        self.data_check = data_regression
        opt = request.config.getoption
        self.name1: str = opt("--snapshot1")
        self.name2: Optional[str] = opt("--snapshot2")
        self.regen: bool = bool(opt("regen_all") or opt("force_regen"))
        self.clean: bool = bool(opt("--snapshot-clean"))
        module_file = Path(request.module.__file__)
        root = opt("--snapshots-dir")
        self.root = Path(root) if root else module_file.parent / "snapshots"
        self.default_subdir = f"{module_file.stem}/{request.node.originalname}"

    def folder(self, name: str, subdir: Optional[str] = None) -> Path:
        return self.root / (subdir or self.default_subdir) / name

    def check(self, row: Sequence[Any], tolerance: Optional[dict] = None, subdir: Optional[str] = None) -> None:
        __tracebackhide__ = True
        group, name, func, args, kwargs = _normalize_row(row)
        stem = row_id(group, name)
        tolerance = dict(DEFAULT_TOLERANCE if tolerance is None else tolerance)
        dir1 = self.folder(self.name1, subdir)
        if self.name2 is not None:
            if self.regen:
                pytest.fail("--snapshot2 cannot be combined with --regen-all / --force-regen")
            dir2 = self.folder(self.name2, subdir)
            parts = read_parts(dir2, stem)
            if not parts:
                pytest.fail(f"{stem}: nothing recorded in snapshot {self.name2!r} ({dir2})")
        else:
            parts = to_parts(run_row(func, args, kwargs))
            if self.regen and self.clean:
                cleaned = self.request.config.stash.setdefault(_CLEANED, set())
                if dir1 not in cleaned:
                    shutil.rmtree(dir1, ignore_errors=True)
                    cleaned.add(dir1)
        failures = []  # every part is checked (and, when missing, created) before the row fails
        for suffix, value in parts:
            is_frame = isinstance(value, pd.DataFrame)
            path = dir1 / f"{stem}{suffix}.{'csv' if is_frame else 'yml'}"
            try:
                if self.name2 is not None and not path.is_file():
                    pytest.fail(f"{stem}: not recorded in snapshot {self.name1!r} ({path})")
                if is_frame:
                    self.df_check.check(value, fullpath=path, default_tolerance=tolerance)
                else:
                    self.data_check.check(value, fullpath=path)
            except (AssertionError, pytest.fail.Exception) as exc:
                failures.append(exc)
        if len(failures) == 1:
            raise failures[0]
        if failures:
            pytest.fail("\n\n".join(f"{type(exc).__name__}: {exc}" for exc in failures))


@pytest.fixture
def snapshot(request, dataframe_regression, data_regression) -> Snapshot:
    """Records or checks one matrix row against the snapshot named by ``--snapshot1``."""
    if not request.config.getoption("--snapshot1"):
        pytest.skip("--snapshot1 not given")
    return Snapshot(request, dataframe_regression, data_regression)


def snapshot_test(matrix: Iterable[Sequence[Any]], tolerance: Optional[dict] = None,
                  subdir: Optional[str] = None) -> Callable[..., None]:
    """Turn a matrix into a parametrized pytest test; assign the result to a ``test_*`` name.

    ``tolerance`` (``{"rtol": ..., "atol": ...}``) applies to every numeric
    column of every frame in this matrix; ``subdir`` fixes the folder under
    the snapshots root (default ``<module stem>/<test name>``).
    Raises ``ValueError`` on malformed rows or duplicated ``group__name`` ids.
    """
    rows = [_normalize_row(r) for r in matrix]
    ids = [row_id(g, n) for g, n, *_ in rows]
    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    if duplicated:
        raise ValueError(f"duplicated matrix ids: {duplicated}")
    tol = dict(DEFAULT_TOLERANCE if tolerance is None else tolerance)

    @pytest.mark.parametrize("row", rows, ids=ids)
    def test(row, snapshot):
        __tracebackhide__ = True
        snapshot.check(row, tolerance=tol, subdir=subdir)

    test.snapshot_subdir = subdir
    return test


# --------------------------------------------------------------------------- python api


def _run_pytest(test_module: Union[str, os.PathLike], options: Sequence[str], env: Optional[Dict[str, str]],
                python: Optional[str]) -> bool:
    cmd = [python or sys.executable, "-m", "pytest", "-p", PLUGIN, str(test_module), *options]
    full_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", **(env or {})}
    proc = subprocess.Popen(cmd, env=full_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    assert proc.stdout is not None
    for line in proc.stdout:  # streamed, so notebooks and terminals both see progress
        print(line, end="")
    return proc.wait() == 0


def _dir_option(snapshots_dir: Optional[Union[str, os.PathLike]]) -> List[str]:
    return ["--snapshots-dir", str(snapshots_dir)] if snapshots_dir else []


def generate(test_module: Union[str, os.PathLike], name: str, snapshots_dir: Optional[Union[str, os.PathLike]] = None,
             env: Optional[Dict[str, str]] = None, python: Optional[str] = None, extra: Sequence[str] = (),
             clean: bool = True) -> bool:
    """Record snapshot ``name`` for the matrices in ``test_module`` (a file or a directory of ``test_*.py``).

    Runs ``pytest -p fuchitools.snapshots <test_module> --snapshot1 <name> --regen-all``
    in a subprocess -- ``python`` selects the interpreter (another venv), ``env``
    adds environment variables for that run only, ``extra`` appends pytest
    options. ``clean`` empties each snapshot folder before writing (drop it when
    ``extra`` selects a subset of rows with ``-k``). Returns ``True`` on success.
    """
    options = ["--snapshot1", name, "--regen-all", *(["--snapshot-clean"] if clean else []),
               *_dir_option(snapshots_dir), *extra]
    return _run_pytest(test_module, options, env, python)


def compare(test_module: Union[str, os.PathLike], snapshot1: str, snapshot2: Optional[str] = None,
            snapshots_dir: Optional[Union[str, os.PathLike]] = None, env: Optional[Dict[str, str]] = None,
            python: Optional[str] = None, extra: Sequence[str] = ()) -> bool:
    """Run the matrices in ``test_module`` and compare with ``snapshot1``; or, given
    ``snapshot2``, compare the two recordings without running anything.

    Same subprocess mechanics as ``generate``. Returns ``True`` when every row matches.
    """
    options = ["--snapshot1", snapshot1, *(["--snapshot2", snapshot2] if snapshot2 else []),
               *_dir_option(snapshots_dir), *extra]
    return _run_pytest(test_module, options, env, python)


def remove(test_module: Union[str, os.PathLike], snapshot: Optional[str] = None, subdir: Optional[str] = None,
           snapshots_dir: Optional[Union[str, os.PathLike]] = None) -> List[Path]:
    """Delete recorded snapshots and return the folders removed.

    The base is ``<root>/<subdir>`` when ``subdir`` is given, ``<root>/<module stem>``
    for a test file (the default folders of its matrices) or ``<root>`` for a
    directory. Without ``snapshot`` the whole base goes; with it, only the
    folders of that name below the base. Tests are not files: to drop them,
    delete the module or its ``snapshot_test`` line.
    """
    p = Path(test_module)
    root = Path(snapshots_dir) if snapshots_dir else (p if p.is_dir() else p.parent) / "snapshots"
    if subdir:
        base = root / subdir
    elif p.is_dir():
        base = root
    else:
        base = root / p.stem
    if not base.is_dir():
        return []
    targets = [base] if snapshot is None else sorted(d for d in base.rglob(snapshot) if d.is_dir())
    for t in targets:
        shutil.rmtree(t)
    return targets

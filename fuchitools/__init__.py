"""General purpose utilities: dates, DataFrames in and out of databases,
browser scraping, Jupyter kernels.

Only the light modules are imported here. ``duckdb``, ``selenium``, ``jupyter``
and ``misc`` are imported explicitly by the caller (``from fuchitools import
jupyter``); ``selenium`` and ``jupyter`` need their optional extras installed.
"""

from importlib.metadata import PackageNotFoundError, version as _version

try:
    __version__ = _version("fuchitools")
except PackageNotFoundError:  # not installed, e.g. running from a checkout
    __version__ = "0.0.0"

from . import datetimes
from . import sqlite
from . import pandas

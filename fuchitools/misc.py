"""A console logger in one line, for scripts that want output without
setting up logging properly."""

import logging
from typing import Optional, Union

__all__ = ["stream_logger"]


def _resolve_level(level: Union[int, str]) -> int:
    if isinstance(level, bool):
        raise ValueError(f"invalid logging level: {level!r}")
    if isinstance(level, int):
        return level
    resolved = logging.getLevelName(str(level).upper())
    if not isinstance(resolved, int):
        raise ValueError(
            f"unknown logging level {level!r}; use DEBUG, INFO, WARNING, ERROR or CRITICAL"
        )
    return resolved


def stream_logger(
    module_name: str,
    level: Union[int, str] = "ERROR",
    fmt: Optional[str] = None,
    stream=None,
) -> logging.Logger:
    """Return the logger ``module_name`` with a console handler attached.

    Calling it again for the same name reuses the handler it attached the
    first time (updating its level, stream and format), so messages are not
    printed twice.

    Parameters
    ----------
    module_name : str
        Logger name, typically ``__name__``.
    level : int | str, default "ERROR"
        A logging level as an int or its name (case-insensitive). Applied to
        both the logger and the handler.
    fmt : str, optional
        A ``logging.Formatter`` format string, e.g.
        ``"%(asctime)s %(levelname)-8s %(name)s | %(message)s"``. By default
        lines come out as the bare message.
    stream : file-like, optional
        Where to write; ``None`` means ``sys.stderr`` (logging's default).

    Raises
    ------
    ValueError
        If ``level`` is not a known level name.

    Examples
    --------
    >>> log = stream_logger(__name__, "INFO")
    >>> log.info("cargando cuenta %s", 1001)
    """
    lvl = _resolve_level(level)
    logger = logging.getLogger(module_name)
    logger.setLevel(lvl)

    handler = next((h for h in logger.handlers if getattr(h, "_fuchitools", False)), None)
    if handler is None:
        handler = logging.StreamHandler(stream)
        handler._fuchitools = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    elif stream is not None:
        handler.setStream(stream)

    handler.setLevel(lvl)
    if fmt is not None:
        handler.setFormatter(logging.Formatter(fmt))
    return logger

# `fuchitools.misc`

One function, for scripts that want log output on the console without setting
up logging properly.

## `stream_logger(module_name, level="ERROR", fmt=None, stream=None)`

```python
from fuchitools.misc import stream_logger

log = stream_logger(__name__, level="INFO")

log.info("cargando cartera %s", 93702)
log.error("no se pudo abrir %s", path)
```

Returns the `logging.Logger` named `module_name` with a `StreamHandler`
attached, both set to `level`.

- `level` is a standard level name, case-insensitive (`"DEBUG"`, `"info"`,
  ...) or an int (`logging.WARNING`). An unknown name raises `ValueError`.
- `fmt` is an optional `logging.Formatter` format string. Without it, lines
  come out as the bare message — no timestamp, level or logger name:

```python
log = stream_logger(__name__, "INFO", fmt="%(asctime)s %(levelname)-8s %(name)s | %(message)s")
```

- `stream` is where to write; the default is `sys.stderr`, logging's own.

**Calling it twice for the same name is safe.** The handler it attached the
first time is found again and updated (level, stream, format) instead of a
second one being added, so nothing is printed twice. Handlers you attached
yourself are left alone.

For a long-running or unattended job, prefer `logging.basicConfig` or a proper
configuration: this helper exists to save three lines in a script, not to
manage logging for an application.

## Tests

`tests/test_misc.py`, writing to in-memory streams.

# `fuchitools.misc`

One function, for scripts that want log output on the console without setting
up logging properly.

## `stream_logger(module_name, level="ERROR")`

```python
from fuchitools.misc import stream_logger

log = stream_logger(__name__, level="INFO")

log.info("cargando cartera %s", 93702)
log.error("no se pudo abrir %s", path)
```

Returns a `logging.Logger` under `module_name` with a `StreamHandler` attached,
both set to `level`. `level` is the name of a standard logging level as a
string: `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"`, `"CRITICAL"`.

Two things to watch:

- **Calling it twice with the same name attaches a second handler**, and every
  message is then printed twice. `logging.getLogger` returns the same logger
  object, but a new `StreamHandler` is added unconditionally. Call it once per
  module, at import time, and keep the result.
- **No formatter is set**, so lines come out as the bare message, with no
  timestamp, level or logger name. For anything you will read later, attach a
  formatter yourself:

```python
import logging
from fuchitools.misc import stream_logger

log = stream_logger(__name__, "INFO")
log.handlers[0].setFormatter(
    logging.Formatter("%(asctime)s %(levelname)-8s %(name)s | %(message)s")
)
```

For a long-running or unattended job, prefer `logging.basicConfig` or a proper
configuration: this helper exists to save three lines in a script, not to
manage logging for an application.

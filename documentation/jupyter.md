# `fuchitools.jupyter`

Find the Jupyter kernels running on this machine — whoever started them: the
VSCode Jupyter extension, a JupyterLab/Notebook server, or `jupyter kernel` in
a terminal — and then do things with them: run code inside one, stop one, see
which processes are attached to it and which notebook it belongs to. Code
running *inside* a kernel can also ask where it is.

It does not need a Jupyter server to be installed, registered or alive. Every
kernel it reports has been confirmed by contacting the process or the kernel;
nothing is inferred from files alone.

The module is **not** imported by `fuchitools/__init__.py` (it pulls in
`psutil`, `jupyter_client` and `jupyter_core`), so import it explicitly:

```python
from fuchitools import jupyter
from fuchitools.jupyter import list_active_kernels, format_table
```

The reasoning behind the design — why the obvious approaches fail, what had to
be measured and worked around — is in [`memory/jupyter.md`](../memory/jupyter.md).
This page is the how-to.

## Quick start

```python
from fuchitools.jupyter import list_active_kernels, format_table

for k in list_active_kernels():
    print(k.origin, k.pid, k.cwd)

print(format_table(list_active_kernels()))
```

Or from a shell: `python -m fuchitools.jupyter`

```
ORIGIN  PID    STATE     KERNEL ID       STARTED           EXECUTABLE  CWD
vscode  18420  responds  v3a1b2c3d4e5f6  2026-01-15 09:30  python.exe  c:\...\notebooks
vscode  24680  responds  v3d4e5f6a7b8c9  2026-01-15 09:30  python.exe  d:\...\notebooks
```

A full listing takes about 1.5 s with a couple of live kernels and a thousand
stale connection files lying around, which is the normal state of a machine.

## Listing kernels

```python
list_active_kernels(timeout=3.0, include_dead=False) -> list[KernelInfo]
```

Returns one `KernelInfo` per live kernel, oldest first (unknown start times
last). `timeout` is the budget for each kernel ping and each server query;
pings run in parallel. `include_dead=True` also returns every stale
`kernel-*.json` in the runtime directories with `alive=False` — there may be
thousands, so only ask for them when you mean it.

```python
# the kernel working in this directory
import os
mine = [k for k in list_active_kernels() if k.cwd == os.getcwd()]

# everything VSCode has open
vscode = [k for k in list_active_kernels() if k.origin == "vscode"]
```

### `KernelInfo`

| Field | Meaning |
|---|---|
| `connection_file` | `Path` to the `kernel-*.json` |
| `kernel_id` | id parsed out of the file name |
| `pid` | kernel process, when the process sweep found it |
| `origin` | `vscode` / `server` / `terminal` / `unknown` |
| `kernel_name` | as declared in the connection file |
| `ports` | shell, iopub, stdin, control, hb |
| `executable` | interpreter (virtualenv) running the kernel |
| `cwd` | working directory — in practice the best way to tell kernels apart |
| `started` | process start time |
| `alive` | there is evidence the kernel exists (process seen, or it answered) |
| `responds` | it answered the ping |

### `alive` vs `responds`

A kernel busy running a long cell has its shell channel blocked and does not
answer a ping, yet it is perfectly healthy. It comes out as `alive=True,
responds=False`; `format_table` shows the three states as `responds`, `busy`
and `dead`. Do not treat `responds=False` as dead when `alive` is True.

### `origin`

A heuristic over the connection file's name and contents, not a fact:
`vscode` (raw kernels started by the extension), `server` (listed by a live
server's `/api/kernels`), `terminal` (`jupyter kernel`, `jupyter console`), or
`unknown` when in doubt. `classify_origin(connection_file, data, server_kernels)`
is the function behind it if you need to call it yourself.

### Runtime directories

```python
runtime_dirs() -> list[Path]
```

Every existing Jupyter runtime directory (environment, user, system,
`$JUPYTER_RUNTIME_DIR`), deduplicated. Useful for a quick look at how many
stale files have piled up:

```python
for d in runtime_dirs():
    print(d, len(list(d.glob("kernel-*.json"))))
```

## Referring to a kernel

Every function below takes `kernel` as any of:

- a `KernelInfo` from `list_active_kernels()` or `current_kernel()`;
- a path to a connection file, `str` or `Path`;
- a kernel id such as `"v3a1b2c3d4e5f6"` (the file is looked up in the
  runtime directories; `FileNotFoundError` if nothing matches).

## Running code in a kernel

```python
execute_in_kernel(kernel, code, timeout=15.0, store_history=False) -> ExecutionResult
```

Runs `code` in someone's live session and returns what it produced:

| `ExecutionResult` | |
|---|---|
| `output` | stdout, stderr and the text repr of the last expression, concatenated |
| `error` | the traceback as one string if the code raised, else `None` |
| `timed_out` | True if the budget ran out before the kernel went idle |
| `success` | property: `error is None and not timed_out` |

```python
from fuchitools.jupyter import execute_in_kernel, list_active_kernels, KernelUnreachable

kernel = list_active_kernels()[0]

execute_in_kernel(kernel, "print(df.shape)").output          # '(72, 36)\n'

# inspect without touching the session's objects
execute_in_kernel(kernel, "print(df.copy().describe())").output

r = execute_in_kernel(kernel, "1/0")
r.success                                                     # False
"ZeroDivisionError" in r.error                                # True

# a kernel that may be gone: do not spend the full budget on it
try:
    execute_in_kernel(kernel, "1+1", timeout=3.0)
except KernelUnreachable:
    ...
```

This is a loaded gun. The code has full access to the session's namespace and
nothing stops it from mutating state; for inspection work on copies
(`df.copy()`, not `df`). `store_history=False` (default) keeps the notebook's
`In`/`Out` numbering untouched; pass `True` if the execution should count as a
cell.

`KernelUnreachable` (a `RuntimeError`) means the kernel did not answer within
`timeout`. That covers both a dead kernel and one busy on another cell — the
two cannot be told apart from outside. Only the output of *your* request is
collected; whatever other clients (the notebook the user is typing in) produce
on the shared iopub channel is filtered out.

## Stopping a kernel

```python
shutdown_kernel(kernel, timeout=5.0, force=False) -> bool
```

Sends a polite `shutdown_request` on the control channel — the kernel runs its
exit handlers and closes its sockets — and waits up to `timeout` seconds for
the process to go away. Because the control channel has its own thread, this
reaches even a kernel busy on a long cell. Returns True if the kernel is gone
when it returns. With `force=True`, a process still alive at the deadline is
killed outright (nothing flushed, no exit handlers).

```python
from fuchitools.jupyter import list_active_kernels, shutdown_kernel

# stop every kernel left over from a directory nobody works in
for k in list_active_kernels():
    if k.cwd and "scratch" in k.cwd:
        shutdown_kernel(k)

# one that ignores the request
shutdown_kernel(k, timeout=3.0, force=True)
```

The polite path takes 0.2–0.7 s in practice.

## From inside a kernel

```python
running_in_kernel() -> bool
current_kernel() -> KernelInfo | None
```

`running_in_kernel()` is True under a notebook, JupyterLab, VSCode or
qtconsole — anything driving an ipykernel. It is False in a plain script **and
in an IPython terminal session**, which has an interactive shell but no kernel.

```python
from fuchitools.jupyter import running_in_kernel, current_kernel

if running_in_kernel():
    from tqdm.notebook import tqdm
else:
    from tqdm import tqdm

me = current_kernel()
if me:
    print(me.kernel_id, me.executable, me.cwd)

# every other kernel running right now
others = [k for k in list_active_kernels() if k.pid != me.pid]

# write output next to the notebook, wherever it was started from
destination = Path(me.cwd) / "report.xlsx" if me else Path("report.xlsx")
```

`current_kernel()` is exact and free: the connection file comes from ipykernel
itself, not from a sweep. Its `responds` is deliberately left False — a kernel
cannot ping itself, because the shell channel is busy with the very call that
is asking.

## Who is attached, and to which notebook

```python
kernel_clients(kernel) -> list[ClientInfo]
notebook_of(kernel, allow_execution=True, timeout=10.0) -> str | None
```

`kernel_clients` reads the TCP table (nothing is sent to the kernel) and
returns one `ClientInfo` (`pid`, `name`, `executable`, `ports`) per process
with an established connection to the kernel's ports, excluding the kernel's
own process family.

```python
from fuchitools.jupyter import kernel_clients, notebook_of

for k in list_active_kernels():
    for c in kernel_clients(k):
        print(k.kernel_id[:14], "<-", c.name, c.pid, c.ports)

# v3a1b2c3d4e5f6 <- Code.exe 21500 [9001, 9002, 9003, 9004]
```

Read it for what it is: inference from open sockets, not a roster the kernel
keeps. One VSCode window is one process multiplexing every notebook, so it
shows up once per kernel with no way to tell which tab is which; and an open
connection may be a tab opened yesterday and forgotten.

`notebook_of` tells you the document a kernel belongs to, trying two routes:

1. a live server's `/api/sessions` — side-effect free, but only server-launched
   kernels are in it (VSCode never registers a session);
2. the kernel's own namespace (`__vsc_ipynb_file__`, `__session__`) — a pure
   read run inside the kernel, so it needs `allow_execution=True` (default).

```python
notebook_of(k)
# 'c:\\proyectos\\notebooks\\analisis.ipynb'

notebook_of(k, allow_execution=False)
# None for a VSCode kernel: no server knows about it
```

Returns None for a terminal kernel (no document) and for a busy kernel (cannot
be probed).

## Rendering

```python
format_table(kernels) -> str
```

The fixed-width table shown in the quick start; `python -m fuchitools.jupyter`
prints it for `list_active_kernels()`.

## Things that will bite you if you do not know them

- **`responds=False` is not "dead".** A kernel running a long cell is alive
  and busy. Check `alive` first, and `format_table` already says `busy`.
- **A busy kernel the process sweep cannot see is reported as dead.** If the
  process is not inspectable (permissions, another user), the ping is the only
  evidence left, and a busy kernel fails it.
- **Talking to a dead kernel costs the whole `timeout`.** `execute_in_kernel`
  on a kernel that is gone burns the full budget (16 s with the default)
  before raising `KernelUnreachable`. Pass a small `timeout`, or list first.
- **`execute_in_kernel` cannot interrupt what it starts.** Code that overruns
  the budget comes back as `timed_out=True` but keeps running in the kernel.
- **VSCode kernels are invisible to servers.** `jupyter server list`,
  `/api/kernels` and `/api/sessions` never list them; that is why the listing
  works from processes and connection files, and why `notebook_of` has route 2.
- **`include_dead=True` returns every stale file** in the runtime directories,
  which on a long-lived machine means hundreds or thousands of entries.
- **Local only.** Remote kernels are out of scope: the process sweep is local
  by construction and the ping assumes reachable ports.
- **`current_kernel()` is None in an IPython terminal** — there is no kernel
  there, only a shell.

## Tests

`tests/test_jupyter.py`, 84 tests, ~2 s. Entirely synthetic — no kernel is
started, pinged, stopped or inspected — so it is safe to run with live
notebooks open. The functions that talk to real kernels were verified by hand
against kernels started for the purpose; the details, measurements and the two
jupyter_client quirks that had to be worked around are in
[`memory/jupyter.md`](../memory/jupyter.md).

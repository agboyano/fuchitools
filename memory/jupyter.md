# `fuchitools.jupyter`

Discovery of the Jupyter kernels running on the local machine, whatever
started them: the VSCode Jupyter extension, a JupyterLab/Notebook server, or
`jupyter kernel` from a terminal. On top of the listing it can run code inside
a given kernel, stop one, say which processes are attached to it and which
document it belongs to, and tell code running inside a kernel where it is.

Written 26-08-2026. Everything below was measured on a Windows 11 workstation
with Python 3.13, jupyter_client 8.8, jupyter_core 5.9, ipykernel 7.2 and
psutil 7.2.

## Why it exists

The immediate need was to read variables out of a live notebook kernel from
outside VSCode — inspecting a DataFrame mid-session without disturbing the
notebook. Step one of that is knowing which kernels are alive, and none of the
obvious answers works.

### What the Jupyter CLI does not give you

| Command | What it actually does |
|---|---|
| `jupyter kernel list` | **Does not exist.** `jupyter kernel` *starts* a kernel and blocks; `list` is swallowed as an argument. Running it leaves a stray kernel behind. |
| `jupyter kernelspec list` | Lists installed kernel *types*, not running instances. |
| `jupyter server list` | Lists registered servers, and never verifies they are alive. |

`jupyter server list` deserves its own note. It reads `jpserver-<pid>.json`
files, which are only deleted on a clean shutdown; after a kill, a reboot or a
Windows logoff the registration survives indefinitely. On the machine this was
developed on, the command cheerfully reported a server on port 8888 whose
registration was dated March 2023, whose pid no longer existed and whose port
nothing was listening on.

And even a genuinely live server only knows about the kernels it launched
itself. **VSCode does not use a server**: the extension launches kernels raw,
so no `/api/kernels` endpoint will ever list them.

### What the runtime directory does not give you either

Listing `kernel-*.json` files fails for the same reason `jupyter server list`
does: the files outlive their processes. The development machine held **1,118
connection files against 2 live kernels**, some dating back to 2019.

The conclusion that drives the whole design: **the only acceptable proof of
life is contacting the process or the kernel.** Anything that merely reads a
directory is reporting fiction.

## Design

### Double sweep

Neither available source is trustworthy alone, so both are scanned and joined
by connection file:

1. **By process** (primary). Walk the process table with psutil, keep processes
   whose command line contains `ipykernel_launcher`, and extract the connection
   file path from it. This catches kernels whose connection file lives outside
   the runtime directories, and yields pid, interpreter, cwd and start time.

2. **By connection file** (secondary). Walk every `kernel-*.json` in every
   runtime directory. This catches kernels whose process could not be
   inspected — denied permissions, another user — which the process sweep
   misses entirely.

Every surviving candidate is then confirmed with a real ping:
`BlockingKernelClient` + `load_connection_file` + `start_channels` +
`wait_for_ready`, in a `try/finally` that always calls `stop_channels`. No user
code is executed, so the kernel's `In`/`Out` history is left untouched.

Runtime directories are discovered with `jupyter_core.paths.jupyter_path("runtime")`,
which returns one per installation level, plus `jupyter_runtime_dir()` and
`$JUPYTER_RUNTIME_DIR`. Using only `jupyter_runtime_dir()` is the classic
mistake that silently loses kernels.

### Port screening, and why it turned out to be necessary

A failed ping costs about a second. Pinging 1,118 files, even 16 at a time,
took over two minutes — the first working version simply hung. Files that come
only from the file sweep are therefore screened first, and the screening went
through three iterations before it was correct:

**Attempt 1 — is anything listening on the shell port?** Cut 1,118 down to
337. Not enough, because **VSCode reuses ports**: it always starts at 9000, so
197 dead files share shell port 9002 with a running kernel.

**Attempt 2 — drop files whose port is owned by a pid the process sweep already
found.** Matched nothing at all. The reason is that **the port is held by the
launcher process, not by the kernel**: port 9002 belonged to pid 18410 while
the ipykernel process was pid 18420.

**Attempt 3 — compare against the whole process family.** `_scan_processes`
now returns every pid whose command line mentions ipykernel, undeduplicated,
alongside the deduplicated kernel listing. Screening against that set takes the
337 candidates down to 0, and a full listing to 1.4 seconds.

When `psutil.net_connections()` is unavailable (it needs privileges that are
not always granted) the code falls back to a direct TCP probe, which cannot
tell owners apart but still rules out closed ports.

### Why port reuse does not cause false positives

A stale file whose port has been inherited by a different kernel carries a
different HMAC `key`. Its messages fail signature verification and are dropped,
so the ping fails. The screening is an optimisation; the ping is what decides.

### Origin heuristic

`classify_origin` labels each kernel `vscode`, `server`, `terminal` or
`unknown`, from the file name and contents:

- **vscode** — name prefixed `kernel-v3` or `kernel-v2-`, plus an opaque
  `kernel_name` (`""`, or the literal `"undefined.-xfrozen_modules=off"`).
- **server** — the kernel id appears in `/api/kernels` of a server that
  actually answers. Server registrations are pid-checked before being queried,
  since most of them are dead.
- **terminal** — plain UUID name with a readable `kernel_name` such as
  `"python3"`.

It is pattern matching, not a fact, so it returns `unknown` rather than forcing
a label. On the development machine that left 950 of the 1,118 stale files
unclassified, which is the intended conservative behaviour.

## API

```python
from fuchitools.jupyter import list_active_kernels, format_table

for k in list_active_kernels():
    print(k.origin, k.pid, k.cwd)

print(format_table(list_active_kernels()))
```

Or as a script: `python -m fuchitools.jupyter`

```
ORIGIN  PID    STATE     KERNEL ID       STARTED           EXECUTABLE  CWD
vscode  18420  responds  v3a1b2c3d4e5f6  2026-01-15 09:30  python.exe  c:\...\notebooks
vscode  24680  responds  v3d4e5f6a7b8c9  2026-01-15 09:30  python.exe  d:\...\notebooks
```

### `list_active_kernels(timeout=3.0, include_dead=False)`

Returns a list of `KernelInfo` sorted by age, oldest first. `include_dead=True`
also reports stale connection files — there may be thousands.

### `KernelInfo`

| Field | Meaning |
|---|---|
| `connection_file` | `Path` to the `kernel-*.json` |
| `kernel_id` | id parsed out of the file name |
| `pid` | kernel process, when the process sweep found it |
| `origin` | `vscode` / `server` / `terminal` / `unknown` |
| `kernel_name` | as declared in the connection file |
| `ports` | shell, iopub, stdin, control, hb |
| `executable` | interpreter / venv running the kernel |
| `cwd` | working directory — in practice the best way to tell kernels apart |
| `started` | process start time |
| `alive` | there is evidence the kernel exists |
| `responds` | it answered the ping |

### `alive` vs `responds`

The distinction is not cosmetic. A kernel busy running a long cell has its
shell channel blocked, so `wait_for_ready` times out even though the kernel is
perfectly healthy. Verified by running `time.sleep(40)` in a test kernel:

```
direct ping while computing: False
found -> alive=True responds=False origin=terminal
```

`format_table` renders the three resulting states as `responds`, `busy` and
`dead`.

### `execute_in_kernel(kernel, code, timeout=15.0, store_history=False)`

Runs code inside a live kernel and returns an `ExecutionResult` with `output`
(stdout, stderr and the repr of the last expression), `error` (the traceback,
if it raised), `timed_out` and a `success` property. `kernel` may be a
`KernelInfo`, a path to a connection file, or a kernel id.

```python
from fuchitools.jupyter import execute_in_kernel, list_active_kernels

kernel = list_active_kernels()[0]
print(execute_in_kernel(kernel, "print(df.shape)").output)
```

This is a loaded gun: the code runs in someone's live session with full access
to its namespace. `store_history=False` keeps the kernel's `In`/`Out`
numbering untouched — verified, the counter does not move — but nothing stops
the code itself from mutating state. For inspection, work on copies:
`df.copy()`, not `df`.

Raises `KernelUnreachable` when the kernel does not answer within the budget,
which covers both a dead kernel and one busy running something else. The two
cannot be told apart from outside.

Only iopub messages whose `parent_header.msg_id` matches our own request are
collected. iopub is a broadcast channel: without that filter the output of
other clients — the notebook the user is typing in — leaks into the result.

### `shutdown_kernel(kernel, timeout=5.0, force=False)`

Sends a `shutdown_request` on the control channel, which is the clean way: the
kernel runs its exit handlers and closes its sockets. The control channel has
its own thread, so this reaches even a kernel busy on a long cell. Returns
whether the kernel is gone by the time it returns; with `force=True` a process
that has not died by the deadline is killed outright.

Measured: 0.2–0.7 s for the polite path.

### `running_in_kernel()` and `current_kernel()`

`running_in_kernel()` is True under a notebook, JupyterLab, VSCode or
qtconsole. It is False in a plain script and **also in an IPython terminal
session**, which has an interactive shell but no kernel — the check is on the
shell class, `ZMQInteractiveShell` against `TerminalInteractiveShell`.

`current_kernel()` returns the `KernelInfo` of the kernel the calling code is
running in, or None. The connection file comes from ipykernel itself rather
than from any sweep, so it is exact and costs nothing. Its `responds` field is
deliberately left False: pinging your own kernel cannot succeed, because the
shell channel is occupied by the very call asking the question — which is
exactly the `alive but busy` state.

Run from inside a kernel:

```
running_in_kernel: True
id: tmpa1b2c3d4e5 | origin: terminal | pid: 7310
alive: True | responds: False
cwd: c:\proyectos\fuchitools
```

### `kernel_clients(kernel)`

The processes holding an established connection to a kernel, read from the TCP
table so nothing is sent to the kernel. Returns one `ClientInfo` per process
(`pid`, `name`, `executable`, `ports`).

```python
for kernel in list_active_kernels():
    for client in kernel_clients(kernel):
        print(kernel.kernel_id[:14], "<-", client.name, client.pid, client.ports)
```

```
v3a1b2c3d4e5f6 <- Code.exe 21500 [9001, 9002, 9003, 9004]
v3b2c3d4e5f6a7 <- Code.exe 21500 [9016, 9017, 9018, 9019]
v3c3d4e5f6a7b8 <- Code.exe 21500 [9006, 9007, 9013, 9014]
```

The kernel's own process family is filtered out, or the launcher — which holds
the listening sockets — would show up as a client of the kernel it started.

Three limits worth stating plainly:

- **The protocol has no roster of clients.** iopub is a broadcast channel and
  anyone may subscribe without announcing themselves. This is inference from
  open sockets, not an answer from the kernel. It is the same fact that forces
  `execute_in_kernel` to filter on `parent_header`.
- **One VSCode window is one process** multiplexing every notebook, so it
  appears once per kernel with no way to tell which tab is which. What
  separates the notebooks is `notebook_of`, by the other route entirely.
- **An established connection is not an active user** — it may be a tab opened
  yesterday and forgotten.

### `notebook_of(kernel, allow_execution=True, timeout=10.0)`

The document a kernel belongs to. Two routes, tried in order:

1. A server's `/api/sessions`, which maps kernels to documents directly. No
   side effects, but only server launched kernels are in it.
2. The kernel's own namespace: the VSCode extension leaves the notebook path
   in `__vsc_ipynb_file__`, and some frontends set `__session__`. This needs
   code run inside the kernel, hence the switch.

```python
notebook_of(kernel)
# 'c:\\proyectos\\notebooks\\analisis.ipynb'

notebook_of(kernel, allow_execution=False)
# None — no live server knows about a VSCode kernel
```

Measured against three live VSCode kernels, route 2 identified all three
(`analisis.ipynb`, `Untitled-1.ipynb`, `scraping_web.ipynb`) and route 1
none of them, which is exactly what the design predicts.

The probe is a pure read — `globals().get(...)`, no assignment, no history
entry — but it is still somebody's live session, so `allow_execution=False`
exists to keep the choice deliberate.

## Two things that had to be worked around

Both were found by testing against real kernels, and neither is guessable from
the documentation.

**A kernel that has just started reports itself dead.** Called immediately
after `start_kernel()`, `wait_for_ready` raises `RuntimeError: Kernel died
before replying to kernel_info`. Without a parent `KernelManager` the client
judges liveness by the heartbeat channel, which has not begun beating yet.
It clears in well under a second. `_wait_until_ready` therefore retries an
instant failure for a `READY_GRACE` of 2 s. A busy kernel is a different
shape — it consumes the whole budget without answering — so one failure there
is the answer, and the grace period does not stretch the wait.

**Closing the client after a shutdown request hangs forever.** With all
channels open, `stop_channels()` never returns once the kernel is gone;
measured hanging past 5 s in a thread that had to be abandoned. Opening only
the control channel returns in 0.01 s and the kernel dies cleanly. And the
reply must be waited for before closing: without that wait the socket can be
closed before the request is even flushed, which showed up as an intermittent
shutdown that silently did nothing.

## Known limitations

- **A busy kernel the process sweep cannot see is reported as dead.** If the
  process is not inspectable (permissions, another user) the only evidence
  left is the ping, which a busy kernel fails. Treating "port held by a live
  process that does not answer" as alive was considered and rejected: the port
  could belong to any other program. Covering it properly would need a fourth
  state, not a looser `alive`.
- **Local only.** Remote kernels are out of scope; the process sweep is local
  by construction and the ping assumes reachable ports.
- **`include_dead=True` is expensive to consume**, not to produce — it returns
  every stale file in the runtime directories.
- **Talking to a dead kernel costs the whole `timeout`.** `execute_in_kernel`
  on a kernel that is gone took 16 s with the default budget: the client keeps
  believing the heartbeat until the deadline. Pass a smaller `timeout` when the
  kernel may be gone, or check `list_active_kernels` first.
- **`execute_in_kernel` cannot interrupt what it starts.** Code that overruns
  the budget is reported as `timed_out` but keeps running in the kernel.

## Tests

`tests/test_jupyter.py`, 84 tests, ~2s. Entirely synthetic: no kernel is
started, pinged, stopped or inspected, so the suite is safe to run with live
notebooks open. Coverage concentrates on the parts that actually hold logic:

- the four command line spellings of the connection file flag (`-f path`,
  `-f=path`, `--f path`, `--f=path`);
- the launcher/kernel deduplication of the process sweep, asserting that both
  pids are collected — the bug that made the first screening useless;
- all five paths through `_worth_pinging`, including the TCP fallback;
- origin classification against real v2 / v3 / terminal samples;
- four integration tests of `list_active_kernels` with the sweeps mocked:
  join of both sweeps, busy kernel, stale files hidden by default, age order;
- `execute_in_kernel` driven by a fake client: output collection, the
  `parent_header` filter against another client's traffic, tracebacks, the
  history flag, timeout, and the ready retry;
- `shutdown_kernel` against a fake process: polite path, giving up, `force`,
  the fallback with no pid, and an assertion that **only** the control channel
  is opened — the workaround is easy to undo by accident;
- `running_in_kernel` for the three shell cases and `current_kernel` against a
  faked `ipykernel.connect`;
- `kernel_clients` against a faked socket table: grouping by process, the
  exclusion of the kernel's own family, and the states and ports that must be
  ignored;
- `notebook_of` for both routes, including an assertion that the kernel is
  **not** touched when a server already knows the answer, and that
  `allow_execution=False` runs nothing at all.

The functions that talk to real kernels were verified separately, by hand,
against kernels started for the purpose: execution and persistent state
between calls, tracebacks, `store_history` moving the `In` counter or not,
resolution by id, polite shutdown, `force` on a kernel deaf to the request
(simulated with a mismatched HMAC key), and `KernelUnreachable` afterwards.

## Package changes made along the way

- `pyproject.toml` had `dependencies = []` while the package already used
  pandas, selenium and undetected-chromedriver. All of them are now declared,
  together with this module's `psutil`, `jupyter-client` and `jupyter-core`.
  Lower bounds are set below the installed versions so installing does not
  force upgrades. `pytest` and `duckdb` went into a `test` extra — `fuchitools.duckdb`
  takes the connection as an argument and never imports duckdb itself.
- `fuchitools/jupyter.py` is deliberately **not** imported from `__init__.py`,
  following the existing convention: only `datetimes`, `sqlite` and `pandas`
  are, while modules with heavy dependencies (`duckdb`, `selenium`, `misc`) are
  imported explicitly.
- `tests/test_duckdb_update_table.py` imported a non-existent top level
  `duckdb_update_table` module, which broke collection and aborted the whole
  suite. Fixed to `from fuchitools.duckdb import duckdb_update_table`; its 28
  tests now run and pass.

Full suite as of the last change: **212 passed**.

Every public function carries an `Example:` block in its docstring. They are
plain indented code, not `>>>` doctests: several of them print machine
specific output, and doctests that cannot pass are worse than none.

## Prior art in this repo

The module supersedes a throwaway script (`kinspect.py`) written during a data
run, which connected to the last 8 connection files by mtime and executed
inspection code in each. `execute_in_kernel` now
covers what that script did, on top of a listing that tells live kernels from
the 1,118 dead files instead of guessing by modification time.

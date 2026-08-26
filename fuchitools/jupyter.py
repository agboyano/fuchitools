"""Discovery of the Jupyter kernels running on the local machine.

Finds kernels started by any means -- the VSCode Jupyter extension, a
JupyterLab/Notebook server, or `jupyter kernel` from a terminal -- without
relying on a Jupyter server being installed, registered or alive.

The listing comes from a double sweep, because neither available source is
trustworthy on its own:

* The `kernel-*.json` files in the runtime directories are left behind when a
  process dies without shutting down cleanly, so their presence proves
  nothing. Thousands of stale files against a handful of live kernels is the
  normal state of affairs.
* The process table misses kernels whose process cannot be inspected (denied
  permissions) and kernels started with a connection file outside the runtime
  directories.

Both sources are scanned, joined by connection file, and every candidate is
confirmed with a real ping to the kernel. Since a failed ping costs about a
second, files coming only from the second sweep are screened by port first:
see `_worth_pinging`.

On top of the listing, `execute_in_kernel` runs code inside a given kernel and
`shutdown_kernel` stops one. Code running inside a kernel itself can use
`running_in_kernel` and `current_kernel` to find out where it is.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Set, Tuple, Union

try:
    import psutil
    from jupyter_client import BlockingKernelClient
    from jupyter_core.paths import jupyter_path, jupyter_runtime_dir
except ImportError as exc:  # pragma: no cover - depends on the environment
    raise ImportError(
        "fuchitools.jupyter needs the 'jupyter' extra: pip install fuchitools[jupyter]"
    ) from exc

__all__ = [
    "KernelInfo",
    "ClientInfo",
    "ExecutionResult",
    "KernelUnreachable",
    "KernelRef",
    "runtime_dirs",
    "classify_origin",
    "list_active_kernels",
    "execute_in_kernel",
    "shutdown_kernel",
    "running_in_kernel",
    "current_kernel",
    "kernel_clients",
    "notebook_of",
    "format_table",
]

PORT_FIELDS = ("shell_port", "iopub_port", "stdin_port", "control_port", "hb_port")

# the VSCode extension starts kernels raw, with recognisable file names and
# kernel_name values. two generations of the format are in the wild
VSCODE_PREFIXES = ("kernel-v2-", "kernel-v3")
OPAQUE_KERNEL_NAMES = ("undefined", "none")

MAX_WORKERS = 16
PORT_PROBE_TIMEOUT = 0.15

# how long to keep retrying a kernel that reports itself dead the instant it is
# asked; a kernel that has only just started needs a moment to begin beating
READY_GRACE = 2.0


@dataclass
class KernelInfo:
    """A candidate kernel and whatever could be found out about it.

    `alive` means there is evidence the kernel exists: either its process is
    in the process table, or it answered the ping. `responds` is stricter and
    only the ping can set it: a kernel busy running a long cell has its shell
    channel blocked and comes out as `alive=True, responds=False`.
    """

    connection_file: Path
    kernel_id: str = ""
    pid: Optional[int] = None
    origin: str = "unknown"
    kernel_name: Optional[str] = None
    ports: Dict[str, int] = field(default_factory=dict)
    executable: Optional[str] = None
    cwd: Optional[str] = None
    started: Optional[datetime] = None
    alive: bool = False
    responds: bool = False


# --------------------------------------------------------------------------
# directory and file discovery
# --------------------------------------------------------------------------


def _path_key(path: Path) -> str:
    """Deduplication key for paths, case insensitive on Windows."""
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    return os.path.normcase(str(resolved))


def runtime_dirs() -> List[Path]:
    """Existing Jupyter runtime directories, without duplicates.

    `jupyter_path("runtime")` returns one per installation level (environment,
    user, system); `jupyter_runtime_dir()` only returns the preferred one, and
    settling for it is the classic mistake that loses kernels.

    Example:
        for directory in runtime_dirs():
            print(directory, len(list(directory.glob("kernel-*.json"))))

        # C:\\Users\\you\\AppData\\Roaming\\jupyter\\runtime 1118
    """
    candidates = [Path(p) for p in jupyter_path("runtime")]
    candidates.append(Path(jupyter_runtime_dir()))

    from_env = os.environ.get("JUPYTER_RUNTIME_DIR")
    if from_env:
        candidates.append(Path(from_env))

    seen: Set[str] = set()
    dirs = []
    for d in candidates:
        key = _path_key(d)
        if key in seen:
            continue
        seen.add(key)
        try:
            if d.is_dir():
                dirs.append(d)
        except OSError:
            continue
    return dirs


def _connection_files() -> List[Path]:
    """Every `kernel-*.json` in every runtime directory."""
    files: List[Path] = []
    for d in runtime_dirs():
        try:
            files.extend(d.glob("kernel-*.json"))
        except OSError:
            continue
    return files


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    """Load a json file, returning None if it is unreadable or corrupt."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _kernel_id(path: Path) -> str:
    """`kernel-<id>.json` -> `<id>`."""
    name = path.stem
    return name[len("kernel-"):] if name.startswith("kernel-") else name


# --------------------------------------------------------------------------
# process sweep
# --------------------------------------------------------------------------


def _is_kernel_cmdline(cmdline: Optional[Sequence[str]]) -> bool:
    """Recognise the command line of an ipykernel."""
    if not cmdline:
        return False
    return any("ipykernel_launcher" in part or part == "ipykernel" for part in cmdline)


def _connection_file_from_cmdline(cmdline: Sequence[str]) -> Optional[Path]:
    """Pull the connection file path out of a command line.

    All four spellings occur in practice: `-f path`, `-f=path`, `--f path` and
    `--f=path`. A server uses the first one, VSCode the last one.
    """
    for i, part in enumerate(cmdline):
        if part in ("-f", "--f") and i + 1 < len(cmdline):
            return Path(cmdline[i + 1])
        if part.startswith("-"):
            stripped = part.lstrip("-")
            if stripped.startswith("f="):
                return Path(stripped[2:])
    return None


def _is_older(a: KernelInfo, b: KernelInfo) -> bool:
    """True if `a` started before `b`. Unknown start times sort last."""
    if a.started is None:
        return False
    if b.started is None:
        return True
    return a.started < b.started


def _scan_processes() -> Tuple[Dict[str, KernelInfo], Set[int]]:
    """Kernels deduced from the process table.

    Returns:
        A `(kernels, pids)` tuple. `kernels` is keyed by normalised connection
        file; when several processes share one -- the launcher and the kernel
        proper both carry the same command line -- the oldest wins. `pids`
        collects them all without deduplication, which is what later lets a
        listening port be attributed to an already known process family.
    """
    found: Dict[str, KernelInfo] = {}
    pids: Set[int] = set()

    attrs = ["pid", "cmdline", "exe", "create_time", "cwd"]
    for proc in psutil.process_iter(attrs=attrs, ad_value=None):
        try:
            info = proc.info
            if not _is_kernel_cmdline(info.get("cmdline")):
                continue

            path = _connection_file_from_cmdline(info["cmdline"])
            if path is None:
                continue

            if info.get("pid"):
                pids.add(info["pid"])

            create_time = info.get("create_time")
            kernel = KernelInfo(
                connection_file=path,
                kernel_id=_kernel_id(path),
                pid=info.get("pid"),
                executable=info.get("exe"),
                cwd=info.get("cwd"),
                started=datetime.fromtimestamp(create_time) if create_time else None,
                alive=True,
            )
        except (psutil.Error, OSError, ValueError):
            continue

        key = _path_key(path)
        previous = found.get(key)
        if previous is None or _is_older(kernel, previous):
            found[key] = kernel

    return found, pids


# --------------------------------------------------------------------------
# port screening
# --------------------------------------------------------------------------


def _listening_ports() -> Optional[Dict[int, Optional[int]]]:
    """Map `port -> pid` of listening TCP sockets, or None if unavailable.

    This needs privileges that are not always granted; returning None means
    "could not find out", not "there are none".
    """
    try:
        connections = psutil.net_connections(kind="tcp")
    except (psutil.Error, OSError):
        return None

    listening: Dict[int, Optional[int]] = {}
    for c in connections:
        try:
            if c.status == psutil.CONN_LISTEN and c.laddr:
                listening.setdefault(c.laddr.port, c.pid)
        except (AttributeError, IndexError):
            continue
    return listening


def _port_open(ip: str, port: int, timeout: float = PORT_PROBE_TIMEOUT) -> bool:
    """Whether anything accepts connections on the port. Cheap, needs no rights."""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def _worth_pinging(
    data: Optional[Dict[str, Any]],
    listening: Optional[Dict[int, Optional[int]]],
    kernel_pids: Set[int],
) -> bool:
    """Decide whether a stale connection file earns the cost of a ping.

    The screening matters because these files pile up by the thousand and a
    failed ping costs close to a second. Two reasons to discard one:

    * Nobody is listening on its shell port, so the kernel cannot be alive.
    * The port belongs to a process the process sweep already knows. Connection
      files reuse ports heavily (VSCode always starts at 9000), so hundreds of
      dead files point at a live kernel's port; that kernel is already in the
      listing under its own file, and the stale one would add nothing. Note
      the port is usually held by the launcher process rather than by the
      kernel, hence the comparison against every pid in the family instead of
      just the kernel's own.

    With no socket information available this falls back to a direct TCP
    probe, which cannot tell owners apart but still rules out closed ports.
    """
    if not data:
        return False

    port = data.get("shell_port")
    if not isinstance(port, int):
        return False

    if listening is None:
        return _port_open(data.get("ip") or "127.0.0.1", port)

    if port not in listening:
        return False

    return listening[port] not in kernel_pids


# --------------------------------------------------------------------------
# liveness probe
# --------------------------------------------------------------------------


def _responds(connection_file: Path, timeout: float) -> bool:
    """Check that the kernel answers, without disturbing its state.

    Only the client is opened and the `kernel_info_reply` implied by
    `wait_for_ready` is awaited: no code is executed, so the kernel's `In`/`Out`
    history stays untouched. The HMAC signature in the connection file makes
    the check conclusive: a stale file whose port has been inherited by another
    kernel carries a different `key`, its messages are dropped, and the ping
    fails.
    """
    client = BlockingKernelClient()
    try:
        client.load_connection_file(str(connection_file))
        client.start_channels()
        client.wait_for_ready(timeout=timeout)
        return True
    except Exception:
        return False
    finally:
        try:
            client.stop_channels()
        except Exception:
            pass


# --------------------------------------------------------------------------
# origin
# --------------------------------------------------------------------------


def _server_registrations() -> List[Dict[str, Any]]:
    """Registrations of servers whose pid still exists.

    The `jpserver-*.json` files suffer the same problem as connection files:
    they are only removed on a clean shutdown, so a registration proves
    nothing on its own. Checking the pid first is what keeps the dead ones --
    the vast majority -- from costing a network timeout each.
    """
    registrations = []

    files: List[Path] = []
    for d in runtime_dirs():
        try:
            files.extend(d.glob("jpserver-*.json"))
            files.extend(d.glob("nbserver-*.json"))
        except OSError:
            continue

    for path in files:
        data = _read_json(path)
        if not data or not data.get("url"):
            continue
        pid = data.get("pid")
        if isinstance(pid, int) and not psutil.pid_exists(pid):
            continue
        registrations.append(data)

    return registrations


def _server_query(registration: Dict[str, Any], endpoint: str, timeout: float) -> Optional[list]:
    """GET one endpoint of a server's REST API, or None if it does not answer."""
    request = "{}{}".format(registration["url"], endpoint)
    token = registration.get("token")
    if token:
        request = "{}?token={}".format(request, token)

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except (urllib.error.URLError, OSError, ValueError):
        return None

    return payload if isinstance(payload, list) else None


def _live_servers(timeout: float) -> Dict[str, str]:
    """Map `kernel_id -> server url` for the servers that actually answer."""
    kernels: Dict[str, str] = {}

    for registration in _server_registrations():
        listing = _server_query(registration, "api/kernels", timeout)
        for k in listing or []:
            if isinstance(k, dict) and k.get("id"):
                kernels[k["id"]] = registration["url"]

    return kernels


def _server_sessions(timeout: float) -> Dict[str, str]:
    """Map `kernel_id -> notebook path` from every server that answers.

    This is the clean way to tie a kernel to a document, and the only one that
    needs no code run inside the kernel. It exists solely for server launched
    kernels: VSCode never registers a session.
    """
    sessions: Dict[str, str] = {}

    for registration in _server_registrations():
        listing = _server_query(registration, "api/sessions", timeout)
        for session in listing or []:
            if not isinstance(session, dict):
                continue
            kernel_id = (session.get("kernel") or {}).get("id")
            path = session.get("path") or session.get("notebook", {}).get("path")
            if kernel_id and path:
                sessions[kernel_id] = path

    return sessions


def classify_origin(
    connection_file: Path,
    data: Optional[Dict[str, Any]],
    server_kernels: Dict[str, str],
) -> str:
    """Work out who started the kernel: `vscode`, `server`, `terminal` or `unknown`.

    This is a heuristic over the file name and its contents, not a fact: when
    in doubt it returns `unknown` rather than forcing a label.

    Example:
        path = Path("kernel-v36d60449783f1.json")
        classify_origin(path, _read_json(path), _live_servers(2.0))
        # 'vscode'
    """
    if _kernel_id(connection_file) in server_kernels:
        return "server"

    kernel_name = (data or {}).get("kernel_name")
    opaque_name = not kernel_name or str(kernel_name).lower().startswith(OPAQUE_KERNEL_NAMES)

    if connection_file.name.startswith(VSCODE_PREFIXES):
        return "vscode" if opaque_name else "unknown"

    if data is None:
        return "unknown"

    return "unknown" if opaque_name else "terminal"


# --------------------------------------------------------------------------
# public api
# --------------------------------------------------------------------------


def list_active_kernels(
    timeout: float = 3.0,
    include_dead: bool = False,
) -> List[KernelInfo]:
    """List the running Jupyter kernels, whatever their origin.

    Args:
        timeout: Seconds to wait for each kernel ping and for each server
            query. The pings run in parallel.
        include_dead: If True, stale connection files are reported too, with
            `alive=False`. There may be thousands of them.

    Returns:
        A list of KernelInfo sorted by age, oldest first. Kernels with an
        unknown start time go last.

    Example:
        for kernel in list_active_kernels():
            print(kernel.origin, kernel.pid, kernel.cwd)

        # vscode 16864 g:\\arquitectura_gestora\\desarrollo\\notebooks
        # vscode 23040 g:\\arquitectura_gestora\\desarrollo\\fondos\\notebooks

        # the one working on a given notebook
        mine = [k for k in list_active_kernels() if k.cwd == os.getcwd()]
    """
    by_process, kernel_pids = _scan_processes()
    listening = _listening_ports()

    # files from the process sweep are always pinged; of the rest, only those
    # that survive the port screening
    candidates: Dict[str, Path] = {k: v.connection_file for k, v in by_process.items()}
    data_by_key: Dict[str, Optional[Dict[str, Any]]] = {}
    screened_out: Dict[str, Path] = {}

    for path in _connection_files():
        key = _path_key(path)
        if key in candidates or key in screened_out:
            continue
        data = _read_json(path)
        data_by_key[key] = data
        if _worth_pinging(data, listening, kernel_pids):
            candidates[key] = path
        elif include_dead:
            screened_out[key] = path

    if not candidates and not screened_out:
        return []

    keys = list(candidates)
    answers: List[bool] = []
    if keys:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(keys))) as pool:
            answers = list(pool.map(lambda k: _responds(candidates[k], timeout), keys))

    server_kernels = _live_servers(timeout=min(timeout, 2.0))

    kernels = []
    for key, path, responds in _iter_candidates(candidates, keys, answers, screened_out):
        kernel = by_process.get(key) or KernelInfo(
            connection_file=path,
            kernel_id=_kernel_id(path),
        )
        data = data_by_key.get(key)
        if data is None:
            data = _read_json(path)

        kernel.responds = responds
        kernel.alive = kernel.alive or responds
        if data:
            kernel.kernel_name = data.get("kernel_name")
            kernel.ports = {p: data[p] for p in PORT_FIELDS if p in data}
        kernel.origin = classify_origin(path, data, server_kernels)

        if kernel.alive or include_dead:
            kernels.append(kernel)

    kernels.sort(key=lambda k: (k.started is None, k.started or datetime.max))
    return kernels


def _iter_candidates(
    candidates: Dict[str, Path],
    keys: Sequence[str],
    answers: Sequence[bool],
    screened_out: Dict[str, Path],
) -> Iterator[Tuple[str, Path, bool]]:
    """Chain the pinged candidates with the ones the screening threw out."""
    for key, responds in zip(keys, answers):
        yield key, candidates[key], responds
    for key, path in screened_out.items():
        yield key, path, False


# --------------------------------------------------------------------------
# talking to one kernel
# --------------------------------------------------------------------------


KernelRef = Union[KernelInfo, Path, str]


class KernelUnreachable(RuntimeError):
    """The kernel did not answer, so nothing could be sent to it.

    Raised where silence is indistinguishable from death: a kernel busy on a
    long cell cannot be told apart from one that is gone.
    """


@dataclass
class ExecutionResult:
    """What came back from a kernel after running a piece of code."""

    output: str = ""
    error: Optional[str] = None
    timed_out: bool = False

    @property
    def success(self) -> bool:
        return self.error is None and not self.timed_out


def _resolve_connection_file(kernel: KernelRef) -> Path:
    """Accept a KernelInfo, a connection file path or a kernel id."""
    if isinstance(kernel, KernelInfo):
        return kernel.connection_file

    path = Path(kernel)
    try:
        if path.exists():
            return path
    except OSError:
        pass

    wanted = str(kernel)
    for candidate in _connection_files():
        if _kernel_id(candidate) == wanted or candidate.name == wanted:
            return candidate

    raise FileNotFoundError("no connection file matches {!r}".format(kernel))


def _wait_until_ready(client: BlockingKernelClient, path: Path, deadline: float) -> None:
    """Block until the kernel is ready to take work, or give up.

    A kernel that started milliseconds ago has not begun beating yet and
    `wait_for_ready` declares it dead on the spot, so an instant failure is
    retried for a short grace period. A busy kernel is different: it consumes
    the whole budget without answering, and one failure is the answer.

    Raises:
        KernelUnreachable: The kernel is dead, or was still busy at the
            deadline. The two cannot be told apart from here.
    """
    grace = time.monotonic() + READY_GRACE

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise KernelUnreachable("{} did not answer in time".format(path.name))

        try:
            client.wait_for_ready(timeout=remaining)
            return
        except Exception as exc:
            if time.monotonic() >= grace:
                raise KernelUnreachable("{} did not answer".format(path.name)) from exc
            time.sleep(0.1)


def execute_in_kernel(
    kernel: KernelRef,
    code: str,
    timeout: float = 15.0,
    store_history: bool = False,
) -> ExecutionResult:
    """Run `code` inside a running kernel and collect what it prints.

    This is a loaded gun: the code runs in someone's live session with full
    access to its namespace. `store_history` defaults to False so the kernel's
    `In`/`Out` numbering is left alone, but nothing stops the code itself from
    mutating state. For inspection, work on copies -- `df.copy()`, not `df`.

    Args:
        kernel: A KernelInfo, a path to a connection file, or a kernel id.
        code: Python source to execute in the kernel.
        timeout: Budget in seconds for the whole call, connection included.
        store_history: If True the execution counts as a cell and shows up in
            the kernel's `In`/`Out` history.

    Returns:
        An ExecutionResult holding everything the kernel wrote to stdout/stderr
        plus the text representation of the last expression, and the traceback
        if the code raised.

    Raises:
        KernelUnreachable: The kernel did not answer within the budget, either
            because it is dead or because it is busy running something else.
        FileNotFoundError: No connection file matches `kernel`.

    Example:
        kernel = list_active_kernels()[0]

        result = execute_in_kernel(kernel, "print(df.shape)")
        print(result.output)          # (72, 36)

        # inspect without touching the session's own objects
        execute_in_kernel(kernel, "print(df.copy().describe())").output

        result = execute_in_kernel(kernel, "1/0")
        result.success                # False
        "ZeroDivisionError" in result.error

        # a kernel that may be gone: do not spend the full budget on it
        try:
            execute_in_kernel(kernel, "1+1", timeout=3.0)
        except KernelUnreachable:
            pass
    """
    path = _resolve_connection_file(kernel)
    deadline = time.monotonic() + timeout

    client = BlockingKernelClient()
    chunks: List[str] = []
    result = ExecutionResult()

    try:
        client.load_connection_file(str(path))
        client.start_channels()
        _wait_until_ready(client, path, deadline)

        msg_id = client.execute(code, store_history=store_history)

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                result.timed_out = True
                break

            try:
                message = client.get_iopub_msg(timeout=min(1.0, remaining))
            except Exception:
                continue

            # iopub carries traffic from every client of the kernel, so
            # anything not answering our own request has to be dropped
            if message["parent_header"].get("msg_id") != msg_id:
                continue

            kind = message["msg_type"]
            content = message["content"]

            if kind == "stream":
                chunks.append(content.get("text", ""))
            elif kind in ("execute_result", "display_data"):
                chunks.append(content.get("data", {}).get("text/plain", ""))
            elif kind == "error":
                result.error = "\n".join(content.get("traceback", []))
            elif kind == "status" and content.get("execution_state") == "idle":
                break
    finally:
        try:
            client.stop_channels()
        except Exception:
            pass

    result.output = "".join(chunks)
    return result


def shutdown_kernel(
    kernel: KernelRef,
    timeout: float = 5.0,
    force: bool = False,
) -> bool:
    """Stop a running kernel, politely first.

    A `shutdown_request` goes out on the control channel, which is the clean
    way: the kernel runs its exit handlers and closes its sockets. The control
    channel is served by its own thread, so this reaches even a kernel busy on
    a long cell.

    Args:
        kernel: A KernelInfo, a path to a connection file, or a kernel id.
        timeout: Seconds to wait for the process to go away.
        force: If the polite request has not worked by then, kill the process.
            Nothing is flushed and no exit handler runs.

    Returns:
        True if the kernel is gone by the time this returns.

    Example:
        # stop every kernel left over from a directory nobody works in
        for kernel in list_active_kernels():
            if kernel.cwd and "scratch" in kernel.cwd:
                shutdown_kernel(kernel)

        # one that ignores the request
        shutdown_kernel(kernel, timeout=3.0, force=True)
    """
    path = _resolve_connection_file(kernel)

    pid = kernel.pid if isinstance(kernel, KernelInfo) else None
    if pid is None:
        by_process, _ = _scan_processes()
        known = by_process.get(_path_key(path))
        pid = known.pid if known else None

    client = BlockingKernelClient()
    try:
        client.load_connection_file(str(path))
        # only the control channel: `shutdown_request` travels on it, and it is
        # the one channel that tears down cleanly afterwards. Opening the rest
        # makes `stop_channels` block for good once the kernel is gone
        client.start_channels(shell=False, iopub=False, stdin=False, hb=False, control=True)
        client.shutdown()
        # wait for the reply before closing anything: the kernel sends it from
        # an atexit handler, so it doubles as confirmation, and without the
        # wait the socket can be closed before the request is even flushed
        try:
            client.get_control_msg(timeout=timeout)
        except Exception:
            pass
    except Exception:
        pass
    finally:
        try:
            client.stop_channels()
        except Exception:
            pass

    # without a pid the only evidence available is that it stopped answering
    if pid is None:
        return not _responds(path, min(timeout, 2.0))

    try:
        process = psutil.Process(pid)
    except psutil.Error:
        return True

    try:
        process.wait(timeout=timeout)
        return True
    except psutil.TimeoutExpired:
        pass
    except psutil.Error:
        return not process.is_running()

    if not force:
        return not process.is_running()

    try:
        process.kill()
        process.wait(timeout=timeout)
    except psutil.Error:
        pass

    return not process.is_running()


# --------------------------------------------------------------------------
# the kernel we are running in, if any
# --------------------------------------------------------------------------


def running_in_kernel() -> bool:
    """Whether this process is executing inside a Jupyter kernel.

    True under a notebook, JupyterLab, VSCode or qtconsole -- anything driving
    an ipykernel. False in a plain script and also in an IPython terminal
    session, which has an interactive shell but no kernel: the check is on the
    shell class, `ZMQInteractiveShell` against `TerminalInteractiveShell`.

    Example:
        # a progress bar or a plot backend that only makes sense in a notebook
        if running_in_kernel():
            from tqdm.notebook import tqdm
        else:
            from tqdm import tqdm
    """
    try:
        from IPython import get_ipython
    except ImportError:
        return False

    shell = get_ipython()
    return shell is not None and type(shell).__name__ == "ZMQInteractiveShell"


def current_kernel() -> Optional[KernelInfo]:
    """Describe the kernel this code is running in, or None if there is none.

    The connection file comes from ipykernel itself rather than from any of
    the sweeps, so this is exact and costs nothing.

    `responds` is left False on purpose. Pinging your own kernel cannot
    succeed: the shell channel is occupied by the very call asking the
    question, which is precisely the `alive but busy` state.

    Example:
        me = current_kernel()
        if me:
            print(me.kernel_id, me.executable, me.cwd)

        # everything else that is running right now
        others = [k for k in list_active_kernels() if k.pid != me.pid]

        # write output next to the notebook, wherever it was started from
        destination = Path(me.cwd) / "report.xlsx" if me else Path("report.xlsx")
    """
    if not running_in_kernel():
        return None

    try:
        from ipykernel.connect import get_connection_file

        path = Path(get_connection_file())
    except Exception:
        return None

    data = _read_json(path)
    pid = os.getpid()

    started = None
    try:
        started = datetime.fromtimestamp(psutil.Process(pid).create_time())
    except (psutil.Error, OSError, ValueError):
        pass

    return KernelInfo(
        connection_file=path,
        kernel_id=_kernel_id(path),
        pid=pid,
        origin=classify_origin(path, data, _live_servers(timeout=1.0)),
        kernel_name=(data or {}).get("kernel_name"),
        ports={p: data[p] for p in PORT_FIELDS if data and p in data},
        executable=sys.executable,
        cwd=os.getcwd(),
        started=started,
        alive=True,
        responds=False,
    )


# --------------------------------------------------------------------------
# who is attached to a kernel, and to what document
# --------------------------------------------------------------------------


@dataclass
class ClientInfo:
    """A process holding an open connection to a kernel."""

    pid: Optional[int] = None
    name: Optional[str] = None
    executable: Optional[str] = None
    ports: List[int] = field(default_factory=list)


def kernel_clients(kernel: KernelRef) -> List[ClientInfo]:
    """Processes with an established connection to a kernel.

    Read from the TCP table, so nothing is sent to the kernel. The kernel's own
    process family is filtered out: the launcher holds the listening sockets
    and would otherwise show up as a client of the kernel it started.

    What this can and cannot tell you is worth being clear about. The protocol
    has no roster of clients -- iopub is a broadcast channel and anyone may
    subscribe without announcing themselves -- so this is inference from open
    sockets, not an answer from the kernel. A single VSCode window is one
    process multiplexing every notebook, so it appears once per kernel with no
    way to tell which tab is which. And an established connection may just as
    well be a tab opened yesterday and forgotten.

    Args:
        kernel: A KernelInfo, a path to a connection file, or a kernel id.

    Returns:
        One ClientInfo per connected process, `pid` left None where the socket
        table gives no owner. Empty if nothing is attached, or if the TCP table
        could not be read.

    Example:
        for kernel in list_active_kernels():
            for client in kernel_clients(kernel):
                print(kernel.kernel_id, "<-", client.name, client.pid)

        # v36d60449783f1 <- Code.exe 20348
    """
    path = _resolve_connection_file(kernel)
    data = _read_json(path)
    ports = {data[p] for p in PORT_FIELDS if data and isinstance(data.get(p), int)}
    if not ports:
        return []

    try:
        connections = psutil.net_connections(kind="tcp")
    except (psutil.Error, OSError):
        return []

    _, kernel_pids = _scan_processes()

    attached: Dict[Optional[int], Set[int]] = {}
    for c in connections:
        try:
            if c.status != psutil.CONN_ESTABLISHED or not c.raddr:
                continue
            if c.raddr.port not in ports or c.pid in kernel_pids:
                continue
        except (AttributeError, IndexError):
            continue
        attached.setdefault(c.pid, set()).add(c.raddr.port)

    clients = []
    for pid, used in attached.items():
        name = None
        executable = None
        if pid is not None:
            try:
                process = psutil.Process(pid)
                name = process.name()
                executable = process.exe()
            except (psutil.Error, OSError):
                pass
        clients.append(ClientInfo(pid=pid, name=name, executable=executable, ports=sorted(used)))

    clients.sort(key=lambda c: (c.pid is None, c.pid or 0))
    return clients


# a pure read: looks the name up without creating or touching anything
NOTEBOOK_PROBE = (
    "print(next((globals()[_n] for _n in ('__vsc_ipynb_file__', '__session__')"
    " if isinstance(globals().get(_n), str)), ''))"
)


def notebook_of(
    kernel: KernelRef,
    allow_execution: bool = True,
    timeout: float = 10.0,
) -> Optional[str]:
    """The document a kernel belongs to, if it can be established.

    Two routes, tried in that order:

    1. A server's `/api/sessions`, which maps kernels to documents directly.
       Free of side effects, but only server launched kernels are in it.
    2. The kernel's own namespace. The VSCode extension leaves the notebook
       path in `__vsc_ipynb_file__`, and some frontends set `__session__`.
       This needs code run inside the kernel, hence `allow_execution`.

    The probe is a pure read and does not count as a cell, but it is still
    somebody's live session, so the switch is there to keep it deliberate.

    Args:
        kernel: A KernelInfo, a path to a connection file, or a kernel id.
        allow_execution: Whether route 2 may be used. With False, only kernels
            registered with a live server can be resolved.
        timeout: Budget for the server query and for the probe.

    Returns:
        The document path, or None: a terminal kernel has no document, and a
        busy kernel cannot be probed.

    Example:
        notebook_of(list_active_kernels()[0])
        # 'g:\\\\arquitectura_gestora\\\\desarrollo\\\\notebooks\\\\carga_imve.ipynb'

        # without touching the kernel at all
        notebook_of(kernel, allow_execution=False)
        # None, unless a live server knows about it
    """
    path = _resolve_connection_file(kernel)

    session = _server_sessions(timeout=min(timeout, 2.0)).get(_kernel_id(path))
    if session:
        return session

    if not allow_execution:
        return None

    try:
        result = execute_in_kernel(path, NOTEBOOK_PROBE, timeout=timeout)
    except (KernelUnreachable, FileNotFoundError):
        return None

    name = result.output.strip()
    return name or None


def format_table(kernels: Sequence[KernelInfo]) -> str:
    """Render the listing as a fixed width table.

    Example:
        print(format_table(list_active_kernels()))

        # ORIGIN  PID    STATE     KERNEL ID       STARTED           EXECUTABLE  CWD
        # vscode  16864  responds  v36d60449783f1  2026-08-25 13:26  python.exe  g:\\...\\notebooks
    """
    header = ("ORIGIN", "PID", "STATE", "KERNEL ID", "STARTED", "EXECUTABLE", "CWD")

    rows = [header]
    for k in kernels:
        state = "responds" if k.responds else ("busy" if k.alive else "dead")
        rows.append(
            (
                k.origin,
                str(k.pid) if k.pid else "-",
                state,
                k.kernel_id[:14],
                k.started.strftime("%Y-%m-%d %H:%M") if k.started else "-",
                Path(k.executable).name if k.executable else "-",
                k.cwd or "-",
            )
        )

    widths = [max(len(r[i]) for r in rows) for i in range(len(header))]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip() for row in rows)


if __name__ == "__main__":
    active = list_active_kernels()
    if not active:
        print("No Jupyter kernel is running.")
    else:
        print(format_table(active))
        print("\n{} active kernel(s).".format(len(active)))

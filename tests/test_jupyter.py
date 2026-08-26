"""Unit tests for fuchitools.jupyter.

Everything here runs against synthetic data: no kernel is started, pinged or
inspected, so the suite is deterministic and safe to run on a machine with
live notebooks open.
"""

from __future__ import annotations

import json
import os
import sys
import time
import types
from datetime import datetime
from pathlib import Path

import pytest

from fuchitools import jupyter as jup


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


VSCODE_V3 = {
    "key": "037a132c-d522-47a4-b9d0-ca27c9379dcd",
    "signature_scheme": "hmac-sha256",
    "transport": "tcp",
    "ip": "127.0.0.1",
    "hb_port": 9000,
    "control_port": 9001,
    "shell_port": 9002,
    "stdin_port": 9003,
    "iopub_port": 9004,
    "kernel_name": "undefined.-xfrozen_modules=off",
}

TERMINAL = {
    "shell_port": 51261,
    "iopub_port": 51262,
    "stdin_port": 51263,
    "control_port": 51265,
    "hb_port": 51264,
    "ip": "127.0.0.1",
    "key": "d791313d-69bfc35260c837739832c830",
    "transport": "tcp",
    "signature_scheme": "hmac-sha256",
    "kernel_name": "python3",
}


def write_connection_file(directory: Path, name: str, data: dict) -> Path:
    """Drop a connection file into `directory` and return its path."""
    path = directory / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class FakeProcess:
    """Stands in for a psutil.Process as yielded by process_iter(attrs=...)."""

    def __init__(self, **info):
        self.info = info


# --------------------------------------------------------------------------
# file and path helpers
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, expected",
    [
        ("kernel-1234.json", "1234"),
        ("kernel-v36d60449783f1e73.json", "v36d60449783f1e73"),
        ("kernel-v2-10564vnF3ooI9Azwt.json", "v2-10564vnF3ooI9Azwt"),
        ("something-else.json", "something-else"),
    ],
)
def test_kernel_id(name, expected):
    assert jup._kernel_id(Path(name)) == expected


def test_read_json_missing_file(tmp_path):
    assert jup._read_json(tmp_path / "nope.json") is None


def test_read_json_corrupt_file(tmp_path):
    path = tmp_path / "kernel-broken.json"
    path.write_text("{not json", encoding="utf-8")
    assert jup._read_json(path) is None


def test_read_json_rejects_non_mapping(tmp_path):
    """A well formed json that is not an object is as useless as a broken one."""
    path = tmp_path / "kernel-list.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert jup._read_json(path) is None


def test_read_json_ok(tmp_path):
    path = write_connection_file(tmp_path, "kernel-ok.json", TERMINAL)
    assert jup._read_json(path)["shell_port"] == 51261


def test_runtime_dirs_deduplicates_and_drops_missing(tmp_path, monkeypatch):
    real = tmp_path / "runtime"
    real.mkdir()
    missing = tmp_path / "gone"

    # the same directory reported by every source, plus one that does not exist
    monkeypatch.setattr(jup, "jupyter_path", lambda _: [str(real), str(missing)])
    monkeypatch.setattr(jup, "jupyter_runtime_dir", lambda: str(real))
    monkeypatch.setenv("JUPYTER_RUNTIME_DIR", str(real))

    assert jup.runtime_dirs() == [real]


def test_runtime_dirs_keeps_every_installation_level(tmp_path, monkeypatch):
    """jupyter_path returns one directory per level and all of them count."""
    env_level = tmp_path / "env"
    user_level = tmp_path / "user"
    for d in (env_level, user_level):
        d.mkdir()

    monkeypatch.setattr(jup, "jupyter_path", lambda _: [str(env_level), str(user_level)])
    monkeypatch.setattr(jup, "jupyter_runtime_dir", lambda: str(user_level))
    monkeypatch.delenv("JUPYTER_RUNTIME_DIR", raising=False)

    assert jup.runtime_dirs() == [env_level, user_level]


# --------------------------------------------------------------------------
# process sweep
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cmdline, expected",
    [
        (["python.exe", "-m", "ipykernel_launcher", "-f", "k.json"], True),
        (["python", "-m", "ipykernel", "-f", "k.json"], True),
        (["python", "/path/to/ipykernel_launcher.py", "-f", "k.json"], True),
        (["python", "-m", "http.server"], False),
        ([], False),
        (None, False),
    ],
)
def test_is_kernel_cmdline(cmdline, expected):
    assert jup._is_kernel_cmdline(cmdline) is expected


@pytest.mark.parametrize(
    "cmdline, expected",
    [
        # the four spellings seen in the wild
        (["python", "-m", "ipykernel_launcher", "-f", "a.json"], "a.json"),
        (["python", "-m", "ipykernel_launcher", "-f=b.json"], "b.json"),
        (["python", "-m", "ipykernel_launcher", "--f", "c.json"], "c.json"),
        (["python", "-m", "ipykernel_launcher", "--f=d.json"], "d.json"),
        # no connection file at all, or the flag left dangling
        (["python", "-m", "ipykernel_launcher"], None),
        (["python", "-m", "ipykernel_launcher", "-f"], None),
    ],
)
def test_connection_file_from_cmdline(cmdline, expected):
    result = jup._connection_file_from_cmdline(cmdline)
    assert result == (Path(expected) if expected else None)


def test_connection_file_from_cmdline_ignores_other_flags():
    cmdline = ["python", "-Xfrozen_modules=off", "-m", "ipykernel_launcher", "--f=real.json"]
    assert jup._connection_file_from_cmdline(cmdline) == Path("real.json")


def test_is_older_puts_unknown_start_times_last():
    old = jup.KernelInfo(Path("a"), started=datetime(2026, 1, 1))
    new = jup.KernelInfo(Path("b"), started=datetime(2026, 6, 1))
    unknown = jup.KernelInfo(Path("c"), started=None)

    assert jup._is_older(old, new)
    assert not jup._is_older(new, old)
    assert jup._is_older(old, unknown)
    assert not jup._is_older(unknown, old)


def test_scan_processes_keeps_oldest_and_collects_every_pid(tmp_path, monkeypatch):
    """The launcher and the kernel share a command line and a connection file.

    Only one KernelInfo must come out -- the older process, which is the real
    kernel -- but both pids matter: on Windows the ports are held by the
    launcher, and the port screening compares against the whole family.
    """
    path = tmp_path / "kernel-shared.json"
    cmdline = ["python", "-m", "ipykernel_launcher", "--f={}".format(path)]

    processes = [
        FakeProcess(pid=100, cmdline=cmdline, exe="python.exe", create_time=1000.0, cwd="/a"),
        FakeProcess(pid=200, cmdline=cmdline, exe="python.exe", create_time=2000.0, cwd="/a"),
        FakeProcess(pid=300, cmdline=["python", "-m", "http.server"], exe="python.exe",
                    create_time=1500.0, cwd="/b"),
    ]
    monkeypatch.setattr(jup.psutil, "process_iter", lambda **kw: iter(processes))

    kernels, pids = jup._scan_processes()

    assert len(kernels) == 1
    assert list(kernels.values())[0].pid == 100
    assert pids == {100, 200}


def test_scan_processes_survives_unreadable_process(tmp_path, monkeypatch):
    """One process blowing up must not abort the whole sweep."""
    path = tmp_path / "kernel-good.json"
    good = FakeProcess(
        pid=100,
        cmdline=["python", "-m", "ipykernel_launcher", "-f", str(path)],
        exe="python.exe",
        create_time=1000.0,
        cwd="/a",
    )

    class Exploding(FakeProcess):
        @property
        def info(self):
            raise jup.psutil.AccessDenied(pid=999)

        @info.setter
        def info(self, value):
            pass

    monkeypatch.setattr(jup.psutil, "process_iter", lambda **kw: iter([Exploding(), good]))

    kernels, pids = jup._scan_processes()

    assert pids == {100}


# --------------------------------------------------------------------------
# port screening
# --------------------------------------------------------------------------


def test_worth_pinging_without_data():
    assert jup._worth_pinging(None, {}, set()) is False


def test_worth_pinging_without_usable_port():
    assert jup._worth_pinging({"shell_port": "9002"}, {}, set()) is False
    assert jup._worth_pinging({}, {}, set()) is False


def test_worth_pinging_port_not_listening():
    assert jup._worth_pinging(VSCODE_V3, {8888: 1}, set()) is False


def test_worth_pinging_port_owned_by_known_family():
    """The commonest case: a stale file pointing at a live kernel's port.

    VSCode reuses ports from 9000 up, so hundreds of dead files share the port
    of a running kernel. That kernel is already listed under its own file, and
    the port is held by its launcher (pid 500 here), not by the kernel itself
    (pid 501) -- which is why the whole family is passed in.
    """
    listening = {9002: 500}
    assert jup._worth_pinging(VSCODE_V3, listening, {500, 501}) is False


def test_worth_pinging_port_owned_by_unknown_process():
    """A live kernel whose process could not be inspected still gets a ping."""
    listening = {9002: 700}
    assert jup._worth_pinging(VSCODE_V3, listening, {500, 501}) is True


def test_worth_pinging_falls_back_to_tcp_probe(monkeypatch):
    """With no socket table available, an open port is enough to earn a ping."""
    probed = []

    def fake_probe(ip, port, timeout=jup.PORT_PROBE_TIMEOUT):
        probed.append((ip, port))
        return True

    monkeypatch.setattr(jup, "_port_open", fake_probe)

    assert jup._worth_pinging(VSCODE_V3, None, {500}) is True
    assert probed == [("127.0.0.1", 9002)]


def test_worth_pinging_tcp_probe_defaults_to_localhost(monkeypatch):
    monkeypatch.setattr(jup, "_port_open", lambda ip, port, timeout=0.1: ip == "127.0.0.1")
    data = dict(VSCODE_V3)
    del data["ip"]
    assert jup._worth_pinging(data, None, set()) is True


# --------------------------------------------------------------------------
# origin
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, data, expected",
    [
        # VSCode: recognisable prefix plus an opaque kernel_name
        ("kernel-v36d60449783f1e73.json", VSCODE_V3, "vscode"),
        ("kernel-v2-10564vnF3ooI9Azwt.json", {"kernel_name": ""}, "vscode"),
        # a VSCode looking name with a real kernel_name is not a pattern we know
        ("kernel-v36d60449783f1e73.json", {"kernel_name": "python3"}, "unknown"),
        # plain uuid plus a readable kernel_name: started from a terminal
        ("kernel-f6b25f29-31f1-4613.json", TERMINAL, "terminal"),
        # nothing to go on
        ("kernel-f6b25f29-31f1-4613.json", {"kernel_name": ""}, "unknown"),
        ("kernel-f6b25f29-31f1-4613.json", None, "unknown"),
    ],
)
def test_classify_origin(name, data, expected):
    assert jup.classify_origin(Path(name), data, {}) == expected


def test_classify_origin_server_wins_over_file_name():
    """A kernel claimed by a live server is a server kernel, whatever its name."""
    name = Path("kernel-v36d60449783f1e73.json")
    server_kernels = {"v36d60449783f1e73": "http://localhost:8888/"}
    assert jup.classify_origin(name, VSCODE_V3, server_kernels) == "server"


# --------------------------------------------------------------------------
# public api
# --------------------------------------------------------------------------


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    """An isolated runtime directory with no server registrations in it."""
    directory = tmp_path / "runtime"
    directory.mkdir()
    monkeypatch.setattr(jup, "jupyter_path", lambda _: [str(directory)])
    monkeypatch.setattr(jup, "jupyter_runtime_dir", lambda: str(directory))
    monkeypatch.delenv("JUPYTER_RUNTIME_DIR", raising=False)
    monkeypatch.setattr(jup, "_live_servers", lambda timeout: {})
    return directory


def test_list_active_kernels_joins_both_sweeps(runtime, monkeypatch):
    """Each sweep contributes what the other cannot see.

    `from_process` is only in the process table (its file lives outside the
    runtime directory) and never answers the ping; the process is evidence
    enough. `on_disk` is only on disk, with its port held by an unknown
    process. Both must come out, and the stale file must not.
    """
    outside = runtime.parent / "kernel-from-process.json"
    write_connection_file(runtime.parent, "kernel-from-process.json", TERMINAL)
    on_disk = write_connection_file(runtime, "kernel-v3fromfile.json", VSCODE_V3)
    write_connection_file(runtime, "kernel-v3stale.json", dict(VSCODE_V3, shell_port=9010))

    from_process = jup.KernelInfo(
        connection_file=outside,
        kernel_id="from-process",
        pid=100,
        started=datetime(2026, 1, 1),
        alive=True,
    )
    monkeypatch.setattr(
        jup, "_scan_processes", lambda: ({jup._path_key(outside): from_process}, {100})
    )
    # nobody listens on the stale file's port, so it never reaches the ping
    monkeypatch.setattr(jup, "_listening_ports", lambda: {9002: 700})
    monkeypatch.setattr(jup, "_responds", lambda path, timeout: path == on_disk)

    kernels = jup.list_active_kernels()
    files = {k.connection_file for k in kernels}

    assert files == {outside, on_disk}
    assert [k.responds for k in kernels if k.connection_file == outside] == [False]


def test_list_active_kernels_marks_busy_kernel_alive(runtime, monkeypatch):
    """A kernel stuck on a long cell has a process but never answers the ping."""
    path = write_connection_file(runtime, "kernel-busy.json", TERMINAL)
    busy = jup.KernelInfo(connection_file=path, kernel_id="busy", pid=100, alive=True)

    monkeypatch.setattr(jup, "_scan_processes", lambda: ({jup._path_key(path): busy}, {100}))
    monkeypatch.setattr(jup, "_listening_ports", lambda: {})
    monkeypatch.setattr(jup, "_responds", lambda path, timeout: False)

    kernel = jup.list_active_kernels()[0]

    assert kernel.alive is True
    assert kernel.responds is False


def test_list_active_kernels_hides_stale_files_by_default(runtime, monkeypatch):
    write_connection_file(runtime, "kernel-v3stale.json", VSCODE_V3)
    monkeypatch.setattr(jup, "_scan_processes", lambda: ({}, set()))
    monkeypatch.setattr(jup, "_listening_ports", lambda: {})
    monkeypatch.setattr(jup, "_responds", lambda path, timeout: False)

    assert jup.list_active_kernels() == []

    stale = jup.list_active_kernels(include_dead=True)
    assert len(stale) == 1
    assert stale[0].alive is False
    assert stale[0].origin == "vscode"
    assert stale[0].ports["shell_port"] == 9002


def test_list_active_kernels_sorted_by_age(runtime, monkeypatch):
    files = {}
    for name, when in (("old", datetime(2026, 1, 1)), ("new", datetime(2026, 6, 1)), ("none", None)):
        path = write_connection_file(runtime, "kernel-{}.json".format(name), TERMINAL)
        files[jup._path_key(path)] = jup.KernelInfo(
            connection_file=path, kernel_id=name, pid=1, started=when, alive=True
        )

    monkeypatch.setattr(jup, "_scan_processes", lambda: (files, {1}))
    monkeypatch.setattr(jup, "_listening_ports", lambda: {})
    monkeypatch.setattr(jup, "_responds", lambda path, timeout: True)

    assert [k.kernel_id for k in jup.list_active_kernels()] == ["old", "new", "none"]


def test_list_active_kernels_empty_when_nothing_found(runtime, monkeypatch):
    monkeypatch.setattr(jup, "_scan_processes", lambda: ({}, set()))
    monkeypatch.setattr(jup, "_listening_ports", lambda: {})
    assert jup.list_active_kernels() == []


def test_format_table_reports_the_three_states():
    kernels = [
        jup.KernelInfo(Path("kernel-a.json"), kernel_id="a", pid=1, origin="vscode",
                       alive=True, responds=True),
        jup.KernelInfo(Path("kernel-b.json"), kernel_id="b", pid=2, origin="terminal",
                       alive=True, responds=False),
        jup.KernelInfo(Path("kernel-c.json"), kernel_id="c", origin="unknown"),
    ]

    lines = jup.format_table(kernels).splitlines()

    assert lines[0].startswith("ORIGIN")
    assert "responds" in lines[1]
    assert "busy" in lines[2]
    assert "dead" in lines[3]


def test_format_table_columns_line_up():
    kernels = [
        jup.KernelInfo(Path("k.json"), kernel_id="short", pid=1, origin="vscode", alive=True),
        jup.KernelInfo(Path("k.json"), kernel_id="a-much-longer-id", pid=123456,
                       origin="terminal", alive=True),
    ]

    lines = jup.format_table(kernels).splitlines()
    starts = {line.index("busy") for line in lines[1:]}

    assert len(starts) == 1


# --------------------------------------------------------------------------
# talking to one kernel
# --------------------------------------------------------------------------


class FakeClient:
    """Stands in for BlockingKernelClient.

    `messages` is the iopub traffic it hands out, one per get_iopub_msg call,
    after which it raises the way an empty queue does.
    """

    last = None

    def __init__(self, messages=(), ready=True):
        self.messages = list(messages)
        self.ready = ready
        self.loaded = None
        self.channels = None
        self.code = None
        self.store_history = None
        self.stopped = False
        self.shutdown_called = False
        self.ready_calls = 0
        FakeClient.last = self

    def load_connection_file(self, path):
        self.loaded = path

    def start_channels(self, **kwargs):
        self.channels = kwargs

    def wait_for_ready(self, timeout):
        self.ready_calls += 1
        if not self.ready:
            raise RuntimeError("Kernel died before replying to kernel_info")

    def execute(self, code, store_history=False):
        self.code = code
        self.store_history = store_history
        return "msg-1"

    def get_iopub_msg(self, timeout):
        if not self.messages:
            raise RuntimeError("empty")
        return self.messages.pop(0)

    def get_control_msg(self, timeout):
        return {}

    def shutdown(self):
        self.shutdown_called = True

    def stop_channels(self):
        self.stopped = True


def iopub(msg_type, content, parent="msg-1"):
    return {"msg_type": msg_type, "content": content, "parent_header": {"msg_id": parent}}


IDLE = iopub("status", {"execution_state": "idle"})


@pytest.fixture
def fake_client(monkeypatch):
    """Install a FakeClient factory in place of BlockingKernelClient."""

    def install(messages=(), ready=True):
        monkeypatch.setattr(jup, "BlockingKernelClient", lambda: FakeClient(messages, ready))

    return install


def test_resolve_connection_file_from_kernel_info():
    kernel = jup.KernelInfo(Path("somewhere/kernel-a.json"))
    assert jup._resolve_connection_file(kernel) == Path("somewhere/kernel-a.json")


def test_resolve_connection_file_from_existing_path(tmp_path):
    path = write_connection_file(tmp_path, "kernel-a.json", TERMINAL)
    assert jup._resolve_connection_file(str(path)) == path


def test_resolve_connection_file_from_kernel_id(tmp_path, monkeypatch):
    path = write_connection_file(tmp_path, "kernel-abc123.json", TERMINAL)
    monkeypatch.setattr(jup, "_connection_files", lambda: [path])

    assert jup._resolve_connection_file("abc123") == path
    assert jup._resolve_connection_file("kernel-abc123.json") == path


def test_resolve_connection_file_unknown(monkeypatch):
    monkeypatch.setattr(jup, "_connection_files", lambda: [])
    with pytest.raises(FileNotFoundError):
        jup._resolve_connection_file("nothing-like-this")


@pytest.mark.parametrize(
    "error, timed_out, success",
    [(None, False, True), ("boom", False, False), (None, True, False), ("boom", True, False)],
)
def test_execution_result_success(error, timed_out, success):
    assert jup.ExecutionResult("out", error, timed_out).success is success


def test_execute_in_kernel_collects_output(tmp_path, fake_client):
    path = write_connection_file(tmp_path, "kernel-a.json", TERMINAL)
    fake_client([
        iopub("stream", {"text": "hello\n"}),
        iopub("execute_result", {"data": {"text/plain": "42"}}),
        IDLE,
    ])

    result = jup.execute_in_kernel(path, "print(1)\n42")

    assert result.output == "hello\n42"
    assert result.success
    assert FakeClient.last.stopped


def test_execute_in_kernel_ignores_other_clients_traffic(tmp_path, fake_client):
    """iopub is broadcast, so anything not replying to our request is noise."""
    path = write_connection_file(tmp_path, "kernel-a.json", TERMINAL)
    fake_client([
        iopub("stream", {"text": "someone else\n"}, parent="another-msg"),
        iopub("stream", {"text": "ours\n"}),
        IDLE,
    ])

    assert jup.execute_in_kernel(path, "pass").output == "ours\n"


def test_execute_in_kernel_reports_traceback(tmp_path, fake_client):
    path = write_connection_file(tmp_path, "kernel-a.json", TERMINAL)
    fake_client([
        iopub("error", {"traceback": ["Traceback", "ZeroDivisionError: division by zero"]}),
        IDLE,
    ])

    result = jup.execute_in_kernel(path, "1/0")

    assert not result.success
    assert "ZeroDivisionError" in result.error


def test_execute_in_kernel_keeps_history_clean_by_default(tmp_path, fake_client):
    path = write_connection_file(tmp_path, "kernel-a.json", TERMINAL)
    fake_client([IDLE])

    jup.execute_in_kernel(path, "pass")
    assert FakeClient.last.store_history is False

    fake_client([IDLE])
    jup.execute_in_kernel(path, "pass", store_history=True)
    assert FakeClient.last.store_history is True


def test_execute_in_kernel_times_out(tmp_path, fake_client):
    """No idle message ever arrives: the budget runs out and says so."""
    path = write_connection_file(tmp_path, "kernel-a.json", TERMINAL)
    fake_client([iopub("stream", {"text": "partial"})])

    result = jup.execute_in_kernel(path, "while True: pass", timeout=0.3)

    assert result.timed_out
    assert not result.success
    assert result.output == "partial"


def test_execute_in_kernel_unreachable(tmp_path, fake_client, monkeypatch):
    path = write_connection_file(tmp_path, "kernel-a.json", TERMINAL)
    monkeypatch.setattr(jup, "READY_GRACE", 0.0)
    fake_client(ready=False)

    with pytest.raises(jup.KernelUnreachable):
        jup.execute_in_kernel(path, "pass", timeout=1.0)


def test_wait_until_ready_retries_a_just_started_kernel():
    """A kernel that has only just started reports itself dead, then works."""

    class Flaky(FakeClient):
        def wait_for_ready(self, timeout):
            self.ready_calls += 1
            if self.ready_calls < 3:
                raise RuntimeError("Kernel died before replying to kernel_info")

    client = Flaky()
    jup._wait_until_ready(client, Path("kernel-a.json"), time.monotonic() + 5.0)

    assert client.ready_calls == 3


class FakeHandle:
    """Stands in for psutil.Process in the shutdown path."""

    def __init__(self, dies_on_request=True):
        self.dies_on_request = dies_on_request
        self.killed = False

    def wait(self, timeout=None):
        if self.dies_on_request or self.killed:
            return 0
        raise jup.psutil.TimeoutExpired(timeout)

    def kill(self):
        self.killed = True

    def is_running(self):
        return not (self.dies_on_request or self.killed)


def test_shutdown_kernel_asks_politely(tmp_path, fake_client, monkeypatch):
    path = write_connection_file(tmp_path, "kernel-a.json", TERMINAL)
    fake_client()
    handle = FakeHandle(dies_on_request=True)
    monkeypatch.setattr(jup.psutil, "Process", lambda pid: handle)

    assert jup.shutdown_kernel(jup.KernelInfo(path, pid=100)) is True
    assert FakeClient.last.shutdown_called
    assert not handle.killed


def test_shutdown_kernel_only_opens_the_control_channel(tmp_path, fake_client, monkeypatch):
    """Opening the other channels makes stop_channels block once it is gone."""
    path = write_connection_file(tmp_path, "kernel-a.json", TERMINAL)
    fake_client()
    monkeypatch.setattr(jup.psutil, "Process", lambda pid: FakeHandle())

    jup.shutdown_kernel(jup.KernelInfo(path, pid=100))

    assert FakeClient.last.channels == {
        "shell": False,
        "iopub": False,
        "stdin": False,
        "hb": False,
        "control": True,
    }


def test_shutdown_kernel_gives_up_without_force(tmp_path, fake_client, monkeypatch):
    path = write_connection_file(tmp_path, "kernel-a.json", TERMINAL)
    fake_client()
    handle = FakeHandle(dies_on_request=False)
    monkeypatch.setattr(jup.psutil, "Process", lambda pid: handle)

    assert jup.shutdown_kernel(jup.KernelInfo(path, pid=100), timeout=0.1) is False
    assert not handle.killed


def test_shutdown_kernel_force_kills(tmp_path, fake_client, monkeypatch):
    path = write_connection_file(tmp_path, "kernel-a.json", TERMINAL)
    fake_client()
    handle = FakeHandle(dies_on_request=False)
    monkeypatch.setattr(jup.psutil, "Process", lambda pid: handle)

    assert jup.shutdown_kernel(jup.KernelInfo(path, pid=100), timeout=0.1, force=True) is True
    assert handle.killed


def test_shutdown_kernel_without_pid_falls_back_to_the_ping(tmp_path, fake_client, monkeypatch):
    """With no process to watch, silence is the only evidence available."""
    path = write_connection_file(tmp_path, "kernel-a.json", TERMINAL)
    fake_client()
    monkeypatch.setattr(jup, "_scan_processes", lambda: ({}, set()))
    monkeypatch.setattr(jup, "_responds", lambda path, timeout: False)

    assert jup.shutdown_kernel(path) is True


# --------------------------------------------------------------------------
# the kernel we are running in
# --------------------------------------------------------------------------


def install_shell(monkeypatch, shell_class_name):
    """Fake IPython.get_ipython returning a shell of the given class, or None."""
    module = types.ModuleType("IPython")
    if shell_class_name is None:
        module.get_ipython = lambda: None
    else:
        shell = type(shell_class_name, (), {})()
        module.get_ipython = lambda: shell
    monkeypatch.setitem(sys.modules, "IPython", module)


@pytest.mark.parametrize(
    "shell_class_name, expected",
    [
        ("ZMQInteractiveShell", True),
        # ipython in a terminal has a shell but no kernel
        ("TerminalInteractiveShell", False),
        # plain script
        (None, False),
    ],
)
def test_running_in_kernel(monkeypatch, shell_class_name, expected):
    install_shell(monkeypatch, shell_class_name)
    assert jup.running_in_kernel() is expected


def test_current_kernel_outside_a_kernel(monkeypatch):
    monkeypatch.setattr(jup, "running_in_kernel", lambda: False)
    assert jup.current_kernel() is None


def test_current_kernel_describes_this_process(tmp_path, monkeypatch):
    path = write_connection_file(tmp_path, "kernel-v3self.json", VSCODE_V3)

    monkeypatch.setattr(jup, "running_in_kernel", lambda: True)
    monkeypatch.setattr(jup, "_live_servers", lambda timeout: {})
    module = types.ModuleType("ipykernel.connect")
    module.get_connection_file = lambda app=None: str(path)
    monkeypatch.setitem(sys.modules, "ipykernel.connect", module)

    kernel = jup.current_kernel()

    assert kernel.connection_file == path
    assert kernel.pid == os.getpid()
    assert kernel.executable == sys.executable
    assert kernel.cwd == os.getcwd()
    assert kernel.origin == "vscode"
    assert kernel.ports["shell_port"] == 9002
    assert kernel.alive is True
    # pinging yourself cannot work: the shell channel is busy with this call
    assert kernel.responds is False


# --------------------------------------------------------------------------
# who is attached to a kernel, and to what document
# --------------------------------------------------------------------------


class FakeConnection:
    """Stands in for a psutil sconn record."""

    def __init__(self, port, pid, status=None, remote=True):
        self.status = status if status is not None else jup.psutil.CONN_ESTABLISHED
        self.raddr = types.SimpleNamespace(ip="127.0.0.1", port=port) if remote else None
        self.laddr = types.SimpleNamespace(ip="127.0.0.1", port=port)
        self.pid = pid


def install_connections(monkeypatch, connections, kernel_pids=frozenset()):
    monkeypatch.setattr(jup.psutil, "net_connections", lambda kind="tcp": connections)
    monkeypatch.setattr(jup, "_scan_processes", lambda: ({}, set(kernel_pids)))
    monkeypatch.setattr(
        jup.psutil, "Process", lambda pid: types.SimpleNamespace(
            name=lambda: "Code.exe", exe=lambda: r"C:\VSCode\Code.exe"
        )
    )


def test_kernel_clients_groups_ports_by_process(tmp_path, monkeypatch):
    path = write_connection_file(tmp_path, "kernel-a.json", VSCODE_V3)
    install_connections(monkeypatch, [
        FakeConnection(9001, 20348),
        FakeConnection(9002, 20348),
        FakeConnection(9004, 20348),
    ])

    clients = jup.kernel_clients(path)

    assert len(clients) == 1
    assert clients[0].pid == 20348
    assert clients[0].name == "Code.exe"
    assert clients[0].ports == [9001, 9002, 9004]


def test_kernel_clients_excludes_the_kernels_own_family(tmp_path, monkeypatch):
    """The launcher holds the listening sockets and is not a client."""
    path = write_connection_file(tmp_path, "kernel-a.json", VSCODE_V3)
    install_connections(
        monkeypatch,
        [FakeConnection(9002, 16516), FakeConnection(9002, 20348)],
        kernel_pids={16516, 16864},
    )

    assert [c.pid for c in jup.kernel_clients(path)] == [20348]


def test_kernel_clients_ignores_other_ports_and_states(tmp_path, monkeypatch):
    path = write_connection_file(tmp_path, "kernel-a.json", VSCODE_V3)
    install_connections(monkeypatch, [
        FakeConnection(9002, 20348, status=jup.psutil.CONN_LISTEN),
        FakeConnection(8888, 20348),
        FakeConnection(9002, 20348, remote=False),
        FakeConnection(9003, 777),
    ])

    assert [c.pid for c in jup.kernel_clients(path)] == [777]


def test_kernel_clients_without_a_socket_table(tmp_path, monkeypatch):
    path = write_connection_file(tmp_path, "kernel-a.json", VSCODE_V3)

    def denied(kind="tcp"):
        raise jup.psutil.AccessDenied(pid=1)

    monkeypatch.setattr(jup.psutil, "net_connections", denied)

    assert jup.kernel_clients(path) == []


def test_kernel_clients_without_ports(tmp_path, monkeypatch):
    """A connection file with no ports cannot be matched against anything."""
    path = write_connection_file(tmp_path, "kernel-a.json", {"kernel_name": "python3"})
    assert jup.kernel_clients(path) == []


def test_notebook_of_prefers_the_server_session(tmp_path, monkeypatch):
    path = write_connection_file(tmp_path, "kernel-abc.json", TERMINAL)
    monkeypatch.setattr(jup, "_server_sessions", lambda timeout: {"abc": "work/analysis.ipynb"})

    def must_not_run(*args, **kwargs):
        raise AssertionError("the kernel must not be touched when a server knows")

    monkeypatch.setattr(jup, "execute_in_kernel", must_not_run)

    assert jup.notebook_of(path) == "work/analysis.ipynb"


def test_notebook_of_falls_back_to_the_kernel_namespace(tmp_path, monkeypatch):
    path = write_connection_file(tmp_path, "kernel-v3abc.json", VSCODE_V3)
    monkeypatch.setattr(jup, "_server_sessions", lambda timeout: {})
    monkeypatch.setattr(
        jup, "execute_in_kernel",
        lambda k, code, timeout=None: jup.ExecutionResult(output="notebooks/carga_imve.ipynb\n"),
    )

    assert jup.notebook_of(path) == "notebooks/carga_imve.ipynb"


def test_notebook_of_can_refuse_to_touch_the_kernel(tmp_path, monkeypatch):
    path = write_connection_file(tmp_path, "kernel-v3abc.json", VSCODE_V3)
    monkeypatch.setattr(jup, "_server_sessions", lambda timeout: {})

    def must_not_run(*args, **kwargs):
        raise AssertionError("allow_execution=False must not run anything")

    monkeypatch.setattr(jup, "execute_in_kernel", must_not_run)

    assert jup.notebook_of(path, allow_execution=False) is None


def test_notebook_of_when_the_kernel_has_no_document(tmp_path, monkeypatch):
    """A terminal kernel answers the probe with an empty line."""
    path = write_connection_file(tmp_path, "kernel-abc.json", TERMINAL)
    monkeypatch.setattr(jup, "_server_sessions", lambda timeout: {})
    monkeypatch.setattr(
        jup, "execute_in_kernel",
        lambda k, code, timeout=None: jup.ExecutionResult(output="\n"),
    )

    assert jup.notebook_of(path) is None


def test_notebook_of_unreachable_kernel(tmp_path, monkeypatch):
    path = write_connection_file(tmp_path, "kernel-abc.json", TERMINAL)
    monkeypatch.setattr(jup, "_server_sessions", lambda timeout: {})

    def unreachable(*args, **kwargs):
        raise jup.KernelUnreachable("gone")

    monkeypatch.setattr(jup, "execute_in_kernel", unreachable)

    assert jup.notebook_of(path) is None


def test_server_sessions_maps_kernels_to_documents(monkeypatch):
    monkeypatch.setattr(jup, "_server_registrations", lambda: [{"url": "http://localhost:8888/"}])
    monkeypatch.setattr(
        jup, "_server_query",
        lambda registration, endpoint, timeout: [
            {"kernel": {"id": "abc"}, "path": "work/one.ipynb"},
            {"kernel": {"id": "def"}, "path": "work/two.ipynb"},
            {"no kernel": True},
        ],
    )

    assert jup._server_sessions(1.0) == {"abc": "work/one.ipynb", "def": "work/two.ipynb"}


def test_server_registrations_skips_dead_pids(tmp_path, monkeypatch):
    """A registration outlives its server, so the pid is what decides."""
    alive = tmp_path / "jpserver-100.json"
    alive.write_text(json.dumps({"pid": 100, "url": "http://localhost:8888/"}), encoding="utf-8")
    dead = tmp_path / "jpserver-200.json"
    dead.write_text(json.dumps({"pid": 200, "url": "http://localhost:9999/"}), encoding="utf-8")

    monkeypatch.setattr(jup, "runtime_dirs", lambda: [tmp_path])
    monkeypatch.setattr(jup.psutil, "pid_exists", lambda pid: pid == 100)

    assert [r["pid"] for r in jup._server_registrations()] == [100]

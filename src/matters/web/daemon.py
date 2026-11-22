"""Running the viewer in the background, and finding it again.

One small file per running viewer, so `matters stop` and `matters status` can find
it: serve-<port>.pid in matters' state folder (see matters.paths). A viewer started
with `matters start` writes its output next to it, to serve-<port>.log.
"""

import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import FrameType

from matters.paths import state_dir


def running(port: int) -> int | None:
    """The pid of the viewer serving this port, if one is. Clears stale records."""
    record = _record(port)
    try:
        pid = int(record.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None
    if _alive(pid) and _is_matters(pid):
        return pid
    record.unlink(missing_ok=True)
    return None


@dataclass(frozen=True, slots=True)
class Started:
    pid: int | None  # None: it exited before it was serving; the log says why
    log: Path
    already: bool = False


def start(port: int, timeout: float = 10.0) -> Started:
    """Start `matters serve` detached from this terminal; return once it is serving.

    It runs in its own session, so closing the terminal does not stop it."""
    log = log_path(port)
    if pid := running(port):
        return Started(pid, log, already=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "matters", "serve", "--no-open", "--port", str(port)]
    with log.open("ab") as out:
        child = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if child.poll() is not None:
            return Started(None, log)
        if running(port) == child.pid and _listening(port):
            child.returncode = 0  # it outlives us on purpose: nothing to reap here
            return Started(child.pid, log)
        time.sleep(0.1)
    return Started(child.pid if child.poll() is None else None, log)


def status() -> dict[int, int]:
    """Every running viewer: port -> pid."""
    return {port: pid for port in _recorded_ports() if (pid := running(port))}


def log_path(port: int) -> Path:
    return state_dir() / f"serve-{port}.log"


def _listening(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.2)
        return probe.connect_ex(("127.0.0.1", port)) == 0


@contextmanager
def recorded(port: int) -> Iterator[None]:
    """Record this process as the viewer for `port`; let SIGTERM stop it like Ctrl+C."""
    record = _record(port)
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(str(os.getpid()))
    previous = signal.signal(signal.SIGTERM, _interrupt)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)
        if record.exists() and record.read_text().strip() == str(os.getpid()):
            record.unlink()


def stop(port: int | None = None, timeout: float = 3.0) -> list[int]:
    """Stop the viewer on `port`, or every recorded viewer. Returns the ports stopped."""
    ports = [port] if port is not None else _recorded_ports()
    stopped = []
    for each in ports:
        pid = running(each)
        if pid is None:
            continue
        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + timeout
        while _alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        _record(each).unlink(missing_ok=True)
        stopped.append(each)
    return stopped


def _record(port: int) -> Path:
    return state_dir() / f"serve-{port}.pid"


def _recorded_ports() -> list[int]:
    ports = (p.stem.removeprefix("serve-") for p in state_dir().glob("serve-*.pid"))
    return sorted(int(p) for p in ports if p.isdigit())


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A child that has exited but not been reaped still answers signal 0.
    try:
        reaped, _ = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return True
    return reaped == 0


def _is_matters(pid: int) -> bool:
    """Guard against pid reuse: only ever signal a process that is running matters."""
    command = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, check=False
    ).stdout
    return "matters" in command


def _interrupt(signum: int, frame: FrameType | None) -> None:
    raise KeyboardInterrupt

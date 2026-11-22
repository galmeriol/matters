import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from matters.web import daemon


@pytest.fixture(autouse=True)
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("MATTERS_STATE_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def viewer_process() -> Iterator[subprocess.Popen[bytes]]:
    """Stands in for a running viewer: its command line names matters."""
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)  # matters serve"]
    )
    yield process
    process.kill()
    process.wait()


def test_stop_ends_the_recorded_viewer_and_clears_its_record(
    state: Path, viewer_process: subprocess.Popen[bytes]
) -> None:
    (state / "serve-9001.pid").write_text(str(viewer_process.pid))
    assert daemon.running(9001) == viewer_process.pid
    assert daemon.stop(9001) == [9001]
    assert viewer_process.wait(timeout=5) is not None
    assert not (state / "serve-9001.pid").exists()


def test_stop_without_a_port_stops_every_recorded_viewer(
    state: Path, viewer_process: subprocess.Popen[bytes]
) -> None:
    (state / "serve-9002.pid").write_text(str(viewer_process.pid))
    assert daemon.stop() == [9002]


def test_stale_records_are_cleared_and_never_signalled(state: Path) -> None:
    finished = subprocess.Popen([sys.executable, "-c", "pass"])
    finished.wait()
    (state / "serve-9003.pid").write_text(str(finished.pid))
    assert daemon.running(9003) is None
    assert not (state / "serve-9003.pid").exists()
    assert daemon.stop() == []


def test_never_signals_a_process_that_is_not_matters(state: Path) -> None:
    other = subprocess.Popen(["sleep", "30"])
    try:
        (state / "serve-9004.pid").write_text(str(other.pid))
        assert daemon.stop(9004) == []
        assert other.poll() is None
    finally:
        other.kill()
        other.wait()


def test_recorded_writes_this_process_and_cleans_up(state: Path) -> None:
    with daemon.recorded(9005):
        assert (state / "serve-9005.pid").read_text() == str(os.getpid())
    assert not (state / "serve-9005.pid").exists()


def free_port() -> int:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_start_runs_a_detached_viewer_that_stop_ends(
    state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))  # no sessions: nothing private is read
    port = free_port()
    started = daemon.start(port)
    try:
        assert started.pid is not None and not started.already
        assert daemon.status() == {port: started.pid}
        assert "Serving" in started.log.read_text()
        again = daemon.start(port)
        assert again.already and again.pid == started.pid
    finally:
        assert daemon.stop(port) == [port]
    assert daemon.status() == {}


def test_start_reports_a_viewer_that_could_not_start(
    state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MATTERS_EFFORT", "nonsense")  # serve exits at once
    started = daemon.start(free_port(), timeout=10)
    assert started.pid is None
    assert "nonsense" in started.log.read_text().lower()


def test_restart_starts_the_viewer_again_on_its_port(
    state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from matters.cli import main

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))  # no sessions: nothing private is read
    port = free_port()
    first = daemon.start(port)
    try:
        assert main(["restart"]) == 0
        viewers = daemon.status()
        assert list(viewers) == [port] and viewers[port] != first.pid
    finally:
        daemon.stop()
    assert daemon.status() == {}

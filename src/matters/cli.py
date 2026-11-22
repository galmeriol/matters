import argparse
import contextlib
import sys
import webbrowser
from collections.abc import Sequence
from pathlib import Path

from matters.sources import all_sources

DEFAULT_PORT = 8765


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="matters", description="Your local agent sessions.")
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="browse every local session in your browser")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--no-open", action="store_true", help="don't open a browser tab")

    start = commands.add_parser("start", help="run the viewer in the background")
    start.add_argument("--port", type=int, default=DEFAULT_PORT)
    start.add_argument("--open", action="store_true", help="open a browser tab once it is up")

    commands.add_parser("status", help="list running viewers")

    stop = commands.add_parser("stop", help="stop a running viewer")
    stop.add_argument("--port", type=int, help="only this port (default: every running viewer)")

    restart = commands.add_parser(
        "restart", help="restart the background viewer, with the code installed now"
    )
    restart.add_argument(
        "--port", type=int, help="only this port (default: every running viewer, or a new one)"
    )
    restart.add_argument("--open", action="store_true", help="open a browser tab once it is up")

    briefing = commands.add_parser(
        "brief", help="where a project stands: last ask, what is open, files touched"
    )
    briefing.add_argument(
        "project",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="project directory (default: current directory)",
    )

    args = parser.parse_args(argv)
    match args.command:
        case "brief":
            return _brief(args.project.expanduser().resolve())
        case "stop":
            return _stop(args.port)
        case "start":
            return _start(args.port, open_browser=args.open)
        case "restart":
            return _restart(args.port, open_browser=args.open)
        case "status":
            return _status()
        case _:
            return _serve(args.port, open_browser=not args.no_open)


def _serve(port: int, *, open_browser: bool) -> int:
    from matters.errors import SettingError
    from matters.llm.registry import from_env
    from matters.paths import state_dir
    from matters.web import daemon
    from matters.web.app import serve
    from matters.workbench import Workbench

    url = f"http://127.0.0.1:{port}/"
    if pid := daemon.running(port):
        print(f"Already serving at {url} (pid {pid}). Stop it with: matters stop", file=sys.stderr)
        if open_browser:
            webbrowser.open(url)
        return 0
    try:
        provider = from_env()
    except SettingError as error:
        print(error, file=sys.stderr)
        return 2
    bench = Workbench(provider, state_dir() / "matters.db")
    if provider.configured():
        model = provider.model or "its default model"
        print(f"Knowledge extraction uses headless Claude Code, {model}", file=sys.stderr)
    else:
        print("Claude Code isn't on PATH: knowledge extraction is off.", file=sys.stderr)
    print(f"Serving your sessions at {url}  (Ctrl+C or `matters stop` to stop)", file=sys.stderr)
    if open_browser:
        webbrowser.open(url)
    with contextlib.suppress(KeyboardInterrupt), daemon.recorded(port):
        serve(all_sources(), port, bench)
    return 0


def _brief(project: Path) -> int:
    from matters.brief import Brief

    sessions = [s for source in all_sources() for s in source.sessions(project)]
    if not sessions:
        print(f"No sessions for {project}.", file=sys.stderr)
        return 1
    sys.stdout.write(Brief.of(sessions, project).to_markdown())
    return 0


def _start(port: int, *, open_browser: bool) -> int:
    from matters.web import daemon

    url = f"http://127.0.0.1:{port}/"
    started = daemon.start(port)
    if started.pid is None:
        tail = started.log.read_text(errors="replace").splitlines()[-10:]
        print(f"The viewer did not start. From {started.log}:", *tail, sep="\n", file=sys.stderr)
        return 1
    state = "Already running" if started.already else "Running in the background"
    print(f"{state} at {url} (pid {started.pid})", file=sys.stderr)
    print(f"Log: {started.log}\nStop it with: matters stop", file=sys.stderr)
    if open_browser:
        webbrowser.open(url)
    return 0


def _restart(port: int | None, *, open_browser: bool) -> int:
    """Stop the viewers that are running and start them again on the same ports; with
    none running, start one."""
    from matters.web import daemon

    ports = daemon.stop(port) or [port or DEFAULT_PORT]
    return max(_start(each, open_browser=open_browser) for each in ports)


def _status() -> int:
    from matters.web import daemon

    viewers = daemon.status()
    if not viewers:
        print("No viewer is running.", file=sys.stderr)
        return 1
    for port, pid in viewers.items():
        print(f"http://127.0.0.1:{port}/  pid {pid}  log {daemon.log_path(port)}")
    return 0


def _stop(port: int | None) -> int:
    from matters.web import daemon

    stopped = daemon.stop(port)
    if not stopped:
        print("No viewer is running.", file=sys.stderr)
        return 0
    for each in stopped:
        print(f"Stopped the viewer on port {each}.", file=sys.stderr)
    return 0

"""Runs the core service and the frontend dev server together, on any platform.

The cross-platform equivalent of scripts/dev.sh and of `make dev`. Windows
has neither bash nor make, and that convenience gap was the only thing
standing between a native Windows checkout and a working demo, so this
closes it:

    python scripts/dev.py

    core:     http://localhost:8000
    frontend: http://localhost:5173

Ctrl+C stops both. If either process exits on its own, the other is shut
down too, so a crashed backend cannot leave a frontend serving stale data
in front of a jury.

dev.sh stays as the POSIX path, since it is what `make dev` execs and it
is the one that has been exercised. This file is not a rewrite of it: it
is the same two commands with the process handling that Windows needs.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")

IS_WINDOWS = os.name == "nt"
VENV_BIN = os.path.join(BACKEND_DIR, ".venv", "Scripts" if IS_WINDOWS else "bin")
VENV_PYTHON = os.path.join(VENV_BIN, "python.exe" if IS_WINDOWS else "python")
NPM = "npm.cmd" if IS_WINDOWS else "npm"


def _preflight() -> int:
    """Fails with the command that fixes it, rather than with a traceback
    from deep inside subprocess."""
    if not os.path.exists(VENV_PYTHON):
        print(f"No Python environment at {VENV_PYTHON}", file=sys.stderr)
        print("Build it first:", file=sys.stderr)
        if IS_WINDOWS:
            print(r"    cd backend && py -3.11 -m venv .venv", file=sys.stderr)
            print(r"    .\.venv\Scripts\python -m pip install -r requirements.txt", file=sys.stderr)
        else:
            print("    make venv", file=sys.stderr)
        return 1

    if not os.path.isdir(os.path.join(FRONTEND_DIR, "node_modules")):
        print(f"No node_modules in {FRONTEND_DIR}", file=sys.stderr)
        print("Install the frontend dependencies first:", file=sys.stderr)
        print("    cd frontend && npm install", file=sys.stderr)
        return 1

    return 0


def _spawn(args: list[str], cwd: str, env: dict[str, str]) -> subprocess.Popen:
    """Starts a child in its own process group, so the whole tree can be
    taken down later. npm spawns vite as a grandchild, so killing only the
    direct child would leave the dev server running and port 5173 held."""
    kwargs: dict = {"cwd": cwd, "env": env}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(args, **kwargs)


def _terminate(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if IS_WINDOWS:
            # taskkill /T because the grandchildren are the real servers.
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                check=False,
            )
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        process.terminate()


def main() -> int:
    failed = _preflight()
    if failed:
        return failed

    backend_env = dict(os.environ, PYTHONPATH=".")

    core = _spawn(
        [
            VENV_PYTHON, "-m", "uvicorn", "services.core.app:app",
            "--host", "0.0.0.0", "--port", "8000", "--reload",
        ],
        cwd=BACKEND_DIR,
        env=backend_env,
    )
    frontend = _spawn([NPM, "run", "dev"], cwd=FRONTEND_DIR, env=dict(os.environ))

    processes = [("core", core), ("frontend", frontend)]

    print()
    print("core:     http://localhost:8000")
    print("frontend: http://localhost:5173")
    print("Ctrl+C stops both.")
    print()

    try:
        while True:
            for name, process in processes:
                if process.poll() is not None:
                    print(f"\n{name} exited with code {process.returncode}, stopping the other")
                    raise KeyboardInterrupt
            time.sleep(0.4)
    except KeyboardInterrupt:
        print("\nshutting down ...")
    finally:
        for _, process in processes:
            _terminate(process)
        for _, process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

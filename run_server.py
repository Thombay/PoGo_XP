from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _print_local_url(host: str, port: int) -> None:
    url = f"http://{host}:{port}"
    # Plain URL is clickable in most terminals/IDEs.
    print(f"Open dashboard: {url}", flush=True)


def _google_drive_connect_cmd(root: Path) -> list[str]:
    return [sys.executable, str(root / "tools" / "google_drive_connect.py")]


def _streamlit_cmd(root: Path, host: str, port: int) -> list[str]:
    return [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(root / "webapp" / "app.py"),
        f"--server.address={host}",
        f"--server.port={port}",
    ]


def connect_google_drive(root: Path) -> int:
    print("Connecting Google Drive...", flush=True)
    completed = subprocess.run(_google_drive_connect_cmd(root), cwd=root, check=False)
    return int(completed.returncode)


def main() -> int:
    root = Path(__file__).resolve().parent
    host = "127.0.0.1"
    port = 8050
    try:
        connect_rc = connect_google_drive(root)
    except KeyboardInterrupt:
        print("\nGoogle Drive connection cancelled; not starting the server.", flush=True)
        return 130
    if connect_rc != 0:
        print("Google Drive connection failed; not starting the server.", flush=True)
        return connect_rc

    _print_local_url(host, port)
    proc = subprocess.Popen(_streamlit_cmd(root, host, port), cwd=root)
    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        print("\nServer stopped.", flush=True)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

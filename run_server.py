from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _print_local_url(host: str, port: int) -> None:
    url = f"http://{host}:{port}"
    # Plain URL is clickable in most terminals/IDEs.
    print(f"Open dashboard: {url}", flush=True)


def main() -> int:
    root = Path(__file__).resolve().parent
    app_file = root / "webapp" / "app.py"
    host = "127.0.0.1"
    port = 8050
    _print_local_url(host, port)
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_file),
        f"--server.address={host}",
        f"--server.port={port}",
    ]
    return subprocess.call(cmd, cwd=root)


if __name__ == "__main__":
    raise SystemExit(main())

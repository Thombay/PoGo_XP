from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# A listening TCP row has no remote peer. Matching that is independent of the
# localized state word (LISTENING, ABHÖREN, ...).
_LISTEN_REMOTES = {"0.0.0.0:0", "[::]:0", "*:*", "*:0"}


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


def listening_pids_from_netstat(output: str, port: int) -> set[int]:
    pids: set[int] = set()
    for raw in output.splitlines():
        parts = raw.split()
        if len(parts) < 4 or parts[0].upper() != "TCP":
            continue
        if not _address_has_port(parts[1], port):
            continue
        if parts[2] not in _LISTEN_REMOTES:
            continue
        if parts[-1].isdigit():
            pids.add(int(parts[-1]))
    return pids


def is_our_streamlit(command_line: str, root: Path) -> bool:
    normalized = command_line.replace("\\", "/").lower()
    app = str(root / "webapp" / "app.py").replace("\\", "/").lower()
    return "streamlit" in normalized and app in normalized


def free_dashboard_port(port: int, root: Path) -> int:
    """Stop a previous local dashboard still listening on this port.

    Returns 0 when the port is free afterwards. Returns 1 when another program
    is listening, or the previous dashboard does not exit.
    """
    listeners = sorted(_listening_pids(port) - {os.getpid()})
    if not listeners:
        return 0

    ours = [pid for pid in listeners if is_our_streamlit(_command_line(pid), root)]
    others = [pid for pid in listeners if pid not in ours]
    for pid in ours:
        print(f"Stopping previous dashboard on port {port} (pid {pid}).", flush=True)
        _stop_process(pid)
    if ours and not _wait_until_gone(port, set(ours)):
        print(f"Previous dashboard on port {port} did not stop.", flush=True)
        return 1
    if others:
        print(
            f"Port {port} is already in use by another program (pid {others[0]}).",
            flush=True,
        )
        return 1
    return 0


def _address_has_port(address: str, port: int) -> bool:
    _host, sep, local_port = address.rpartition(":")
    return bool(sep) and local_port == str(port)


def _listening_pids(port: int) -> set[int]:
    if os.name == "nt":
        completed = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            check=False,
        )
        return listening_pids_from_netstat(completed.stdout, port)
    completed = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        capture_output=True,
        text=True,
        check=False,
    )
    return {int(line) for line in completed.stdout.split() if line.isdigit()}


def _command_line(pid: int) -> str:
    if os.name == "nt":
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return completed.stdout.strip()
    try:
        raw = Path(f"/proc/{int(pid)}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()


def _stop_process(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        return
    os.kill(pid, signal.SIGTERM)


def _wait_until_gone(port: int, pids: set[int], timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while True:
        if not (_listening_pids(port) & pids):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.2)


def main() -> int:
    root = Path(__file__).resolve().parent
    host = "127.0.0.1"
    port = 8502
    try:
        connect_rc = connect_google_drive(root)
    except KeyboardInterrupt:
        print("\nGoogle Drive connection cancelled; not starting the server.", flush=True)
        return 130
    if connect_rc != 0:
        print("Google Drive connection failed; not starting the server.", flush=True)
        return connect_rc

    if free_dashboard_port(port, root) != 0:
        print("Not starting the server.", flush=True)
        return 1

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

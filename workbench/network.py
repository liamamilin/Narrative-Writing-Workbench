"""Addresses shown to a user running the local Workbench launcher."""

from __future__ import annotations

import os
import socket
import subprocess


def _detect_lan_host() -> str | None:
    configured = os.environ.get("WORKBENCH_ADVERTISED_HOST", "").strip()
    if configured:
        return configured
    # macOS is the supported desktop launcher. Keep this best-effort so the
    # API also works on Linux/Windows or when no Wi-Fi interface is connected.
    for interface in ("en0", "en1"):
        try:
            result = subprocess.run(
                ["ipconfig", "getifaddr", interface],
                capture_output=True, text=True, timeout=0.5, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        address = result.stdout.strip()
        if address:
            return address
    return None


def server_info() -> dict:
    public_host = os.environ.get(
        "WORKBENCH_PUBLIC_HOST",
        os.environ.get("WORKBENCH_HOST", "127.0.0.1"),
    ).strip()
    try:
        port = int(os.environ.get(
            "WORKBENCH_PUBLIC_PORT",
            os.environ.get("WORKBENCH_PORT", "8600"),
        ))
    except ValueError:
        port = 8600
    lan_host = _detect_lan_host()
    lan_enabled = public_host not in {"127.0.0.1", "localhost", "::1"}
    return {
        "local_url": f"http://127.0.0.1:{port}",
        "lan_url": f"http://{lan_host}:{port}" if lan_enabled and lan_host else None,
        "lan_host": lan_host if lan_enabled else None,
        "lan_enabled": lan_enabled,
        "port": port,
        "hostname": socket.gethostname(),
    }

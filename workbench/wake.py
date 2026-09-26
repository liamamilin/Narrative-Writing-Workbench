"""Keep the launcher URL alive while the Workbench worker sleeps.

The worker still exits after ``WORKBENCH_IDLE_TIMEOUT``.  This small standard
library proxy keeps the public port open, starts a worker on demand, and
forwards the request.  It lets the app reclaim its Python/LLM resources while
an old browser bookmark remains usable.
"""

from __future__ import annotations

import http.client
import http.server
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
from urllib.request import urlopen


_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}


def _free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


class WakeProxy:
    def __init__(self, public_host: str, public_port: int,
                 child_host: str = "127.0.0.1"):
        self.public_host = public_host
        self.public_port = public_port
        self.child_host = child_host
        self.child_port: int | None = None
        self.child: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._stopping = False
        self.httpd: http.server.ThreadingHTTPServer | None = None

    def _child_is_ready(self) -> bool:
        if self.child is None or self.child.poll() is not None or not self.child_port:
            return False
        try:
            with urlopen(f"http://{self.child_host}:{self.child_port}/settings",
                         timeout=0.8) as response:
                return response.status == 200
        except Exception:
            return False

    def ensure_child(self) -> int:
        with self._lock:
            if self._child_is_ready():
                return self.child_port  # type: ignore[return-value]
            if self._stopping:
                raise RuntimeError("Workbench wake proxy is stopping.")
            if self.child is not None and self.child.poll() is None:
                self.child.terminate()
                try:
                    self.child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.child.kill()
                    self.child.wait(timeout=2)
            self.child_port = _free_port(self.child_host)
            env = os.environ.copy()
            env["WORKBENCH_HOST"] = self.child_host
            env["WORKBENCH_PORT"] = str(self.child_port)
            # Preserve the public listener details for the Settings page.
            env.setdefault("WORKBENCH_PUBLIC_PORT", str(self.public_port))
            env.setdefault("WORKBENCH_PUBLIC_HOST", self.public_host)
            # The proxy owns the public port and is itself the wake mechanism.
            env["WORKBENCH_WAKE_PROXY"] = "0"
            root = Path(__file__).resolve().parent.parent
            self.child = subprocess.Popen(
                [sys.executable, "-m", "workbench.server"],
                cwd=str(root), env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if self._child_is_ready():
                    return self.child_port
                if self.child.poll() is not None:
                    break
                time.sleep(0.1)
            detail = "worker exited" if self.child.poll() is not None else "worker startup timed out"
            raise RuntimeError(f"Workbench {detail}.")

    def stop(self) -> None:
        with self._lock:
            self._stopping = True
            child = self.child
            if child is not None and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=3)

    def serve(self) -> None:
        proxy = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _forward(self):
                length = int(self.headers.get("Content-Length", "0") or 0)
                body = self.rfile.read(length) if length else None
                try:
                    port = proxy.ensure_child()
                    response = self._request(port, body)
                except Exception:
                    # A worker can exit between readiness and forwarding. Wake
                    # one fresh worker and retry the same request once.
                    with proxy._lock:
                        if proxy.child is not None:
                            proxy.child_port = None
                    try:
                        port = proxy.ensure_child()
                        response = self._request(port, body)
                    except Exception as exc:
                        self.send_error(503, f"Workbench is waking: {exc}")
                        return
                self._write_response(response)

            def _request(self, port: int, body: bytes | None):
                connection = http.client.HTTPConnection(
                    proxy.child_host, port, timeout=120)
                headers = {
                    key: value for key, value in self.headers.items()
                    if key.lower() not in _HOP_BY_HOP and key.lower() != "content-length"
                }
                headers["Host"] = self.headers.get("Host", f"{proxy.public_host}:{proxy.public_port}")
                if body is not None:
                    headers["Content-Length"] = str(len(body))
                connection.request(self.command, self.path, body=body, headers=headers)
                return connection, connection.getresponse()

            def _write_response(self, result):
                connection, response = result
                try:
                    self.send_response(response.status, response.reason)
                    content_type = response.getheader("Content-Type", "")
                    streaming = content_type.lower().startswith("text/event-stream")
                    for key, value in response.getheaders():
                        if key.lower() in _HOP_BY_HOP or key.lower() == "content-length":
                            continue
                        self.send_header(key, value)
                    if not streaming:
                        data = response.read()
                        self.send_header("Content-Length", str(len(data)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    if self.command == "HEAD":
                        pass
                    elif streaming:
                        reader = getattr(response, "read1", response.read)
                        while True:
                            data = reader(8192)
                            if not data:
                                break
                            self.wfile.write(data)
                            self.wfile.flush()
                    elif data:
                        self.wfile.write(data)
                    self.close_connection = True
                finally:
                    response.close()
                    connection.close()

            def do_GET(self): self._forward()
            def do_HEAD(self): self._forward()
            def do_POST(self): self._forward()
            def do_PATCH(self): self._forward()
            def do_PUT(self): self._forward()
            def do_DELETE(self): self._forward()

            def log_message(self, *_args):
                return

        self.httpd = http.server.ThreadingHTTPServer(
            (self.public_host, self.public_port), Handler)
        self.httpd.daemon_threads = True
        try:
            self.httpd.serve_forever(poll_interval=0.2)
        finally:
            self.stop()
            self.httpd.server_close()


def main() -> None:
    host = os.environ.get("WORKBENCH_HOST", "127.0.0.1")
    port = int(os.environ.get("WORKBENCH_PORT", "8600"))
    proxy = WakeProxy(host, port)

    def stop(_signum, _frame):
        if proxy.httpd is not None:
            # ``shutdown`` must run from a different thread than
            # ``serve_forever``; signal handlers execute on that same thread.
            threading.Thread(target=proxy.httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print(f"Workbench wake proxy -> http://{host}:{port}", flush=True)
    proxy.serve()


if __name__ == "__main__":
    main()

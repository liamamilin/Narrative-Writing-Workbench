"""Isolated mock server for browser checks; deletes owned test data on shutdown.

python scripts/mock_server.py [--port 8601] [--data-dir /tmp/restart-case]
Never reads the user's settings/database and never calls a real provider.
"""
import argparse
from contextlib import nullcontext
import os
from pathlib import Path
import socket
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    import uvicorn
    from workbench import settings
    from workbench.api import create_app
    from workbench.db import Database
    from workbench.engine.mock import MockWritingEngine
    from workbench.service import Service
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--data-dir")
    args = parser.parse_args()
    for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "WORKBENCH_ENGINE", "WORKBENCH_CONFIG"):
        os.environ.pop(key, None)

    class BrowserEngine(MockWritingEngine):
        delay = 0
        def generate(self, **kwargs):
            time.sleep(self.delay)
            return super().generate(**kwargs)
        def review(self, **kwargs):
            result = super().review(**kwargs)
            result["summary"].update({"decision": "PASS", "wq": 28})
            return result

    class BrowserService(Service):
        def update_settings(self, payload):
            # Exercise persistence, but keep all browser checks hermetic.
            settings.save({**payload, "engine": "mock"})
            return self.settings_view()

    workspace = (nullcontext(args.data_dir) if args.data_dir
                 else tempfile.TemporaryDirectory(prefix="workbench-browser-"))
    with workspace as directory:
        Path(directory).mkdir(parents=True, exist_ok=True)
        settings.SETTINGS_PATH = Path(directory) / "settings.json"
        settings.save({"engine": "mock"})
        svc = BrowserService(Database(Path(directory) / "test.db"), BrowserEngine())
        app = create_app(svc)
        @app.get("/_test/ready")
        def ready():
            return {"engine": "mock"}
        @app.post("/_test/delay")
        def delay(body: dict):
            svc.engine.delay = min(8, max(0, float(body.get("seconds", 0))))
            return {"ok": True}
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", args.port))
        print(f"MOCK_URL=http://127.0.0.1:{sock.getsockname()[1]}", flush=True)
        try:
            uvicorn.Server(uvicorn.Config(app, log_level="warning", timeout_graceful_shutdown=1)).run(sockets=[sock])
        finally:
            svc.db.conn.close()
            sock.close()


if __name__ == "__main__":
    main()

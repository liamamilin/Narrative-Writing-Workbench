"""Workbench server: python -m workbench.server  → http://127.0.0.1:8600"""

from __future__ import annotations

import os


def main() -> None:
    from .db import DEFAULT_DB
    from .instance import server_lease
    with server_lease(os.environ.get("WORKBENCH_DB", DEFAULT_DB)):
        serve()


def serve() -> None:
    import uvicorn
    from .api import create_app
    from .idle import IdleTracker, install, timeout_from_env
    from .settings import apply_env, engine_mode, load
    apply_env(load())
    port = int(os.environ.get("WORKBENCH_PORT", "8600"))
    host = os.environ.get("WORKBENCH_HOST", "127.0.0.1")
    app = create_app()
    idle_s = timeout_from_env()
    if idle_s > 0:
        install(app, IdleTracker(idle_s))
    print(f"Narrative Writing Workbench -> http://{host}:{port} "
          f"(engine={engine_mode()}, idle-shutdown={'off' if not idle_s else f'{idle_s/60:g}min'})",
          flush=True)
    uvicorn.run(app, host=host, port=port, log_level="warning",
                timeout_graceful_shutdown=5)   # never hang on open SSE tabs


if __name__ == "__main__":
    main()

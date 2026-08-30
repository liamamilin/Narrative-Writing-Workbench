"""Workbench server: python -m workbench.server  → http://127.0.0.1:8600"""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn
    from .api import create_app
    from .settings import apply_env, engine_mode, load
    apply_env(load())
    port = int(os.environ.get("WORKBENCH_PORT", "8600"))
    print(f"Narrative Writing Workbench -> http://127.0.0.1:{port} "
          f"(engine={engine_mode()})")
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()

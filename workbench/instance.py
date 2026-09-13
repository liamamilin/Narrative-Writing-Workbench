"""An OS lease for the supported single-process local server (macOS/Linux)."""
from contextlib import contextmanager
import fcntl
from pathlib import Path


@contextmanager
def server_lease(db_path):
    path = Path(str(db_path) + ".server.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("此数据库已有 Workbench 服务运行，请关闭原服务后重试。") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)

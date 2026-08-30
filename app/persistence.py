"""Run persistence.

Layout per docs/09:

    runs/<run_id>/
      input.json wir.json draft.md critique.json final.md metadata.json
      raw/architect.txt raw/writer.txt raw/critic.txt raw/patcher.txt
      raw/errors.txt

Writes are best-effort: a persistence failure is logged and recorded in the
in-memory error list, but never destroys in-flight run data or raises.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .schemas import SchemaSet

logger = logging.getLogger(__name__)


class RunStore:
    def __init__(self, runs_dir: str | Path, schemas: SchemaSet | None = None):
        self.runs_dir = Path(runs_dir)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.schemas = schemas
        self.persistence_errors: dict[str, list[str]] = {}

    # ---- run lifecycle -------------------------------------------------

    def create_run(self) -> str:
        existing = [
            p.name for p in self.runs_dir.iterdir() if p.is_dir() and p.name.isdigit()
        ]
        next_num = (max(int(n) for n in existing) + 1) if existing else 1
        run_id = f"{next_num:06d}"
        (self.run_dir_path(run_id) / "raw").mkdir(parents=True, exist_ok=True)
        return run_id

    def run_dir_path(self, run_id: str) -> Path:
        return self.runs_dir / run_id

    # ---- low-level writers ----------------------------------------------

    def _record_error(self, run_id: str, message: str) -> None:
        self.persistence_errors.setdefault(run_id, []).append(message)
        logger.error("persistence failure (run %s): %s", run_id, message)

    def _write_text(self, run_id: str, relpath: str, content: str) -> bool:
        try:
            path = self.run_dir_path(run_id) / relpath
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return True
        except OSError as exc:
            self._record_error(run_id, f"could not write {relpath}: {exc}")
            return False

    def _write_json(self, run_id: str, relpath: str, obj) -> bool:
        return self._write_text(
            run_id, relpath, json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
        )

    # ---- artifacts -------------------------------------------------------

    def save_input(self, run_id: str, payload: dict) -> bool:
        return self._write_json(run_id, "input.json", payload)

    def save_wir(self, run_id: str, wir: dict) -> bool:
        return self._write_json(run_id, "wir.json", wir)

    def save_draft(self, run_id: str, text: str) -> bool:
        return self._write_text(run_id, "draft.md", text)

    def save_critique(self, run_id: str, critique: dict) -> bool:
        return self._write_json(run_id, "critique.json", critique)

    def save_final(self, run_id: str, text: str) -> bool:
        return self._write_text(run_id, "final.md", text)

    def save_raw(self, run_id: str, stage: str, text: str) -> bool:
        return self._write_text(run_id, f"raw/{stage}.txt", text)

    def append_error(self, run_id: str, text: str) -> bool:
        return self._append(run_id, "raw/errors.txt", text)

    def _append(self, run_id: str, relpath: str, content: str) -> bool:
        try:
            path = self.run_dir_path(run_id) / relpath
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(content.rstrip("\n") + "\n")
            return True
        except OSError as exc:
            self._record_error(run_id, f"could not append {relpath}: {exc}")
            return False

    def save_metadata(self, run_id: str, metadata: dict) -> bool:
        ok = self._write_json(run_id, "metadata.json", metadata)
        if ok and self.schemas is not None:
            errors = self.schemas.validate_run_metadata(metadata)
            if errors:
                msg = "metadata.json failed run.schema validation: " + "; ".join(errors)
                logger.warning("run %s: %s", run_id, msg)
                self._append(run_id, "raw/errors.txt", msg)
        return ok

"""Schema loading and validation. The supplied /schemas files are source of truth."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

WIR_SCHEMA_FILE = "wir.schema.json"
CRITIQUE_SCHEMA_FILE = "critique.schema.json"
RUN_SCHEMA_FILE = "run.schema.json"
OUTLINE_SCHEMA_FILE = "outline.schema.json"


def _format_error(err) -> str:
    path = "/".join(str(p) for p in err.absolute_path) or "<root>"
    return f"{path}: {err.message}"


class SchemaSet:
    def __init__(self, schemas_dir: str | Path):
        schemas_dir = Path(schemas_dir)
        self.wir = self._load(schemas_dir / WIR_SCHEMA_FILE)
        self.critique = self._load(schemas_dir / CRITIQUE_SCHEMA_FILE)
        self.run = self._load(schemas_dir / RUN_SCHEMA_FILE)
        self.outline = self._load(schemas_dir / OUTLINE_SCHEMA_FILE)
        self._wir_validator = Draft202012Validator(self.wir)
        self._critique_validator = Draft202012Validator(self.critique)
        self._run_validator = Draft202012Validator(self.run)
        self._outline_validator = Draft202012Validator(self.outline)
        # Fail fast if a supplied schema itself is broken.
        for name, schema in (
            (WIR_SCHEMA_FILE, self.wir),
            (CRITIQUE_SCHEMA_FILE, self.critique),
            (RUN_SCHEMA_FILE, self.run),
            (OUTLINE_SCHEMA_FILE, self.outline),
        ):
            Draft202012Validator.check_schema(schema)

    @staticmethod
    def _load(path: Path) -> dict:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def validate_wir(self, obj) -> list[str]:
        """Return a list of validation error strings; empty list means valid."""
        if not isinstance(obj, dict):
            return ["WIR must be a JSON object"]
        return [_format_error(e) for e in self._wir_validator.iter_errors(obj)]

    def validate_critique(self, obj) -> list[str]:
        if not isinstance(obj, dict):
            return ["critique must be a JSON object"]
        return [_format_error(e) for e in self._critique_validator.iter_errors(obj)]

    def validate_outline(self, obj) -> list[str]:
        if not isinstance(obj, dict):
            return ["outline must be a JSON object"]
        return [_format_error(e) for e in self._outline_validator.iter_errors(obj)]

    def validate_run_metadata(self, obj) -> list[str]:
        if not isinstance(obj, dict):
            return ["run metadata must be a JSON object"]
        return [_format_error(e) for e in self._run_validator.iter_errors(obj)]

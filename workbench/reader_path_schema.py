"""Structured output contract for Product V0.6 reader-path review."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "reader_path_review.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SCHEMA)
_VALIDATOR = Draft202012Validator(SCHEMA)


def validate_reader_path(data) -> list[str]:
    if not isinstance(data, dict):
        return ["reader-path review must be a JSON object"]
    errors = []
    for err in _VALIDATOR.iter_errors(data):
        path = "/".join(str(part) for part in err.absolute_path) or "<root>"
        errors.append(f"{path}: {err.message}")
    if errors:
        return errors
    for key in ("steps", "issues"):
        seen = set()
        for index, item in enumerate(data[key]):
            if item["id"] in seen:
                errors.append(f"{key}[{index}].id duplicates an earlier id")
            seen.add(item["id"])
    for index, issue in enumerate(data["issues"]):
        if issue["paragraph_end"] < issue["paragraph_start"]:
            errors.append(f"issues[{index}] has a reversed paragraph range")
    return errors

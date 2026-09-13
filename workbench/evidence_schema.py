"""Structured output contract for Product V0.5 evidence cards."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "evidence_check.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SCHEMA)
_VALIDATOR = Draft202012Validator(SCHEMA)


def validate_evidence(data) -> list[str]:
    if not isinstance(data, dict):
        return ["evidence check must be a JSON object"]
    errors = []
    for err in _VALIDATOR.iter_errors(data):
        path = "/".join(str(part) for part in err.absolute_path) or "<root>"
        errors.append(f"{path}: {err.message}")
    if errors:
        return errors
    seen = set()
    for index, claim in enumerate(data["claims"]):
        if claim["id"] in seen:
            errors.append(f"claims[{index}].id duplicates an earlier id")
        seen.add(claim["id"])
        if claim["paragraph_end"] < claim["paragraph_start"]:
            errors.append(f"claims[{index}] has a reversed paragraph range")
        if claim["relation"] in ("supported", "conflict") and (
                not claim["source_id"] or not claim["source_quote"]):
            errors.append(
                f"claims[{index}] relation {claim['relation']} requires a source quote")
    return errors

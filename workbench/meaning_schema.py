"""Meaning Discovery validation (product/13, product/14).

JSON-Schema check plus two semantic rules the schema can't express:
- selected_angle_id must reference a real candidate;
- candidate angles must be meaningfully distinct (not paraphrase duplicates).

Kept in workbench/ so the engine's SchemaSet (app/, V1.2 scope closed) is
untouched.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "meaning_discovery.schema.json"

# Progression contract (thinking-chain steps 6-8): how the Architect must
# order beats once this meaning block is injected into the WIR stage.
PROGRESSION_CONTRACT = (
    "## Progression contract (how the beats must be ordered)\n"
    "- Derive, don't enumerate: beats must follow the mechanism through "
    "successive orders of consequence — first-order phenomenon → "
    "second-order reaction → third-order structure. 并列铺陈 = failure.\n"
    "- One beat must face the strongest counterexample head-on and answer "
    "it from the mechanism, not by dismissing it.\n"
    "- The closing beat states the boundary: where the thesis holds, "
    "where it does not. No absolutism.\n"
    "- Each beat's meaning_gain records what the reader's understanding "
    "gained at that step of the chain.")

with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
    MEANING_SCHEMA = json.load(fh)

Draft202012Validator.check_schema(MEANING_SCHEMA)
_VALIDATOR = Draft202012Validator(MEANING_SCHEMA)

_WS = re.compile(r"[\s，。、,.!?；;：:'\"“”‘’()（）\-—]+")


def _normalize(text: str) -> str:
    return _WS.sub("", (text or "").lower())


def _format_error(err) -> str:
    path = "/".join(str(p) for p in err.absolute_path) or "<root>"
    return f"{path}: {err.message}"


def validate_meaning(obj) -> list[str]:
    """Return a list of error strings; empty means valid."""
    if not isinstance(obj, dict):
        return ["meaning discovery must be a JSON object"]
    errors = [_format_error(e) for e in _VALIDATOR.iter_errors(obj)]
    if errors:
        return errors  # structural problems first; semantic checks need a valid shape

    candidates = obj.get("candidate_angles") or []
    ids = [c.get("id") for c in candidates]
    sel = obj.get("selected_angle_id")
    if sel not in ids:
        errors.append(f"selected_angle_id '{sel}' is not one of the candidate ids {ids}")

    # distinctness: no two candidate labels may be trivial paraphrases
    labels = [_normalize(c.get("label")) for c in candidates]
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            if labels[i] and labels[i] == labels[j]:
                errors.append(
                    f"candidate_angles {candidates[i]['id']} and "
                    f"{candidates[j]['id']} duplicate the same label")

    # framework migration must actually happen (thinking-chain step 4→9):
    # the refined thesis may not restate the default reading.
    if _normalize(obj.get("refined_thesis")) == _normalize(obj.get("common_reading")):
        errors.append("refined_thesis must differ from common_reading "
                      "(no frame migration detected)")
    return errors


def selected_angle(obj: dict) -> dict:
    """Return the selected candidate object (assumes obj passed validation)."""
    for c in obj.get("candidate_angles", []):
        if c.get("id") == obj.get("selected_angle_id"):
            return c
    return {}


def meaning_to_wir_block(obj: dict) -> dict:
    """Handoff to WIR (product/13 'Output to WIR') + thinking-chain fields."""
    sel = selected_angle(obj)
    return {
        "selected_angle": sel.get("label", obj.get("new_reading", "")),
        "core_question": obj.get("core_question", ""),
        "deep_meaning": obj.get("deep_meaning", ""),
        "reader_end_state": obj.get("reader_end_state", ""),
        "key_tensions": obj.get("key_tensions") or obj.get("candidate_tensions") or [],
        "refined_thesis": obj.get("refined_thesis", ""),
        "strongest_counterexample": obj.get("strongest_counterexample", ""),
        "boundary": obj.get("boundary", ""),
    }


def product_safe_summary(obj: dict) -> dict:
    """GET /tasks/:id/meaning payload — refined products only, no reasoning
    trace (product/17; v2 adds refined_thesis per user request — see review)."""
    sel = selected_angle(obj)
    return {
        "topic": obj.get("topic", ""),
        "selected_angle": sel.get("label", ""),
        "core_question": obj.get("core_question", ""),
        "reader_end_state": obj.get("reader_end_state", ""),
        "refined_thesis": obj.get("refined_thesis", ""),
    }

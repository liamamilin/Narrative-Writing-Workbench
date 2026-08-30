"""Shared small utilities: hashing, ISO timestamps, JSON output parsing."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_FENCE_HEAD = re.compile(r"^```(?:json)?\s*", re.IGNORECASE)
_FENCE_TAIL = re.compile(r"\s*```\s*$")


def parse_json_output(text: str):
    """Parse a model output that should contain a JSON object.

    Tolerates markdown code fences and surrounding prose. Raises ValueError
    when no valid JSON object can be recovered.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("empty model output: no JSON object found")
    s = text.strip()
    if s.startswith("```"):
        s = _FENCE_TAIL.sub("", _FENCE_HEAD.sub("", s))
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        start = s.find("{")
        end = s.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(s[start : end + 1])
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON in model output: {exc}") from exc
        raise ValueError("no JSON object found in model output")

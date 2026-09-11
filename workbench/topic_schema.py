"""Validation for topic-suggestion structured output (product-safe view).

Shape: {"topics": [{"text": str, "hook": str}, ...]} — exactly 3 items,
distinct, single-sentence, non-filler.
"""

from __future__ import annotations

_TOPICS_MIN, _TOPICS_MAX = 3, 3
_TEXT_MIN, _TEXT_MAX = 4, 40
_HOOK_MIN, _HOOK_MAX = 2, 24
_BANNED = ("谈谈", "浅析", "感人", "深刻", "有意义", "引人深思", "值得思考")


def validate_topics(data: object) -> list[str]:
    """Return [] when valid; otherwise human-readable error strings."""
    if not isinstance(data, dict):
        return ["output must be a JSON object"]
    errors: list[str] = []
    topics = data.get("topics")
    if not isinstance(topics, list):
        return ["topics must be a list"]
    if len(topics) < _TOPICS_MIN:
        errors.append(f"need at least {_TOPICS_MIN} topics, got {len(topics)}")
    if len(topics) > _TOPICS_MAX:
        errors.append(f"at most {_TOPICS_MAX} topics, got {len(topics)}")
    seen: set[str] = set()
    for i, t in enumerate(topics):
        if not isinstance(t, dict):
            errors.append(f"topics[{i}] must be an object")
            continue
        text = str(t.get("text") or "").strip()
        if not (_TEXT_MIN <= len(text) <= _TEXT_MAX):
            errors.append(
                f"topics[{i}].text must be {_TEXT_MIN}-{_TEXT_MAX} chars")
        low = text.lower()
        if any(b in low for b in _BANNED):
            errors.append(f"topics[{i}].text uses filler wording: {text[:12]}…")
        if text in seen:
            errors.append(f"topics[{i}].text duplicates an earlier topic")
        seen.add(text)
        hook = str(t.get("hook") or "").strip()
        if not (_HOOK_MIN <= len(hook) <= _HOOK_MAX):
            errors.append(
                f"topics[{i}].hook must be {_HOOK_MIN}-{_HOOK_MAX} chars")
    return errors

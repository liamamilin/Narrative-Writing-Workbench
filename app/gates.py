"""Hard fidelity gates (docs/14 §5).

Deterministic functional checks that run BEFORE literary evaluation.
A failed gate is a functional failure: the text must not win on prose quality
alone. Gate results are stored separately from quality scores.
"""

from __future__ import annotations

import re

GATE_NAMES = (
    "expected_language_match",
    "task_completion",
    "non_empty_output",
    "factual_fidelity",
    "no_instruction_format_leakage",
)

CJK = re.compile(r"[\u4e00-\u9fff]")
LATIN_LETTER = re.compile(r"[A-Za-z]")
DIGITS = re.compile(r"\d+")
CAPITALIZED = re.compile(r"\b[A-Z][a-z]{1,}\b|\b[A-Z]{2,}\b")
QUOTE_SPANS = re.compile(r"[“「『]([^”」』]{16,})[”」』]")
REFUSALS = (
    re.compile(r"(?:抱歉|对不起)[^。！？\n]{0,20}(?:不能|无法|没有能力)"),
    re.compile(r"(?:作为|身为)(?:一个|一名)?\s*(?:AI|人工智能|语言模型|大模型)", re.I),
    re.compile(r"\bI (?:cannot|can't|am unable|am not able)\b", re.I),
    re.compile(r"\bAs an AI\b", re.I),
)
LEAK_MARKERS = (
    "reader_state", "start_state", "end_state", "wir_version", "patch_targets",
    "outline_version", "core_point", "## Source Material", "## Writing Instruction",
    "## Task Constraints", "## Required Output Schema", "```json", "```",
    "Text A", "Text B", "rationale:", "immersion:",
)
LATIN_STOPLIST = {
    "A", "B", "C", "DNA", "OK", "pH", "GDP", "AI", "QQ", "X", "Y", "Z", "TV",
    "CBD", "ID", "PM", "US", "UK", "JSON", "WIR",
}


def _cjk_ratio(text: str) -> float:
    letters = sum(1 for ch in text if LATIN_LETTER.match(ch))
    cjk = len(CJK.findall(text))
    total = letters + cjk
    return cjk / total if total else 0.0


def detect_language(text: str) -> str:
    """Deterministic zh/en heuristic; 'unknown' when there is no signal."""
    if not text or not text.strip():
        return "unknown"
    ratio = _cjk_ratio(text)
    if ratio >= 0.2:
        return "zh"
    if ratio == 0.0:
        return "en"
    return "en"


def expected_language(case: dict) -> str:
    probe = (case.get("instruction") or "") + (case.get("material") or "")
    return "zh" if _cjk_ratio(probe) >= 0.5 else "en"


def resolve_expected_language(case: dict, config_default: str = "auto") -> str:
    """Explicit values win over the heuristic (docs/17 §2).

    Priority: case["expected_language"] > config.expected_language > zh/en
    text heuristic. Only "zh"/"en" are explicit; anything else is "auto".
    """
    for value in (case.get("expected_language"), config_default):
        if value in ("zh", "en"):
            return value
    return expected_language(case)


def hard_gates(text: str | None, case: dict) -> dict:
    """Evaluate all deterministic gates; returns gate record (docs/14 §5)."""
    body = (text or "").strip()
    reasons: list[str] = []

    exp = resolve_expected_language(case)
    act = detect_language(body) if body else "empty"
    language_match = bool(body) and act == exp
    if not language_match:
        reasons.append(f"language mismatch: expected {exp}, got {act}")

    non_empty = len(body) >= 30
    if not non_empty:
        reasons.append(f"output too short ({len(body)} chars)")

    target = case.get("target_length") or 0
    refusal = any(p.search(body) for p in REFUSALS)
    if target:
        task_ok = 0.35 * target <= len(body) <= 3 * target and not refusal
        if not task_ok and not refusal:
            reasons.append(f"length {len(body)} outside [{int(0.35*target)}, {int(3*target)}]")
    else:
        task_ok = len(body) >= 100 and not refusal
        if not task_ok and not refusal:
            reasons.append("length below 100 chars")
    if refusal:
        reasons.append("refusal pattern")

    material = case.get("material") or ""
    fidelity_ok = True
    if not case.get("allow_new_facts"):
        new_digits = set(DIGITS.findall(body)) - set(DIGITS.findall(material))
        if new_digits:
            fidelity_ok = False
            reasons.append(f"unsupported numerals: {sorted(new_digits)[:5]}")
        new_names = (set(CAPITALIZED.findall(body)) - set(CAPITALIZED.findall(material))
                     - LATIN_STOPLIST)
        if new_names:
            fidelity_ok = False
            reasons.append(f"unsupported latin names: {sorted(new_names)[:5]}")
        long_quotes = [q.strip() for q in QUOTE_SPANS.findall(body)]
        fabricated = [q for q in long_quotes if q not in material]
        if fabricated:
            fidelity_ok = False
            reasons.append(f"unsupported long quotation: {fabricated[0][:30]}…")

    leaked = [m for m in LEAK_MARKERS if m in body]
    leakage_ok = not leaked
    if leaked:
        reasons.append(f"format leakage: {leaked[:4]}")

    checks = {
        "expected_language_match": language_match,
        "task_completion": task_ok,
        "non_empty_output": non_empty,
        "factual_fidelity": fidelity_ok,
        "no_instruction_format_leakage": leakage_ok,
    }
    return {
        "expected_language": exp,
        "actual_language": act,
        "checks": checks,
        "functional_failure": not all(checks.values()),
        "failure_reasons": reasons if not all(checks.values()) else [],
    }
